"""Customers and Billing aggregates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.billing.enums import PlanCode, SubscriptionStatus
from app.domains.customers.enums import CustomerStatus

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.user import User


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A verified owner of a claimed business."""

    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True
    )
    plan: Mapped[PlanCode] = mapped_column(enum_type(PlanCode), default=PlanCode.FREE, index=True)
    status: Mapped[CustomerStatus] = mapped_column(enum_type(CustomerStatus), default=CustomerStatus.ACTIVE)
    activated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship()
    business: Mapped[Business] = relationship()


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[PlanCode] = mapped_column(enum_type(PlanCode), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    price_monthly_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="PHP")
    features: Mapped[dict[str, Any]] = mapped_column(default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "uq_subscriptions_customer_active",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    plan_code: Mapped[PlanCode] = mapped_column(enum_type(PlanCode), ForeignKey("plans.code"))
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_type(SubscriptionStatus), default=SubscriptionStatus.ACTIVE
    )
    provider: Mapped[str] = mapped_column(String(32), default="manual")
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    current_period_start: Mapped[datetime] = mapped_column(server_default=func.now())
    current_period_end: Mapped[datetime | None]
    canceled_at: Mapped[datetime | None]

    plan: Mapped[Plan] = relationship()


class Lead(UUIDPrimaryKeyMixin, Base):
    """Contact-form submissions captured on generated websites."""

    __tablename__ = "leads"

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
