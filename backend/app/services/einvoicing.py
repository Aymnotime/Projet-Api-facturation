"""Génération des formats de facturation électronique EN 16931.

Implémente :
- la sérialisation XML **Cross Industry Invoice (UN/CEFACT CII D16B)** —
  sémantique commune à Factur-X et aux PDP français ;
- l'assemblage d'un fichier hybride **Factur-X** (PDF + XML injecté en
  pièce jointe PDF ``factur-x.xml``, conformance déclarée PDF/A-3B) ;
- un export **UBL 2.1** minimal pour l'interopérabilité internationale.

Montants : les modèles stockent des unités mineures (centimes) ; ici on
convertit en unités majeures avec Decimal pour respecter le schéma CII.
"""
from __future__ import annotations

import io
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from lxml import etree

from app.core.einvoicing import (
    CONFORMANCE_LEVEL,
    DOC_TYPE_CREDIT_NOTE,
    DOC_TYPE_INVOICE,
    PROFILE_COMFORT,
    TAX_CATEGORY_VAT,
    tax_category_for_rate,
    tax_exemption_reason,
    to_unece_unit,
)

# ---------------------------------------------------------------------------
# Namespaces CII (UN/CEFACT Cross Industry Invoice, schema D16B — profil
# Factur-X). Ce sont les espaces utilisés par les implémentations de
# référence (Factur-X SDK, Chorus Pro).
# ---------------------------------------------------------------------------

NS_R = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def minor_to_major(value_minor: int | None) -> Decimal:
    """Convertit une unité mineure (centimes) en unité majeure Decimal."""
    return (Decimal(value_minor or 0) / Decimal(100)).quantize(Decimal("0.01"))


def _fmt_date(d: date | datetime | None) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()


# ---------------------------------------------------------------------------
# DTO neutres : découplent le générateur des modèles ORM
# ---------------------------------------------------------------------------


@dataclass
class PartyData:
    name: str
    street: Optional[str] = None
    line2: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None
    country: str = "FR"
    siret: Optional[str] = None
    vat_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


@dataclass
class LineData:
    id: str
    description: str
    quantity: Decimal
    unit: str                      # unité interne -> convertie en UNECE
    unit_price_minor: int          # HT en centimes
    line_total_minor: int          # HT ligne en centimes
    tax_rate: Decimal
    tax_amount_minor: int
    gross_amount_minor: int
    discount_minor: int = 0
    product_code: Optional[str] = None


@dataclass
class InvoiceDocumentData:
    number: str
    issue_date: date | datetime | None
    due_date: date | datetime | None = None
    currency: str = "EUR"
    seller: PartyData = field(default_factory=lambda: PartyData(name=""))
    buyer: PartyData = field(default_factory=lambda: PartyData(name=""))
    lines: list[LineData] = field(default_factory=list)
    subtotal_minor: int = 0
    tax_total_minor: int = 0
    total_minor: int = 0
    paid_minor: int = 0
    due_minor: int = 0
    payment_means: str = "transfer"  # transfer | card
    order_reference: Optional[str] = None
    contract_reference: Optional[str] = None
    buyer_reference: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    is_credit_note: bool = False

    @property
    def doc_type_code(self) -> str:
        return DOC_TYPE_CREDIT_NOTE if self.is_credit_note else DOC_TYPE_INVOICE


# ---------------------------------------------------------------------------
# Construction du XML CII (lxml, namespaces propres)
# ---------------------------------------------------------------------------


def _sub(parent: etree._Element, qname: str, text: str | None = None) -> etree._Element:
    child = etree.SubElement(parent, qname)
    if text is not None:
        child.text = text
    return child


