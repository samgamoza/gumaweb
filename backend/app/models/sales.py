"""Sales CRM: Guma OS's own prospect pipeline (docs/SALES_CRM_PLAN.md). A prospect is a business (1:1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.sales import ActivitySource, ActivityType, ProspectStage
from app.models.business import Business


class Prospect(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prospects"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
        Index("ix_prospects_stage_last_touch_at", "stage", "last_touch_at"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), unique=True)
    stage: Mapped[ProspectStage] = mapped_column(enum_type(ProspectStage), default=ProspectStage.NEW)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    score: Mapped[int | None] = mapped_column(Integer)  # outbound priority (domains/sales/priority.py)
    score_reasons: Mapped[list[Any]] = mapped_column(default=list)
    channels: Mapped[list[Any]] = mapped_column(default=list)  # usable channels, e.g. ["email", "phone"]
    reachable: Mapped[bool] = mapped_column(Boolean, default=False)  # bool(channels), indexable
    scored_at: Mapped[datetime | None]
    last_touch_at: Mapped[datetime | None]
    stage_changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lost_reason: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[datetime | None]  # outreach skips a lost prospect until then

    business: Mapped[Business] = relationship()


class ProspectActivity(UUIDPrimaryKeyMixin, Base):
    """One entry of a prospect's timeline. `external_id` makes replays (backfill, dialer sync) no-ops."""

    __tablename__ = "prospect_activities"
    __table_args__ = (Index("ix_prospect_activities_prospect_id_occurred_at", "prospect_id", "occurred_at"),)

    prospect_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"))
    type: Mapped[ActivityType] = mapped_column(enum_type(ActivityType))
    source: Mapped[ActivitySource] = mapped_column(enum_type(ActivitySource), default=ActivitySource.SYSTEM)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProspectTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prospect_tasks"
    __table_args__ = (Index("ix_prospect_tasks_assignee_user_id_done_at_due_at", "assignee_user_id", "done_at",
                            "due_at"),)

    prospect_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prospects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    due_at: Mapped[datetime]
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    done_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
