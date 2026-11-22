"""BusinessDiscovery + BusinessProfile aggregates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.business_discovery.enums import BusinessStatus, DiscoveryRunStatus, DiscoverySource
from app.domains.business_profile.enums import ProfileSource

if TYPE_CHECKING:
    from app.models.website import Website


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        Index("ix_businesses_candidate_score", "generate_candidate", "score"),
        Index("ix_businesses_industry_city", "industry", "city"),
    )

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    industry: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    province: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2), default="PH")
    postal_code: Mapped[str | None] = mapped_column(String(16))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    website: Mapped[str | None] = mapped_column(String(500))
    facebook: Mapped[str | None] = mapped_column(String(500))
    google_business_url: Mapped[str | None] = mapped_column(String(500))

    source: Mapped[DiscoverySource] = mapped_column(enum_type(DiscoverySource), default=DiscoverySource.MANUAL)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL")
    )

    status: Mapped[BusinessStatus] = mapped_column(
        enum_type(BusinessStatus), default=BusinessStatus.DISCOVERED, index=True
    )
    score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[dict[str, Any] | None]
    generate_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_at: Mapped[datetime | None]

    profile: Mapped[BusinessProfile | None] = relationship(
        back_populates="business", uselist=False, cascade="all, delete-orphan"
    )
    website_record: Mapped[Website | None] = relationship(back_populates="business", uselist=False)


class BusinessProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured profile produced by the Business Intelligence Engine."""

    __tablename__ = "business_profiles"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True
    )
    industry: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64), index=True)  # template master category
    services: Mapped[list[Any]] = mapped_column(default=list)
    keywords: Mapped[list[Any]] = mapped_column(default=list)
    local_keywords: Mapped[list[Any]] = mapped_column(default=list)
    target_audience: Mapped[str | None] = mapped_column(String(64))
    brand_voice: Mapped[str | None] = mapped_column(String(255))
    brand_tone: Mapped[str | None] = mapped_column(String(32))
    tagline: Mapped[str | None] = mapped_column(String(255))
    recommended_template: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[ProfileSource] = mapped_column(enum_type(ProfileSource), default=ProfileSource.RULE_BASED)

    business: Mapped[Business] = relationship(back_populates="profile")


class DiscoveryRun(UUIDPrimaryKeyMixin, Base):
    """One execution of a discovery connector or bulk import."""

    __tablename__ = "discovery_runs"

    source: Mapped[DiscoverySource] = mapped_column(enum_type(DiscoverySource))
    status: Mapped[DiscoveryRunStatus] = mapped_column(
        enum_type(DiscoveryRunStatus), default=DiscoveryRunStatus.RUNNING
    )
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[Any]] = mapped_column(default=list)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
