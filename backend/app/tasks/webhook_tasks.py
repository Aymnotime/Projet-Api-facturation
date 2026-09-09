"""Async webhook delivery tasks."""
from celery import Task
from typing import Any
import hashlib
import hmac
import json
import time

import httpx

from app.workers.celery_app import celery_app


def generate_webhook_signature(payload: str, secret: str, timestamp: int) -> str:
    """Generate HMAC signature for webhook payload (Stripe-style)."""
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def deliver_webhook(
    self: Task,
    webhook_id: str,
    endpoint_url: str,
    secret: str,
    event_type: str,
    payload: dict[str, Any]
) -> dict[str, Any]:
    """Deliver a webhook to an endpoint with retry logic."""
    timestamp = int(time.time())
    payload_str = json.dumps(payload, separators=(',', ':'))
    signature = generate_webhook_signature(payload_str, secret, timestamp)
    
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-ID": webhook_id,
        "X-Webhook-Timestamp": str(timestamp),
        "X-Webhook-Signature": signature,
        "X-Webhook-Event": event_type,
    }
    
    try:
        async def _send():
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    endpoint_url,
                    content=payload_str,
                    headers=headers
                )
                return response.status_code, response.text
        
        # For sync compatibility, use sync httpx client
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                endpoint_url,
                content=payload_str,
                headers=headers
            )
            status_code = response.status_code
            body = response.text
        
        if status_code >= 500:
            raise Exception(f"Server error: {status_code}")
        elif status_code >= 400:
            return {
                "status": "failed",
                "webhook_id": webhook_id,
                "status_code": status_code,
                "body": body,
                "retry": False  # Client error, don't retry
            }
        
        return {
            "status": "success",
            "webhook_id": webhook_id,
            "status_code": status_code,
            "delivered_at": timestamp
        }
        
    except httpx.TimeoutException as exc:
        raise self.retry(exc=exc, countdown=120)
    except httpx.ConnectError as exc:
        raise self.retry(exc=exc, countdown=60)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        return {
            "status": "failed",
            "webhook_id": webhook_id,
            "error": str(exc),
            "retries_exhausted": True
        }
