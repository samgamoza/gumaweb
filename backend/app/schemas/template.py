from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domains.template_management.enums import ComponentType, TemplateStatus
from app.schemas.common import ORMModel


class TemplateRead(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    category: str
    version: int
    description: str | None
    status: TemplateStatus
    is_default: bool
    pages: list[dict[str, Any]]
    theme: dict[str, Any]
    industries: list[str]
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
    name: str = Field(max_length=200)
    category: str = Field(max_length=64)
    version: int = Field(1, ge=1)
    description: str | None = None
    is_default: bool = False
    pages: list[dict[str, Any]]
    theme: dict[str, Any]
    industries: list[str] = []


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    status: TemplateStatus | None = None
    is_default: bool | None = None
    pages: list[dict[str, Any]] | None = None
    theme: dict[str, Any] | None = None
    industries: list[str] | None = None


class TemplateComponentRead(ORMModel):
    id: uuid.UUID
    slug: str
    component_type: ComponentType
    variant: str
    name: str
    template_path: str


class TemplateSyncResult(BaseModel):
    templates_created: int
    templates_updated: int
    components_registered: int
