"""Phase 4 aggregates: automation, voice receptionist, API keys, webhooks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.automation.rules import Trigger


# --- Business automation -----------------------------------------------------------------------
class AutomationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "automation_rules"
    __table_args__ = (Index("ix_automation_rules_business_trigger", "business_id", "trigger", "enabled"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[Trigger] = mapped_column(enum_type(Trigger))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # hours_before / idle_days
    conditions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    actions: Mapped[list[Any]] = mapped_column(default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    preset_key: Mapped[str | None] = mapped_column(String(64))


class AutomationRun(UUIDPrimaryKeyMixin, Base):
    """One execution of a rule for one subject. The idempotency key makes replays and
    overlapping scheduler ticks harmless (e.g. a reminder is sent once per appointment)."""

    __tablename__ = "automation_runs"

    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("automation_rules.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # succeeded | skipped | failed
    results: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


# --- Voice AI receptionist ---------------------------------------------------------------------
class VoiceSettings(TimestampMixin, Base):
    __tablename__ = "voice_settings"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"),
                                                   primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Inbound number (DID) routed to the receptionist by the telephony gateway, E.164 digits.
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    forward_number: Mapped[str | None] = mapped_column(String(32))  # call routing target
    take_messages: Mapped[bool] = mapped_column(Boolean, default=True)


class Call(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (Index("ix_calls_business_started", "business_id", "started_at"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    caller_number: Mapped[str | None] = mapped_column(String(32))
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)  # portal simulator
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | completed
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    transcript: Mapped[list[Any]] = mapped_column(default=list)  # [{"speaker": "caller"|"assistant", "text"}]
    outcome: Mapped[str | None] = mapped_column(String(16))
    summary: Mapped[str | None] = mapped_column(Text)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]
    duration_seconds: Mapped[int | None] = mapped_column(Integer)


# --- Integrations: API keys + webhooks ---------------------------------------------------------
class ApiKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "api_keys"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in the UI to identify the key
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # the key itself is never stored
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list[Any]] = mapped_column(default=list)
    secret_version: Mapped[int] = mapped_column(Integer, default=1)  # secret is derived, see webhooks.endpoint_secret
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class WebhookDelivery(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
                                                   index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    delivered_at: Mapped[datetime | None]
