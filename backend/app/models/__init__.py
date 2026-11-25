"""Import every model so Base.metadata is complete (Alembic autogenerate, create_all)."""

from app.models.automation import (
    ApiKey,
    AutomationRule,
    AutomationRun,
    Call,
    VoiceSettings,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.models.business import Business, BusinessContact, BusinessProfile, DiscoveryRun
from app.models.claim import Claim
from app.models.customer import Customer, Lead, Plan, Subscription
from app.models.engagement import (
    Appointment,
    BookingSettings,
    ChatbotSettings,
    ChatConversation,
    ChatMessage,
    Contact,
    ContactActivity,
    KnowledgeEntry,
)
from app.models.factory import AIGeneration, FactoryJob, ProviderUsage
from app.models.outreach import OutreachCampaign, OutreachEvent, OutreachMessage, OutreachSuppression
from app.models.platform import AuditLog, DomainEvent, SiteEvent
from app.models.presence import CustomDomain, Mailbox, MailDomain, PresenceKit
from app.models.template import Template, TemplateComponent
from app.models.user import User
from app.models.website import Deployment, MediaAsset, SeoMetadata, Website, WebsiteContent

__all__ = [
    "CustomDomain",
    "MailDomain",
    "Mailbox",
    "PresenceKit",
    "ProviderUsage",
    "AIGeneration",
    "ApiKey",
    "AutomationRule",
    "AutomationRun",
    "Call",
    "VoiceSettings",
    "WebhookDelivery",
    "WebhookEndpoint",
    "Appointment",
    "BookingSettings",
    "ChatConversation",
    "ChatMessage",
    "ChatbotSettings",
    "Contact",
    "ContactActivity",
    "KnowledgeEntry",
    "AuditLog",
    "FactoryJob",
    "Business",
    "BusinessContact",
    "BusinessProfile",
    "Claim",
    "Customer",
    "Deployment",
    "DiscoveryRun",
    "DomainEvent",
    "Lead",
    "MediaAsset",
    "OutreachCampaign",
    "OutreachEvent",
    "OutreachMessage",
    "OutreachSuppression",
    "Plan",
    "SeoMetadata",
    "SiteEvent",
    "Subscription",
    "Template",
    "TemplateComponent",
    "User",
    "Website",
    "WebsiteContent",
]
