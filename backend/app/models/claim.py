"""Claims aggregate (11-claim-ownership-platform)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.domains.claims.enums import ClaimStatus, VerificationMethod

if TYPE_CHECKING:
    from app.models.business import Business


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        # A business can have at most one approved owner.
        Index(
            "uq_claims_business_approved",
            "business_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
            sqlite_where=text("status = 'approved'"),
        ),
        Index("ix_claims_business_status", "business_id", "status"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    website_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("websites.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    claimant_name: Mapped[str] = mapped_column(String(200))
    claimant_email: Mapped[str] = mapped_column(String(320), index=True)
    claimant_phone: Mapped[str | None] = mapped_column(String(32))
    method: Mapped[VerificationMethod] = mapped_column(enum_type(VerificationMethod))
    status: Mapped[ClaimStatus] = mapped_column(
        enum_type(ClaimStatus), default=ClaimStatus.PENDING_VERIFICATION
    )

    verification_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64))
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime]
    verified_at: Mapped[datetime | None]

    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_factors: Mapped[list[Any]] = mapped_column(default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)  # business identity documents/links
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None]
    review_notes: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship()
