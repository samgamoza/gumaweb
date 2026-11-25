"""Audited actions (19-security-compliance: logins, claims, updates, subscriptions)."""

from enum import StrEnum


class AuditAction(StrEnum):
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    PASSWORD_CHANGED = "auth.password_changed"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"

    BUSINESS_CREATED = "business.created"
    BUSINESS_UPDATED = "business.updated"
    BUSINESS_ARCHIVED = "business.archived"
    BUSINESS_IMPORTED = "business.imported"

    TEMPLATE_CREATED = "template.created"
    TEMPLATE_UPDATED = "template.updated"
    TEMPLATES_SYNCED = "template.synced"

    WEBSITE_GENERATED = "website.generated"
    WEBSITE_PUBLISHED = "website.published"
    WEBSITE_UNPUBLISHED = "website.unpublished"
    CONTENT_UPDATED = "website.content_updated"

    CLAIM_STARTED = "claim.started"
    CLAIM_VERIFIED = "claim.verified"
    CLAIM_APPROVED = "claim.approved"
    CLAIM_REJECTED = "claim.rejected"

    SUBSCRIPTION_CHANGED = "subscription.changed"
    CAMPAIGN_CREATED = "outreach.campaign_created"
    CAMPAIGN_DISPATCHED = "outreach.campaign_dispatched"
    SUPPRESSION_ADDED = "outreach.suppression_added"
    SUPPRESSION_REMOVED = "outreach.suppression_removed"
    DISCOVERY_CAMPAIGN_CREATED = "discovery.campaign_created"
    DISCOVERY_CAMPAIGN_UPDATED = "discovery.campaign_updated"
    DISCOVERY_CAMPAIGN_DELETED = "discovery.campaign_deleted"
    DISCOVERY_CAMPAIGN_STARTED = "discovery.campaign_started"
    DISCOVERY_CAMPAIGN_CANCELLED = "discovery.campaign_cancelled"
