from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.domains.claims.enums import ClaimStatus, VerificationMethod
from app.schemas.auth import TokenPair
from app.schemas.common import ORMModel


class ClaimStart(BaseModel):
    subdomain: str = Field(max_length=63)
    claimant_name: str = Field(min_length=2, max_length=200)
    claimant_email: EmailStr
    claimant_phone: str | None = Field(None, max_length=32)
    method: VerificationMethod = VerificationMethod.EMAIL
    evidence: dict[str, Any] = Field(default_factory=dict, description="Registration no., official links, ...")
    ref: str | None = Field(None, max_length=64, description="Outreach tracking token, for attribution")
    website: str | None = Field(None, description="Honeypot: must be empty")

    @model_validator(mode="after")
    def _phone_for_sms(self) -> ClaimStart:
        if self.method == VerificationMethod.SMS and not self.claimant_phone:
            raise ValueError("claimant_phone is required for SMS verification")
        return self


class ClaimStarted(BaseModel):
    claim_id: uuid.UUID
    status: ClaimStatus
    method: VerificationMethod
    expires_at: datetime
    message: str


class ClaimVerify(BaseModel):
    token: str | None = Field(None, max_length=200)
    claim_id: uuid.UUID | None = None
    otp: str | None = Field(None, pattern=r"^\d{6}$")
    password: str | None = Field(None, min_length=10, max_length=200)

    @model_validator(mode="after")
    def _token_or_otp(self) -> ClaimVerify:
        if not self.token and not (self.claim_id and self.otp):
            raise ValueError("provide either token, or claim_id and otp")
        return self


class ClaimVerified(BaseModel):
    claim_id: uuid.UUID
    status: ClaimStatus
    message: str
    tokens: TokenPair | None = None


class ClaimRead(ORMModel):
    id: uuid.UUID
    business_id: uuid.UUID
    website_id: uuid.UUID | None
    user_id: uuid.UUID | None
    claimant_name: str
    claimant_email: str
    claimant_phone: str | None
    method: VerificationMethod
    status: ClaimStatus
    risk_score: int
    risk_factors: list[str]
    evidence: dict[str, Any]
    verified_at: datetime | None
    reviewed_at: datetime | None
    review_notes: str | None
    expires_at: datetime
    created_at: datetime


class ClaimReview(BaseModel):
    notes: str | None = Field(None, max_length=2000)
