"""Phase 4 API contracts: automations, voice receptionist, API keys, webhooks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.automation.rules import Trigger
from app.schemas.common import ORMModel


class AutomationRead(ORMModel):
    id: uuid.UUID
    name: str
    trigger: Trigger
    config: dict[str, Any]
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    enabled: bool
    preset_key: str | None
    created_at: datetime


class AutomationWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    trigger: Trigger
    config: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(min_length=1, max_length=5)
    enabled: bool = True


class AutomationUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    config: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = Field(None, min_length=1, max_length=5)
    enabled: bool | None = None


class PresetRead(BaseModel):
    key: str
    name: str
    trigger: Trigger
    config: dict[str, Any]
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]


class AutomationRunRead(ORMModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    subject_type: str
    subject_id: str
    status: str
    results: list[dict[str, Any]]
    created_at: datetime


class VoiceSettingsRead(ORMModel):
    enabled: bool
    phone_number: str | None
    forward_number: str | None
    take_messages: bool


class VoiceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    phone_number: str | None = Field(None, max_length=32)
    forward_number: str | None = Field(None, max_length=32)
    take_messages: bool | None = None


class CallRead(ORMModel):
    id: uuid.UUID
    caller_number: str | None
    is_test: bool
    status: str
    outcome: str | None
    summary: str | None
    transcript: list[dict[str, Any]]
    contact_id: uuid.UUID | None
    appointment_id: uuid.UUID | None
    started_at: datetime
    duration_seconds: int | None


class VoiceTurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class VoiceTurnOut(BaseModel):
    call_id: uuid.UUID
    say: str
    action: str
    transfer_to: str | None = None


class InboundCall(BaseModel):
    to: str = Field(max_length=32)
    caller: str | None = Field(None, alias="from", max_length=32)


class TestCallIn(BaseModel):
    caller: str | None = Field(None, max_length=32)


class ApiKeyRead(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str
    read_only: bool
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    read_only: bool = True


class ApiKeyCreated(ApiKeyRead):
    key: str  # shown once


class WebhookRead(ORMModel):
    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    consecutive_failures: int
    created_at: datetime


class WebhookCreate(BaseModel):
    url: str = Field(max_length=500)
    events: list[str] = Field(min_length=1, max_length=10)


class WebhookUpdate(BaseModel):
    url: str | None = Field(None, max_length=500)
    events: list[str] | None = Field(None, max_length=10)
    active: bool | None = None


class WebhookSecret(BaseModel):
    secret: str


class DeliveryRead(ORMModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None
