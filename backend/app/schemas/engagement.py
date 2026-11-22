"""Phase 3 API contracts: CRM, booking, chatbot, entitlements."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.domains.booking.enums import AppointmentStatus
from app.domains.crm.enums import ActivityType, ContactSource, ContactStage
from app.schemas.common import ORMModel


# --- Entitlements -----------------------------------------------------------------------------
class FeatureAccess(BaseModel):
    plan: str
    features: dict[str, bool]


# --- CRM ---------------------------------------------------------------------------------------
class ContactRead(ORMModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    source: ContactSource
    stage: ContactStage
    value_cents: int | None
    tags: list[str]
    notes: str | None
    last_activity_at: datetime | None
    created_at: datetime


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=32)
    stage: ContactStage = ContactStage.NEW
    value_cents: int | None = Field(None, ge=0, le=10_000_000_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(None, max_length=5000)


class ContactUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=32)
    stage: ContactStage | None = None
    value_cents: int | None = Field(None, ge=0, le=10_000_000_000)
    tags: list[str] | None = Field(None, max_length=20)
    notes: str | None = Field(None, max_length=5000)


class ActivityRead(ORMModel):
    id: uuid.UUID
    type: ActivityType
    body: str | None
    data: dict[str, Any]
    occurred_at: datetime


class ActivityCreate(BaseModel):
    type: ActivityType = ActivityType.NOTE
    body: str = Field(min_length=1, max_length=4000)


class ContactDetail(ContactRead):
    activities: list[ActivityRead]


class PipelineStage(BaseModel):
    stage: ContactStage
    count: int
    value_cents: int


# --- Booking -----------------------------------------------------------------------------------
class BookableService(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=10, le=480)


class BookingSettingsRead(ORMModel):
    enabled: bool
    timezone: str
    slot_minutes: int
    buffer_minutes: int
    lead_time_hours: int
    max_days_ahead: int
    auto_confirm: bool
    weekly_hours: dict[str, list[list[str]]]
    services: list[BookableService]


class BookingSettingsUpdate(BaseModel):
    enabled: bool | None = None
    timezone: str | None = Field(None, max_length=64)
    slot_minutes: int | None = None
    buffer_minutes: int | None = None
    lead_time_hours: int | None = None
    max_days_ahead: int | None = None
    auto_confirm: bool | None = None
    weekly_hours: dict[str, list[list[str]]] | None = None
    services: list[BookableService] | None = Field(None, max_length=30)


class AppointmentRead(ORMModel):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    service_name: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    customer_name: str
    customer_email: str | None
    customer_phone: str | None
    notes: str | None
    created_at: datetime


class BookingRequest(BaseModel):
    service: str = Field(max_length=120)
    start: datetime
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=32)
    notes: str | None = Field(None, max_length=1000)
    website: str | None = None  # honeypot

    @field_validator("start")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("start must include a timezone offset")
        return value


class BookingResult(BaseModel):
    appointment_id: uuid.UUID
    status: AppointmentStatus
    starts_at: datetime
    message: str


class Slot(BaseModel):
    start: datetime
    label: str


# --- Chatbot -----------------------------------------------------------------------------------
class ChatbotSettingsRead(ORMModel):
    enabled: bool
    greeting: str
    handoff_message: str
    collect_leads: bool


class ChatbotSettingsUpdate(BaseModel):
    enabled: bool | None = None
    greeting: str | None = Field(None, min_length=2, max_length=300)
    handoff_message: str | None = Field(None, min_length=2, max_length=300)
    collect_leads: bool | None = None


class KnowledgeRead(ORMModel):
    id: uuid.UUID
    source: str
    section: str | None
    title: str
    content: str
    updated_at: datetime


class KnowledgeWrite(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=2, max_length=4000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_token: str | None = Field(None, max_length=200)


class ChatOut(BaseModel):
    session_token: str
    reply: str


class ChatMessageRead(ORMModel):
    role: str
    content: str
    strategy: str | None
    created_at: datetime


class ConversationRead(ORMModel):
    id: uuid.UUID
    message_count: int
    lead_captured: bool
    contact_id: uuid.UUID | None
    started_at: datetime
    last_message_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[ChatMessageRead]
