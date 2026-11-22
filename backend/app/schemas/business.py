from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.domains.business_discovery.enums import BusinessStatus, DiscoveryRunStatus, DiscoverySource
from app.domains.business_profile.enums import ProfileSource
from app.schemas.common import ORMModel


class BusinessBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    industry: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=5000)
    address: str | None = Field(None, max_length=1000)
    city: str | None = Field(None, max_length=120)
    province: str | None = Field(None, max_length=120)
    postal_code: str | None = Field(None, max_length=16)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None
    website: str | None = Field(None, max_length=500)
    facebook: str | None = Field(None, max_length=500)
    google_business_url: str | None = Field(None, max_length=500)


class BusinessCreate(BusinessBase):
    source: DiscoverySource = DiscoverySource.MANUAL
    source_ref: str | None = Field(None, max_length=255)


class BusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    industry: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=5000)
    address: str | None = Field(None, max_length=1000)
    city: str | None = Field(None, max_length=120)
    province: str | None = Field(None, max_length=120)
    postal_code: str | None = Field(None, max_length=16)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None
    website: str | None = Field(None, max_length=500)
    facebook: str | None = Field(None, max_length=500)


class BusinessRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    industry: str | None
    description: str | None
    address: str | None
    city: str | None
    province: str | None
    country: str
    phone: str | None
    email: str | None
    website: str | None
    facebook: str | None
    source: DiscoverySource
    status: BusinessStatus
    score: int | None
    score_breakdown: dict[str, Any] | None
    generate_candidate: bool
    scored_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BusinessFilters(BaseModel):
    q: str | None = None
    status: BusinessStatus | None = None
    industry: str | None = None
    city: str | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    generate_candidate: bool | None = None


class BusinessProfileRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    industry: str
    category: str
    services: list[str]
    keywords: list[str]
    local_keywords: list[str]
    target_audience: str | None
    brand_voice: str | None
    brand_tone: str | None
    tagline: str | None
    recommended_template: str | None
    confidence: float
    source: ProfileSource
    updated_at: datetime


class BusinessProfileUpdate(BaseModel):
    services: list[str] | None = Field(None, max_length=30)
    target_audience: str | None = Field(None, max_length=64)
    brand_tone: str | None = Field(None, max_length=32)
    tagline: str | None = Field(None, max_length=255)


class DiscoveryRunRead(ORMModel):
    id: uuid.UUID
    source: DiscoverySource
    status: DiscoveryRunStatus
    total_records: int
    created_count: int
    duplicate_count: int
    error_count: int
    errors: list[Any]
    started_at: datetime
    finished_at: datetime | None
