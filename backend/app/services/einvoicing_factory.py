"""Fabrique InvoiceDocumentData depuis les modèles ORM.

Sépare la couche persistance de la génération XML/PDF : le service
``app.services.einvoicing`` ne connaît que les DTO.
"""
from __future__ import annotations

from decimal import Decimal

from app.models import Customer, Invoice, Organization
from app.services.einvoicing import InvoiceDocumentData, LineData, PartyData


def party_from_organization(org: Organization) -> PartyData:
    return PartyData(
        name=org.name,
        street=org.address_line1,
        zip=org.postal_code,
        city=org.city,
        country=org.country or "FR",
        siret=org.siret,
        vat_id=org.tax_id,
        contact_email=org.email,
    )


def party_from_customer(customer: Customer) -> PartyData:
    street = customer.address_line1
    if not street and customer.email:
        street = None
    return PartyData(
        name=customer.name,
        street=street,
        line2=customer.address_line2,
        zip=customer.postal_code,
        city=customer.city,
        country=customer.country or "FR",
        siret=customer.siret,
        vat_id=customer.tax_id,
        contact_email=customer.email,
    )


def document_from_invoice(invoice: Invoice, organization: Organization, customer: Customer) -> InvoiceDocumentData:
    """Assemble le DTO Factur-X complet à partir d'une facture persistée."""
    lines = sorted(invoice.lines, key=lambda l: (l.position, l.id))
    paid_minor = 0
    due_minor = invoice.amount_due_minor or 0
    if invoice.status == "paid":
        paid_minor = invoice.total_minor
        due_minor = 0

    notes: list[str] = []
    if invoice.notes:
        notes.append(invoice.notes)
    if invoice.payment_terms:
        notes.append(f"Conditions de paiement : {invoice.payment_terms}")

    return InvoiceDocumentData(
        number=invoice.number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        seller=party_from_organization(organization),
        buyer=party_from_customer(customer),
        lines=[
            LineData(
                id=str(idx + 1),
                description=line.description,
                quantity=Decimal(str(line.quantity)),
                unit=line.unit,
                unit_price_minor=line.unit_price_minor,
                line_total_minor=line.line_total_minor,
                tax_rate=Decimal(str(line.tax_rate)),
                tax_amount_minor=line.tax_amount_minor,
                gross_amount_minor=line.line_gross_minor,
                discount_minor=line.discount_amount_minor or 0,
                product_code=line.product_code,
            )
            for idx, line in enumerate(lines)
        ],
        subtotal_minor=invoice.subtotal_minor,
        tax_total_minor=invoice.tax_total_minor,
        total_minor=invoice.total_minor,
        paid_minor=paid_minor,
        due_minor=due_minor,
        order_reference=invoice.purchase_order_number,
        notes=notes,
    )
