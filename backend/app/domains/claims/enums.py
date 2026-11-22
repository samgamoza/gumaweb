from enum import StrEnum


class ClaimStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    MANUAL_REVIEW = "manual_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


ACTIVE_CLAIM_STATUSES = (ClaimStatus.PENDING_VERIFICATION, ClaimStatus.MANUAL_REVIEW)


class VerificationMethod(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    BUSINESS_IDENTITY = "business_identity"
