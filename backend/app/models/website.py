"""WebsiteFactory, SEO and Publishing aggregates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.publishing.enums import DeploymentStatus
from app.domains.website_factory.enums import ContentSource, WebsiteStatus

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.template import Template


class Website(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "websites"

    # One website per business in Phase 1; regeneration bumps `version`.
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), index=True
    )
    subdomain: Mapped[str] = mapped_column(String(63), unique=True)
    url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[WebsiteStatus] = mapped_column(
        enum_type(WebsiteStatus), default=WebsiteStatus.DRAFT, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=0)
    blueprint: Mapped[dict[str, Any] | None]
    quality_score: Mapped[int | None] = mapped_column(Integer)
    quality_report: Mapped[dict[str, Any] | None]
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_path: Mapped[str | None] = mapped_column(String(500))
    generated_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]

    business: Mapped[Business] = relationship(back_populates="website_record")
    template: Mapped[Template | None] = relationship()
    contents: Mapped[list[WebsiteContent]] = relationship(
        back_populates="website", cascade="all, delete-orphan", order_by="WebsiteContent.section_key"
    )
    seo: Mapped[SeoMetadata | None] = relationship(
        back_populates="website", uselist=False, cascade="all, delete-orphan"
    )


class WebsiteContent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content cache: one row per section (hero, about, services, faq, ...)."""

    __tablename__ = "website_content"
    __table_args__ = (UniqueConstraint("website_id", "section_key"),)

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    section_key: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[ContentSource] = mapped_column(enum_type(ContentSource), default=ContentSource.TEMPLATE)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    website: Mapped[Website] = relationship(back_populates="contents")


class SeoMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seo_metadata"

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), unique=True)
    page_title: Mapped[str] = mapped_column(String(255))
    meta_description: Mapped[str] = mapped_column(String(500))
    keywords: Mapped[list[Any]] = mapped_column(default=list)
    local_keywords: Mapped[list[Any]] = mapped_column(default=list)
    schema_markup: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # {"about": {"title": "...", "description": "..."}, ...} - per-page metadata (Phase 2 SEO engine)
    pages: Mapped[dict[str, Any]] = mapped_column(default=dict)
    audit: Mapped[dict[str, Any] | None]  # latest SEO audit: score, checks, content gaps
    seo_score: Mapped[int] = mapped_column(Integer, default=0)

    website: Mapped[Website] = relationship(back_populates="seo")


class Deployment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deployments"

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[DeploymentStatus] = mapped_column(
        enum_type(DeploymentStatus), default=DeploymentStatus.PENDING
    )
    storage_backend: Mapped[str] = mapped_column(String(16))
    artifact_path: Mapped[str | None] = mapped_column(String(500))
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class MediaAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Asset library (08-image-factory): generate once, reuse thousands of times."""

    __tablename__ = "media_assets"

    business_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )  # null => shared library asset
    industry: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(64))  # hero, service, gallery, ...
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100), default="image/jpeg")
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)  # "generate once, reuse thousands of times"
    tags: Mapped[list[Any]] = mapped_column(default=list)
    alt_text: Mapped[str | None] = mapped_column(String(255))
    quality_score: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="library")  # library|generated|upload
