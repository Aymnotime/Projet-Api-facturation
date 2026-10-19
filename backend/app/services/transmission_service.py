"""Service de transmission PDP : orchestration entre l'ORM et ``PDPAdapter``.

Responsabilités :
- construire le ``PDPDocument`` depuis une facture persistée (Factur-X par
  défaut, XML CII en repli si le PDF est indisponible) ;
- créer/reprendre les lignes ``Transmission`` avec idempotence interne
  (un numéro de facture = une seule transmission active par fournisseur) ;
- mapper les résultats normalisés de l'adaptateur vers ``TransmissionStatus`` ;
- rafraîchir le cycle de vie depuis la plateforme (polling).

La couche PDP elle-même (``app.services.pdp.adapter``) reste pure : ce module
est le seul point de contact avec la base de données.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, Organization, Transmission, TransmissionStatus
from app.services.pdp.adapter import (
    PDPAdapter,
    PDPDocument,
    PDPDocumentType,
    PDPTransmissionError,
    get_pdp_adapter,
)

logger = logging.getLogger(__name__)

# Statuts considérés comme « terminaux côté plateforme » : pas de re-soumission.
_ACTIVE_STATUSES = {
    TransmissionStatus.READY_TO_SEND.value,
    TransmissionStatus.TRANSMITTING.value,
    TransmissionStatus.TRANSMITTED.value,
    TransmissionStatus.ACCEPTED.value,
}


def build_pdf_bytes(db: Session, invoice: Invoice, organization: Organization) -> bytes | None:
    """Génère le PDF simple ; ``None`` si ReportLab échoue (repli sur XML pur)."""
    try:
        from app.tasks.invoice_tasks import build_invoice_pdf_bytes

        return build_invoice_pdf_bytes(db, invoice, organization)
    except Exception:  # pragma: no cover - dépendance optionnelle / environnement de test
        logger.exception("PDF generation failed for invoice %s", invoice.id)
        return None


def document_from_invoice(
    db: Session, invoice: Invoice, organization: Organization, *, prefer: str = "factur-x"
) -> PDPDocument:
    """Construit le document électronique transmissible pour une facture."""
    from app.services.einvoicing import build_cii_xml, generate_factur_x
    from app.services.einvoicing_factory import document_from_invoice as doc_dto

    customer = db.get(Customer, invoice.customer_id) if invoice.customer_id else None
    if not customer:
        raise PDPTransmissionError(
            f"Facture {invoice.number} sans client : transmission impossible", status_code=422
        )
    dto = doc_dto(invoice, organization, customer)

    number = invoice.number
    seller_siret = organization.siret or ""
    buyer_siret = customer.siret

    if prefer == "xml":
        content = build_cii_xml(dto)
        return PDPDocument(
            content=content,
            document_type=PDPDocumentType.FACTURE,
            filename=f"facture-{number}.xml",
            number=number,
            seller_siret=seller_siret,
            buyer_siret=buyer_siret,
            buyer_datex=None,
            media_type="application/xml",
            organization_id=organization.id,
        )

    xml_bytes = build_cii_xml(dto)
    pdf_bytes = build_pdf_bytes(db, invoice, organization)
    if pdf_bytes is not None:
        hybrid, _metadata = generate_factur_x(pdf_bytes, dto)
        content, filename, media = hybrid, f"facture-{number}-factur-x.pdf", "application/pdf"
    else:  # repli : CII nu si le PDF n'est pas générable
        content, filename, media = xml_bytes, f"facture-{number}.xml", "application/xml"

    return PDPDocument(
        content=content,
        document_type=PDPDocumentType.FACTURE,
        filename=filename,
        number=number,
        seller_siret=seller_siret,
        buyer_siret=buyer_siret,
        media_type=media,
        organization_id=organization.id,
    )


class TransmissionService:
    """Cas d'usage de transmission pour une organisation."""

    def __init__(self, db: Session):
        self.db = db

    def _get_invoice(self, organization: Organization, invoice_id: str) -> Invoice:
        invoice = self.db.scalar(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id)
        )
        if not invoice:
            raise LookupError("Invoice not found")
        return invoice

    def _existing_transmission(self, invoice: Invoice, provider: str) -> Transmission | None:
        return self.db.scalar(
            select(Transmission).where(
                Transmission.invoice_id == invoice.id, Transmission.pdp_provider == provider
            )
        )

    def submit_invoice(
        self,
        organization: Organization,
        invoice_id: str,
        provider: str = "mock",
        *,
        format: str = "factur-x",
    ) -> Transmission:
        """Transmet une facture à une PDP et persiste la ``Transmission``.

        Idempotent : si une transmission active existe déjà pour ce couple
        (facture, fournisseur), elle est retournée sans nouveau dépôt.
        Lève ``LookupError`` (404 API) ou ``ValueError``/``PDPTransmissionError``.
        """
        invoice = self._get_invoice(organization, invoice_id)

        existing = self._existing_transmission(invoice, provider)
        if existing and existing.status in _ACTIVE_STATUSES:
            logger.info("Transmission déjà active (%s) pour facture %s", existing.status, invoice.number)
            return existing

        adapter: PDPAdapter = get_pdp_adapter(provider)

        transmission = existing or Transmission(
            organization_id=organization.id,
            invoice_id=invoice.id,
            pdp_provider=provider,
            status=TransmissionStatus.READY_TO_SEND.value,
        )
        transmission.attempt_count += 1
        transmission.last_attempt_at = datetime.now(timezone.utc)
        transmission.error_message = None
        if transmission not in self.db.session:
            self.db.add(transmission)

        try:
            document = document_from_invoice(self.db, invoice, organization, prefer=format)
            result = adapter.submit(document)
        except PDPTransmissionError as exc:
            transmission.status = TransmissionStatus.FAILED.value
            transmission.error_message = str(exc)
            self.db.commit()
            raise

        if result.accepted:
            transmission.status = TransmissionStatus(result.status).value
            transmission.external_reference = result.external_reference
            transmission.transmitted_at = datetime.now(timezone.utc)
        else:
            transmission.status = TransmissionStatus.REJECTED.value
            transmission.error_message = "; ".join(result.messages) or "Rejet sans message"
        self.db.commit()
        self.db.refresh(transmission)
        return transmission

    def refresh_status(self, organization: Organization, transmission_id: str) -> Transmission:
        """Interroge la PDP pour mettre à jour le cycle de vie d'une transmission."""
        transmission = self.db.scalar(
            select(Transmission).where(
                Transmission.id == transmission_id,
                Transmission.organization_id == organization.id,
            )
        )
        if not transmission:
            raise LookupError("Transmission not found")
        if not transmission.external_reference:
            raise ValueError("Transmission has no external reference yet")

        adapter = get_pdp_adapter(transmission.pdp_provider)
        info = adapter.get_status(transmission.external_reference)
        new_status = TransmissionStatus(info.status).value
        if new_status != transmission.status:
            transmission.status = new_status
            if new_status == TransmissionStatus.ACCEPTED.value:
                transmission.accepted_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(transmission)
        return transmission
