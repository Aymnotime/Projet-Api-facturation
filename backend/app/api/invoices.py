"""Endpoints de facturation : création avec lignes, cycle de vie, consultation."""
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.idempotency import IdempotencyHandler
from app.core.logic import (
    CalculationError,
    InvoiceStatus,
    calculate_invoice_totals,
    get_next_valid_statuses,
    validate_invoice_data,
    validate_state_transition,
)
from app.db import get_db
from app.models import Customer, Invoice, InvoiceLine, Organization
from app.schemas import (
    InvoiceCreateWithLines,
    InvoiceRead,
    InvoiceReadWithLines,
    InvoiceUpdate,
    PaginatedInvoices,
)
from app.security import require_organization
from app.services.invoice_numbering_service import InvoiceNumberingService
from app.services.pagination import paginate
from app.tasks.invoice_tasks import generate_invoice_pdf, validate_invoice_en16931

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/invoices", tags=["invoices"])


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _get_invoice_or_404(db: Session, organization: Organization, invoice_id: str) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id)
    )
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


def _transition_or_409(invoice: Invoice, target: InvoiceStatus, action: str) -> None:
    """Valide une transition d'état ; lève un 409 explicite sinon."""
    current = InvoiceStatus(invoice.status)
    if not validate_state_transition(current, target):
        valid = [s.value for s in get_next_valid_statuses(current)]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action}. Current status: {invoice.status}. Valid transitions: {valid}",
        )


def _trigger_async_processing(invoice_id: str) -> None:
    """Déclenche validation EN 16931 et génération PDF si Celery/Redis est configuré."""
    if not os.getenv("REDIS_URL"):
        return
    try:
        validate_invoice_en16931.delay(invoice_id)
        generate_invoice_pdf.delay(invoice_id)
    except Exception:
        logger.warning("Async processing unavailable for invoice %s", invoice_id, exc_info=True)


def _serialize_invoice(invoice: Invoice) -> dict:
    """Sérialise une facture (avec lignes) pour le stockage idempotent."""
    return {
        "id": invoice.id,
        "organization_id": invoice.organization_id,
        "customer_id": invoice.customer_id,
        "number": invoice.number,
        "currency": invoice.currency,
        "status": invoice.status,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "issued_at": invoice.issued_at,
        "subtotal_minor": invoice.subtotal_minor,
        "tax_total_minor": invoice.tax_total_minor,
        "total_minor": invoice.total_minor,
        "amount_due_minor": invoice.amount_due_minor,
        "notes": invoice.notes,
        "payment_terms": invoice.payment_terms,
        "purchase_order_number": invoice.purchase_order_number,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price_minor": line.unit_price_minor,
                "tax_rate": line.tax_rate,
                "line_total_minor": line.line_total_minor,
                "tax_amount_minor": line.tax_amount_minor,
                "line_gross_minor": line.line_gross_minor,
                "product_code": line.product_code,
            }
            for line in invoice.lines
        ],
    }


def _store_idempotent_response(db: Session, idempotency_result: dict, invoice: Invoice) -> None:
    if not idempotency_result.get("idempotency_key"):
        return
    try:
        from app.services.idempotency_service import IdempotencyService

        IdempotencyService.store_response(
            db=db,
            idempotency_key=idempotency_result["idempotency_key"],
            response_status=status.HTTP_201_CREATED,
            response_body=_serialize_invoice(invoice),
        )
    except Exception:
        logger.warning("Failed to store idempotent response", exc_info=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=InvoiceReadWithLines, status_code=status.HTTP_201_CREATED)
