"""Interface contractuelle PDP et implémentation de mock conforme au contrat.

Le contrat (documenté dans la docstring de ``PDPAdapter``) s'inspire des
plateformes réelles (Chorus Pro, PDP agréés GTL2 / e-delivery Peppol) :

1. ``submit(document)`` est **idempotent par numéro de document** : renvoyer
   deux fois le même document retourne le même ``external_reference`` avec
   ``accepted=True`` (pas de doublon côté plateforme).
2. Le statut initial après dépôt est soit ``ACCEPTED`` (validation synchrone),
   soit ``TRANSMITTED`` (validation asynchrone) — jamais ``REJECTED`` sans
   messages d'erreur.
3. ``get_status(reference)`` doit accepter toute référence retournée par
   ``submit`` et lever ``PDPTransmissionError`` pour une référence inconnue.
4. Les rejets comportent toujours une liste de ``messages`` non vide.
5. Toute erreur réseau/API se traduit par ``PDPTransmissionError`` ; les
   appelants ne doivent jamais voir d'exception technique brute.

``MockPDPAdapter`` respecte ce contrat et sert de référence d'implémentation
pour les tests et le développement local.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PDPTransmissionError(RuntimeError):
    """Erreur technique ou fonctionnelle remontée par une plateforme PDP."""

    def __init__(self, message: str, *, provider: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Objets valeur normalisés (indépendants du format JSON propre à chaque PDP)
# ---------------------------------------------------------------------------


class PDPDocumentType(str, Enum):
    FACTURE = "facture"                    # facture electronique entrante/sortante
    AVOIR = "avoir"                        # note de credit electronique
    ENGAGEMENT = "engagement"              # bon de commande / BIC (marche public)


class PDPLifecycleState(str, Enum):
    INTEGRATION = "integration"            # recu, en cours d'integration
    ENVOI_EN_COURS = "envoi_en_cours"      # en route vers la plateforme publique
    REMISE = "remise"                      # remis au destinataire
    DEPOSEE = "deposee"                    # deposee sur la plateforme publique
    SOUMISE = "soumise"                    # soumise a validation
    REJETEE = "rejetee"                    # rejetee par la plateforme
    TRAITEE = "traitee"                    # traitee par le destinataire


@dataclass(frozen=True)
class PDPDocument:
    """Document électronique prêt à être transmis (sortie du pipeline Factur-X)."""

    content: bytes                          # octets du document (PDF hybride ou XML)
    document_type: PDPDocumentType
    filename: str
    number: str                             # numéro de facture (clé d'idempotence)
    seller_siret: str                       # SIRET émetteur (14 chiffres)
    buyer_siret: str | None = None          # SIRET destinataire si connu
    buyer_datex: str | None = None          # code DATEX/PAGEZE du marché public
    media_type: str = "application/pdf"     # application/xml pour un CII/UBL brut
    organization_id: str | None = None      # tenant interne (traçabilité)

    def checksum(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass
class TransmissionResult:
    """Réponse normalisée d'un dépôt auprès d'une PDP."""

    accepted: bool
    external_reference: str | None = None   # id retour PDP (ex. uuid Chorus)
    status: str = "transmitted"             # statut interne mappé (TransmissionStatus)
    messages: list[str] = field(default_factory=list)  # rejets / avertissements
    raw: dict[str, Any] = field(default_factory=dict)  # payload brut (debug)


@dataclass
class LifecycleInfo:
    """État de cycle de vie d'un document déjà déposé."""

    reference: str
    state: PDPLifecycleState
    status: str                             # statut interne mappé
    events: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Interface contractuelle
# ---------------------------------------------------------------------------


