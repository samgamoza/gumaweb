"""Private claim link (A7): what the `/start/<token>` page reads and sends."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.domains.claims.enums import VerificationMethod


class StartDetails(BaseModel):
    name: str
    description: str | None = None
    address: str | None = None
    facebook: str | None = None
    services: list[str] = Field(default_factory=list)
    phone: str | None = None  # only what the owner entered here; the number on record is masked below
    email: str | None = None


class StartInfo(BaseModel):
    business_name: str
    industry: str | None
    city: str | None
    province: str | None
    status: Literal["ready", "claimed"]
    expires_at: datetime
    preview_url: str
    masked_email: str | None
    masked_phone: str | None
    details: StartDetails
    pending_claim: str | None = None  # status of a claim already in progress


class StartDetailsUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = Field(None, max_length=2000)
    address: str | None = Field(None, max_length=1000)
    facebook: str | None = Field(None, max_length=500)
    services: list[str] | None = Field(None, max_length=12)
    phone: str | None = Field(None, max_length=32)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def _short_services(self) -> StartDetailsUpdate:
        if self.services and any(len(s) > 80 for s in self.services):
            raise ValueError("each service must be at most 80 characters")
        return self


class StartClaim(BaseModel):
    claimant_name: str = Field(min_length=2, max_length=200)
    claimant_email: EmailStr
    claimant_phone: str | None = Field(None, max_length=32)
    method: Literal[VerificationMethod.EMAIL, VerificationMethod.SMS] = VerificationMethod.EMAIL
    website: str | None = Field(None, description="Honeypot: must be empty")

    @model_validator(mode="after")
    def _phone_for_sms(self) -> StartClaim:
        if self.method == VerificationMethod.SMS and not self.claimant_phone:
            raise ValueError("claimant_phone is required for SMS verification")
        return self
