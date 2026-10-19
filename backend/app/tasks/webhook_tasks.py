"""Tâches Celery de livraison des webhooks.

Garanties :
* signature **HMAC-SHA256** Stripe-style sur ``timestamp.payload`` ;
* **retries exponentiels** (30s * 2^n, max 5 tentatives) pour les erreurs
  réseau / 5xx / 408 / 429 ;
* pas de retry sur les 4xx client définitifs → échec immédiat en DLQ ;
* à l'épuisement des retries, la livraison bascule en **dead-letter**
  (statut ``dead`` dans ``WebhookDelivery``), consultable et rejouable
  via l'API ;
* idempotence : ``X-Webhook-ID`` = identifiant de livraison, stable entre
  toutes les tentatives, pour que le récepteur puisse dédupliquer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from celery import Task

from app.workers.celery_app import celery_app

MAX_ATTEMPTS = 5


class TransientWebhookError(Exception):
    """Erreur temporaire justifiant un nouveau retry."""


def generate_webhook_signature(payload: str, secret: str, timestamp: int) -> str:
    """Signature HMAC-SHA256 Stripe-style : ``t=<ts>,v1=<hex>``."""
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_webhook_signature(
    payload: str, secret: str, header_value: str, tolerance_seconds: int = 300
) -> bool:
    """Vérifie une signature reçue (utilisé par les tests contractuels)."""
    try:
        parts = dict(
            kv.split("=", 1) for kv in header_value.split(",") if "=" in kv
        )
        timestamp = int(parts["t"])
        provided = parts["v1"]
    except (ValueError, KeyError):
        return False
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{timestamp}.{payload}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def _update_delivery(delivery_id: str, **kwargs: Any) -> None:
    """Persiste le résultat d'une tentative (session dédiée hors request)."""
    from app.db import SessionLocal
    from app.services.webhook_service import WebhookService

    db = SessionLocal()
    try:
        WebhookService(db).record_result(delivery_id, **kwargs)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.webhook.deliver", max_retries=MAX_ATTEMPTS)
def deliver_webhook(
    self: Task,
    delivery_id: str,
    endpoint_url: str,
    secret: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Livre un webhook avec signature, retries exponentiels et dead-letter queue."""
    timestamp = int(time.time())
    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = generate_webhook_signature(payload_str, secret, timestamp)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BillingAPI-Webhooks/1.0",
        "X-Webhook-ID": delivery_id,          # stable → idempotence consommateur
        "X-Webhook-Timestamp": str(timestamp),
        "X-Webhook-Signature": signature,
        "X-Webhook-Event": event_type,
        "X-Webhook-Attempt": str(self.request.retries + 1),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint_url, content=payload_str, headers=headers)
        status_code, body = response.status_code, response.text[:2000]

        if 200 <= status_code < 300:
            _update_delivery(
                delivery_id, status="success", http_status=status_code, response_body=body
            )
            return {"status": "delivered", "delivery_id": delivery_id, "http_status": status_code}

        if status_code in (408, 429) or status_code >= 500:
            raise TransientWebhookError(f"transient HTTP {status_code}")

        # 4xx définitif : pas de retry, direction la dead-letter queue.
        _update_delivery(
            delivery_id,
            status="dead",
            http_status=status_code,
            response_body=body,
            error=f"client error {status_code}, no retry",
        )
        return {"status": "dead", "delivery_id": delivery_id, "http_status": status_code}

    except (httpx.TimeoutException, httpx.ConnectError, TransientWebhookError) as exc:
        attempt = self.request.retries
        if attempt < MAX_ATTEMPTS - 1:
            countdown = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s…
            _update_delivery(
                delivery_id, status="retry",
                error=f"attempt {attempt + 1} failed: {exc}",
            )
            raise self.retry(exc=exc, countdown=countdown)
        _update_delivery(
            delivery_id,
            status="dead",
            error=f"retries exhausted after {MAX_ATTEMPTS} attempts: {exc}",
        )
        return {"status": "dead", "delivery_id": delivery_id, "retries_exhausted": True}
