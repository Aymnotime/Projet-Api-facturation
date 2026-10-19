"""Endpoints de gestion des clients."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.idempotency import IdempotencyHandler
from app.db import get_db
from app.models import Customer, Organization
from app.schemas import CustomerCreate, CustomerRead, PaginatedCustomers
from app.security import require_organization
from app.services.idempotency_service import IdempotencyService
from app.services.pagination import paginate

router = APIRouter(prefix="/v1/customers", tags=["customers"])


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
    idempotency_result: dict = Depends(IdempotencyHandler()),
) -> Customer:
    # Si une réponse est déjà associée à la clé d'idempotence, on la renvoie.
    if idempotency_result.get("cached_response"):
        return idempotency_result["cached_response"]

    customer = Customer(organization_id=organization.id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)

    # Mémoriser la réponse si une clé d'idempotence a été fournie.
    if idempotency_result.get("idempotency_key"):
        try:
            IdempotencyService.store_response(
                db=db,
                idempotency_key=idempotency_result["idempotency_key"],
                response_status=status.HTTP_201_CREATED,
                response_body={"id": customer.id, "name": customer.name, "email": customer.email},
            )
        except Exception:
            pass  # Ne pas faire échouer la requête si le stockage idempotent échoue

    return customer


@router.get("", response_model=PaginatedCustomers)
def list_customers(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> PaginatedCustomers:
    stmt = (
        select(Customer)
        .where(Customer.organization_id == organization.id)
        .order_by(Customer.created_at.desc())
    )
    return PaginatedCustomers(**paginate(db, stmt, page, per_page))
