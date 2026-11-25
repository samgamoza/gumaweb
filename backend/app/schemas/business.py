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
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


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
    campaign_id: uuid.UUID | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False
    started_at: datetime
    finished_at: datetime | None


class DiscoverySourceRead(BaseModel):
    id: str
    name: str
    category: str
    discovery_source: DiscoverySource
    requires_key: bool
    configured: bool
    billed: bool
    note: str | None = None


class DiscoverRequest(BaseModel):
    source: str = Field(description="a source id from GET /businesses/discovery-sources, e.g. osm")
    category: str | None = Field(None, max_length=100, description='e.g. "dental clinic"')
    city: str | None = Field(None, max_length=120, description='e.g. "Cebu City"')
    query: str | None = Field(None, max_length=200, description="free text; overrides category/city where supported")
    limit: int = Field(30, ge=1, le=500)


class BusinessContactRead(ORMModel):
    id: uuid.UUID
    kind: str
    value: str
    source: str
    source_ref: str | None
    value_type: str
    verification_status: str
    confidence: float
    purpose: str
    policy_decision: str
    reason_code: str | None
    acquired_at: datetime
    retention_until: datetime | None
    discovery_run_id: uuid.UUID | None


class EnrichmentTierRead(BaseModel):
    id: str
    name: str
    billed: bool
    enabled: bool
    note: str


class EnrichRequest(BaseModel):
    tiers: list[str] | None = Field(None, description="narrow to these enabled tier ids; omit for all enabled tiers")


class CampaignWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    cities: list[str] = Field(min_length=1, max_length=50)
    categories: list[str] = Field(min_length=1, max_length=50)
    sources: list[str] = Field(default_factory=lambda: ["osm"], min_length=1)
    enrichment_tiers: list[str] | None = Field(None, description="None: every enabled tier; []: no enrichment")
    target: int = Field(100, ge=1, le=5000, description="stop once this many unique businesses are found")
    per_query: int = Field(50, ge=1, le=500)


class CampaignRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    cities: list[str]
    categories: list[str]
    sources: list[str]
    enrichment_tiers: list[str] | None
    target: int
    per_query: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_run: DiscoveryRunRead | None = None
