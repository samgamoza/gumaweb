from enum import StrEnum


class OutreachChannel(StrEnum):
    EMAIL = "email"
    CONTACT_FORM = "contact_form"
    SMS = "sms"  # Phase 2
    VOICE = "voice"  # Phase 2
    FACEBOOK = "facebook"  # Phase 2


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class MessageStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"  # suppressed, already claimed, etc.


class OutreachEventType(StrEnum):
    """Engagement events from 13-outreach-engine."""

    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    LINK_CLICKED = "link_clicked"
    WEBSITE_VISITED = "website_visited"
    CLAIM_STARTED = "claim_started"
    CLAIM_COMPLETED = "claim_completed"
    UNSUBSCRIBED = "unsubscribed"
