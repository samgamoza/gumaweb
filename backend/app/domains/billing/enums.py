from enum import StrEnum


class PlanCode(StrEnum):
    """Product ladder from 14-monetization."""

    FREE = "free"
    PROFESSIONAL = "professional"
    BUSINESS = "business"
    AI = "ai"
    VOICE_AI = "voice_ai"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
