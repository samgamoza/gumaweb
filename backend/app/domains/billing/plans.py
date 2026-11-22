"""Plan catalog and entitlements (02-business-model, 14-monetization).

Prices are placeholders pending commercial sign-off; they live in the `plans`
table so they can change without a deploy.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domains.billing.enums import PlanCode

PLAN_CATALOG: list[dict[str, Any]] = [
    {
        "code": PlanCode.FREE, "name": "Free", "price_monthly_cents": 0, "sort_order": 0,
        "description": "Hosted website on a GumaWeb subdomain.",
        "features": {"subdomain": True, "hosting": True, "content_editing": "basic", "seo": "basic",
                     "contact_form": True, "storage_mb": 100, "max_pages": 5},
    },
    {
        "code": PlanCode.PROFESSIONAL, "name": "Professional", "price_monthly_cents": 49900, "sort_order": 1,
        "description": "Custom domain, analytics and advanced SEO.",
        "features": {"subdomain": True, "hosting": True, "custom_domain": True, "business_email": True,
                     "content_editing": "advanced", "seo": "advanced", "analytics": True,
                     "contact_form": True, "storage_mb": 2000, "max_pages": 15},
    },
    {
        "code": PlanCode.BUSINESS, "name": "Business Plus", "price_monthly_cents": 149900, "sort_order": 2,
        "description": "CRM, booking and lead management.",
        "features": {"custom_domain": True, "business_email": True, "analytics": True, "crm": True,
                     "booking": True, "lead_management": True, "customer_database": True,
                     "content_editing": "advanced", "seo": "advanced", "storage_mb": 10000, "max_pages": 30},
    },
    {
        "code": PlanCode.AI, "name": "AI", "price_monthly_cents": 299900, "sort_order": 3,
        "description": "AI chatbot, AI content writer and knowledge base.",
        "features": {"custom_domain": True, "analytics": True, "crm": True, "booking": True,
                     "ai_chatbot": True, "ai_content_writer": True, "knowledge_base": True,
                     "lead_assistant": True, "content_editing": "advanced", "seo": "advanced",
                     "storage_mb": 20000, "max_pages": 50},
    },
    {
        "code": PlanCode.VOICE_AI, "name": "Voice AI", "price_monthly_cents": 499900, "sort_order": 4,
        "description": "AI receptionist with call routing and summaries.",
        "features": {"custom_domain": True, "analytics": True, "crm": True, "booking": True,
                     "ai_chatbot": True, "voice_receptionist": True, "appointment_booking": True,
                     "call_routing": True, "call_summaries": True, "content_editing": "advanced",
                     "seo": "advanced", "storage_mb": 50000, "max_pages": 100},
    },
]

PLAN_ORDER = [p["code"] for p in PLAN_CATALOG]


def is_upgrade(current: PlanCode, target: PlanCode) -> bool:
    return PLAN_ORDER.index(target) > PLAN_ORDER.index(current)


class PaymentProvider(Protocol):
    """Seam for a payment gateway (e.g. PayMongo/Xendit for PH). Phase 1 uses manual invoicing."""

    name: str

    def create_subscription(self, customer_id: str, plan: PlanCode) -> str: ...

    def cancel_subscription(self, provider_ref: str) -> None: ...


class ManualPaymentProvider:
    name = "manual"

    def create_subscription(self, customer_id: str, plan: PlanCode) -> str:
        return f"manual:{customer_id}:{plan.value}"

    def cancel_subscription(self, provider_ref: str) -> None:
        return None
