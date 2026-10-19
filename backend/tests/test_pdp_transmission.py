"""Tests de l'interface PDPAdapter et du mock contractuel.

Deux niveaux :
1. ``TestPDPContract``  : vérifie que ``MockPDPAdapter`` respecte le contrat
   (idempotence, rejets typés, erreurs techniques, cycle de vie) — ces tests
   servent de **suite contractuelle** réutilisable pour toute future PDP.
2. ``TestTransmissionAPI`` : bout-en-bout via FastAPI — dépôt d'une facture
   émise, idempotence HTTP, rafraîchissement du cycle de vie, fournisseurs.

Les tests d'API utilisent un adaptateur d'intégration enregistré sous le nom
``mock`` : ils valident tout le pipeline (génération de document, service,
persistance, endpoints) sans dépendre des aléas de ReportLab dans l'env de test.
"""
import pytest

from app.models import Organization, Transmission
from app.services.pdp.adapter import (
    LifecycleInfo,
    MockPDPAdapter,
    PDPAdapter,
    PDPDocument,
    PDPDocumentType,
    PDPLifecycleState,
    PDPTransmissionError,
    get_pdp_adapter,
    register_pdp_adapter,
    registered_providers,
)


def make_doc(number: str = "F-2026-001", content: bytes = b"<xml/>", siret: str = "12345678901234") -> PDPDocument:
    return PDPDocument(
        content=content,
        document_type=PDPDocumentType.FACTURE,
        filename=f"{number}.xml",
        number=number,
        seller_siret=siret,
        buyer_siret="98765432109876",
        media_type="application/xml",
    )


# ---------------------------------------------------------------------------
# Suite contractuelle (MockPDPAdapter)
# ---------------------------------------------------------------------------


class TestPDPContract:
    def setup_method(self):
        self.adapter = MockPDPAdapter()

    def test_is_pdp_adapter(self):
        assert isinstance(self.adapter, PDPAdapter)
        assert self.adapter.provider_name == "mock"

    def test_valid_document_accepted(self):
        result = self.adapter.submit(make_doc())
        assert result.accepted is True
        assert result.external_reference
        assert result.status == "transmitted"

    def test_submit_is_idempotent_by_number(self):
        """Règle 1 du contrat : même numéro -> même référence, pas de doublon."""
        first = self.adapter.submit(make_doc("F-IDEM"))
        second = self.adapter.submit(make_doc("F-IDEM"))
        assert second.accepted is True
        assert second.external_reference == first.external_reference

    def test_reject_has_messages(self):
        """Règle 4 du contrat : rejet => messages non vides, accepted=False."""
        result = self.adapter.submit(make_doc(content=b"not a pdf or xml"))
        assert result.accepted is False
        assert result.status == "rejected"
        assert len(result.messages) > 0

    def test_validate_document_rejects_bad_siret(self):
        errors = self.adapter.validate_document(make_doc(siret="123"))
        assert any("SIRET" in e for e in errors)

    def test_validate_document_rejects_empty_content(self):
        errors = self.adapter.validate_document(make_doc(content=b""))
        assert any("vide" in e.lower() for e in errors)

    def test_pdf_facturx_accepted(self):
        result = self.adapter.submit(make_doc(content=b"%PDF-1.7 fake hybrid invoice"))
        assert result.accepted is True

    def test_unknown_reference_raises_typed_error(self):
        """Règle 3 du contrat : référence inconnue => PDPTransmissionError."""
        with pytest.raises(PDPTransmissionError) as excinfo:
            self.adapter.get_status("does-not-exist")
        assert excinfo.value.status_code == 404

    def test_lifecycle_progresses_to_accepted(self):
        ref = self.adapter.submit(make_doc()).external_reference
        states = [self.adapter.get_status(ref).state for _ in range(3)]
        assert states[0] == PDPLifecycleState.INTEGRATION
        assert states[-1] == PDPLifecycleState.REMISE
        final = self.adapter.get_status(ref)
        assert isinstance(final, LifecycleInfo)
        assert final.status == "accepted"

    def test_fail_mode_raises_technical_error(self):
        """Règle 5 du contrat : panne plateforme => erreur typée."""
        adapter = MockPDPAdapter(fail_mode=True)
        with pytest.raises(PDPTransmissionError) as excinfo:
            adapter.submit(make_doc())
        assert excinfo.value.status_code == 503

    def test_force_reject_for(self):
        adapter = MockPDPAdapter(force_reject_for={"F-BAD"})
        result = adapter.submit(make_doc("F-BAD"))
        assert result.accepted is False
        assert any("simulé" in m for m in result.messages)

    def test_cancel_before_delivery(self):
        ref = self.adapter.submit(make_doc()).external_reference
        assert self.adapter.cancel(ref) is True
        assert self.adapter.get_status(ref).status == "rejected"

    def test_deterministic_refs_option(self):
        a = MockPDPAdapter(deterministic_refs=True)
        b = MockPDPAdapter(deterministic_refs=True)
        assert a.submit(make_doc("F-DET")).external_reference == b.submit(make_doc("F-DET")).external_reference


