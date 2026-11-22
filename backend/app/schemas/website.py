from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.publishing.enums import DeploymentStatus
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.schemas.common import ORMModel


class GenerateWebsiteRequest(BaseModel):
    business_id: uuid.UUID
    template_slug: str | None = None
    publish: bool = False


class RegenerateWebsiteRequest(BaseModel):
    template_slug: str | None = None
    reset_content: bool = False
    publish: bool = False


class PublishRequest(BaseModel):
    force: bool = Field(False, description="Admin only: publish even if the quality gate fails")


class WebsiteRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    template_id: uuid.UUID | None
    subdomain: str
    url: str | None
    status: WebsiteStatus
    version: int
    quality_score: int | None
    quality_report: dict[str, Any] | None
    is_claimed: bool
    generated_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebsiteSummary(WebsiteRead):
    business_name: str
    template_slug: str | None


class BlueprintRead(BaseModel):
    website_id: uuid.UUID
    blueprint: dict[str, Any]


class ContentBlockRead(ORMModel):
    section_key: str
    content: dict[str, Any]
    source: ContentSource
    updated_at: datetime


class ContentUpdate(BaseModel):
    section_key: str = Field(max_length=64)
    updates: dict[str, Any]
    republish: bool = True


class SeoRead(ORMModel):
    page_title: str
    meta_description: str
    keywords: list[str]
    local_keywords: list[str]
    schema_markup: dict[str, Any]
    pages: dict[str, Any]
    audit: dict[str, Any] | None
    seo_score: int


class GenerateBatchRequest(BaseModel):
    """Queue generation for explicit businesses, or for the top-scoring generate candidates."""

    business_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    limit: int = Field(100, ge=1, le=5000)
    publish: bool = True
    priority: int = Field(100, ge=0, le=1000)


class BatchResult(BaseModel):
    enqueued: int
    skipped: int


class JobRead(ORMModel):
    id: uuid.UUID
    kind: str
    status: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_by: str | None
    finished_at: datetime | None
    last_error: str | None
    result: dict[str, Any] | None
    created_at: datetime


class DeploymentRead(ORMModel):
    id: uuid.UUID
    website_id: uuid.UUID
    version: int
    status: DeploymentStatus
    storage_backend: str
    artifact_path: str | None
    file_count: int
    size_bytes: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
