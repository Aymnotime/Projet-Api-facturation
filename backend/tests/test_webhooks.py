"""Tests du pipeline de webhooks.

Couvre :
* signature HMAC-SHA256 (génération + vérification contractuelle) ;
* retries exponentiels Celery et bascule en dead-letter queue ;
* idempotence (X-Webhook-ID stable entre tentatives) ;
* endpoints API : création d'endpoint, test, replay, DLQ.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models import WebhookDelivery, WebhookEndpoint
from app.services.webhook_service import WebhookDispatchError, WebhookService
from app.tasks.webhook_tasks import (
    MAX_ATTEMPTS,
    generate_webhook_signature,
    verify_webhook_signature,
)


# ---------------------------------------------------------------------------
# Signature HMAC-SHA256
# ---------------------------------------------------------------------------

class TestSignature:
    def test_stripe_style_format(self):
        sig = generate_webhook_signature('{"a":1}', "whsec_test", 1700000000)
        assert sig.startswith("t=1700000000,v1=")
        # hexadécimal sha256 = 64 caractères
        assert len(sig.split("v1=")[1]) == 64

    def test_deterministic(self):
        a = generate_webhook_signature("payload", "secret", 123)
        b = generate_webhook_signature("payload", "secret", 123)
        assert a == b

    def test_different_secret_changes_signature(self):
        a = generate_webhook_signature("payload", "secret1", 123)
        b = generate_webhook_signature("payload", "secret2", 123)
        assert a != b

    def test_verify_roundtrip(self):
        payload = '{"id":"x","type":"invoice.paid"}'
        ts = int(time.time())
        sig = generate_webhook_signature(payload, "whsec_topsecret", ts)
        assert verify_webhook_signature(payload, "whsec_topsecret", sig) is True

    def test_verify_rejects_wrong_secret(self):
        payload = "{}"
        ts = int(time.time())
        sig = generate_webhook_signature(payload, "right", ts)
        assert verify_webhook_signature(payload, "wrong", sig) is False

    def test_verify_rejects_tampered_payload(self):
        payload = '{"amount":100}'
        ts = int(time.time())
        sig = generate_webhook_signature(payload, "secret", ts)
        assert verify_webhook_signature('{"amount":999}', "secret", sig) is False

    def test_verify_rejects_expired_timestamp(self):
        payload = "{}"
        old_ts = int(time.time()) - 10_000
        sig = generate_webhook_signature(payload, "secret", old_ts)
        assert verify_webhook_signature(payload, "secret", sig, tolerance_seconds=300) is False

    def test_verify_rejects_malformed_header(self):
        assert verify_webhook_signature("{}", "secret", "garbage") is False
        assert verify_webhook_signature("{}", "secret", "t=abc,v1=def") is False


# ---------------------------------------------------------------------------
# Dispatch service (abonnements, payload, X-Webhook-ID)
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_creates_delivery_for_subscribed_endpoint(self, db_session, test_organization):
        service = WebhookService(db_session)
        service.create_endpoint(
            test_organization.id,
            "https://example.com/hook",
            ["invoice.issued"],
            secret="whsec_unit_test_secret",
        )
        deliveries = service.dispatch_event(
            test_organization.id, "invoice.issued", {"invoice_id": "inv-1"}
        )
        assert len(deliveries) == 1
        payload = json.loads(deliveries[0].payload)
        assert payload["type"] == "invoice.issued"
        assert payload["data"] == {"invoice_id": "inv-1"}
        # L'id dans le payload == id de livraison → idempotence consommateur
        assert payload["id"] == deliveries[0].id
        assert deliveries[0].status == "pending"

    def test_skips_unsubscribed_event(self, db_session, test_organization):
        service = WebhookService(db_session)
        service.create_endpoint(test_organization.id, "https://example.com/hook", ["invoice.paid"])
        deliveries = service.dispatch_event(test_organization.id, "invoice.issued", {})
        assert deliveries == []

    def test_skips_inactive_endpoint(self, db_session, test_organization):
        service = WebhookService(db_session)
        endpoint = service.create_endpoint(
            test_organization.id, "https://example.com/hook", ["*"]
        )
        endpoint.is_active = False
        db_session.commit()
        assert service.dispatch_event(test_organization.id, "any.event", {}) == []

    def test_wildcard_subscription(self, db_session, test_organization):
        service = WebhookService(db_session)
        service.create_endpoint(test_organization.id, "https://example.com/hook", ["*"])
        assert len(service.dispatch_event(test_organization.id, "whatever.happens", {})) == 1

    def test_rejects_non_http_url(self, db_session, test_organization):
        with pytest.raises(WebhookDispatchError):
            WebhookService(db_session).create_endpoint(
                test_organization.id, "ftp://bad.example", ["a.b"]
            )

    def test_secret_auto_generated(self, db_session, test_organization):
        endpoint = WebhookService(db_session).create_endpoint(
            test_organization.id, "https://example.com/hook", ["a.b"]
        )
        assert endpoint.secret.startswith("whsec_")
        assert len(endpoint.secret) >= 20


# ---------------------------------------------------------------------------
# Retries exponentiels + dead-letter queue (tâche Celery)
# ---------------------------------------------------------------------------

def _make_task_result(retries: int = 0) -> MagicMock:
    task = MagicMock()
    task.request.retries = retries
    return task


def _run_bound(task_mock, *args):
    """Exécute deliver_webhook avec self=task_mock (tâche bind=True sans broker)."""
    from app.tasks.webhook_tasks import deliver_webhook

    return deliver_webhook.__wrapped__(task_mock, *args)



class TestCeleryDelivery:
    @patch("app.tasks.webhook_tasks._update_delivery")
    def test_success_marks_delivered(self, mock_update):
        from app.tasks.webhook_tasks import deliver_webhook

        response = MagicMock(status_code=200, text="ok")
        client = MagicMock()
        client.__enter__.return_value.post.return_value = response
        with patch("app.tasks.webhook_tasks.httpx.Client", return_value=client):
            result = deliver_webhook.run(
                "dlv-1", "https://ex.com/hook", "whsec_x", "invoice.paid", {"id": "dlv-1"}
            )
        assert result["status"] == "delivered"
        mock_update.assert_called_once_with("dlv-1", status="success", http_status=200, response_body="ok")

    @patch("app.tasks.webhook_tasks._update_delivery")
    def test_4xx_goes_to_dlq_without_retry(self, mock_update):
        from app.tasks.webhook_tasks import deliver_webhook

        response = MagicMock(status_code=400, text="bad request")
        client = MagicMock()
        client.__enter__.return_value.post.return_value = response
        with patch("app.tasks.webhook_tasks.httpx.Client", return_value=client):
            result = deliver_webhook.run(
                "dlv-2", "https://ex.com/hook", "whsec_x", "invoice.paid", {}
            )
        assert result["status"] == "dead"
        kwargs = mock_update.call_args.kwargs
        assert kwargs["status"] == "dead"
        assert "no retry" in kwargs["error"]

    @patch("app.tasks.webhook_tasks._update_delivery")
    def test_5xx_schedules_exponential_retry(self, mock_update):
        from app.tasks.webhook_tasks import TransientWebhookError, deliver_webhook

        task = _make_task_result(retries=2)
        response = MagicMock(status_code=503, text="unavailable")
        client = MagicMock()
        client.__enter__.return_value.post.return_value = response
        with patch("app.tasks.webhook_tasks.httpx.Client", return_value=client):
            with pytest.raises(TransientWebhookError):
                _run_bound(
                    task, "dlv-3", "https://ex.com/hook", "whsec_x", "invoice.paid", {}
                )
        # self.retry doit être appelé avec countdown = 30 * 2^2 = 120
        task.retry.assert_called_once()
        assert task.retry.call_args.kwargs["countdown"] == 30 * (2 ** 2)

    @patch("app.tasks.webhook_tasks._update_delivery")
    def test_retries_exhausted_moves_to_dlq(self, mock_update):
        from app.tasks.webhook_tasks import deliver_webhook

        task = _make_task_result(retries=MAX_ATTEMPTS - 1)
        client = MagicMock()
        client.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")
        with patch("app.tasks.webhook_tasks.httpx.Client", return_value=client):
            result = _run_bound(
                task, "dlv-4", "https://ex.com/hook", "whsec_x", "invoice.paid", {}
            )
        assert result["status"] == "dead"
        assert result["retries_exhausted"] is True
        assert "retries exhausted" in mock_update.call_args.kwargs["error"]

    @patch("app.tasks.webhook_tasks._update_delivery")
    def test_webhook_id_header_is_stable(self, mock_update):
        """Idempotence : X-Webhook-ID identique sur toutes les tentatives."""
        from app.tasks.webhook_tasks import deliver_webhook

        captured = []

        def fake_post(url, content=None, headers=None):
            captured.append(headers["X-Webhook-ID"])
            return MagicMock(status_code=200, text="ok")

        client = MagicMock()
        client.__enter__.return_value.post.side_effect = fake_post
        with patch("app.tasks.webhook_tasks.httpx.Client", return_value=client):
            for attempt in range(3):
                deliver_webhook.run(
                    "dlv-stable", "https://ex.com/hook", "whsec_x", "e.t", {},
                )
        assert set(captured) == {"dlv-stable"}


# ---------------------------------------------------------------------------
# Service : record_result / dead_letters / requeue
# ---------------------------------------------------------------------------

class TestDeadLetterQueue:
    def _delivery(self, db_session, test_organization) -> WebhookDelivery:
        service = WebhookService(db_session)
        service.create_endpoint(test_organization.id, "https://ex.com/hook", ["invoice.paid"])
        return service.dispatch_event(test_organization.id, "invoice.paid", {})[0]

    def test_record_dead(self, db_session, test_organization):
        service = WebhookService(db_session)
        delivery = self._delivery(db_session, test_organization)
        updated = service.record_result(delivery.id, status="dead", error="all retries failed")
        assert updated.status == "dead"
        assert updated.error_message == "all retries failed"

    def test_dead_letters_listing(self, db_session, test_organization):
        service = WebhookService(db_session)
        delivery = self._delivery(db_session, test_organization)
        assert service.dead_letters(test_organization.id) == []
        service.record_result(delivery.id, status="dead", error="x")
        dlq = service.dead_letters(test_organization.id)
        assert [d.id for d in dlq] == [delivery.id]

    def test_requeue_resets_state(self, db_session, test_organization):
        service = WebhookService(db_session)
        delivery = self._delivery(db_session, test_organization)
        service.record_result(delivery.id, status="dead", error="x")
        revived = service.requeue(delivery)
        assert revived.status == "pending"
        assert revived.error_message is None
        assert service.dead_letters(test_organization.id) == []

    def test_attempt_count_increments(self, db_session, test_organization):
        service = WebhookService(db_session)
        delivery = self._delivery(db_session, test_organization)
        service.record_result(delivery.id, status="retry", error="timeout")
        service.record_result(delivery.id, status="success", http_status=200)
        fresh = db_session.get(WebhookDelivery, delivery.id)
        assert fresh.attempt_count == 2
        assert fresh.status == "delivered"
        assert fresh.delivered_at is not None


# ---------------------------------------------------------------------------
# Endpoints API
# ---------------------------------------------------------------------------

class TestWebhookEndpointsAPI:
    def test_create_endpoint_returns_secret(self, client, auth_headers):
        resp = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["invoice.*"]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["secret"].startswith("whsec_")
        assert body["events"] == ["invoice.*"]

    def test_list_and_delete_endpoint(self, client, auth_headers):
        created = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["a.b"]},
        ).json()
        listing = client.get("/v1/webhooks/endpoints", headers=auth_headers)
        assert listing.status_code == 200
        assert created["id"] in [e["id"] for e in listing.json()]
        deleted = client.delete(f"/v1/webhooks/endpoints/{created['id']}", headers=auth_headers)
        assert deleted.status_code == 204

    def test_invalid_url_rejected(self, client, auth_headers):
        resp = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "javascript:alert(1)", "events": ["a.b"]},
        )
        assert resp.status_code == 422

    def test_test_endpoint_creates_signed_delivery(self, client, auth_headers):
        created = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["webhook.test"]},
        ).json()
        resp = client.post(
            f"/v1/webhooks/endpoints/{created['id']}/test",
            headers=auth_headers,
            json={"event_type": "webhook.test", "data": {"hello": "world"}},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "webhook.test"

    def test_test_endpoint_not_subscribed_409(self, client, auth_headers):
        created = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["other.event"]},
        ).json()
        resp = client.post(
            f"/v1/webhooks/endpoints/{created['id']}/test",
            headers=auth_headers,
            json={"event_type": "webhook.test"},
        )
        assert resp.status_code == 409

    def test_dlq_and_replay_flow(self, client, auth_headers, db_session):
        created = client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["invoice.paid"]},
        ).json()
        service = WebhookService(db_session)
        delivery = service.dispatch_event(
            service.get_endpoint_by_id(created["id"]).organization_id,
            "invoice.paid", {"invoice_id": "i1"},
        )[0]
        # Simule un échec définitif → DLQ
        service.record_result(delivery.id, status="dead", error="retries exhausted")

        dlq = client.get("/v1/webhooks/dead-letters", headers=auth_headers)
        assert dlq.status_code == 200
        assert delivery.id in [d["id"] for d in dlq.json()]

        replay = client.post(f"/v1/webhooks/deliveries/{delivery.id}/replay", headers=auth_headers)
        assert replay.status_code == 200
        assert replay.json()["status"] == "pending"

        dlq_after = client.get("/v1/webhooks/dead-letters", headers=auth_headers)
        assert delivery.id not in [d["id"] for d in dlq_after.json()]

    def test_deliveries_filter_by_status(self, client, auth_headers):
        client.post(
            "/v1/webhooks/endpoints",
            headers=auth_headers,
            json={"url": "https://example.com/hooks", "events": ["*"]},
        )
        resp = client.get("/v1/webhooks/deliveries?status=pending", headers=auth_headers)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        assert client.get("/v1/webhooks/endpoints").status_code in (401, 403)
