"""Service de dispatch des webhooks : création des livraisons et file morte.

Responsabilités :
* construire l'événement (id, type, payload) et le diffuser aux endpoints
  actifs de l'organisation abonnés au type d'événement ;
* persister une ``WebhookDelivery`` par endpoint (statut ``pending``) ;
* déclencher la livraison asynchrone Celery si un broker est configuré,
  sinon la laisser en attente pour un traitement différé (mode test/dev) ;
* gérer la **dead-letter queue** : les livraisons dont tous les retries
  sont épuisés passent en statut ``dead`` et peuvent être rejouées via
  l'API (endpoints de réémission).
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import WebhookDelivery, WebhookEndpoint


class WebhookDispatchError(ValueError):
    """Erreur de construction d'un événement webhook."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WebhookService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ CRUD
    def create_endpoint(
        self,
        organization_id: str,
        url: str,
        events: list[str],
        secret: str | None = None,
    ) -> WebhookEndpoint:
        if not url.startswith(("http://", "https://")):
            raise WebhookDispatchError("url must start with http:// or https://")
        endpoint = WebhookEndpoint(
            organization_id=organization_id,
            url=url,
            secret=secret or f"whsec_{secrets.token_hex(24)}",
            events=json.dumps(sorted(set(events))),
            is_active=True,
        )
        self.db.add(endpoint)
        self.db.commit()
        self.db.refresh(endpoint)
        return endpoint

    def list_endpoints(self, organization_id: str) -> list[WebhookEndpoint]:
        return list(
            self.db.scalars(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.organization_id == organization_id
                )
            )
        )

    def get_endpoint(self, organization_id: str, endpoint_id: str) -> WebhookEndpoint | None:
        return self.db.scalar(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.organization_id == organization_id,
            )
        )

    def delete_endpoint(self, endpoint: WebhookEndpoint) -> None:
        self.db.delete(endpoint)
        self.db.commit()

    # -------------------------------------------------------------- dispatch
    def dispatch_event(
        self,
        organization_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> list[WebhookDelivery]:
        """Crée une livraison pour chaque endpoint actif abonné à ``event_type``.

        L'identifiant de livraison sert aussi de ``X-Webhook-ID`` : le
        récepteur peut donc dédupliquer (idempotence côté consommateur).
        """
        deliveries: list[WebhookDelivery] = []
        for endpoint in self.list_endpoints(organization_id):
            if not endpoint.is_active:
                continue
            subscribed = set(json.loads(endpoint.events or "[]"))
            if "*" not in subscribed and event_type not in subscribed:
                continue
            payload = {
                "id": None,  # rempli après flush (id généré par défaut SQLAlchemy)
                "type": event_type,
                "created_at": _utcnow().isoformat(),
                "data": data,
            }
            delivery = WebhookDelivery(
                webhook_id=endpoint.id,
                event_type=event_type,
                payload=json.dumps(payload),
                status="pending",
            )
            self.db.add(delivery)
            self.db.flush()
            payload["id"] = delivery.id
            delivery.payload = json.dumps(payload)
            deliveries.append(delivery)
        self.db.commit()

        settings = get_settings()
        if settings.async_processing_enabled and deliveries:
            from app.tasks.webhook_tasks import deliver_webhook  # local import: celery optional

            for delivery, endpoint in zip(
                deliveries,
                [self.get_endpoint_by_id(d.webhook_id) for d in deliveries],
            ):
                if endpoint is None:
                    continue
                deliver_webhook.delay(
                    delivery.id,
                    endpoint.url,
                    endpoint.secret,
                    delivery.event_type,
                    json.loads(delivery.payload),
                )
        return deliveries

    def get_endpoint_by_id(self, endpoint_id: str) -> WebhookEndpoint | None:
        return self.db.get(WebhookEndpoint, endpoint_id)

    # ------------------------------------------------------ dead-letter queue
    def record_result(
        self,
        delivery_id: str,
        *,
        status: str,
        http_status: int | None = None,
        response_body: str | None = None,
        error: str | None = None,
    ) -> WebhookDelivery | None:
        """Met à jour une livraison après une tentative (appelé par Celery).

        Si les retries sont épuisés (``retries_exhausted`` dans ``error`` ou
        statut ``failed`` explicite), la livraison bascule en ``dead`` :
        c'est la dead-letter queue, consultable/rejouable via l'API.
        """
        delivery = self.db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return None
        delivery.attempt_count = (delivery.attempt_count or 0) + 1
        delivery.http_status = http_status
        delivery.response_body = (response_body or "")[:2000] or response_body
        if status == "success":
            delivery.status = "delivered"
            delivery.delivered_at = _utcnow()
            delivery.next_retry_at = None
        elif status == "retry":
            delivery.status = "retrying"
        else:
            delivery.status = "dead"
            delivery.error_message = error
            delivery.next_retry_at = None
        self.db.commit()
        self.db.refresh(delivery)
        return delivery

    def dead_letters(self, organization_id: str) -> list[WebhookDelivery]:
        """Liste les livraisons en dead-letter pour l'organisation."""
        return list(
            self.db.scalars(
                select(WebhookDelivery)
                .join(WebhookEndpoint, WebhookDelivery.webhook_id == WebhookEndpoint.id)
                .where(
                    WebhookEndpoint.organization_id == organization_id,
                    WebhookDelivery.status == "dead",
                )
                .order_by(WebhookDelivery.created_at.desc())
            )
        )

    def requeue(self, delivery: WebhookDelivery) -> WebhookDelivery:
        """Réinitialise une livraison morte pour nouvelle tentative."""
        delivery.status = "pending"
        delivery.next_retry_at = None
        delivery.error_message = None
        self.db.commit()
        self.db.refresh(delivery)
        settings = get_settings()
        if settings.async_processing_enabled:
            from app.tasks.webhook_tasks import deliver_webhook

            endpoint = self.get_endpoint_by_id(delivery.webhook_id)
            if endpoint is not None:
                deliver_webhook.delay(
                    delivery.id,
                    endpoint.url,
                    endpoint.secret,
                    delivery.event_type,
                    json.loads(delivery.payload),
                )
        return delivery
