"""Factory-scale infrastructure tables: durable job queue and AI generation log/cache."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.website_factory.jobs import JobKind, JobStatus


class FactoryJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Postgres-backed work queue (claimed with FOR UPDATE SKIP LOCKED) - no extra broker to run."""

    __tablename__ = "factory_jobs"
    __table_args__ = (
        Index("ix_factory_jobs_pickup", "status", "run_after", "priority"),
        # At most one queued/running job per dedupe key (e.g. one generation per business).
        Index(
            "uq_factory_jobs_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
            sqlite_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
        ),
    )

    kind: Mapped[JobKind] = mapped_column(enum_type(JobKind))
    status: Mapped[JobStatus] = mapped_column(enum_type(JobStatus), default=JobStatus.QUEUED)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower runs first
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(128))
    finished_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None]


class AIGeneration(UUIDPrimaryKeyMixin, Base):
    """Every LLM/image-model call: the content cache (doc 07) and the cost/latency ledger (doc 17)."""

    __tablename__ = "ai_generations"

    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    task: Mapped[str] = mapped_column(String(64), index=True)  # content | review | image
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict[str, Any]] = mapped_column(default=dict)
    response: Mapped[dict[str, Any] | None]
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reasons: Mapped[list[Any]] = mapped_column(default=list)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
