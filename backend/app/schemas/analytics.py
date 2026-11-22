from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.analytics.enums import SiteEventType
from app.schemas.common import ORMModel


class SiteEventIn(BaseModel):
    event_type: SiteEventType
    path: str | None = Field(None, max_length=500)
    referrer: str | None = Field(None, max_length=500)


class PlatformOverview(BaseModel):
    kpis: dict[str, Any]
    funnel: dict[str, int]
    page_views_30d: int


class DailyCount(BaseModel):
    day: date
    count: int


class WebsiteAnalytics(BaseModel):
    website_id: uuid.UUID
    days: int
    page_views: list[DailyCount]
    totals: dict[str, int]
    leads: int


class AuditLogRead(ORMModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    data: dict[str, Any]
    ip_address: str | None
    created_at: datetime


class DomainEventRead(ORMModel):
    id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    occurred_at: datetime
    processed_at: datetime | None


class PublicSiteInfo(BaseModel):
    subdomain: str
    business_name: str
    industry: str | None
    city: str | None
    province: str | None
    url: str | None
    is_claimed: bool
    masked_email: str | None
    masked_phone: str | None