def _ram(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    return _sub(parent, f"{{{NS_RAM}}}{tag}", text)


def _date_el(parent: etree._Element, tag: str, iso: str | None) -> None:
    if not iso:
        return
    dt = _ram(parent, tag)
    node = _sub(dt, f"{{{NS_UDT}}}DateTimeString", iso)
    node.set("format", "102")


def _amount_el(parent: etree._Element, tag: str, value: Decimal, currency: str | None = None) -> None:
    am = _ram(parent, tag)
    node = _sub(am, f"{{{NS_UDT}}}Amount", f"{value:.2f}")
    if currency:
        node.set("currencyID", currency)


def _build_party(parent: etree._Element, tag: str, party: PartyData, with_contact: bool = False) -> None:
    """Émet un ram:TradeParty (Seller/Buyer/ShipTo...)."""
    p = _ram(parent, tag)
    if party.siret:
        idn = _ram(p, "ID", party.siret)
        idn.set("schemeID", "0002")  # SIRET (ORGL France)
    if party.name:
        _ram(p, "Name", party.name)

    addr = _ram(p, "PostalTradeAddress")
    if party.zip:
        _ram(addr, "PostcodeCode", party.zip)
    if party.street:
        _ram(addr, "LineOne", party.street)
    if party.line2:
        _ram(addr, "LineTwo", party.line2)
    if party.city:
        _ram(addr, "CityName", party.city)
    _ram(addr, "CountryID", party.country)

    if party.vat_id:
        tax_repr = _ram(p, "SpecifiedTaxRegistration")
        tr_id = _ram(tax_repr, "ID", party.vat_id)
        tr_id.set("schemeID", "VA")

    if with_contact and (party.contact_name or party.contact_email or party.contact_phone):
        cnt = _ram(p, "DefinedTradeContact")
        if party.contact_name:
            _ram(cnt, "PersonName", party.contact_name)
        if party.contact_email:
            em = _ram(cnt, "EmailUniversalTradeCommunication")
            _ram(em, "URIID", party.contact_email)


def build_cii_xml(doc: InvoiceDocumentData) -> bytes:
    """Sérialise le document en XML CII (syntaxe Factur-X / MINXFR enrichi)."""
    nsmap = {"rsm": NS_R, "ram": NS_RAM, "udt": NS_UDT}
    root = etree.Element(f"{{{NS_R}}}CrossIndustryInvoice", nsmap=nsmap)

    # --- ExchangedDocumentContext (profil) ---
    ctx = _sub(root, f"{{{NS_R}}}ExchangedDocumentContext")
    guideline = _ram(ctx, "GuidelineSpecifiedDocumentContextParameter")
    _ram(guideline, "ID", PROFILE_COMFORT)

    # --- ExchangedDocument (en-tête) ---
    exd = _sub(root, f"{{{NS_R}}}ExchangedDocument")
    _ram(exd, "ID", doc.number)
    _ram(exd, "TypeCode", doc.doc_type_code)
    _date_el(exd, "IssueDateTime", _fmt_date(doc.issue_date))
    for note in doc.notes:
        n = _ram(exd, "IncludedNote")
        _ram(n, "Content", note)

    # --- SupplyChainTradeTransaction ---
    tx = _sub(root, f"{{{NS_R}}}SupplyChainTradeTransaction")

    # ApplicableHeaderTradeAgreement
    ag = _ram(tx, "ApplicableHeaderTradeAgreement")
    if doc.buyer_reference:
        _ram(ag, "BuyerReference", doc.buyer_reference)
    _build_party(ag, "SellerTradeParty", doc.seller, with_contact=True)
    _build_party(ag, "BuyerTradeParty", doc.buyer)
    if doc.order_reference:
        ord_ref = _ram(ag, "BuyerOrderReferencedDocument")
        _ram(ord_ref, "IssuerAssignedID", doc.order_reference)
    if doc.contract_reference:
        ctr = _ram(ag, "ContractReferencedDocument")
        _ram(ctr, "IssuerAssignedID", doc.contract_reference)

    # ApplicableHeaderTradeDelivery
    dl = _ram(tx, "ApplicableHeaderTradeDelivery")
    ship_to = _ram(dl, "ShipToTradeParty")
    _ram(ship_to, "Name", doc.buyer.name)
    ship_addr = _ram(ship_to, "PostalTradeAddress")
    _ram(ship_addr, "CountryID", doc.buyer.country)

    # ApplicableHeaderTradeSettlement
    st = _ram(tx, "ApplicableHeaderTradeSettlement")
    _ram(st, "PaymentReference", doc.number)
    _ram(st, "InvoiceCurrencyCode", doc.currency)

    payee = _ram(st, "PayeeTradeParty")
    _ram(payee, "Name", doc.seller.name)

    pm = _ram(st, "SpecifiedTradeSettlementPaymentMeans")
    _ram(pm, "TypeCode", "30" if doc.payment_means == "card" else "58")  # 58 = virement

    # Taxes : agrégation par (catégorie, taux)
    tax_groups: dict[tuple[str, Decimal], tuple[Decimal, Decimal]] = {}
    for line in doc.lines:
        cat = tax_category_for_rate(line.tax_rate)
        key = (cat, line.tax_rate)
        base, amount = tax_groups.get(key, (Decimal("0"), Decimal("0")))
        tax_groups[key] = (
            base + minor_to_major(line.line_total_minor),
            amount + minor_to_major(line.tax_amount_minor),
        )

    # Taxe globale (header) : catégorie dominante
    primary_cat = next((k[0] for k in tax_groups if k[0] != TAX_CATEGORY_VAT), TAX_CATEGORY_VAT)
    tt = _ram(st, "ApplicableTradeTax")
    _amount_el(tt, "CalculatedAmount", minor_to_major(doc.tax_total_minor))
    _ram(tt, "CategoryCode", primary_cat)
    if primary_cat != TAX_CATEGORY_VAT:
        reason = tax_exemption_reason(primary_cat)
        if reason:
            _ram(tt, "ExemptionReason", reason[0])
    _amount_el(tt, "BasisAmount", minor_to_major(doc.subtotal_minor))

    # Détail par (catégorie, taux)
    for (cat, rate), (_base, amount) in sorted(tax_groups.items()):
        lt = _ram(st, "ApplicableTradeTax")
        _amount_el(lt, "CalculatedAmount", amount)
        _ram(lt, "CategoryCode", cat)
        _ram(lt, "RateApplicablePercent", f"{rate:.2f}")
        if cat != TAX_CATEGORY_VAT:
            reason = tax_exemption_reason(cat)
            if reason:
                _ram(lt, "ExemptionReason", reason[0])

    if doc.due_date:
        pd = _ram(st, "SpecifiedTradePaymentTerms")
        _date_el(pd, "DueDateDateTime", _fmt_date(doc.due_date))

    # Sommes monétaires d'en-tête (ordre imposé par le schéma CII)
    mt = _ram(st, "SpecifiedTradeSettlementHeaderMonetarySummation")
    _amount_el(mt, "LineTotalAmount", minor_to_major(doc.subtotal_minor))
    _amount_el(mt, "ChargeTotalAmount", Decimal("0.00"))
    _amount_el(mt, "AllowanceTotalAmount", Decimal("0.00"))
    _amount_el(mt, "TaxBasisTotalAmount", minor_to_major(doc.subtotal_minor))
    _amount_el(mt, "TaxTotalAmount", minor_to_major(doc.tax_total_minor), doc.currency)
    _amount_el(mt, "GrandTotalAmount", minor_to_major(doc.total_minor))
    _amount_el(mt, "TotalPrepaidAmount", minor_to_major(doc.paid_minor))
    _amount_el(mt, "DuePayableAmount", minor_to_major(doc.due_minor))

    # Lignes
    for line in doc.lines:
        li = _ram(tx, "SupplyChainTradeLineItem")
        iid = _ram(li, "AssociatedDocumentLineDocument")
        _ram(iid, "LineID", line.id)

        prod = _ram(li, "SpecifiedTradeProduct")
        if line.product_code:
            _ram(prod, "SellerAssignedID", line.product_code)
        _ram(prod, "Name", line.description)

        aq = _ram(li, "SpecifiedLineTradeAgreement")
        np = _ram(aq, "NetPriceProductTradePrice")
        _amount_el(np, "ChargeAmount", minor_to_major(line.unit_price_minor))

        deliv = _ram(li, "SpecifiedLineTradeDelivery")
        bq = _sub(deliv, f"{{{NS_RAM}}}BilledQuantity", f"{line.quantity.normalize():f}")
        bq.set("unitCode", to_unece_unit(line.unit))

        setl = _ram(li, "SpecifiedLineTradeSettlement")
        lt_tax = _ram(setl, "ApplicableTradeTax")
        _ram(lt_tax, "TypeCode", "VAT")
        _ram(lt_tax, "CategoryCode", tax_category_for_rate(line.tax_rate))
        _ram(lt_tax, "RateApplicablePercent", f"{line.tax_rate:.2f}")

        summands = _ram(setl, "SpecifiedTradeSettlementLineMonetarySummation")
        _amount_el(summands, "LineTotalAmount", minor_to_major(line.line_total_minor))

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")


# ---------------------------------------------------------------------------
# Métadonnées XMP Factur-X (à intégrer dans le PDF)
# ---------------------------------------------------------------------------


def facturx_xmp_packet(filename_hint: str = "factur-x.xml") -> bytes:
    """Packet XMP décrivant le profil Factur-X et la conformance PDF/A-3B."""
    xmp = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"\n'
        '    xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">\n'
        "   <pdfaid:part>3</pdfaid:part>\n"
        "   <pdfaid:conformance>B</pdfaid:conformance>\n"
        "   <fx:DocumentName>factur-x</fx:DocumentName>\n"
        f"   <fx:DocumentFileName>{filename_hint}</fx:DocumentFileName>\n"
        "   <fx:Version>1.0</fx:Version>\n"
        f"   <fx:ConformanceLevel>{CONFORMANCE_LEVEL}</fx:ConformanceLevel>\n"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )
    return xmp.encode("utf-8")


