from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.outreach.enums import CampaignStatus, OutreachChannel
from app.schemas.common import ORMModel


class SequenceStep(BaseModel):
    step: int = Field(ge=0, le=20)
    day: int = Field(ge=0, le=90)
    subject: str = Field(max_length=255)
    body: str = Field(max_length=10000)


class TargetFilter(BaseModel):
    industry: str | None = None
    city: str | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    limit: int = Field(500, ge=1, le=10000)


class CampaignCreate(BaseModel):
    name: str = Field(max_length=200)
    channel: OutreachChannel = OutreachChannel.EMAIL
    sequence: list[SequenceStep] | None = None  # defaults to Day 0/3/7/14
    target_filter: TargetFilter = Field(default_factory=TargetFilter)
    launch: bool = False


class CampaignRead(ORMModel):
    id: uuid.UUID
    name: str
    channel: OutreachChannel
    status: CampaignStatus
    sequence: list[dict[str, Any]]
    target_filter: dict[str, Any]
    started_at: datetime | None
    created_at: datetime


class LaunchResult(BaseModel):
    campaign_id: uuid.UUID
    enrolled_businesses: int
    scheduled_messages: int


class DispatchResult(BaseModel):
    sent: int
    skipped: int
    failed: int


class CampaignStats(BaseModel):
    campaign_id: uuid.UUID
    outreach_sent: int
    opens: int
    clicks: int
    claims: int
    conversions: int
    unsubscribes: int
