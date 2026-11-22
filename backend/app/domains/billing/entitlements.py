"""Plan entitlements (14-monetization): which plan unlocks which Phase 3 module."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.core.exceptions import GumaWebError


class Feature(StrEnum):
    CRM = "crm"
    LEAD_MANAGEMENT = "lead_management"
    BOOKING = "booking"
    AI_CHATBOT = "ai_chatbot"
    KNOWLEDGE_BASE = "knowledge_base"
    LEAD_INTELLIGENCE = "lead_intelligence"  # Phase 4
    AUTOMATION = "automation"  # Phase 4
    INTEGRATIONS = "integrations"  # Phase 4: API keys + webhooks (Guma OS)
    VOICE_RECEPTIONIST = "voice_receptionist"  # Phase 4
    SOCIAL_KIT = "social_kit"  # Phase 5: logo, profile picture, cover, bios (every plan)
    PRESENCE_KIT = "presence_kit"  # Phase 5: posts, stories, Google Business pack, SEO profile, ZIP
    CUSTOM_DOMAIN = "custom_domain"  # Phase 5
    BUSINESS_EMAIL = "business_email"  # Phase 5


class PlanUpgradeRequired(GumaWebError):
    status_code = 403
    code = "plan_upgrade_required"


def has_feature(plan_features: dict[str, Any] | None, feature: Feature) -> bool:
    return bool((plan_features or {}).get(feature.value))


def require(plan_features: dict[str, Any] | None, feature: Feature, plan_name: str) -> None:
    if not has_feature(plan_features, feature):
        raise PlanUpgradeRequired(f"{feature.value.replace('_', ' ').title()} is not included in the {plan_name} plan")
