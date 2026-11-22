"""Guma OS integration: customer API keys and signed outbound webhooks."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import GumaWebError, NotFoundError, ValidationFailedError
from app.domains.integrations.webhooks import (
    WebhookEvent,
    encode_payload,
    endpoint_secret,
    generate_api_key,
    hash_api_key,
    sign,
    validate_webhook_url,
)
from app.domains.website_factory.jobs import JobKind
from app.models import ApiKey, WebhookDelivery, WebhookEndpoint
from app.services.job_queue import JobQueue
from app.services.providers import providers

logger = logging.getLogger("gumaweb.webhooks")
MAX_KEYS = 10
MAX_ENDPOINTS = 5


class DeliveryFailed(GumaWebError):
    """Raised inside a webhook job so the job queue retries it with backoff."""

    status_code = 502
    code = "webhook_delivery_failed"


class IntegrationService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- API keys ----------------------------------------------------------------------------
    def api_keys(self, business_id: uuid.UUID) -> Sequence[ApiKey]:
        return self.db.scalars(select(ApiKey).where(ApiKey.business_id == business_id, ApiKey.revoked_at.is_(None))
                               .order_by(ApiKey.created_at.desc())).all()

    def create_api_key(self, business_id: uuid.UUID, user_id: uuid.UUID, name: str,
                       read_only: bool) -> tuple[ApiKey, str]:
        if len(self.api_keys(business_id)) >= MAX_KEYS:
            raise ValidationFailedError(f"At most {MAX_KEYS} active API keys")
        key = generate_api_key()
        row = ApiKey(business_id=business_id, user_id=user_id, name=name, prefix=key[:12],
                     key_hash=hash_api_key(key), read_only=read_only)
        self.db.add(row)
        self.db.commit()
        return row, key  # plaintext is returned exactly once

    def revoke_api_key(self, business_id: uuid.UUID, key_id: uuid.UUID) -> None:
        row = self.db.get(ApiKey, key_id)
        if row is None or row.business_id != business_id:
            raise NotFoundError("API key not found")
        row.revoked_at = datetime.now(UTC)
        self.db.commit()

    def authenticate(self, presented: str) -> ApiKey | None:
        row = self.db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(presented),
                                                  ApiKey.revoked_at.is_(None)))
        if row is not None:
            now = datetime.now(UTC)
            last = row.last_used_at.replace(tzinfo=row.last_used_at.tzinfo or UTC) if row.last_used_at else None
            if last is None or now - last > timedelta(minutes=5):  # throttle write amplification
                row.last_used_at = now
                self.db.commit()
        return row

    # --- Webhook endpoints -------------------------------------------------------------------
    def endpoints(self, business_id: uuid.UUID) -> Sequence[WebhookEndpoint]:
        return self.db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.business_id == business_id)
                               .order_by(WebhookEndpoint.created_at)).all()

    def endpoint(self, business_id: uuid.UUID, endpoint_id: uuid.UUID) -> WebhookEndpoint:
        row = self.db.get(WebhookEndpoint, endpoint_id)
        if row is None or row.business_id != business_id:
            raise NotFoundError("Webhook endpoint not found")
        return row

    def _check(self, url: str, events: list[str]) -> None:
        validate_webhook_url(url, allow_private=self.settings.webhook_allow_private,
                             require_https=self.settings.environment == "production")
        unknown = set(events) - {e.value for e in WebhookEvent}
        if unknown or not events:
            raise ValidationFailedError(f"Choose events from: {', '.join(e.value for e in WebhookEvent)}")

    def create_endpoint(self, business_id: uuid.UUID, url: str, events: list[str]) -> WebhookEndpoint:
        if len(self.endpoints(business_id)) >= MAX_ENDPOINTS:
            raise ValidationFailedError(f"At most {MAX_ENDPOINTS} webhook endpoints")
        self._check(url, events)
        row = WebhookEndpoint(business_id=business_id, url=url, events=sorted(set(events)))
        self.db.add(row)
        self.db.commit()
        return row

    def update_endpoint(self, row: WebhookEndpoint, url: str | None, events: list[str] | None,
                        active: bool | None) -> WebhookEndpoint:
        self._check(url or row.url, events if events is not None else row.events)
        if url is not None:
            row.url = url
        if events is not None:
            row.events = sorted(set(events))
        if active is not None:
            row.active = active
            if active:
                row.consecutive_failures = 0
        self.db.commit()
        return row

    def secret(self, row: WebhookEndpoint) -> str:
        return endpoint_secret(self.settings.jwt_secret_key, str(row.id), row.secret_version)

    def rotate_secret(self, row: WebhookEndpoint) -> str:
        row.secret_version += 1
        self.db.commit()
        return self.secret(row)

    def send_test(self, row: WebhookEndpoint) -> WebhookDelivery:
        delivery = WebhookDelivery(endpoint_id=row.id, event_type="ping", payload={"message": "Hello from GumaWeb"})
        self.db.add(delivery)
        self.db.flush()
        JobQueue(self.db).enqueue(JobKind.DELIVER_WEBHOOK, {"delivery_id": str(delivery.id)}, priority=10,
                                  max_attempts=1)
        self.db.commit()
        return delivery

    def deliveries(self, business_id: uuid.UUID, limit: int = 50) -> Sequence[WebhookDelivery]:
        return self.db.scalars(
            select(WebhookDelivery).join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id)
            .where(WebhookEndpoint.business_id == business_id)
            .order_by(WebhookDelivery.created_at.desc()).limit(limit)).all()

    # --- Delivery (worker) -------------------------------------------------------------------
    def deliver(self, delivery_id: uuid.UUID) -> dict[str, object]:
        delivery = self.db.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status == "delivered":
            return {"skipped": "already delivered or deleted"}
        endpoint = self.db.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.active:
            delivery.status = "failed"
            delivery.last_error = "endpoint disabled"
            self.db.commit()
            return {"skipped": "endpoint disabled"}
        delivery.attempts += 1
        try:
            # Re-validate at send time: DNS can change after the endpoint was saved (rebinding).
            validate_webhook_url(endpoint.url, allow_private=self.settings.webhook_allow_private,
                                 require_https=self.settings.environment == "production")
            body = encode_payload(delivery.event_type, delivery.payload, str(delivery.id))
            response = providers.http.post(endpoint.url, content=body, headers={
                "Content-Type": "application/json", "User-Agent": "GumaWeb-Webhooks/1.0",
                "GumaWeb-Event": delivery.event_type, "GumaWeb-Delivery": str(delivery.id),
                "GumaWeb-Signature": sign(self.secret(endpoint), body),
            })
            delivery.response_status = response.status_code
            if not 200 <= response.status_code < 300:
                raise DeliveryFailed(f"HTTP {response.status_code}")
        except Exception as exc:
            delivery.last_error = str(exc)[:500]
            endpoint.consecutive_failures += 1
            if endpoint.consecutive_failures >= self.settings.webhook_disable_after_failures:
                endpoint.active = False  # stop hammering a dead receiver; owner can re-enable
                logger.warning("webhook endpoint %s disabled after repeated failures", endpoint.id)
            delivery.status = "failed"
            self.db.commit()
            raise DeliveryFailed(f"Webhook delivery failed: {exc}") from exc
        delivery.status = "delivered"
        delivery.delivered_at = datetime.now(UTC)
        delivery.last_error = None
        endpoint.consecutive_failures = 0
        self.db.commit()
        return {"delivered": True, "status": delivery.response_status}
