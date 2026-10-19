"""Endpoints de gestion des organisations et des clés API."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Organization
from app.schemas import ApiKeyCreate, ApiKeyRead, OrganizationCreate, OrganizationRead
from app.security import generate_api_key, require_organization

router = APIRouter(tags=["organizations"])


@router.post("/v1/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)) -> Organization:
    organization = Organization(name=payload.name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/v1/organizations/me", response_model=OrganizationRead)
def get_current_organization(
    organization: Organization = Depends(require_organization),
) -> Organization:
    """Retourne l'organisation associée à la clé API utilisée."""
    return organization


@router.post(
    "/v1/organizations/{organization_id}/api-keys",
    response_model=ApiKeyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_api_key(
    organization_id: str, payload: ApiKeyCreate, db: Session = Depends(get_db)
) -> ApiKeyRead:
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    raw_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(organization_id=organization_id, name=payload.name, prefix=prefix, key_hash=key_hash)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyRead(
        id=api_key.id, name=api_key.name, prefix=api_key.prefix, key=raw_key, created_at=api_key.created_at
    )