# ---------------------------------------------------------------------------
# Injection du XML comme pièce jointe PDF (pièce jointe nominative,
# conforme à l'exigence Factur-X : fichier nommé « factur-x.xml »)
# ---------------------------------------------------------------------------


def embed_xml_in_pdf(pdf_bytes: bytes, xml_bytes: bytes, filename: str = "factur-x.xml") -> bytes:
    """Attache le XML au PDF via pypdf (Filespec /EmbeddedFiles + AFRelationship).

    Les viewers conformes Factur-X extraient la pièce jointe nommée
    ``factur-x.xml`` depuis le catalogue ``/Names /EmbeddedFiles``.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)

    compressed = zlib.compress(xml_bytes)
    file_stream = DecodedStreamObject()
    file_stream.set_data(compressed)
    file_stream.update({
        NameObject("/Type"): NameObject("/EmbeddedFile"),
        NameObject("/Subtype"): NameObject("/application/xml"),
        NameObject("/Filter"): NameObject("/FlateDecode"),
    })
    stream_ref = writer._add_object(file_stream)

    fs_dict = DictionaryObject({
        NameObject("/F"): stream_ref,
        NameObject("/Type"): NameObject("/Filespec"),
        NameObject("/UF"): TextStringObject(filename),
        NameObject("/Desc"): TextStringObject("Factur-X Cross Industry Invoice XML (EN 16931)"),
        NameObject("/EF"): DictionaryObject({NameObject("/F"): stream_ref}),
        NameObject("/AFRelationship"): NameObject("/Data"),
    })
    filespec_ref = writer._add_object(fs_dict)

    names_arr = ArrayObject([TextStringObject(filename), filespec_ref])
    ef_root = writer._add_object(DictionaryObject({NameObject("/Names"): names_arr}))

    catalog = writer._root_object
    catalog[NameObject("/Names")] = DictionaryObject({NameObject("/EmbeddedFiles"): ef_root})
    catalog[NameObject("/Lang")] = TextStringObject("fr-FR")
    # Déclare la pièce jointe comme document attaché (PDF 2.0 / AF)
    existing_af = catalog.get(NameObject("/AF"))
    if existing_af is not None and hasattr(existing_af, "append"):
        existing_af.append(filespec_ref)
    else:
        catalog[NameObject("/AF")] = ArrayObject([filespec_ref])

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def extract_facturx_xml(pdf_bytes: bytes) -> bytes | None:
    """Relit un PDF hybride et retourne le XML CII embarqué (None si absent).

    Utilisé par les tests et par la validation pré-transmission PDP.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    for key in list(reader.attachments.keys()):
        if key.lower().endswith(".xml"):
            data = reader.attachments[key]
            if isinstance(data, list):  # pypdf renvoie une liste de flux
                data = data[0]
            return data
    return None


