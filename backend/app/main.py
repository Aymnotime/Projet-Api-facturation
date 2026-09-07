from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import ApiKey, Customer, Invoice, Organization
from .schemas import (
    ApiKeyCreate,
    ApiKeyRead,
    CustomerCreate,
    CustomerRead,
    InvoiceCreate,
    InvoiceRead,
    OrganizationCreate,
    OrganizationRead,
)
from .security import generate_api_key, require_organization

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Projet API Facturation", version="0.1.0", description="API-first billing infrastructure")


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
    payload: CustomerCreate, organization: Organization = Depends(require_organization), db: Session = Depends(get_db)
) -> Customer:
    customer = Customer(organization_id=organization.id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get("/v1/customers", response_model=list[CustomerRead])
def list_customers(
    organization: Organization = Depends(require_organization), db: Session = Depends(get_db)
) -> list[Customer]:
    return list(db.scalars(select(Customer).where(Customer.organization_id == organization.id).order_by(Customer.created_at.desc())))


@app.post("/v1/invoices", response_model=InvoiceRead, status_code=201)
def create_invoice(
    payload: InvoiceCreate, organization: Organization = Depends(require_organization), db: Session = Depends(get_db)
) -> Invoice:
    customer = db.scalar(select(Customer).where(Customer.id == payload.customer_id, Customer.organization_id == organization.id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    existing = db.scalar(select(Invoice).where(Invoice.organization_id == organization.id, Invoice.number == payload.number))
    if existing:
        raise HTTPException(status_code=409, detail="Invoice number already exists")
    invoice = Invoice(organization_id=organization.id, status="draft", **payload.model_dump())
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@app.get("/v1/invoices", response_model=list[InvoiceRead])
def list_invoices(
    organization: Organization = Depends(require_organization), db: Session = Depends(get_db)
) -> list[Invoice]:
    return list(db.scalars(select(Invoice).where(Invoice.organization_id == organization.id).order_by(Invoice.created_at.desc())))


@app.post("/v1/invoices/{invoice_id}/issue", response_model=InvoiceRead)
def issue_invoice(
    invoice_id: str, organization: Organization = Depends(require_organization), db: Session = Depends(get_db)
) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization.id))
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft invoices can be issued")
    invoice.status = "issued"
    invoice.issued_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invoice)
    return invoice
