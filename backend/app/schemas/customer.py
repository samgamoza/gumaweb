from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.domains.billing.enums import PlanCode, SubscriptionStatus
from app.domains.customers.enums import CustomerStatus
from app.schemas.common import ORMModel


class CustomerRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    business_id: uuid.UUID
    plan: PlanCode
    status: CustomerStatus
    activated_at: datetime


class PlanRead(ORMModel):
    code: PlanCode
    name: str
    description: str | None
    price_monthly_cents: int
    currency: str
    features: dict[str, Any]


class SubscriptionRead(ORMModel):
    id: uuid.UUID
    plan_code: PlanCode
    status: SubscriptionStatus
    provider: str
    current_period_start: datetime
    current_period_end: datetime | None
    canceled_at: datetime | None


class ChangePlanRequest(BaseModel):
    plan: PlanCode


class CustomerProfileUpdate(BaseModel):
    """Business profile fields the owner can manage (12-customer-portal)."""

    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = Field(None, max_length=5000)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=1000)
    facebook: str | None = Field(None, max_length=500)
    republish: bool = True


class LeadRead(ORMModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    message: str
    created_at: datetime


class DashboardWebsite(BaseModel):
    id: uuid.UUID
    subdomain: str
    url: str | None
    status: str
    version: int
    quality_score: int | None
    seo_score: int | None
    published_at: datetime | None


class DashboardStats(BaseModel):
    page_views_30d: int
    leads_30d: int
    phone_clicks_30d: int


class SeoSummary(BaseModel):
    score: int
    content_gaps: list[dict[str, Any]]


class CustomerDashboard(BaseModel):
    customer: CustomerRead
    business: dict[str, Any]
    website: DashboardWebsite | None
    plan: PlanRead
    stats: DashboardStats
    recent_leads: list[LeadRead]
    seo: SeoSummary | None = None


class MediaRead(ORMModel):
    id: uuid.UUID
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    alt_text: str | None
    created_at: datetime
