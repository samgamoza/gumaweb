"""Resolve plan entitlements and site features for a business, and keep published sites in sync."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.billing.entitlements import Feature, has_feature, require
from app.domains.website_factory.enums import WebsiteStatus
from app.models import BookingSettings, ChatbotSettings, Customer, Plan
from app.repositories.repositories import CustomerRepository, WebsiteRepository
from app.services.support import Actor

logger = logging.getLogger("gumaweb.entitlements")


def plan_for_business(db: Session, business_id: uuid.UUID) -> tuple[dict[str, Any], str]:
    """(features, plan name). Unclaimed businesses have no paid features."""
    customer: Customer | None = CustomerRepository(db).by_business(business_id)
    if customer is None:
        return {}, "unclaimed"
    plan = db.get(Plan, customer.plan)
    return (plan.features if plan else {}), (plan.name if plan else customer.plan.value)


def require_feature(db: Session, business_id: uuid.UUID, feature: Feature) -> None:
    features, name = plan_for_business(db, business_id)
    require(features, feature, name)


def site_features(db: Session, business_id: uuid.UUID) -> dict[str, Any]:
    """Interactive modules rendered into the generated site (needs both the plan and the owner's switch)."""
    features, _ = plan_for_business(db, business_id)
    out: dict[str, Any] = {"booking": False, "chat": None}
    booking = db.get(BookingSettings, business_id)
    if booking and booking.enabled and booking.services and has_feature(features, Feature.BOOKING):
        out["booking"] = True
    chat = db.get(ChatbotSettings, business_id)
    if chat and chat.enabled and has_feature(features, Feature.AI_CHATBOT):
        out["chat"] = {"greeting": chat.greeting}
    return out


def refresh_site(db: Session, settings: Settings, business_id: uuid.UUID, actor: Actor) -> None:
    """Rebuild the blueprint (feature sections/widgets) and republish if the site is live."""
    from app.services.publishing_service import PublishingService
    from app.workflows.website_generation import WebsiteGenerationWorkflow

    website = WebsiteRepository(db).by_business(business_id)
    if website is None:
        return
    WebsiteGenerationWorkflow(db, settings).refresh_business_facts(website)
    if website.status == WebsiteStatus.PUBLISHED:
        try:
            PublishingService(db, settings).publish(website, actor, force=True)
        except Exception:  # a storage hiccup must not undo the settings change; next publish catches up
            logger.exception("republish after feature change failed for %s", website.subdomain)