def create_invoice_with_lines(
    payload: InvoiceCreateWithLines,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
    idempotency_result: dict = Depends(IdempotencyHandler()),
) -> Invoice | Response:
    # Réponse déjà calculée pour cette clé d'idempotence : on la rejoue.
    cached = idempotency_result.get("cached_response")
    if cached is not None:
        if isinstance(cached, Response):
            return cached
        return JSONResponse(
            status_code=cached.status_code,
            content=json.loads(cached.body.decode("utf-8")),
        )

    # Vérifier que le client existe et appartient à l'organisation.
    customer = db.scalar(
        select(Customer).where(
            Customer.id == payload.customer_id, Customer.organization_id == organization.id
        )
    )
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    # Numéro fourni ou généré automatiquement.
    invoice_number = payload.number.strip() if payload.number else None
    if not invoice_number:
        try:
            invoice_number = InvoiceNumberingService.generate_number(
                db=db, organization_id=organization.id, year=None, prefix=None
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate invoice number: {exc}",
            )

    existing = db.scalar(
        select(Invoice).where(
            Invoice.organization_id == organization.id, Invoice.number == invoice_number
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice number already exists")

    # Validation métier et calcul des totaux via le noyau logique.
    lines_data = [
        {
            "quantity": float(line.quantity),
            "unit_price": Decimal(str(line.unit_price_minor)) / Decimal("100"),
            "tax_rate": float(line.tax_rate),
        }
        for line in payload.lines
    ]
    try:
        validate_invoice_data({"lines": lines_data})
        totals = calculate_invoice_totals(lines_data)
    except CalculationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    invoice = Invoice(
        organization_id=organization.id,
        customer_id=payload.customer_id,
        number=invoice_number,
        currency=payload.currency,
        status=InvoiceStatus.DRAFT.value,
        notes=payload.notes,
        payment_terms=payload.payment_terms,
        purchase_order_number=payload.purchase_order_number,
        subtotal_minor=int(totals["subtotal"] * 100),
        tax_total_minor=int(totals["total_tax"] * 100),
        total_minor=int(totals["total_including_tax"] * 100),
        amount_due_minor=int(totals["total_including_tax"] * 100),
    )
    db.add(invoice)
    db.flush()  # obtenir l'ID avant de créer les lignes

    for position, line in enumerate(payload.lines):
        line_total = int(
            (line.quantity * Decimal(str(line.unit_price_minor))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        tax_amount = int(
            (Decimal(str(line_total)) * line.tax_rate / Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        db.add(
            InvoiceLine(
                organization_id=organization.id,
                invoice_id=invoice.id,
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                tax_rate=line.tax_rate,
                line_total_minor=line_total,
                tax_amount_minor=tax_amount,
                line_gross_minor=line_total + tax_amount,
                product_code=line.product_code,
                position=position,
            )
        )

    db.commit()
    db.refresh(invoice)

    _store_idempotent_response(db, idempotency_result, invoice)
    _trigger_async_processing(invoice.id)

    return invoice


@router.get("", response_model=PaginatedInvoices)
def list_invoices(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> PaginatedInvoices:
    stmt = select(Invoice).where(Invoice.organization_id == organization.id)
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    stmt = stmt.order_by(Invoice.created_at.desc())
    return PaginatedInvoices(**paginate(db, stmt, page, per_page))


@router.get("/{invoice_id}", response_model=InvoiceReadWithLines)
def get_invoice(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Invoice:
    return _get_invoice_or_404(db, organization, invoice_id)


@router.post("/{invoice_id}/issue", response_model=InvoiceReadWithLines)
def issue_invoice(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = _get_invoice_or_404(db, organization, invoice_id)
    _transition_or_409(invoice, InvoiceStatus.ISSUED, "transition to issued")

    if not invoice.lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot issue an invoice without line items",
        )

    now = datetime.now(timezone.utc)
    invoice.status = InvoiceStatus.ISSUED.value
    invoice.issue_date = now
    invoice.issued_at = now

    db.commit()
    db.refresh(invoice)
    _trigger_async_processing(invoice.id)
    return invoice


@router.post("/{invoice_id}/cancel", response_model=InvoiceReadWithLines)
def cancel_invoice(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = _get_invoice_or_404(db, organization, invoice_id)
    _transition_or_409(invoice, InvoiceStatus.CANCELLED, "cancel invoice")

    invoice.status = InvoiceStatus.CANCELLED.value
    invoice.amount_due_minor = 0
    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceReadWithLines)
def mark_invoice_paid(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = _get_invoice_or_404(db, organization, invoice_id)
    _transition_or_409(invoice, InvoiceStatus.PAID, "mark as paid")

    invoice.status = InvoiceStatus.PAID.value
    invoice.amount_due_minor = 0
    db.commit()
    db.refresh(invoice)
    return invoice


@router.patch("/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdate,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = _get_invoice_or_404(db, organization, invoice_id)
    if invoice.status != InvoiceStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only draft invoices can be updated"
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(invoice, field, value)

    db.commit()
    db.refresh(invoice)
    return invoice


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> None:
    invoice = _get_invoice_or_404(db, organization, invoice_id)
    if invoice.status != InvoiceStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only draft invoices can be deleted"
        )

    db.delete(invoice)
    db.commit()


# ---------------------------------------------------------------------------
# Exports facturation électronique (EN 16931)
# ---------------------------------------------------------------------------


def _load_document_data(db: Session, organization: Organization, invoice_id: str):
    """Charge facture+client et construit le DTO Factur-X ; 404/422 sinon."""
    from app.services.einvoicing_factory import document_from_invoice

    invoice = _get_invoice_or_404(db, organization, invoice_id)
    customer = db.get(Customer, invoice.customer_id) if invoice.customer_id else None
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invoice has no customer; cannot generate e-invoicing format",
        )
    return invoice, document_from_invoice(invoice, organization, customer)


@router.get("/{invoice_id}/export/xml")
def export_invoice_xml(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Response:
    """XML Factur-X (Cross Industry Invoice EN 16931)."""
    from app.services.einvoicing import build_cii_xml

    invoice, doc = _load_document_data(db, organization, invoice_id)
    xml_bytes = build_cii_xml(doc)
    filename = f"facture-{invoice.number}.xml"
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id}/export/ubl")
def export_invoice_ubl(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Response:
    """XML UBL 2.1 (interopérabilité internationale, sémantique EN 16931)."""
    from app.services.einvoicing import generate_ubl_xml

    invoice, doc = _load_document_data(db, organization, invoice_id)
    xml_bytes = generate_ubl_xml(doc)
    filename = f"facture-{invoice.number}-ubl.xml"
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id}/export/factur-x")
def export_invoice_facturx(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Response:
    """PDF hybride Factur-X : PDF lisible + XML CII en pièce jointe."""
    from app.services.einvoicing import generate_factur_x
    from app.tasks.invoice_tasks import build_invoice_pdf_bytes

    invoice, doc = _load_document_data(db, organization, invoice_id)
    pdf_bytes = build_invoice_pdf_bytes(db, invoice, organization)
    hybrid, _ = generate_factur_x(pdf_bytes, doc)
    filename = f"facture-{invoice.number}-factur-x.pdf"
    return Response(
        content=hybrid,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
