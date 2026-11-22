"""Cross-cutting platform tables: Analytics, Audit and the domain event outbox."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, enum_type
from app.domains.analytics.enums import SiteEventType


class SiteEvent(UUIDPrimaryKeyMixin, Base):
    """First-party, cookieless analytics events from generated websites."""

    __tablename__ = "site_events"
    __table_args__ = (Index("ix_site_events_website_type_time", "website_id", "event_type", "occurred_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    event_type: Mapped[SiteEventType] = mapped_column(enum_type(SiteEventType))
    path: Mapped[str | None] = mapped_column(String(500))
    referrer: Mapped[str | None] = mapped_column(String(500))
    visitor_hash: Mapped[str | None] = mapped_column(String(64))  # salted hash, no raw IPs stored
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class DomainEvent(UUIDPrimaryKeyMixin, Base):
    """Transactional outbox: events are written in the same transaction as state changes
    and relayed to Redis Streams / NATS by a worker once the platform is split into services."""

    __tablename__ = "domain_events"

    event_type: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(index=True)
