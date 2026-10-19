"""Tests des formats de facturation électronique (EN 16931).

Couvre :
- la sémantique (unités UNECE, catégories TVA UNTDID 5305) ;
- le XML Factur-X CII (structure, namespaces, montants) ;
- l'hybride Factur-X (XML réellement extractible du PDF) ;
- l'export UBL 2.1 ;
- les endpoints d'export de l'API.
"""
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from app.core.einvoicing import (
    TAX_CATEGORY_AE,
    TAX_CATEGORY_VAT,
    TAX_CATEGORY_ZE,
    to_unece_unit,
    tax_category_for_rate,
    tax_exemption_reason,
)
from app.models import Customer, Invoice, InvoiceLine, Organization
from app.services.einvoicing import (
    InvoiceDocumentData,
    LineData,
    PartyData,
    build_cii_xml,
    embed_xml_in_pdf,
    facturx_xmp_packet,
    generate_factur_x,
    generate_ubl_xml,
    minor_to_major,
)
from app.services.einvoicing_factory import document_from_invoice

NS_R = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def _local(parent, tag):
    """Sélecteur robuste : le namespace udt:* est parfois redéclaré avec un
    préfixe différent par les générateurs ; on filtre donc sur local-name().
    lxml ne supporte pas local-name() dans find(), d'où etree.xpath."""
    return parent.xpath(f"*[local-name()='{tag}']")[0]


def _amount_text(el) -> str:
    """Contenu textuel normalisé (les XML pretty-printés portent des nœuds de
    whitespace avant la valeur)."""
    return (el.text or "").strip()


@pytest.fixture
def sample_doc() -> InvoiceDocumentData:
    return InvoiceDocumentData(
        number="FACT-2026-0001",
        issue_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        due_date=datetime(2026, 3, 31, tzinfo=timezone.utc),
        currency="EUR",
        seller=PartyData(
            name="Vendeur SA",
            street="1 rue du Commerce",
            zip="75001",
            city="Paris",
            country="FR",
            siret="12345678901234",
            vat_id="FR12345678901",
            contact_email="compta@vendeur.fr",
        ),
        buyer=PartyData(
            name="Client SARL",
            street="5 avenue des Champs",
            zip="69001",
            city="Lyon",
            country="FR",
            siret="98765432109876",
            vat_id="FR98765432109",
        ),
        lines=[
            LineData(
                id="1",
                description="Prestation de conseil",
                quantity=Decimal("10"),
                unit="hour",
                unit_price_minor=15000,
                line_total_minor=150000,
                tax_rate=Decimal("20"),
                tax_amount_minor=30000,
                gross_amount_minor=180000,
            ),
            LineData(
                id="2",
                description="Exonération formation",
                quantity=Decimal("1"),
                unit="unit",
                unit_price_minor=50000,
                line_total_minor=50000,
                tax_rate=Decimal("0"),
                tax_amount_minor=0,
                gross_amount_minor=50000,
            ),
        ],
        subtotal_minor=200000,
        tax_total_minor=30000,
        total_minor=230000,
        paid_minor=0,
        due_minor=230000,
        order_reference="PO-42",
        notes=["Merci de régler sous 30 jours"],
    )


# ---------------------------------------------------------------------------
# Sémantique EN 16931
# ---------------------------------------------------------------------------

class TestSemantics:
    def test_unit_conversion(self):
        assert to_unece_unit("hour") == "HUR"
        assert to_unece_unit("unit") == "H87"
        assert to_unece_unit("day") == "DAY"
        # déjà en code UNECE
        assert to_unece_unit("KGM") == "KGM"
        # inconnu -> repli H87 (BR-08 : ne jamais émettre de code invalide)
        assert to_unece_unit("machin") == "H87"
        assert to_unece_unit(None) == "H87"

    def test_tax_categories(self):
        assert tax_category_for_rate(Decimal("20")) == TAX_CATEGORY_VAT
        assert tax_category_for_rate(Decimal("0")) == TAX_CATEGORY_ZE
        # BR-CO-04 : un taux nul exige un motif d'exonération
        assert tax_exemption_reason(TAX_CATEGORY_ZE) is not None
        assert tax_exemption_reason(TAX_CATEGORY_AE) is not None
        assert tax_exemption_reason(TAX_CATEGORY_VAT) is None

    def test_minor_to_major(self):
        assert minor_to_major(123456) == Decimal("1234.56")
        assert minor_to_major(None) == Decimal("0.00")


