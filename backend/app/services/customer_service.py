"""Customer Portal + Billing application services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.analytics.enums import SiteEventType
from app.domains.audit.actions import AuditAction
from app.domains.billing.enums import PlanCode, SubscriptionStatus
from app.domains.billing.plans import ManualPaymentProvider
from app.domains.business_discovery import normalization as norm
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.models import Customer, Lead, Plan, SiteEvent, Subscription, User, Website
from app.repositories.repositories import (
    CustomerRepository,
    PlanRepository,
    SubscriptionRepository,
    WebsiteRepository,
)
from app.schemas.customer import (
    CustomerDashboard,
    CustomerProfileUpdate,
    DashboardStats,
    DashboardWebsite,
    LeadRead,
    PlanRead,
    SeoSummary,
)
from app.services.entitlements import refresh_site
from app.services.publishing_service import PublishingService
from app.services.support import Actor, EventType, audit, record_event
from app.workflows.website_generation import WebsiteGenerationWorkflow


class CustomerService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.customers = CustomerRepository(db)
        self.websites = WebsiteRepository(db)
        self.plans = PlanRepository(db)

    def for_user(self, user: User) -> Customer:
        customer = self.customers.by_user(user.id)
        if customer is None:
            raise NotFoundError("No claimed business is linked to this account yet", code="no_customer")
        return customer

    def website(self, customer: Customer) -> Website:
        website = self.websites.by_business(customer.business_id)
        if website is None:
            raise NotFoundError("Website not found")
        return website

    def dashboard(self, customer: Customer) -> CustomerDashboard:
        website = self.websites.by_business(customer.business_id)
        since = datetime.now(UTC) - timedelta(days=30)
        stats = DashboardStats(page_views_30d=0, leads_30d=0, phone_clicks_30d=0)
        leads: list[Lead] = []
        if website:
            counts = dict(
                self.db.execute(
                    select(SiteEvent.event_type, func.count())
                    .where(SiteEvent.website_id == website.id, SiteEvent.occurred_at >= since)
                    .group_by(SiteEvent.event_type)
                ).all()
            )
            leads_30d = self.db.scalar(
                select(func.count(Lead.id)).where(Lead.website_id == website.id, Lead.created_at >= since)
            ) or 0
            stats = DashboardStats(
                page_views_30d=counts.get(SiteEventType.PAGE_VIEW, 0),
                leads_30d=leads_30d,
                phone_clicks_30d=counts.get(SiteEventType.PHONE_CLICK, 0),
            )
            leads = list(self.db.scalars(
                select(Lead).where(Lead.website_id == website.id).order_by(Lead.created_at.desc()).limit(5)
            ))
        business = customer.business
        plan = self.plans.get_or_404(customer.plan)
        return CustomerDashboard(
            customer=customer,  # type: ignore[arg-type]
            business={
                "id": str(business.id), "name": business.name, "industry": business.industry,
                "description": business.description, "phone": business.phone, "email": business.email,
                "address": business.address, "city": business.city, "province": business.province,
                "facebook": business.facebook,
            },
            website=DashboardWebsite(
                id=website.id, subdomain=website.subdomain, url=website.url, status=website.status.value,
                version=website.version, quality_score=website.quality_score,
                seo_score=website.seo.seo_score if website.seo else None, published_at=website.published_at,
            ) if website else None,
            plan=PlanRead.model_validate(plan),
            stats=stats,
            recent_leads=[LeadRead.model_validate(lead) for lead in leads],
            seo=SeoSummary(score=website.seo.audit["score"], content_gaps=website.seo.audit["content_gaps"])
            if website and website.seo and website.seo.audit else None,
        )

    def update_profile(self, customer: Customer, data: CustomerProfileUpdate, actor: Actor) -> Customer:
        business = customer.business
        changes = data.model_dump(exclude_unset=True, exclude={"republish"})
        if "phone" in changes:
            changes["phone"] = norm.normalize_phone(changes["phone"], self.settings.default_country_code)
        if "facebook" in changes:
            changes["facebook"] = norm.normalize_url(changes["facebook"])
        for field, value in changes.items():
            setattr(business, field, value)
        website = self.websites.by_business(business.id)
        if website:
            contact = self.websites.content_map(website.id).get("contact")
            if contact:
                synced = {k: changes[k] for k in ("phone", "email", "address", "facebook") if k in changes}
                contact.content = {**contact.content, **synced}
            WebsiteGenerationWorkflow(self.db, self.settings).refresh_business_facts(website)
            if data.republish and website.status == WebsiteStatus.PUBLISHED:
                PublishingService(self.db, self.settings).publish(website, actor, force=True)
        audit(self.db, actor, AuditAction.BUSINESS_UPDATED, "business", business.id,
              {"fields": sorted(changes), "by": "customer"})
        self.db.commit()
        return customer

    def remove_image_references(self, customer: Customer, asset_id: str, actor: Actor) -> None:
        """Before deleting an upload, drop it from the gallery/hero and republish if it was live."""
        website = self.websites.by_business(customer.business_id)
        if website is None:
            return
        changed = False
        for row in self.websites.content_map(website.id).values():
            content = dict(row.content)
            if isinstance(content.get("image"), dict) and content["image"].get("asset_id") == asset_id:
                content.pop("image")
                changed = True
            if isinstance(content.get("images"), list):
                kept = [i for i in content["images"] if i.get("asset_id") != asset_id]
                changed |= len(kept) != len(content["images"])
                content["images"] = kept
            row.content = content
        if changed:
            WebsiteGenerationWorkflow(self.db, self.settings).validate(website)
            if website.status == WebsiteStatus.PUBLISHED:
                PublishingService(self.db, self.settings).publish(website, actor, force=True)

    def leads(self, customer: Customer, limit: int = 100) -> list[Lead]:
        website = self.website(customer)
        return list(self.db.scalars(
            select(Lead).where(Lead.website_id == website.id).order_by(Lead.created_at.desc()).limit(limit)
        ))

    @staticmethod
    def content_source() -> ContentSource:
        return ContentSource.CUSTOMER


class BillingService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.plans = PlanRepository(db)
        self.subscriptions = SubscriptionRepository(db)
        self.payment = ManualPaymentProvider()

    def list_plans(self) -> list[Plan]:
        return list(self.plans.active())

    def current(self, customer: Customer) -> Subscription:
        subscription = self.subscriptions.active_for_customer(customer.id)
        if subscription is None:
            raise NotFoundError("No active subscription")
        return subscription

    def change_plan(self, customer: Customer, target: PlanCode, actor: Actor) -> Subscription:
        plan = self.plans.get(target)
        if plan is None or not plan.is_active:
            raise ValidationFailedError(f"Plan '{target.value}' is not available")
        if customer.plan == target:
            return self.current(customer)
        previous = customer.plan
        current = self.subscriptions.active_for_customer(customer.id)
        now = datetime.now(UTC)
        if current:
            current.status = SubscriptionStatus.CANCELED
            current.canceled_at = now
            if current.provider_ref:
                self.payment.cancel_subscription(current.provider_ref)
            self.db.flush()
        subscription = Subscription(
            customer_id=customer.id, plan_code=target, provider=self.payment.name,
            provider_ref=self.payment.create_subscription(str(customer.id), target),
            current_period_start=now,
            current_period_end=now + timedelta(days=30) if plan.price_monthly_cents else None,
        )
        self.db.add(subscription)
        customer.plan = target
        record_event(self.db, EventType.CUSTOMER_UPGRADED, "customer", customer.id,
                     {"from": previous.value, "to": target.value})
        self.db.flush()
        # Plan changes add/remove booking & chat modules on the live site.
        refresh_site(self.db, self.settings, customer.business_id, actor)
        audit(self.db, actor, AuditAction.SUBSCRIPTION_CHANGED, "customer", customer.id,
              {"from": previous.value, "to": target.value})
        self.db.commit()
        return subscription