class PDPAdapter(ABC):
    """Interface que toute Plateforme de Dématérialisation doit implémenter.

    Méthodes obligatoires :

    - ``provider_name`` (propriété) : identifiant stable du fournisseur
      (``"mock"``, ``"chorus_pro"``, ``"pdp_xxx"``…) — correspond à
      ``Transmission.pdp_provider``.
    - ``validate_document(document)`` : validation *locale* pré-dépôt
      (format, taille, SIRET…). Doit retourner une liste de messages
      d'erreur (vide si OK). Ne lève pas d'exception pour un document
      invalide.
    - ``submit(document)`` : dépose le document. Respecte l'idempotence par
      ``document.number`` (cf. contrat module). Lève ``PDPTransmissionError``
      sur échec technique.
    - ``get_status(external_reference)`` : interroge le cycle de vie.
    - ``cancel(external_reference)`` : annule un dépôt encore rétractable ;
      ``NotImplementedError`` si la plateforme ne le permet pas.

    Garanties pour les appelants : aucun détail d'authentification ou de
    transport n'est exposé ; toutes les erreurs sont typées.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:  # pragma: no cover - signature abstraite
        ...

    @abstractmethod
    def validate_document(self, document: PDPDocument) -> list[str]:
        """Validation locale pré-dépôt ; retourne la liste des erreurs (vide = OK)."""

    @abstractmethod
    def submit(self, document: PDPDocument) -> TransmissionResult:
        """Dépôt idempotent du document auprès de la plateforme."""

    @abstractmethod
    def get_status(self, external_reference: str) -> LifecycleInfo:
        """Cycle de vie d'un document déposé ; lève PDPTransmissionError si inconnu."""

    def cancel(self, external_reference: str) -> bool:
        """Annulation optionnelle ; False si non annulable, NotImplementedError si non supporté."""
        raise NotImplementedError(f"{self.provider_name} does not support cancellation")


# ---------------------------------------------------------------------------
# Mock contractuel (référence d'implémentation pour tests / dev)
# ---------------------------------------------------------------------------


