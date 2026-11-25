"""Outbound engine pipeline: read models (docs/OUTBOUND_ENGINE_PLAN.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

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