class TestPDPRegistry:
    def test_factory_returns_mock(self):
        assert isinstance(get_pdp_adapter("mock"), MockPDPAdapter)

    def test_factory_unknown_provider(self):
        with pytest.raises(PDPTransmissionError):
            get_pdp_adapter("chorus_inexistante")

    def test_registered_providers_contains_mock(self):
        assert "mock" in registered_providers()

    def test_register_custom_adapter(self):
        class Dummy(MockPDPAdapter):
            provider_name_property = "dummy"

        register_pdp_adapter("dummy", Dummy)
        try:
            assert isinstance(get_pdp_adapter("dummy"), Dummy)
        finally:
            # nettoie le registre global
            from app.services.pdp import adapter as mod

            mod._REGISTRY.pop("dummy", None)

    def test_register_rejects_non_adapter(self):
        with pytest.raises(TypeError):
            register_pdp_adapter("bad", dict)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Bout-en-bout API
# ---------------------------------------------------------------------------


@pytest.fixture
def issued_invoice(client, db_session, auth_headers):
    """Crée une organisation avec SIRET + client, une facture émise; retourne ids/headers."""
    headers = auth_headers()

    cust = client.post(
        "/v1/customers",
        json={"name": "Client PDP", "email": "pdp@client.fr", "tax_id": "FR44444444444"},
        headers=headers,
    )
    assert cust.status_code == 201, cust.text
    customer_id = cust.json()["id"]

    inv = client.post(
        "/v1/invoices",
        json={
            "customer_id": customer_id,
            "number": "PDP-001",
            "currency": "EUR",
            "lines": [
                {"description": "Prestation", "quantity": "2", "unit_price_minor": 15000, "tax_rate": "20"},
            ],
        },
        headers=headers,
    )
    assert inv.status_code == 201, inv.text
    invoice_id = inv.json()["id"]

    issue = client.post(f"/v1/invoices/{invoice_id}/issue", headers=headers)
    assert issue.status_code == 200, issue.text

    # SIRET émetteur valide sur l'organisation (requis par le contrat PDP)
    from app.models import Invoice

    invoice = db_session.get(Invoice, invoice_id)
    organization = db_session.get(Organization, invoice.organization_id)
    organization.siret = "52231012456789"  # 14 chiffres
    db_session.commit()
    return invoice_id, headers


@pytest.fixture
def integration_mock():
    """Enregistre un adaptateur d'intégration (validation assouplie sur le
    contenu, métadonnées strictes) sous le nom ``mock`` pour les tests d'API."""
    from datetime import datetime as _dt

    class IntegrationMock(MockPDPAdapter):
        def validate_document(self, document):
            errors = []
            if not document.number.strip():
                errors.append("Numéro manquant.")
            if not (document.seller_siret.isdigit() and len(document.seller_siret) == 14):
                errors.append("SIRET émetteur invalide.")
            if not document.content:
                errors.append("Contenu vide.")
            return errors

        def submit(self, document):
            errors = self.validate_document(document)
            if errors:
                from app.services.pdp.adapter import TransmissionResult

                return TransmissionResult(accepted=False, status="rejected", messages=errors)
            existing = self._documents.get(document.number)
            if existing:
                return existing["result"]
            ref = f"chorus-{document.number}"
            info = {
                "reference": ref,
                "checksum": document.checksum(),
                "submitted_at": _dt.now(),
                "poll_count": 0,
                "cancelled": False,
            }
            from app.services.pdp.adapter import TransmissionResult

            transmitted = TransmissionResult(accepted=True, external_reference=ref, status="transmitted")
            info["result"] = transmitted
            self._documents[document.number] = info
            self._by_reference[ref] = document.number
            return transmitted

    instance = IntegrationMock()
    import app.services.transmission_service as ts

    real_get = ts.get_pdp_adapter
    ts.get_pdp_adapter = lambda provider, **kw: instance if provider == "mock" else real_get(provider, **kw)
    yield instance
    ts.get_pdp_adapter = real_get


