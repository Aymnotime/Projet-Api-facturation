from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, List, Optional
import math

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import ApiKey, Customer, Invoice, Organization, InvoiceLine, InvoiceStatus as ModelInvoiceStatus
from .schemas import (
    ApiKeyCreate,
    ApiKeyRead,
    CustomerCreate,
    CustomerRead,
    InvoiceCreate,
    InvoiceRead,
    InvoiceUpdate,
    OrganizationCreate,
    OrganizationRead,
    PaginatedCustomers,
    PaginatedInvoices,
)
from .security import generate_api_key, require_organization, require_organization_with_idempotency
from .tasks.invoice_tasks import generate_invoice_pdf, validate_invoice_en16931
from .core.logic import (
    calculate_invoice_totals,
    validate_state_transition,
    validate_invoice_data,
    CalculationError,
    InvoiceStatus,
    get_next_valid_statuses,
)
from .api.auth import router as auth_router
from .api.users import router as users_router
from .api.idempotency import IdempotencyHandler
from .api.invoice_numbering import router as invoice_numbering_router
from fastapi import Request
from sqlalchemy.orm import Session
from .db import get_db
from app.services.idempotency_service import IdempotencyService
import json

class InvoiceLineCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal('1.00'), gt=0)
    unit_price_minor: int = Field(gt=0, description="Unit price excluding tax in cents")
    tax_rate: Decimal = Field(default=Decimal('20.00'), ge=0, le=100, description="Tax rate percentage")
    product_code: Optional[str] = Field(default=None, max_length=64)

class InvoiceCreateWithLines(BaseModel):
    customer_id: str
    number: str = Field(min_length=1, max_length=64)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: Optional[str] = None
    payment_terms: Optional[str] = None
    purchase_order_number: Optional[str] = None
    lines: List[InvoiceLineCreate] = Field(..., min_length=1)

class InvoiceLineRead(BaseModel):
    id: str
    description: str
    quantity: Decimal
    unit_price_minor: int
    tax_rate: Decimal
    line_total_minor: int
    tax_amount_minor: int
    line_gross_minor: int
    product_code: Optional[str] = None
    
    model_config = {"from_attributes": True}

class InvoiceReadWithLines(InvoiceRead):
    lines: List[InvoiceLineRead] = []
    subtotal_minor: int = 0
    tax_total_minor: int = 0
    total_minor: int = 0
    amount_due_minor: int = 0
    issue_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    payment_terms: Optional[str] = None
    purchase_order_number: Optional[str] = None

Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="Projet API Facturation", 
    version="0.4.0", 
    description="API-first billing infrastructure with Identity, Users, RBAC and full business logic"
)

