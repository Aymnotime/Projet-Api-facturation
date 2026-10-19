"""Endpoints de transmission vers les plateformes PDP (facturation électronique).

- POST /v1/transmissions                   : soumettre une facture à un fournisseur
- GET  /v1/transmissions                   : lister les transmissions (paginé, filtres)
- GET  /v1/transmissions/{id}              : détail d'une transmission
- POST /v1/transmissions/{id}/refresh      : ré-interroger le cycle de vie PDP
- GET  /v1/transmissions/providers         : fournisseurs enregistrés
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, Transmission
from app.schemas import (
    PDPProvidersResponse,
    TransmissionRead,
    TransmissionSubmitRequest,
)
from app.security import require_organization
from app.services.pdp.adapter import PDPTransmissionError, registered_providers
from app.services.rate_limit import RateLimiter, get_rate_limiter
from app.services.security_middleware import apply_rate_limit
from app.services.transmission_service import TransmissionService

router = APIRouter(prefix="/v1/transmissions", tags=["transmissions"])


def _get_transmission_or_404(db: Session, organization: Organization, transmission_id: str) -> Transmission:
    transmission = db.scalar(
        select(Transmission).where(
            Transmission.id == transmission_id,
            Transmission.organization_id == organization.id,
        )
    )
    if not transmission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transmission not found")
    return transmission


@router.post("", response_model=TransmissionRead, status_code=status.HTTP_201_CREATED)
def submit_transmission(
    request: Request,
    payload: TransmissionSubmitRequest,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
    limiter: RateLimiter | None = Depends(get_rate_limiter),
) -> Transmission:
    """Transmet une facture émise à une PDP via l'adaptateur du fournisseur.

    Rate limited : les appels PDP sortants sont coûteux et doivent être
    protégés contre les rafales de soumissions.
    """
    apply_rate_limit(request, limiter, bucket_prefix="submit")
    service = TransmissionService(db)
    try:
        return service.submit_invoice(
            organization, payload.invoice_id, provider=payload.provider, format=payload.format
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PDPTransmissionError as exc:
        # L'échec technique est déjà persisté sur la Transmission ; on le remonte en 502.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("", response_model=None)
def list_transmissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    invoice_id: str | None = Query(None),
    provider: str | None = Query(None),
    tx_status: str | None = Query(None, alias="status"),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    """Liste paginée des transmissions de l'organisation."""
    query = select(Transmission).where(Transmission.organization_id == organization.id)
    if invoice_id:
        query = query.where(Transmission.invoice_id == invoice_id)
    if provider:
        query = query.where(Transmission.pdp_provider == provider)
    if tx_status:
        query = query.where(Transmission.status == tx_status)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Transmission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [TransmissionRead.model_validate(t) for t in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/providers", response_model=PDPProvidersResponse)
def list_pdp_providers(organization: Organization = Depends(require_organization)) -> PDPProvidersResponse:
    """Fournisseurs PDP disponibles (adaptateurs enregistrés)."""
    return PDPProvidersResponse(providers=registered_providers())


@router.get("/{transmission_id}", response_model=TransmissionRead)
def get_transmission(
    transmission_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Transmission:
    return _get_transmission_or_404(db, organization, transmission_id)


@router.post("/{transmission_id}/refresh", response_model=TransmissionRead)
def refresh_transmission(
    transmission_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
) -> Transmission:
    """Ré-interroge la plateforme PDP et met à jour le statut du cycle de vie."""
    service = TransmissionService(db)
    try:
        return service.refresh_status(organization, transmission_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transmission not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PDPTransmissionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