class TestTransmissionAPI:
    @pytest.fixture(autouse=True)
    def _use_integration_mock(self, integration_mock):
        self.pdp = integration_mock

    def test_providers_list(self, client, auth_headers):
        r = client.get("/v1/transmissions/providers", headers=auth_headers())
        assert r.status_code == 200
        assert "mock" in r.json()["providers"]

    def test_submit_transmission(self, client, auth_headers, issued_invoice):
        invoice_id, headers = issued_invoice
        r = client.post(
            "/v1/transmissions",
            json={"invoice_id": invoice_id, "provider": "mock", "format": "xml"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["pdp_provider"] == "mock"
        assert body["status"] == "transmitted"
        assert body["external_reference"] == "chorus-PDP-001"
        assert body["error_message"] is None

    def test_submit_is_idempotent_over_http(self, client, auth_headers, issued_invoice):
        invoice_id, headers = issued_invoice
        payload = {"invoice_id": invoice_id, "provider": "mock", "format": "xml"}
        first = client.post("/v1/transmissions", json=payload, headers=headers)
        second = client.post("/v1/transmissions", json=payload, headers=headers)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["external_reference"] == second.json()["external_reference"]

    def test_submit_unknown_invoice_404(self, client, auth_headers):
        r = client.post(
            "/v1/transmissions",
            json={"invoice_id": "nope", "provider": "mock"},
            headers=auth_headers(),
        )
        assert r.status_code == 404

    def test_submit_unknown_provider_502(self, client, auth_headers, issued_invoice):
        invoice_id, headers = issued_invoice
        r = client.post(
            "/v1/transmissions",
            json={"invoice_id": invoice_id, "provider": "pdp_inconnue"},
            headers=headers,
        )
        assert r.status_code == 502
        assert "inconnu" in r.json()["detail"]

    def test_refresh_lifecycle(self, client, auth_headers, issued_invoice, db_session):
        invoice_id, headers = issued_invoice
        tx = client.post(
            "/v1/transmissions",
            json={"invoice_id": invoice_id, "provider": "mock", "format": "xml"},
            headers=headers,
        ).json()
        assert tx["status"] == "transmitted"

        refreshed = client.post(f"/v1/transmissions/{tx['id']}/refresh", headers=headers)
        assert refreshed.status_code == 200
        # integration -> toujours transmitted puis remise -> accepted au 3e poll
        assert refreshed.json()["status"] in ("transmitted", "accepted")

        last = tx["id"]
        statuses = []
        for _ in range(3):
            rr = client.post(f"/v1/transmissions/{last}/refresh", headers=headers)
            assert rr.status_code == 200
            statuses.append(rr.json()["status"])
        assert "accepted" in statuses

    def test_list_and_filter_transmissions(self, client, auth_headers, issued_invoice):
        invoice_id, headers = issued_invoice
        client.post(
            "/v1/transmissions",
            json={"invoice_id": invoice_id, "provider": "mock", "format": "xml"},
            headers=headers,
        )
        r = client.get(f"/v1/transmissions?invoice_id={invoice_id}", headers=headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["invoice_id"] == invoice_id

        r2 = client.get("/v1/transmissions?provider=mock&status=transmitted", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["total"] >= 1

    def test_requires_auth(self, client):
        r = client.get("/v1/transmissions")
        assert r.status_code == 401

    def test_invalid_siret_rejected_via_api(self, client, auth_headers, issued_invoice, db_session):
        invoice_id, headers = issued_invoice
        from app.models import Invoice

        invoice = db_session.get(Invoice, invoice_id)
        org = db_session.get(Organization, invoice.organization_id)
        org.siret = "123"  # SIRET tronqué -> rejet contractuel
        db_session.commit()

        r = client.post(
            "/v1/transmissions",
            json={"invoice_id": invoice_id, "provider": "mock", "format": "xml"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "rejected"
        assert body["error_message"] and "SIRET" in body["error_message"]

    def test_service_maps_rejection_to_db(self, db_session, test_organization):
        """Rejet fonctionnel persisté sans exception (statut rejected + message)."""
        from app.models import Customer, Invoice, InvoiceLine
        from app.services.transmission_service import TransmissionService
        from decimal import Decimal
        from datetime import datetime, timezone

        test_organization.siret = "52231012456789"
        customer = Customer(name="C", organization_id=test_organization.id)
        invoice = Invoice(
            organization_id=test_organization.id,
            customer_id=customer.id,
            number="REJ-001",
            status="issued",
            issue_date=datetime.now(timezone.utc),
            subtotal_minor=1000, tax_total_minor=200, total_minor=1200, amount_due_minor=1200,
        )
        line = InvoiceLine(
            organization_id=test_organization.id, invoice_id=invoice.id,
            description="L", quantity=Decimal("1"), unit="unit", unit_price_minor=1000,
            tax_rate=Decimal("20"), tax_amount_minor=200, line_total_minor=1000, line_gross_minor=1200,
        )
        db_session.add_all([test_organization, customer, invoice, line])
        db_session.commit()

        service = TransmissionService(db_session)
        rejecting = MockPDPAdapter(force_reject_for={"REJ-001"})

        # injection directe de l'adaptateur de test dans la fabrique
        import app.services.transmission_service as ts

        real_get = ts.get_pdp_adapter
        ts.get_pdp_adapter = lambda provider, **kw: rejecting
        try:
            tx = service.submit_invoice(test_organization, invoice.id, provider="mock")
        finally:
            ts.get_pdp_adapter = real_get

        assert tx.status == "rejected"
        assert tx.error_message and "simulé" in tx.error_message
        assert tx.attempt_count == 1
        stored = db_session.query(Transmission).filter_by(invoice_id=invoice.id).one()
        assert stored.status == "rejected"