class MockPDPAdapter(PDPAdapter):
    """Implémentation de test conforme au contrat ``PDPAdapter``.

    Comportement déterministe :
    - idempotence par ``document.number`` (même référence, même résultat) ;
    - rejet si le contenu n'est pas un PDF/XML plausible ou si les métadonnées
      obligatoires manquent (messages non vides, ``accepted=False``) ;
    - ``force_reject_for`` permet de simuler un rejet par numéro ;
    - ``fail_mode`` permet de simuler une panne réseau (PDPTransmissionError) ;
    - cycle de vie qui progresse : integration → envoi_en_cours → remise
      (à chaque appel de ``get_status``, manière simple et testable).
    """

    provider_name_property: ClassVar[str] = "mock"

    def __init__(
        self,
        *,
        force_reject_for: set[str] | None = None,
        fail_mode: bool = False,
        deterministic_refs: bool = False,
    ):
        self._documents: dict[str, dict[str, Any]] = {}   # number -> dossier
        self._by_reference: dict[str, str] = {}           # reference -> number
        self.force_reject_for = set(force_reject_for or ())
        self.fail_mode = fail_mode
        self.deterministic_refs = deterministic_refs

    # -- contrat -------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return self.provider_name_property

    def validate_document(self, document: PDPDocument) -> list[str]:
        errors: list[str] = []
        if not document.content:
            errors.append("Contenu du document vide.")
        elif not (document.content.startswith(b"%PDF") or document.content.lstrip().startswith(b"<")):
            errors.append("Format non supporté : attendu PDF (Factur-X) ou XML (CII/UBL).")
        if len(document.content) > 4_500_000:
            errors.append("Document trop volumineux (limite plateforme ~4,5 Mo).")
        if not document.number.strip():
            errors.append("Numéro de document manquant (nécessaire à l'idempotence).")
        if not (document.seller_siret and document.seller_siret.isdigit() and len(document.seller_siret) == 14):
            errors.append("SIRET émetteur invalide : 14 chiffres attendus.")
        return errors

    def submit(self, document: PDPDocument) -> TransmissionResult:
        if self.fail_mode:
            raise PDPTransmissionError("Plateforme indisponible (simulée)", provider=self.provider_name, status_code=503)

        errors = self.validate_document(document)
        if document.number in self.force_reject_for:
            errors = errors + ["Rejet simulé par la plateforme (règle métier)."]
        if errors:
            return TransmissionResult(accepted=False, status="rejected", messages=errors)

        # Idempotence : même numéro -> même référence, même résultat.
        existing = self._documents.get(document.number)
        if existing:
            logger.info("mock-pdp: dépôt idempotent pour %s", document.number)
            return existing["result"]

        if self.deterministic_refs:
            reference = hashlib.sha256(document.number.encode()).hexdigest()[:36]
        else:
            reference = str(uuid.uuid4())
        info = {
            "reference": reference,
            "checksum": document.checksum(),
            "submitted_at": datetime.now(timezone.utc),
            "poll_count": 0,
            "cancelled": False,
        }
        result = TransmissionResult(
            accepted=True,
            external_reference=reference,
            status="transmitted",
            raw={"provider": self.provider_name, "filename": document.filename},
        )
        info["result"] = result
        self._documents[document.number] = info
        self._by_reference[reference] = document.number
        return result

    def get_status(self, external_reference: str) -> LifecycleInfo:
        number = self._by_reference.get(external_reference)
        if number is None:
            raise PDPTransmissionError(
                f"Référence inconnue : {external_reference}", provider=self.provider_name, status_code=404
            )
        info = self._documents[number]
        if info["cancelled"]:
            return LifecycleInfo(reference=external_reference, state=PDPLifecycleState.REJETEE,
                                 status="rejected", events=[{"type": "cancelled"}])
        # Progression déterministe du cycle de vie à chaque interrogation.
        sequence = [
            PDPLifecycleState.INTEGRATION,
            PDPLifecycleState.ENVOI_EN_COURS,
            PDPLifecycleState.REMISE,
        ]
        idx = min(info["poll_count"], len(sequence) - 1)
        state = sequence[idx]
        info["poll_count"] += 1
        status_map = {
            PDPLifecycleState.INTEGRATION: "transmitted",
            PDPLifecycleState.ENVOI_EN_COURS: "transmitted",
            PDPLifecycleState.REMISE: "accepted",
        }
        return LifecycleInfo(
            reference=external_reference,
            state=state,
            status=status_map[state],
            events=[{"type": state.value, "at": datetime.now(timezone.utc).isoformat()}],
        )

    def cancel(self, external_reference: str) -> bool:
        number = self._by_reference.get(external_reference)
        if number is None:
            raise PDPTransmissionError(
                f"Référence inconnue : {external_reference}", provider=self.provider_name, status_code=404
            )
        info = self._documents[number]
        if info["poll_count"] >= 2:  # trop tard : déjà remis au destinataire
            return False
        info["cancelled"] = True
        return True


# ---------------------------------------------------------------------------
# Registre / fabrique
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[PDPAdapter]] = {MockPDPAdapter.provider_name_property: MockPDPAdapter}


def register_pdp_adapter(name: str, cls: type[PDPAdapter]) -> None:
    """Enregistre un adaptateur PDP sous ``name`` (appelé par les intégrations)."""
    if not issubclass(cls, PDPAdapter):
        raise TypeError(f"{cls!r} must implement PDPAdapter")
    _REGISTRY[name] = cls


def registered_providers() -> list[str]:
    return sorted(_REGISTRY)


def get_pdp_adapter(provider: str, **config: Any) -> PDPAdapter:
    """Fabrique l'adaptateur du fournisseur enregistré.

    Lève ``PDPTransmissionError`` si le fournisseur est inconnu — comportement
    identique à celui d'un appelant face à une configuration erronée.
    """
    cls = _REGISTRY.get(provider)
    if cls is None:
        raise PDPTransmissionError(
            f"Fournisseur PDP inconnu : {provider!r}. Providers disponibles : {registered_providers()}",
            provider=provider,
            status_code=None,
        )
    return cls(**config)
