"""Business event fan-out: one business event → matching automation rules + subscribed webhooks.

Called inside the same transaction as the state change, it only *enqueues* work
(factory_jobs rows, webhook_deliveries rows); workers execute it. So a rolled-back
booking never sends a webhook, and a crash after commit never loses one.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.automation.rules import Trigger
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.integrations.webhooks import WebhookEvent
from app.domains.website_factory.jobs import JobKind
from app.models import AutomationRule, Contact, WebhookDelivery, WebhookEndpoint
from app.services.entitlements import plan_for_business
from app.services.job_queue import JobQueue


def contact_context(contact: Contact) -> dict[str, Any]:
    return {
        "id": str(contact.id), "name": contact.name, "first_name": contact.name.split()[0] if contact.name else "",
        "email": contact.email, "phone": contact.phone, "source": contact.source.value,
        "stage": contact.stage.value, "lead_score": contact.lead_score,
        "temperature": contact.lead_temperature, "reasons": "; ".join(contact.score_reasons or []),
        "tags": list(contact.tags or []),
    }


def emit(db: Session, business_id: uuid.UUID, *, trigger: Trigger | None, webhook: WebhookEvent | None,
         subject_type: str, subject_id: Any, context: dict[str, Any]) -> None:
    features, _ = plan_for_business(db, business_id)
    queue = JobQueue(db)
    if trigger is not None and has_feature(features, Feature.AUTOMATION) and db.scalar(
        select(AutomationRule.id).where(AutomationRule.business_id == business_id,
                                        AutomationRule.trigger == trigger,
                                        AutomationRule.enabled.is_(True)).limit(1)
    ):
        queue.enqueue(JobKind.RUN_AUTOMATION, {
            "business_id": str(business_id), "trigger": trigger.value, "subject_type": subject_type,
            "subject_id": str(subject_id), "context": context,
        }, priority=50)
    if webhook is not None and has_feature(features, Feature.INTEGRATIONS):
        endpoints = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.business_id == business_id,
                                                             WebhookEndpoint.active.is_(True))).all()
        for endpoint in endpoints:
            if webhook.value not in endpoint.events:
                continue
            delivery = WebhookDelivery(endpoint_id=endpoint.id, event_type=webhook.value,
                                       payload={"subject_type": subject_type, "subject_id": str(subject_id),
                                                **context})
            db.add(delivery)
            db.flush()
            queue.enqueue(JobKind.DELIVER_WEBHOOK, {"delivery_id": str(delivery.id)}, priority=40, max_attempts=6)