# Include routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(invoice_numbering_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/organizations", response_model=OrganizationRead, status_code=201)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)) -> Organization:
    organization = Organization(name=payload.name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@app.post("/v1/organizations/{organization_id}/api-keys", response_model=ApiKeyRead, status_code=201)
def create_api_key(
    organization_id: str, payload: ApiKeyCreate, db: Session = Depends(get_db)
) -> ApiKeyRead:
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    raw_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(organization_id=organization_id, name=payload.name, prefix=prefix, key_hash=key_hash)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyRead(id=api_key.id, name=api_key.name, prefix=api_key.prefix, key=raw_key, created_at=api_key.created_at)


@app.post("/v1/customers", response_model=CustomerRead, status_code=201)
def create_customer(
    payload: CustomerCreate, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db),
    request: Request = None,
    idempotency_result: dict = Depends(IdempotencyHandler())
) -> Customer:
    # Check for cached response from idempotency
    if idempotency_result.get("cached_response"):
        return idempotency_result["cached_response"]
    
    customer = Customer(organization_id=organization.id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    
    # Store response for idempotency if key was provided
    if idempotency_result.get("idempotency_key"):
        try:
            IdempotencyService.store_response(
                db=db,
                idempotency_key=idempotency_result["idempotency_key"],
                response_status=201,
                response_body={"id": customer.id, "name": customer.name, "email": customer.email}
            )
        except Exception:
            pass  # Don't fail on idempotency storage error
    
    return customer


@app.get("/v1/customers", response_model=PaginatedCustomers)
def list_customers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> PaginatedCustomers:
    offset = (page - 1) * per_page
    count_query = select(func.count()).select_from(Customer).where(Customer.organization_id == organization.id)
    total = db.scalar(count_query) or 0
    pages = math.ceil(total / per_page) if total > 0 else 1
    
    query = select(Customer).where(Customer.organization_id == organization.id).order_by(Customer.created_at.desc()).offset(offset).limit(per_page)
    items = list(db.scalars(query))
    
    return PaginatedCustomers(items=items, total=total, page=page, per_page=per_page, pages=pages)


@app.post("/v1/invoices", response_model=InvoiceReadWithLines, status_code=201)
def create_invoice_with_lines(
    payload: InvoiceCreateWithLines, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db),
    idempotency_result: dict = Depends(IdempotencyHandler())
) -> Invoice:
    # Check for cached response from idempotency
    if idempotency_result.get("cached_response"):
        # Return the cached response directly
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=idempotency_result["cached_response"].status_code,
            content=json.loads(idempotency_result["cached_response"].body.decode('utf-8'))
        )
    
    # Verify customer exists and belongs to organization
    customer = db.scalar(select(Customer).where(Customer.id == payload.customer_id, Customer.organization_id == organization.id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Auto-generate invoice number if not provided or if empty
    invoice_number = payload.number.strip() if payload.number else None
    if not invoice_number:
        # Generate automatic number using the numbering service
        from app.services.invoice_numbering_service import InvoiceNumberingService
        try:
            invoice_number = InvoiceNumberingService.generate_number(
                db=db,
                organization_id=organization.id,
                year=None,  # Current year
                prefix=None  # Default prefix based on organization
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate invoice number: {str(e)}")
    
    # Check invoice number uniqueness
    existing = db.scalar(select(Invoice).where(Invoice.organization_id == organization.id, Invoice.number == invoice_number))
    if existing:
        raise HTTPException(status_code=409, detail="Invoice number already exists")
    
    # Prepare line data for calculation
    lines_data = []
    for line in payload.lines:
        lines_data.append({
            'quantity': float(line.quantity),
            'unit_price': Decimal(str(line.unit_price_minor)) / Decimal('100'),
            'tax_rate': float(line.tax_rate)
        })
    
    # Validate and calculate totals
    try:
        validate_invoice_data({'lines': lines_data})
        totals = calculate_invoice_totals(lines_data)
    except CalculationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Create invoice
    invoice = Invoice(
        organization_id=organization.id,
        customer_id=payload.customer_id,
        number=invoice_number,
        currency=payload.currency,
        status=InvoiceStatus.DRAFT.value,
        notes=payload.notes,
        payment_terms=payload.payment_terms,
        purchase_order_number=payload.purchase_order_number,
        subtotal_minor=int(totals['subtotal'] * 100),
        tax_total_minor=int(totals['total_tax'] * 100),
        total_minor=int(totals['total_including_tax'] * 100),
        amount_due_minor=int(totals['total_including_tax'] * 100),
    )
    db.add(invoice)
    db.flush()  # Get invoice ID before creating lines
    
    # Create invoice lines
    for position, line in enumerate(payload.lines):
        line_total = int((line.quantity * Decimal(str(line.unit_price_minor))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        tax_amount = int((Decimal(str(line_total)) * line.tax_rate / Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        line_gross = line_total + tax_amount
        
        invoice_line = InvoiceLine(
            organization_id=organization.id,
            invoice_id=invoice.id,
            description=line.description,
            quantity=line.quantity,
            unit_price_minor=line.unit_price_minor,
            tax_rate=line.tax_rate,
            line_total_minor=line_total,
            tax_amount_minor=tax_amount,
            line_gross_minor=line_gross,
            product_code=line.product_code,
            position=position,
        )
        db.add(invoice_line)
    
    db.commit()
    db.refresh(invoice)
    
    # Store response for idempotency if key was provided
    if idempotency_result.get("idempotency_key"):
        try:
            from app.schemas import InvoiceReadWithLines as SchemaInvoiceReadWithLines
            response_data = {
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
                        "product_code": line.product_code
                    }
                    for line in invoice.lines
                ]
            }
            IdempotencyService.store_response(
                db=db,
                idempotency_key=idempotency_result["idempotency_key"],
                response_status=201,
                response_body=response_data
            )
        except Exception as e:
            pass  # Don't fail on idempotency storage error
    
    # Trigger async validation and PDF generation
    import os
    if os.getenv("REDIS_URL"):
        try:
            validate_invoice_en16931.delay(invoice.id)
            generate_invoice_pdf.delay(invoice.id)
        except Exception:
            pass
    
    return invoice


@app.get("/v1/invoices", response_model=PaginatedInvoices)
def list_invoices(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> PaginatedInvoices:
    offset = (page - 1) * per_page
    
    stmt = select(Invoice).where(Invoice.organization_id == organization.id)
    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    
    count_query = select(func.count()).select_from(Invoice).where(Invoice.organization_id == organization.id)
    if status_filter:
        count_query = count_query.where(Invoice.status == status_filter)
    
    total = db.scalar(count_query) or 0
    pages = math.ceil(total / per_page) if total > 0 else 1
    
    stmt = stmt.order_by(Invoice.created_at.desc()).offset(offset).limit(per_page)
    items = list(db.scalars(stmt))
    
    return PaginatedInvoices(items=items, total=total, page=page, per_page=per_page, pages=pages)


@app.get("/v1/invoices/{invoice_id}", response_model=InvoiceReadWithLines)
def get_invoice(
    invoice_id: str, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@app.post("/v1/invoices/{invoice_id}/issue", response_model=InvoiceReadWithLines)
def issue_invoice(
    invoice_id: str, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Validate state transition
    current_status = InvoiceStatus(invoice.status)
    if not validate_state_transition(current_status, InvoiceStatus.ISSUED):
        valid_statuses = [s.value for s in get_next_valid_statuses(current_status)]
        raise HTTPException(
            status_code=409, 
            detail=f"Cannot transition from {invoice.status} to issued. Valid transitions: {valid_statuses}"
        )
    
    # Check invoice has lines
    if not invoice.lines:
        raise HTTPException(status_code=400, detail="Cannot issue an invoice without line items")
    
    invoice.status = InvoiceStatus.ISSUED.value
    invoice.issue_date = datetime.now(timezone.utc)
    invoice.issued_at = datetime.now(timezone.utc)
    
    # Trigger PDF generation and validation on issue
    import os
    if os.getenv("REDIS_URL"):
        try:
            validate_invoice_en16931.delay(invoice.id)
            generate_invoice_pdf.delay(invoice.id)
        except Exception:
            pass
    
    db.commit()
    db.refresh(invoice)
    return invoice


@app.post("/v1/invoices/{invoice_id}/cancel", response_model=InvoiceReadWithLines)
def cancel_invoice(
    invoice_id: str, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    current_status = InvoiceStatus(invoice.status)
    if not validate_state_transition(current_status, InvoiceStatus.CANCELLED):
        valid_statuses = [s.value for s in get_next_valid_statuses(current_status)]
        raise HTTPException(
            status_code=409, 
            detail=f"Cannot cancel invoice with status {invoice.status}. Valid transitions: {valid_statuses}"
        )
    
    invoice.status = InvoiceStatus.CANCELLED.value
    invoice.amount_due_minor = 0
    db.commit()
    db.refresh(invoice)
    return invoice


@app.post("/v1/invoices/{invoice_id}/mark-paid", response_model=InvoiceReadWithLines)
def mark_invoice_paid(
    invoice_id: str, 
    organization: Organization = Depends(require_organization), 
    db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    current_status = InvoiceStatus(invoice.status)
    if not validate_state_transition(current_status, InvoiceStatus.PAID):
        valid_statuses = [s.value for s in get_next_valid_statuses(current_status)]
        raise HTTPException(
            status_code=409, 
            detail=f"Cannot mark as paid. Current status: {invoice.status}. Valid transitions: {valid_statuses}"
        )
    
    invoice.status = InvoiceStatus.PAID.value
    invoice.amount_due_minor = 0
    db.commit()
    db.refresh(invoice)
    return invoice


@app.patch("/v1/invoices/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdate,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft invoices can be updated")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(invoice, field, value)
    
    db.commit()
    db.refresh(invoice)
    return invoice


@app.delete("/v1/invoices/{invoice_id}", status_code=204)
def delete_invoice(
    invoice_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> None:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft invoices can be deleted")
    
    db.delete(invoice)
    db.commit()
