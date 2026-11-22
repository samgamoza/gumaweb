"""Phase 3 engagement aggregates: CRM (contacts, activities), Booking, AI Chatbot."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.booking.availability import DEFAULT_WEEKLY_HOURS
from app.domains.booking.enums import AppointmentStatus
from app.domains.crm.enums import ActivityType, ContactSource, ContactStage


# --- CRM ------------------------------------------------------------------------------------------
class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who contacted a business (form, booking, chat) or was added by the owner."""

    __tablename__ = "contacts"
    __table_args__ = (
        # One contact per email / per phone within a business (dedupe across channels).
        Index("uq_contacts_business_email", "business_id", "email", unique=True,
              postgresql_where=text("email IS NOT NULL"), sqlite_where=text("email IS NOT NULL")),
        Index("uq_contacts_business_phone", "business_id", "phone", unique=True,
              postgresql_where=text("phone IS NOT NULL"), sqlite_where=text("phone IS NOT NULL")),
        Index("ix_contacts_business_stage", "business_id", "stage"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[ContactSource] = mapped_column(enum_type(ContactSource))
    stage: Mapped[ContactStage] = mapped_column(enum_type(ContactStage), default=ContactStage.NEW)
    value_cents: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    last_activity_at: Mapped[datetime | None] = mapped_column(index=True)

    activities: Mapped[list[ContactActivity]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", order_by="ContactActivity.occurred_at.desc()"
    )


class ContactActivity(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "contact_activities"

    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    type: Mapped[ActivityType] = mapped_column(enum_type(ActivityType))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())

    contact: Mapped[Contact] = relationship(back_populates="activities")


# --- Booking --------------------------------------------------------------------------------------
class BookingSettings(TimestampMixin, Base):
    __tablename__ = "booking_settings"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"),
                                                   primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Manila")
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_hours: Mapped[int] = mapped_column(Integer, default=2)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=30)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_hours: Mapped[dict[str, Any]] = mapped_column(default=lambda: dict(DEFAULT_WEEKLY_HOURS))
    # [{"name": "Check-up", "duration_minutes": 30}]
    services: Mapped[list[Any]] = mapped_column(default=list)


class Appointment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_business_start", "business_id", "starts_at"),
        # Last line of defence against double booking the same start time (overlaps are checked
        # under a per-business row lock in BookingService).
        Index("uq_appointments_business_start_active", "business_id", "starts_at", unique=True,
              postgresql_where=text("status IN ('pending', 'confirmed')"),
              sqlite_where=text("status IN ('pending', 'confirmed')")),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    service_name: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    status: Mapped[AppointmentStatus] = mapped_column(enum_type(AppointmentStatus),
                                                      default=AppointmentStatus.PENDING)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(320))
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    manage_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    cancelled_at: Mapped[datetime | None]


# --- AI Chatbot -----------------------------------------------------------------------------------
class ChatbotSettings(TimestampMixin, Base):
    __tablename__ = "chatbot_settings"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"),
                                                   primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    greeting: Mapped[str] = mapped_column(String(300), default="Hi! How can we help you today?")
    handoff_message: Mapped[str] = mapped_column(
        String(300), default="I'm not sure about that. Leave your name and phone or email and we'll get back to you.")
    collect_leads: Mapped[bool] = mapped_column(Boolean, default=True)


class KnowledgeEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_entries"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="custom")  # website | custom
    section: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)


class ChatConversation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_conversations"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    lead_captured: Mapped[bool] = mapped_column(Boolean, default=False)
    visitor_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"),
                                                       index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str | None] = mapped_column(String(16))  # llm | retrieval | handoff
    sources: Mapped[list[Any]] = mapped_column(default=list)  # knowledge entry ids used
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
