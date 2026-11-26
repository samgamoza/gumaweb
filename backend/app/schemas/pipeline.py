"""Outbound engine pipeline: read models (docs/OUTBOUND_ENGINE_PLAN.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.sales import ActivitySource, ActivityType, ProspectStage
from app.schemas.common import ORMModel


class PipelineSummary(BaseModel):
    stages: dict[str, int]  # every stage, zero included
    ready: int  # prospects the outbound engine may work now
    auto_compile_enabled: bool
    auto_compiled_today: int
    auto_compile_daily_limit: int


class ProspectRow(BaseModel):
    business_id: uuid.UUID
    business_name: str
    city: str | None
    industry: str | None
    stage: ProspectStage
    score: int | None
    score_reasons: list[Any]
    channels: list[Any]
    last_touch_at: datetime | None
    stage_changed_at: datetime


class ActivityRead(ORMModel):
    id: uuid.UUID
    type: ActivityType
    source: ActivitySource
    data: dict[str, Any]
    occurred_at: datetime


class ProspectDetail(ProspectRow):
    timeline: list[ActivityRead]


class PlaybookStepStats(BaseModel):
    key: str
    channel: str
    when: str
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class PlaybookRead(BaseModel):
    id: uuid.UUID
    name: str
    active: bool
    max_days: int
    steps: list[dict[str, Any]]
    enrollments: dict[str, int]  # by status
    step_stats: list[PlaybookStepStats]


class PlaybookUpdate(BaseModel):
    active: bool | None = None
    max_days: int | None = Field(None, ge=1, le=180)
    steps: list[dict[str, Any]] | None = None


class TaskRead(ORMModel):
    id: uuid.UUID
    prospect_id: uuid.UUID
    title: str
    due_at: datetime
    assignee_user_id: uuid.UUID | None
    done_at: datetime | None


class DraftRow(BaseModel):
    """A private draft's outreach readiness (A7b)."""

    website_id: uuid.UUID
    business_id: uuid.UUID
    business_name: str
    subdomain: str
    ready: bool
    approved: bool
    issues: list[str]
    reviewed_at: datetime | None
    images: dict[str, str]
    capture_error: str | None
