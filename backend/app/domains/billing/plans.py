"""Plan catalog and entitlements (02-business-model, 14-monetization).

Prices are placeholders pending commercial sign-off; they live in the `plans`
table so they can change without a deploy.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domains.billing.enums import PlanCode

# Each tier adds to the one below it (the product ladder in doc 14), so higher plans never lose features.
_FREE = {"subdomain": True, "hosting": True, "content_editing": "basic", "seo": "basic", "contact_form": True,
         "storage_mb": 100, "max_pages": 5}
_PROFESSIONAL = {**_FREE, "custom_domain": True, "business_email": True, "content_editing": "advanced",
                 "seo": "advanced", "analytics": True, "storage_mb": 2000, "max_pages": 15}
_BUSINESS = {**_PROFESSIONAL, "crm": True, "booking": True, "lead_management": True, "customer_database": True,
             "lead_intelligence": True, "automation": True, "integrations": True,
             "storage_mb": 10000, "max_pages": 30}
_AI = {**_BUSINESS, "ai_chatbot": True, "ai_content_writer": True, "knowledge_base": True, "lead_assistant": True,
       "storage_mb": 20000, "max_pages": 50}
_VOICE = {**_AI, "voice_receptionist": True, "appointment_booking": True, "call_routing": True,
          "call_summaries": True, "storage_mb": 50000, "max_pages": 100}

PLAN_CATALOG: list[dict[str, Any]] = [
    {"code": PlanCode.FREE, "name": "Free", "price_monthly_cents": 0, "sort_order": 0,
     "description": "Hosted website on a GumaWeb subdomain.", "features": _FREE},
    {"code": PlanCode.PROFESSIONAL, "name": "Professional", "price_monthly_cents": 49900, "sort_order": 1,
     "description": "Custom domain, analytics and advanced SEO.", "features": _PROFESSIONAL},
    {"code": PlanCode.BUSINESS, "name": "Business Plus", "price_monthly_cents": 149900, "sort_order": 2,
     "description": "CRM, booking, lead scoring, automations and integrations.", "features": _BUSINESS},
    {"code": PlanCode.AI, "name": "AI", "price_monthly_cents": 299900, "sort_order": 3,
     "description": "AI chatbot, AI content writer and knowledge base.", "features": _AI},
    {"code": PlanCode.VOICE_AI, "name": "Voice AI", "price_monthly_cents": 499900, "sort_order": 4,
     "description": "AI receptionist with call routing and summaries.", "features": _VOICE},
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
