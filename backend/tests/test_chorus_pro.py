"""Tests du connecteur Chorus Pro et du chiffrement des credentials.

Trois niveaux :
1. ``TestCrypto``          : aller-retour Fernet, clés invalides, politique
   production (clair refusé).
2. ``TestChorusProContract``: la suite contractuelle PDP réutilisable, jouée
   contre ``ChorusProAdapter`` avec un faux transport HTTP injectable —
   valide OAuth2, dépôt multipart, idempotence, rejets 400/409, cycle de vie.
3. ``TestChorusProService`` : intégration avec ``TransmissionService`` via les
   variables d'environnement de credentials (mockées).

Aucun appel réseau réel : le transport est toujours injecté.
"""
import pytest

from app.crypto import (
    CredentialsKeyError,
    decrypt_secret,
    encrypt_secret,
    looks_encrypted,
    resolve_secret,
)
from app.services.pdp.adapter import (
    PDPDocument,
    PDPDocumentType,
    PDPLifecycleState,
    PDPTransmissionError,
    get_pdp_adapter,
    registered_providers,
)
from app.services.pdp.chorus_pro import ChorusProAdapter


# ---------------------------------------------------------------------------
# Faux transport HTTP (aucun réseau)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, payload=None, raw: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeTransport:
    """Enregistre les requêtes et répond selon un script (method, path)->resp."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        # Le jeton OAuth est servi automatiquement sauf script contraire.
        if url.endswith("/oauth/token") and not any(
            r[0] == "POST" and r[1].endswith("/oauth/token") for r in self.responses
        ):
            return FakeResponse(200, {"access_token": "tok-123", "expires_in": 3600})
        for i, (m, suffix, resp) in enumerate(self.responses):
            if method == m and url.endswith(suffix):
                self.responses.pop(i)
                return resp
        raise AssertionError(f"unexpected request {method} {url}")

    def token_calls(self):
        return [c for c in self.calls if c[1].endswith("/oauth/token")]


def chorus_doc(number="FAC-001", content=b"%PDF-1.4 fake", siret="12345678901234", buyer_siret="98765432109876"):
    return PDPDocument(
        content=content,
        document_type=PDPDocumentType.FACTURE,
        filename=f"{number}.pdf",
        number=number,
        seller_siret=siret,
        buyer_siret=buyer_siret,
        media_type="application/pdf",
    )


def make_adapter(responses, **kw):
    transport = FakeTransport(responses)
    adapter = ChorusProAdapter(api_key="secret-client", username="tech-id", http_client=transport, **kw)
    return adapter, transport


# ---------------------------------------------------------------------------
# 1. Chiffrement des credentials
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_roundtrip(self):
        token = encrypt_secret("mot-de-passe-api")
        assert looks_encrypted(token)
        assert decrypt_secret(token) == "mot-de-passe-api"
        assert "mot-de-passe-api" not in token

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            encrypt_secret("")

    def test_resolve_passthrough_and_encrypted(self):
        assert resolve_secret("") == ""
        assert resolve_secret("clair-en-dev") == "clair-en-dev"
        enc = encrypt_secret("super-secret")
        assert resolve_secret(enc) == "super-secret"

    def test_corrupted_token(self):
        with pytest.raises(CredentialsKeyError):
            decrypt_secret("gAAAAABx-not-a-valid-token")

    def test_production_requires_explicit_key(self, monkeypatch):
        from app.config import settings_clear_cache

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("JWT_SECRET", "prod-jwt-secret-value")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
        monkeypatch.delenv("CREDENTIALS_KEY", raising=False)
        settings_clear_cache()
        try:
            # Sans CREDENTIALS_KEY explicite : refus en production.
            with pytest.raises(CredentialsKeyError):
                encrypt_secret("x")
            # Avec une cle Fernet valide : chiffrement autorisé.
            monkeypatch.setenv("CREDENTIALS_KEY", _fernet_key())
            settings_clear_cache()
            assert decrypt_secret(encrypt_secret("y")) == "y"
        finally:
            settings_clear_cache()


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# 2. Contrat ChorusProAdapter (suite contractuelle sur faux transport)
# ---------------------------------------------------------------------------


class TestChorusProContract:
    def test_registered_in_registry(self):
        assert "chorus_pro" in registered_providers()
        with pytest.raises(PDPTransmissionError):
            get_pdp_adapter("chorus_pro")  # api_key manquant -> erreur typée

    def test_requires_api_key(self):
        with pytest.raises(PDPTransmissionError):
            ChorusProAdapter(api_key="")

    def test_credentials_stored_encrypted(self):
        adapter, _ = make_adapter([])
        assert adapter._encrypted_api_key != "secret-client"
        assert looks_encrypted(adapter._encrypted_api_key)
        assert adapter.client_secret == "secret-client"
        assert "secret-client" not in repr(vars(adapter))

    def test_oauth_flow_and_submit(self):
        uuid_ref = "a1b2c3d4-0000-0000-0000-000000000001"
        adapter, transport = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(201, {"uuid": uuid_ref})),
        ])
        result = adapter.submit(chorus_doc())
        assert result.accepted is True
        assert result.external_reference == uuid_ref
        assert result.status == "transmitted"
        # Un seul appel token, puis dépôt avec Bearer.
        assert len(transport.token_calls()) == 1
        submit_call = next(c for c in transport.calls if "invoice" in c[1])
        headers = submit_call[2]["headers"]
        assert headers["Authorization"] == "Bearer tok-123"
        assert headers["X-Chorus-Pro-Acces-IdTechnique"] == "tech-id"
        # Multipart : le fichier est bien transmis.
        files = submit_call[2]["files"]
        assert files["attachedFile"][1] == b"%PDF-1.4 fake"

    def test_idempotence_by_number(self):
        uuid_ref = "ref-idem"
        adapter, transport = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(201, {"uuid": uuid_ref})),
        ])
        first = adapter.submit(chorus_doc(number="FAC-IDEM"))
        second = adapter.submit(chorus_doc(number="FAC-IDEM"))
        assert first.external_reference == second.external_reference
        depots = [c for c in transport.calls if "/invoice" in c[1]]
        assert len(depots) == 1  # pas de doublon envoyé à la plateforme

    def test_local_validation_rejects_bad_document(self):
        adapter, transport = make_adapter([])
        bad = chorus_doc(content=b"not-a-pdf", siret="123")
        result = adapter.submit(bad)
        assert result.accepted is False
        assert result.messages
        assert transport.calls == []  # rien n'a quitté l'application

    def test_missing_destination_rejected(self):
        adapter, _ = make_adapter([])
        doc = chorus_doc(buyer_siret=None)
        result = adapter.submit(doc)
        assert result.accepted is False
        assert any("DATEX" in m or "SIRET" in m for m in result.messages)

    def test_platform_rejection_400_has_messages(self):
        adapter, _ = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(400, {
                "erreurs": [{"code": "SCHMA_001", "message": "Facture non conforme EN16931"}]
            })),
        ])
        result = adapter.submit(chorus_doc())
        assert result.accepted is False
        assert result.status == "rejected"
        assert "Facture non conforme EN16931" in result.messages

    def test_duplicate_409_accepted_idempotent(self):
        adapter, _ = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(409, {"uuid": "existing-ref"})),
        ])
        result = adapter.submit(chorus_doc(number="FAC-DUP"))
        assert result.accepted is True
        assert result.external_reference == "existing-ref"

    def test_technical_error_5xx_raises_typed(self):
        adapter, _ = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(503, {"erreur": "maintenance"})),
        ])
        with pytest.raises(PDPTransmissionError) as exc:
            adapter.submit(chorus_doc())
        assert exc.value.status_code == 503
        assert exc.value.provider == "chorus_pro"

    def test_token_refresh_on_401(self):
        uuid_ref = "after-retry"
        adapter, transport = make_adapter([
            ("POST", "/apis/secure/v2/invoice", FakeResponse(401, {})),
            ("POST", "/apis/secure/v2/invoice", FakeResponse(201, {"uuid": uuid_ref})),
        ])
        result = adapter.submit(chorus_doc())
        assert result.accepted is True
        assert len(transport.token_calls()) == 2  # renouvellement unique

    def test_get_status_mapping(self):
        adapter, transport = make_adapter([
            ("GET", "/apis/secure/v2/invoice/ref-9", FakeResponse(200, {
                "invoice": {
                    "status": "REMISE",
                    "evenements": [{"typeCode": "REMISE", "horodatage": "2026-10-19T08:00:00Z"}],
                }
            })),
        ])
        info = adapter.get_status("ref-9")
        assert info.state is PDPLifecycleState.REMISE
        assert info.status == "accepted"
        assert info.events[0]["type"] == "REMISE"

    def test_get_status_unknown_reference(self):
        adapter, _ = make_adapter([
            ("GET", "/apis/secure/v2/invoice/nope", FakeResponse(404, {})),
        ])
        with pytest.raises(PDPTransmissionError) as exc:
            adapter.get_status("nope")
        assert exc.value.status_code == 404

    def test_cancel_not_supported(self):
        adapter, _ = make_adapter([])
        with pytest.raises(NotImplementedError):
            adapter.cancel("whatever")


# ---------------------------------------------------------------------------
# 3. Intégration TransmissionService <-> chorus_pro (credentials par env)
# ---------------------------------------------------------------------------


class TestChorusProServiceIntegration:
    def test_missing_credentials_raises(self, monkeypatch):
        import app.services.transmission_service as ts

        monkeypatch.delenv("PDP_CHORUS_PRO_API_KEY", raising=False)
        service = ts.TransmissionService(None)  # pas de DB pour ce test unitaire
        with pytest.raises(PDPTransmissionError):
            service._build_adapter("chorus_pro")

    def test_build_adapter_from_env_plain_and_encrypted(self, monkeypatch):
        import app.services.transmission_service as ts

        monkeypatch.setenv("PDP_CHORUS_PRO_API_KEY", "clair-test")
        service = ts.TransmissionService(None)  # pas de DB pour ce test unitaire
        adapter = service._build_adapter("chorus_pro")
        assert isinstance(adapter, ChorusProAdapter)
        assert adapter.client_secret == "clair-test"

        encrypted = encrypt_secret("chiffre-test")
        monkeypatch.setenv("PDP_CHORUS_PRO_API_KEY", encrypted)
        adapter2 = service._build_adapter("chorus_pro")
        assert adapter2.client_secret == "chiffre-test"
