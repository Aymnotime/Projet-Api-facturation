"""Connecteur Chorus Pro (https://communaute.chorus-pro.gouv.fr) — PDP agréé.

Implémentation réelle du contrat ``PDPAdapter`` sur l'API REST Chorus Pro :

- **Authentification OAuth2 client-credentials** (portail *Accès à la API
  Chorus Pro*) : jeton bearer obtenu via ``POST /oauth/token``, mis en cache
  jusqu'à expiration, rafraîchi automatiquement sur 401 (une seule tentative).
- **Dépôt de facture électronique** : ``POST /apis/secure/v2/invoice``
  (multipart : le PDF Factur-X joint + métadonnées JSON). Idempotence par
  numéro d'instruction gérée localement (dictionnaire number → référence)
  et côté plateforme (Chorus refuse les doublons factures/marché).
- **Suivi de statut** : ``GET /apis/secure/v2/invoice/{id}`` dont le champ
  ``status`` est mappé vers ``PDPLifecycleState``.

Les credentials (``api_key`` = secret client) sont stockés **chiffrés** au
repos via ``app.crypto`` ; ils ne transitent jamais dans les logs ni dans les
objets valeur exposés aux appelants.

Transport HTTP injectable (``http_client``) pour tester sans réseau : les
tests CI valident le contrat avec un faux transport, exactement comme le
``MockPDPAdapter``, ce qui garantit que les deux implémentations restent
interchangeables.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, ClassVar
from urllib.parse import quote

import httpx

from app.crypto import decrypt_secret, encrypt_secret
from app.services.pdp.adapter import (
    LifecycleInfo,
    PDPAdapter,
    PDPDocument,
    PDPDocumentType,
    PDPTransmissionError,
    PDPLifecycleState,
    TransmissionResult,
    register_pdp_adapter,
)

logger = logging.getLogger(__name__)

PRODUCTION_BASE_URL = "https://api.chorus-pro.gouv.fr"
SANDBOX_BASE_URL = "https://api-demo.chorus-pro.gouv.fr"

# Mapping des statuts Chorus Pro (v2) vers notre cycle de vie normalisé.
_STATUS_MAP: dict[str, tuple[PDPLifecycleState, str]] = {
    "INTEGRATION": (PDPLifecycleState.INTEGRATION, "transmitted"),
    "ENVOI_EN_COURS": (PDPLifecycleState.ENVOI_EN_COURS, "transmitted"),
    "DEPOSEE": (PDPLifecycleState.DEPOSEE, "transmitted"),
    "REMISE": (PDPLifecycleState.REMISE, "accepted"),
    "SOUMISE": (PDPLifecycleState.SOUMISE, "accepted"),
    "REJETEE": (PDPLifecycleState.REJETEE, "rejected"),
    "TRAITEE": (PDPLifecycleState.TRAITEE, "accepted"),
}


class ChorusProAdapter(PDPAdapter):
    """Adaptateur contractuel de l'API Chorus Pro v2.

    Parameters
    ----------
    api_key:
        Secret client OAuth2 (``client_secret``), fourni **en clair** à la
        construction puis stocké chiffré en mémoire interne. Peut aussi être
        passé déjà chiffré (token Fernet) — il est alors déchiffré.
    api_secret / username:
        Identifiant technique (compte applicatif du portail).
    base_url:
        ``PRODUCTION_BASE_URL`` par défaut ; ``SANDBOX_BASE_URL`` pour les
        environnements de recette Chorus.
    http_client:
        callable ``request(method, url, **kwargs) -> ResponseLike`` injectable
        (tests). Par défaut un client ``httpx.Client`` avec timeouts stricts.
    """

    provider_name_property: ClassVar[str] = "chorus_pro"

    _TOKEN_SAFETY_MARGIN = 60  # secondes : renouveler le jeton un peu avant expiration

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        username: str = "",
        base_url: str = PRODUCTION_BASE_URL,
        timeout: float = 30.0,
        http_client: Callable[..., Any] | None = None,
    ):
        if not api_key:
            raise PDPTransmissionError(
                "Chorus Pro : api_key (secret client OAuth2) requis", provider=self.provider_name_property
            )
        # Credentials chiffrés au repos dans l'instance (jamais en clair stocké).
        self._encrypted_api_key = api_key if api_key.startswith("gAAAAA") else encrypt_secret(api_key)
        self._username = username
        self._encrypted_api_secret = (
            api_secret if api_secret.startswith("gAAAAA") else (encrypt_secret(api_secret) if api_secret else "")
        )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_client = http_client
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        # Idempotence locale : numéro de facture -> id Chorus (uuid) + résultat.
        self._submitted: dict[str, TransmissionResult] = {}

    # -- secrets -------------------------------------------------------------

    @property
    def client_secret(self) -> str:
        return decrypt_secret(self._encrypted_api_key)

    # -- transport -----------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client(method, url, **kwargs)
        with httpx.Client(timeout=self.timeout) as client:
            return client.request(method, url, **kwargs)

    # -- OAuth2 client credentials -------------------------------------------

    def _obtain_token(self) -> None:
        payload = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": self.client_secret,
        }
        try:
            resp = self._request("POST", f"{self.base_url}/oauth/token", data=payload)
        except httpx.HTTPError as exc:
            raise PDPTransmissionError(f"Chorus Pro : échec d'authentification ({exc})",
                                       provider=self.provider_name_property) from exc
        if resp.status_code != 200:
            raise PDPTransmissionError(
                f"Chorus Pro OAuth2 : HTTP {resp.status_code}",
                provider=self.provider_name_property,
                status_code=resp.status_code,
            )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise PDPTransmissionError("Chorus Pro OAuth2 : réponse sans access_token",
                                       provider=self.provider_name_property)
        self._token = token
        expires_in = int(body.get("expires_in", 3600) or 3600)
        self._token_expires_at = time.time() + max(expires_in - self._TOKEN_SAFETY_MARGIN, 1)

    def _auth_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        if force_refresh or self._token is None or time.time() >= self._token_expires_at:
            self._obtain_token()
        assert self._token is not None
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._username:
            headers["X-Chorus-Pro-Acces-IdTechnique"] = self._username
        return headers

    def _call(self, method: str, path: str, *, retry_on_401: bool = True, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self._request(method, url, headers=self._auth_headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise PDPTransmissionError(f"Chorus Pro : erreur réseau ({exc})",
                                       provider=self.provider_name_property) from exc
        if resp.status_code == 401 and retry_on_401:
            logger.info("chorus-pro: jeton expiré, renouvellement unique")
            try:
                resp = self._request(method, url, headers=self._auth_headers(force_refresh=True), **kwargs)
            except httpx.HTTPError as exc:
                raise PDPTransmissionError(f"Chorus Pro : erreur réseau ({exc})",
                                           provider=self.provider_name_property) from exc
        return resp

    # -- contrat PDPAdapter ----------------------------------------------------

    @property
    def provider_name(self) -> str:
        return self.provider_name_property

    def validate_document(self, document: PDPDocument) -> list[str]:
        errors: list[str] = []
        if not document.content:
            errors.append("Contenu du document vide.")
        elif document.media_type == "application/pdf" and not document.content.startswith(b"%PDF"):
            errors.append("Factur-X attendu : le fichier ne commence pas par %PDF.")
        if len(document.content) > 4_500_000:
            errors.append("Document trop volumineux (limite Chorus Pro ~4,5 Mo).")
        if not document.number.strip():
            errors.append("Numéro de facture manquant (instructionId nécessaire à l'idempotence).")
        if not (document.seller_siret and document.seller_siret.isdigit() and len(document.seller_siret) == 14):
            errors.append("SIRET émetteur invalide : 14 chiffres attendus.")
        if document.document_type in (PDPDocumentType.FACTURE, PDPDocumentType.AVOIR) and not (
            document.buyer_siret or document.buyer_datex
        ):
            errors.append("Destinataire inconnu : SIRET ou code DATEX/PAGEZE requis pour Chorus Pro.")
        return errors

    def submit(self, document: PDPDocument) -> TransmissionResult:
        errors = self.validate_document(document)
        if errors:
            return TransmissionResult(accepted=False, status="rejected", messages=errors)

        # Idempotence par numéro : même facture -> même référence Chorus.
        existing = self._submitted.get(document.number)
        if existing is not None:
            logger.info("chorus-pro: dépôt idempotent pour %s", document.number)
            return existing

        metadata = {
            "instruction": {
                "mediatype": "application/pdf" if document.media_type == "application/pdf" else "application/xml",
                "schema": "facture-x" if document.media_type == "application/pdf" else "cii-xml",
                "type": "facture" if document.document_type is PDPDocumentType.FACTURE else "avoir",
                "emetteur": {"idType": "siret", "id": document.seller_siret},
                "destination": (
                    {"idType": "datex", "id": document.buyer_datex}
                    if document.buyer_datex
                    else {"idType": "siret", "id": document.buyer_siret or ""}
                ),
                "infoSupplementaire": [{"cle": "numeroFacture", "valeur": document.number}],
            }
        }
        files = {"attachedFile": (document.filename, document.content, document.media_type)}
        resp = self._call(
            "POST",
            "/apis/secure/v2/invoice",
            data={"parametresDepot": json.dumps(metadata, ensure_ascii=False)},
            files=files,
        )

        if resp.status_code in (200, 201):
            body = self._safe_json(resp)
            reference = str(body.get("uuid") or body.get("id") or "")
            if not reference:
                raise PDPTransmissionError("Chorus Pro : réponse de dépôt sans identifiant",
                                           provider=self.provider_name_property)
            result = TransmissionResult(
                accepted=True,
                external_reference=reference,
                status="transmitted",
                raw=body,
            )
            self._submitted[document.number] = result
            return result

        if resp.status_code == 400:
            body = self._safe_json(resp)
            messages = self._extract_errors(body)
            return TransmissionResult(accepted=False, status="rejected", messages=messages or ["Rejet Chorus Pro (400)."], raw=body)
        if resp.status_code == 409:
            # Doublon côté plateforme : on récupère la référence existante si possible.
            body = self._safe_json(resp)
            reference = str(body.get("uuid") or body.get("id") or "")
            result = TransmissionResult(
                accepted=True,
                external_reference=reference or None,
                status="transmitted",
                messages=["Doublon accepté (idem-potence plateforme Chorus Pro)."],
                raw=body,
            )
            if result.external_reference:
                self._submitted[document.number] = result
            return result

        raise PDPTransmissionError(
            f"Chorus Pro : dépôt refusé (HTTP {resp.status_code})",
            provider=self.provider_name_property,
            status_code=resp.status_code,
        )

    def get_status(self, external_reference: str) -> LifecycleInfo:
        if not external_reference:
            raise PDPTransmissionError("Référence vide", provider=self.provider_name_property, status_code=400)
        resp = self._call("GET", f"/apis/secure/v2/invoice/{quote(str(external_reference))}")
        if resp.status_code == 404:
            raise PDPTransmissionError(
                f"Référence inconnue : {external_reference}", provider=self.provider_name_property, status_code=404
            )
        if resp.status_code != 200:
            raise PDPTransmissionError(
                f"Chorus Pro : consultation impossible (HTTP {resp.status_code})",
                provider=self.provider_name_property,
                status_code=resp.status_code,
            )
        body = self._safe_json(resp)
        invoice = body.get("invoice", body)
        raw_state = str(invoice.get("status", "")).upper()
        state, status = _STATUS_MAP.get(raw_state, (PDPLifecycleState.INTEGRATION, "transmitted"))
        events = [
            {"type": ev.get("typeCode", "event"), "at": ev.get("horodatage")}
            for ev in invoice.get("evenements", []) or []
        ]
        return LifecycleInfo(reference=str(external_reference), state=state, status=status, events=events, raw=body)

    def cancel(self, external_reference: str) -> bool:
        # Chorus Pro n'expose pas d'annulation de facture déposée : contrat explicite.
        raise NotImplementedError("chorus_pro does not support cancellation")

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"value": data}
        except (ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _extract_errors(body: dict[str, Any]) -> list[str]:
        errors = body.get("erreurs") or body.get("errors") or []
        out: list[str] = []
        for item in errors if isinstance(errors, list) else [errors]:
            if isinstance(item, dict):
                out.append(str(item.get("message") or item.get("code") or item))
            else:
                out.append(str(item))
        return out


register_pdp_adapter(ChorusProAdapter.provider_name_property, ChorusProAdapter)