# ---------------------------------------------------------------------------
# Façade : construire un Factur-X complet
# ---------------------------------------------------------------------------


def generate_factur_x(pdf_bytes: bytes, doc: InvoiceDocumentData) -> tuple[bytes, bytes]:
    """Retourne (pdf_hybride_facturx, xml_cii)."""
    xml_bytes = build_cii_xml(doc)
    hybrid = embed_xml_in_pdf(pdf_bytes, xml_bytes, "factur-x.xml")
    return hybrid, xml_bytes


def generate_ubl_xml(doc: InvoiceDocumentData) -> bytes:
    """Export UBL 2.1 (interop international ; même sémantique EN 16931)."""
    ns_inv = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    ns_cn = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    ca = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    ct = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

    root_tag = f"{{{ns_cn}}}CreditNote" if doc.is_credit_note else f"{{{ns_inv}}}Invoice"
    root = etree.Element(root_tag, nsmap={"cac": ca, "cbc": ct})

    def _cbc(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
        return _sub(parent, f"{{{ct}}}{tag}", text)

    _cbc(root, "ID", doc.number)
    _cbc(root, "IssueDate", _fmt_date(doc.issue_date))
    _cbc(root, "DocumentCurrencyCode", doc.currency)

    def _party(tag: str, p: PartyData) -> None:
        node = _sub(root, f"{{{ca}}}{tag}")
        party = _sub(node, f"{{{ca}}}Party")
        legal = _sub(party, f"{{{ca}}}PartyLegalEntity")
        _cbc(legal, "RegistrationName", p.name)
        if p.siret:
            _cbc(legal, "CompanyID", p.siret)
        addr = _sub(party, f"{{{ca}}}PostalAddress")
        if p.street:
            _cbc(addr, "StreetName", p.street)
        if p.zip:
            _cbc(addr, "PostalZone", p.zip)
        if p.city:
            _cbc(addr, "CityName", p.city)
        ctry = _sub(addr, f"{{{ca}}}Country")
        _cbc(ctry, "IdentificationCode", p.country)
        if p.vat_id:
            pts = _sub(party, f"{{{ca}}}PartyTaxScheme")
            _cbc(pts, "CompanyID", p.vat_id)

    _party("AccountingSupplierParty", doc.seller)
    _party("AccountingCustomerParty", doc.buyer)

    # Totaux
    tax_totals = _sub(root, f"{{{ca}}}TaxTotal")
    _cbc(tax_totals, "TaxAmount", f"{minor_to_major(doc.tax_total_minor):.2f}")

    lmt = _sub(root, f"{{{ca}}}LegalMonetaryTotal")
    _cbc(lmt, "TaxExclusiveAmount", f"{minor_to_major(doc.subtotal_minor):.2f}")
    _cbc(lmt, "TaxInclusiveAmount", f"{minor_to_major(doc.total_minor):.2f}")
    _cbc(lmt, "PayableAmount", f"{minor_to_major(doc.due_minor):.2f}")

    line_tag = "CreditNoteLine" if doc.is_credit_note else "InvoiceLine"
    qty_tag = "CreditedQuantity" if doc.is_credit_note else "InvoicedQuantity"
    for line in doc.lines:
        il = _sub(root, f"{{{ca}}}{line_tag}")
        _cbc(il, "ID", line.id)
        qty = _cbc(il, qty_tag, f"{line.quantity.normalize():f}")
        qty.set("unitCode", to_unece_unit(line.unit))
        _cbc(il, "LineExtensionAmount", f"{minor_to_major(line.line_total_minor):.2f}")
        itc = _sub(il, f"{{{ca}}}Item")
        _cbc(itc, "Description", line.description)
        _cbc(itc, "Name", line.description)
        pc = _sub(il, f"{{{ca}}}Price")
        _cbc(pc, "PriceAmount", f"{minor_to_major(line.unit_price_minor):.2f}")

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
