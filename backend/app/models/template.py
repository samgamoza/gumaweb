"""TemplateManagement aggregate: master templates and the component library."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.template_management.enums import ComponentType, TemplateStatus


class Template(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "templates"

    slug: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. construction-v1
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TemplateStatus] = mapped_column(enum_type(TemplateStatus), default=TemplateStatus.ACTIVE)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # [{"slug": "home", "title": "Home", "sections": [{"component": "hero", "variant": "modern"}]}]
    pages: Mapped[list[Any]] = mapped_column(default=list)
    # {"palette": {...}, "fonts": {...}}
    theme: Mapped[dict[str, Any]] = mapped_column(default=dict)
    industries: Mapped[list[Any]] = mapped_column(default=list)
    preview_image_url: Mapped[str | None] = mapped_column(String(500))


class TemplateComponent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "template_components"
    __table_args__ = (UniqueConstraint("component_type", "variant"),)

    slug: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. hero-modern
    component_type: Mapped[ComponentType] = mapped_column(enum_type(ComponentType))
    variant: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    template_path: Mapped[str] = mapped_column(String(255))
    content_schema: Mapped[dict[str, Any]] = mapped_column(default=dict)
