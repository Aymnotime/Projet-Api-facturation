"""Endpoints de gestion des webhooks.

- POST   /v1/webhooks/endpoints              : déclarer un endpoint (secret auto si absent)
- GET    /v1/webhooks/endpoints              : lister les endpoints
- GET    /v1/webhooks/endpoints/{id}         : détail
- DELETE /v1/webhooks/endpoints/{id}         : supprimer
- POST   /v1/webhooks/endpoints/{id}/test    : livrer un événement de test (signature incluse)
- GET    /v1/webhooks/deliveries             : historique des livraisons (filtre statut)
- GET    /v1/webhooks/dead-letters           : dead-letter queue
- POST   /v1/webhooks/deliveries/{id}/replay : réémettre une livraison morte
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, WebhookDelivery, WebhookEndpoint
from app.schemas import (
    WebhookDeliveryRead,
    WebhookEndpointCreate,
    WebhookEndpointRead,
    WebhookTestRequest,
)
from app.security import require_organization
from app.services.webhook_service import WebhookDispatchError, WebhookService

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def _service(db: Session) -> WebhookService:
    return WebhookService(db)


def _get_endpoint_or_404(
    db: Session, organization: Organization, endpoint_id: str
) -> WebhookEndpoint:
    endpoint = _service(db).get_endpoint(organization.id, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")
    return endpoint


@router.post(
    "/endpoints",
    response_model=WebhookEndpointRead,
    status_code=status.HTTP_201_CREATED,
)
def create_endpoint(
    payload: WebhookEndpointCreate,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    """Déclare un endpoint webhook. Le secret HMAC est généré si non fourni."""
    try:
        endpoint = _service(db).create_endpoint(
            organization.id, payload.url, payload.events, payload.secret
        )
    except WebhookDispatchError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    # Réponse enrichie du secret en clair (visible une seule fois, comme Stripe).
    data = WebhookEndpointRead.model_validate(endpoint).model_dump()
    data["secret"] = endpoint.secret
    return data


@router.get("/endpoints", response_model=list[WebhookEndpointRead])
def list_endpoints(
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    return _service(db).list_endpoints(organization.id)


@router.get("/endpoints/{endpoint_id}", response_model=WebhookEndpointRead)
def get_endpoint(
    endpoint_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    return _get_endpoint_or_404(db, organization, endpoint_id)


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(
    endpoint_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    _service(db).delete_endpoint(_get_endpoint_or_404(db, organization, endpoint_id))


@router.post("/endpoints/{endpoint_id}/test", response_model=WebhookDeliveryRead)
def test_endpoint(
    endpoint_id: str,
    payload: WebhookTestRequest,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    """Envoie un événement de test signé vers l'endpoint (vérif de signature côté client)."""
    endpoint = _get_endpoint_or_404(db, organization, endpoint_id)
    deliveries = _service(db).dispatch_event(
        organization.id,
        payload.event_type,
        {"test": True, "endpoint_id": endpoint.id, **payload.data},
    )
    if not deliveries:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"endpoint is not subscribed to event '{payload.event_type}'",
        )
    return deliveries[0]


@router.get("/deliveries", response_model=list[WebhookDeliveryRead])
def list_deliveries(
    delivery_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    query = (
        select(WebhookDelivery)
        .join(WebhookEndpoint, WebhookDelivery.webhook_id == WebhookEndpoint.id)
        .where(WebhookEndpoint.organization_id == organization.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    if delivery_status:
        query = query.where(WebhookDelivery.status == delivery_status)
    return list(db.scalars(query))


@router.get("/dead-letters", response_model=list[WebhookDeliveryRead])
def list_dead_letters(
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    """Dead-letter queue : livraisons dont tous les retries sont épuisés."""
    return _service(db).dead_letters(organization.id)


@router.post("/deliveries/{delivery_id}/replay", response_model=WebhookDeliveryRead)
def replay_delivery(
    delivery_id: str,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db),
):
    """Réémet une livraison (morte ou non) : remise en file avec nouvel essai Celery."""
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    endpoint = db.get(WebhookEndpoint, delivery.webhook_id)
    if endpoint is None or endpoint.organization_id != organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    service = _service(db)
    if endpoint.is_active:
        service.dispatch_event(
            organization.id,
            delivery.event_type,
            json.loads(delivery.payload).get("data", {}),
        )
    return service.requeue(delivery)