# ---------------------------------------------------------------------------
# XML Factur-X (CII)
# ---------------------------------------------------------------------------

class TestFacturXXml:
    def test_valid_well_formed_xml(self, sample_doc):
        xml_bytes = build_cii_xml(sample_doc)
        root = etree.fromstring(xml_bytes)
        assert root.tag == f"{{{NS_R}}}CrossIndustryInvoice"

    def test_guideline_profile(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        guideline = root.find(f".//{{{NS_RAM}}}GuidelineSpecifiedDocumentContextParameter/{{{NS_RAM}}}ID")
        assert guideline is not None
        assert "factur-x" in guideline.text

    def test_header_fields(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        exd = root.find(f"{{{NS_R}}}ExchangedDocument")
        assert exd.find(f"{{{NS_RAM}}}ID").text == "FACT-2026-0001"
        assert exd.find(f"{{{NS_RAM}}}TypeCode").text == "380"
        issue = _local(exd.find(f"{{{NS_RAM}}}IssueDateTime"), "DateTimeString")
        assert issue.text == "2026-03-01"
        assert issue.get("format") == "102"

    def test_parties_and_vat_ids(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        ag = root.find(f"{{{NS_R}}}SupplyChainTradeTransaction/{{{NS_RAM}}}ApplicableHeaderTradeAgreement")
        seller = ag.find(f"{{{NS_RAM}}}SellerTradeParty")
        buyer = ag.find(f"{{{NS_RAM}}}BuyerTradeParty")
        assert seller.find(f"{{{NS_RAM}}}Name").text == "Vendeur SA"
        assert buyer.find(f"{{{NS_RAM}}}PostalTradeAddress/{{{NS_RAM}}}CityName").text == "Lyon"
        # TVA enregistrée schemeID=VA (BR-CO-25)
        va = seller.find(f".//{{{NS_RAM}}}SpecifiedTaxRegistration/{{{NS_RAM}}}ID")
        assert va.get("schemeID") == "VA"
        assert va.text == "FR12345678901"
        # SIRET schemeID=0002
        siret = seller.find(f"{{{NS_RAM}}}ID")
        assert siret.get("schemeID") == "0002"
        assert siret.text == "12345678901234"

    def test_monetary_totals(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        mt = root.find(
            f".//{{{NS_RAM}}}SpecifiedTradeSettlementHeaderMonetarySummation"
        )

        def get(tag):
            # ram:SpecifiedTradeSettlementHeaderMonetarySummation porte des
            # montants typés udt:Amount : la valeur est dans l'enfant.
            node = _local(_local(mt, tag), "Amount")
            return Decimal(_amount_text(node)), node.get("currencyID")

        assert get("LineTotalAmount") == (Decimal("2000.00"), None)
        assert get("TaxBasisTotalAmount") == (Decimal("2000.00"), None)
        tax_total, cur = get("TaxTotalAmount")
        assert tax_total == Decimal("300.00")
        assert cur == "EUR"  # BR-CO-16 : TaxTotalAmount avec attribut devise
        assert get("GrandTotalAmount")[0] == Decimal("2300.00")
        assert get("DuePayableAmount")[0] == Decimal("2300.00")

    def test_line_units_and_quantities(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        items = root.findall(f".//{{{NS_RAM}}}SupplyChainTradeLineItem")
        assert len(items) == 2
        bq = items[0].find(f".//{{{NS_RAM}}}BilledQuantity")
        assert bq.get("unitCode") == "HUR"   # hour -> HUR
        assert bq.text == "10"
        bq2 = items[1].find(f".//{{{NS_RAM}}}BilledQuantity")
        assert bq2.get("unitCode") == "H87"  # unit -> H87

    def test_tax_breakdown_categories(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        taxes = root.findall(
            f".//{{{NS_RAM}}}ApplicableHeaderTradeSettlement/{{{NS_RAM}}}ApplicableTradeTax"
        )
        pairs = set()
        for t in taxes:
            cat = t.find(f"{{{NS_RAM}}}CategoryCode").text
            rate_el = t.find(f"{{{NS_RAM}}}RateApplicablePercent")
            pairs.add((cat, rate_el.text if rate_el is not None else None))
        # détail 20% VAT et 0% ZE obligatoires (BR-S-08 / BR-Z-08)
        assert ("VAT", "20.00") in pairs
        assert ("ZE", "0.00") in pairs
        # le taux nul porte un motif d'exonération (BR-CO-04/26)
        ze = [t for t in taxes if t.find(f"{{{NS_RAM}}}CategoryCode").text == "ZE"][0]
        assert ze.find(f"{{{NS_RAM}}}ExemptionReason") is not None

    def test_order_reference(self, sample_doc):
        root = etree.fromstring(build_cii_xml(sample_doc))
        ref = root.find(f".//{{{NS_RAM}}}BuyerOrderReferencedDocument/{{{NS_RAM}}}IssuerAssignedID")
        assert ref.text == "PO-42"

    def test_credit_note_type_code(self, sample_doc):
        sample_doc.is_credit_note = True
        root = etree.fromstring(build_cii_xml(sample_doc))
        assert root.find(f".//{{{NS_RAM}}}TypeCode").text == "381"


# ---------------------------------------------------------------------------
# Hybride Factur-X : le XML est réellement extractible du PDF
# ---------------------------------------------------------------------------

class TestFacturXHybrid:
    def _make_pdf(self) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        doc.build([Paragraph("Facture de test", getSampleStyleSheet()["Normal"])])
        return buf.getvalue()

    def test_embedded_xml_extractable(self, sample_doc):
        from pypdf import PdfReader

        pdf = self._make_pdf()
        hybrid, xml_bytes = generate_factur_x(pdf, sample_doc)
        assert hybrid[:5] == b"%PDF-"
        assert len(hybrid) > len(pdf)

        reader = PdfReader(io.BytesIO(hybrid))
        attachments = reader.attachments
        assert "factur-x.xml" in attachments
        extracted = attachments["factur-x.xml"]
        # pypdf renvoie une liste de bytes (un flux par fichier joint)
        if isinstance(extracted, list):
            extracted = extracted[0]
        # le fichier extrait est bien le XML CII (décompression transparente)
        root = ET.fromstring(extracted)
        assert root.tag.startswith("{urn:un:unece")

    def test_xmp_packet_declares_profile(self):
        xmp = facturx_xmp_packet().decode("utf-8")
        assert "pdfaid" in xmp and "<pdfaid:part>3</pdfaid:part>" in xmp
        assert "factur-x.xml" in xmp
        assert "PDF/A-3B" in xmp

    def test_embed_keeps_original_pages(self, sample_doc):
        from pypdf import PdfReader
        pdf = self._make_pdf()
        hybrid, _ = generate_factur_x(pdf, sample_doc)
        assert len(PdfReader(io.BytesIO(hybrid)).pages) == len(PdfReader(io.BytesIO(pdf)).pages)


# ---------------------------------------------------------------------------
# UBL 2.1
# ---------------------------------------------------------------------------

class TestUbl:
    def test_structure(self, sample_doc):
        root = ET.fromstring(generate_ubl_xml(sample_doc))
        assert root.tag.endswith("Invoice")
        # le premier <ID> est celui de la facture (les suivants portent les
        # références de lignes / documents associés)
        ids = [el.text for el in root.iter() if el.tag.split("}")[1] == "ID" and el.text]
        assert ids[0] == "FACT-2026-0001"
        # plusieurs nœuds peuvent partager le même tag (vendeur ET acheteur
        # portent un RegistrationName) : on collecte toutes les valeurs.
        texts: dict[str, list[str]] = {}
        for el in root.iter():
            if el.text:
                texts.setdefault(el.tag.split("}")[1], []).append(el.text)
        assert "Vendeur SA" in texts.get("RegistrationName", [])
        assert "Client SARL" in texts.get("RegistrationName", [])
        assert "EUR" in texts.get("DocumentCurrencyCode", [])

    def test_credit_note_variant(self, sample_doc):
        sample_doc.is_credit_note = True
        root = ET.fromstring(generate_ubl_xml(sample_doc))
        assert root.tag.endswith("CreditNote")


# ---------------------------------------------------------------------------
# Fabrique ORM -> DTO
# ---------------------------------------------------------------------------

class TestFactory:
    def test_document_from_invoice(self, db_session):
        org = Organization(
            name="Acme Factures", siret="11111111111111", tax_id="FR11111111111",
            address_line1="10 rue A", postal_code="75002", city="Paris", country="FR",
        )
        db_session.add(org)
        db_session.flush()

        customer = Customer(
            organization_id=org.id, name="Client X", email="c@x.fr", tax_id="FR22222222222",
            address_line1="2 rue B", postal_code="33000", city="Bordeaux", country="FR",
        )
        db_session.add(customer)
        db_session.flush()

        invoice = Invoice(
            organization_id=org.id, customer_id=customer.id, number="F-1",
            currency="EUR", status="issued",
            issue_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
            due_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            subtotal_minor=10000, tax_total_minor=2000, total_minor=12000,
            amount_due_minor=12000, purchase_order_number="PO-9",
        )
        db_session.add(invoice)
        db_session.flush()

        line = InvoiceLine(
            organization_id=org.id, invoice_id=invoice.id, description="Service",
            quantity=Decimal("2"), unit="hour", unit_price_minor=5000,
            tax_rate=Decimal("20"), tax_amount_minor=2000,
            line_total_minor=10000, line_gross_minor=12000, position=1,
        )
        db_session.add_all([invoice, line])
        db_session.commit()

        doc = document_from_invoice(invoice, org, customer)
        assert doc.number == "F-1"
        assert doc.seller.name == "Acme Factures"
        assert doc.seller.vat_id == "FR11111111111"
        assert doc.buyer.city == "Bordeaux"
        assert doc.order_reference == "PO-9"
        assert len(doc.lines) == 1
        assert doc.lines[0].unit == "hour"

        # Round-trip complet vers le XML
        xml_bytes = build_cii_xml(doc)
        root = ET.fromstring(xml_bytes)
        assert "F-1" in xml_bytes.decode()


# ---------------------------------------------------------------------------
# Endpoints d'export
# ---------------------------------------------------------------------------

class TestExportEndpoints:
    @pytest.fixture
    def invoice_env(self, client, db_session, auth_headers, test_organization):
        from app.security import generate_api_key  # noqa: F401 (ensure import ok)

        headers = auth_headers()
        cust = client.post(
            "/v1/customers",
            json={"name": "Client Export", "email": "exp@client.fr", "tax_id": "FR33333333333"},
            headers=headers,
        )
        assert cust.status_code == 201, cust.text
        customer_id = cust.json()["id"]

        inv = client.post(
            "/v1/invoices",
            json={
                "customer_id": customer_id,
                "number": "EXP-001",
                "currency": "EUR",
                "lines": [
                    {"description": "Dev", "quantity": "3", "unit_price_minor": 20000, "tax_rate": "20"},
                ],
            },
            headers=headers,
        )
        assert inv.status_code == 201, inv.text
        return inv.json()["id"], headers

    def test_export_xml(self, client, invoice_env):
        invoice_id, headers = invoice_env
        r = client.get(f"/v1/invoices/{invoice_id}/export/xml", headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/xml")
        assert "attachment" in r.headers["content-disposition"]
        root = ET.fromstring(r.content)
        assert root.tag.startswith("{urn:un:unece")
        assert b"EXP-001" in r.content

    def test_export_ubl(self, client, invoice_env):
        invoice_id, headers = invoice_env
        r = client.get(f"/v1/invoices/{invoice_id}/export/ubl", headers=headers)
        assert r.status_code == 200
        assert b"Invoice" in r.content and b"oasis" in r.content

    def test_export_facturx(self, client, invoice_env):
        from pypdf import PdfReader
        invoice_id, headers = invoice_env
        r = client.get(f"/v1/invoices/{invoice_id}/export/factur-x", headers=headers)
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"
        reader = PdfReader(io.BytesIO(r.content))
        assert "factur-x.xml" in reader.attachments
        xml_bytes = reader.attachments["factur-x.xml"]
        if isinstance(xml_bytes, list):
            xml_bytes = xml_bytes[0]
        assert b"CrossIndustryInvoice" in xml_bytes

    def test_export_unknown_invoice_404(self, client, auth_headers):
        r = client.get("/v1/invoices/does-not-exist/export/xml", headers=auth_headers())
        assert r.status_code == 404

    def test_export_requires_auth(self, client, invoice_env):
        invoice_id, _ = invoice_env
        r = client.get(f"/v1/invoices/{invoice_id}/export/xml")
        assert r.status_code == 401
