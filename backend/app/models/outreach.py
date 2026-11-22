"""Outreach aggregate (13-outreach-engine)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.outreach.enums import CampaignStatus, MessageStatus, OutreachChannel, OutreachEventType


class OutreachCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outreach_campaigns"

    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[OutreachChannel] = mapped_column(enum_type(OutreachChannel), default=OutreachChannel.EMAIL)
    status: Mapped[CampaignStatus] = mapped_column(enum_type(CampaignStatus), default=CampaignStatus.DRAFT)
    # [{"step": 0, "day": 0, "subject": "...", "body": "..."}]
    sequence: Mapped[list[Any]] = mapped_column(default=list)
    target_filter: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None]


class OutreachMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outreach_messages"
    __table_args__ = (
        UniqueConstraint("campaign_id", "business_id", "step"),
        Index("ix_outreach_messages_status_scheduled", "status", "scheduled_at"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_campaigns.id", ondelete="CASCADE"))
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("websites.id", ondelete="SET NULL"))
    channel: Mapped[OutreachChannel] = mapped_column(enum_type(OutreachChannel))
    step: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    tracking_token: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[MessageStatus] = mapped_column(enum_type(MessageStatus), default=MessageStatus.SCHEDULED)
    scheduled_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)


class OutreachEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outreach_events"
    __table_args__ = (Index("ix_outreach_events_business_type", "business_id", "event_type"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_campaigns.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outreach_messages.id", ondelete="SET NULL"))
    channel: Mapped[OutreachChannel] = mapped_column(enum_type(OutreachChannel))
    event_type: Mapped[OutreachEventType] = mapped_column(enum_type(OutreachEventType))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class OutreachSuppression(UUIDPrimaryKeyMixin, Base):
    """Do-not-contact list (communications compliance)."""

    __tablename__ = "outreach_suppressions"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    reason: Mapped[str] = mapped_column(String(64), default="unsubscribed")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
