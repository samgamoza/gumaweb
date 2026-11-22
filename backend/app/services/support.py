"""Cross-cutting application support: actor context, audit logging, domain events."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.domains.audit.actions import AuditAction
from app.models import AuditLog, DomainEvent, User

logger = logging.getLogger("gumaweb.events")


@dataclass(frozen=True)
class Actor:
    """Who is performing an operation (None user = public/anonymous or system)."""

    user: User | None = None
    ip: str | None = None
    user_agent: str | None = None

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None


SYSTEM = Actor()


class EventType(StrEnum):
    """Event system from 16-api-specifications."""

    BUSINESS_DISCOVERED = "business_discovered"
    BUSINESS_SCORED = "business_scored"
    WEBSITE_GENERATED = "website_generated"
    WEBSITE_PUBLISHED = "website_published"
    WEBSITE_UNPUBLISHED = "website_unpublished"
    CLAIM_STARTED = "claim_started"
    CLAIM_COMPLETED = "claim_completed"
    CLAIM_REJECTED = "claim_rejected"
    CUSTOMER_UPGRADED = "customer_upgraded"
    OUTREACH_SENT = "outreach_sent"
    APPOINTMENT_BOOKED = "appointment_booked"
    CHAT_LEAD_CAPTURED = "chat_lead_captured"


def record_event(db: Session, event_type: EventType, aggregate_type: str, aggregate_id: Any,
                 payload: dict[str, Any] | None = None) -> DomainEvent:
    """Append to the transactional outbox (committed atomically with the state change)."""
    event = DomainEvent(
        event_type=event_type.value,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload or {},
    )
    db.add(event)
    logger.info("event %s %s:%s", event_type.value, aggregate_type, aggregate_id)
    return event


def audit(db: Session, actor: Actor, action: AuditAction, entity_type: str, entity_id: Any = None,
          data: dict[str, Any] | None = None) -> None:
    db.add(
        AuditLog(
            actor_id=actor.user_id,
            actor_role=actor.user.role.value if actor.user else None,
            action=action.value,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            data=data or {},
            ip_address=actor.ip,
        )
    )
