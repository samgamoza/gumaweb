"""Aggregate repositories. Queries live here; business rules live in domains/services."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select

from app.domains.business_discovery.enums import BusinessStatus
from app.domains.claims.enums import ACTIVE_CLAIM_STATUSES, ClaimStatus
from app.domains.template_management.enums import TemplateStatus
from app.models import (
    AuditLog,
    Business,
    BusinessProfile,
    Claim,
    Customer,
    Deployment,
    DiscoveryRun,
    DomainEvent,
    OutreachCampaign,
    OutreachMessage,
    Plan,
    Subscription,
    Template,
    TemplateComponent,
    User,
    Website,
    WebsiteContent,
)
from app.repositories.base import Repository
from app.schemas.business import BusinessFilters


class UserRepository(Repository[User]):
    model = User

    def by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email.lower()))


class BusinessRepository(Repository[Business]):
    model = Business

    def by_dedupe_key(self, key: str) -> Business | None:
        return self.db.scalar(select(Business).where(Business.dedupe_key == key))

    def slug_exists(self, slug: str) -> bool:
        return self.db.scalar(select(Business.id).where(Business.slug == slug)) is not None

    def filtered(self, f: BusinessFilters):
        stmt = select(Business)
        if f.q:
            like = f"%{f.q.lower()}%"
            stmt = stmt.where(or_(Business.name.ilike(like), Business.city.ilike(like)))
        if f.status:
            stmt = stmt.where(Business.status == f.status)
        else:
            stmt = stmt.where(Business.status != BusinessStatus.ARCHIVED)
        if f.industry:
            stmt = stmt.where(Business.industry == f.industry)
        if f.city:
            stmt = stmt.where(Business.city.ilike(f.city))
        if f.min_score is not None:
            stmt = stmt.where(Business.score >= f.min_score)
        if f.generate_candidate is not None:
            stmt = stmt.where(Business.generate_candidate == f.generate_candidate)
        return stmt.order_by(Business.score.desc().nulls_last(), Business.created_at.desc())


class BusinessProfileRepository(Repository[BusinessProfile]):
    model = BusinessProfile

    def for_business(self, business_id: uuid.UUID) -> BusinessProfile | None:
        return self.db.scalar(select(BusinessProfile).where(BusinessProfile.business_id == business_id))


class DiscoveryRunRepository(Repository[DiscoveryRun]):
    model = DiscoveryRun

    def recent(self, limit: int = 50) -> Sequence[DiscoveryRun]:
        return self.db.scalars(select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(limit)).all()


class TemplateRepository(Repository[Template]):
    model = Template

    def by_slug(self, slug: str) -> Template | None:
        return self.db.scalar(select(Template).where(Template.slug == slug))

    def active(self) -> Sequence[Template]:
        return self.db.scalars(select(Template).where(Template.status == TemplateStatus.ACTIVE)).all()

    def all(self, category: str | None = None) -> Sequence[Template]:
        stmt = select(Template).order_by(Template.category, Template.slug)
        if category:
            stmt = stmt.where(Template.category == category)
        return self.db.scalars(stmt).all()


class TemplateComponentRepository(Repository[TemplateComponent]):
    model = TemplateComponent

    def by_slug(self, slug: str) -> TemplateComponent | None:
        return self.db.scalar(select(TemplateComponent).where(TemplateComponent.slug == slug))

    def all(self) -> Sequence[TemplateComponent]:
        return self.db.scalars(
            select(TemplateComponent).order_by(TemplateComponent.component_type, TemplateComponent.variant)
        ).all()


class WebsiteRepository(Repository[Website]):
    model = Website

    def by_business(self, business_id: uuid.UUID) -> Website | None:
        return self.db.scalar(select(Website).where(Website.business_id == business_id))

    def by_subdomain(self, subdomain: str) -> Website | None:
        return self.db.scalar(select(Website).where(Website.subdomain == subdomain))

    def subdomain_taken(self, subdomain: str) -> bool:
        return self.db.scalar(select(Website.id).where(Website.subdomain == subdomain)) is not None

    def content_map(self, website_id: uuid.UUID) -> dict[str, WebsiteContent]:
        rows = self.db.scalars(select(WebsiteContent).where(WebsiteContent.website_id == website_id)).all()
        return {row.section_key: row for row in rows}

    def deployments(self, website_id: uuid.UUID) -> Sequence[Deployment]:
        return self.db.scalars(
            select(Deployment).where(Deployment.website_id == website_id).order_by(Deployment.started_at.desc())
        ).all()


class ClaimRepository(Repository[Claim]):
    model = Claim

    def by_token_hash(self, token_hash: str) -> Claim | None:
        return self.db.scalar(select(Claim).where(Claim.verification_token_hash == token_hash))

    def active_for_business(self, business_id: uuid.UUID) -> Sequence[Claim]:
        return self.db.scalars(
            select(Claim).where(Claim.business_id == business_id, Claim.status.in_(ACTIVE_CLAIM_STATUSES))
        ).all()

    def count_from_ip_since(self, ip: str, since: datetime) -> int:
        stmt = select(func.count(Claim.id)).where(Claim.ip_address == ip, Claim.created_at >= since)
        return self.db.scalar(stmt) or 0

    def approved_for_business(self, business_id: uuid.UUID) -> Claim | None:
        return self.db.scalar(
            select(Claim).where(Claim.business_id == business_id, Claim.status == ClaimStatus.APPROVED)
        )


class CustomerRepository(Repository[Customer]):
    model = Customer

    def by_user(self, user_id: uuid.UUID) -> Customer | None:
        return self.db.scalar(select(Customer).where(Customer.user_id == user_id))

    def by_business(self, business_id: uuid.UUID) -> Customer | None:
        return self.db.scalar(select(Customer).where(Customer.business_id == business_id))


class PlanRepository(Repository[Plan]):
    model = Plan

    def active(self) -> Sequence[Plan]:
        return self.db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)).all()


class SubscriptionRepository(Repository[Subscription]):
    model = Subscription

    def active_for_customer(self, customer_id: uuid.UUID) -> Subscription | None:
        return self.db.scalar(
            select(Subscription).where(Subscription.customer_id == customer_id, Subscription.status == "active")
        )


class OutreachRepository(Repository[OutreachCampaign]):
    model = OutreachCampaign

    def all(self) -> Sequence[OutreachCampaign]:
        return self.db.scalars(select(OutreachCampaign).order_by(OutreachCampaign.created_at.desc())).all()

    def message_by_token(self, token: str) -> OutreachMessage | None:
        return self.db.scalar(select(OutreachMessage).where(OutreachMessage.tracking_token == token))

    def latest_message_for_business(self, business_id: uuid.UUID) -> OutreachMessage | None:
        return self.db.scalar(
            select(OutreachMessage)
            .where(OutreachMessage.business_id == business_id, OutreachMessage.sent_at.is_not(None))
            .order_by(OutreachMessage.sent_at.desc())
            .limit(1)
        )


class AuditRepository(Repository[AuditLog]):
    model = AuditLog


class DomainEventRepository(Repository[DomainEvent]):
    model = DomainEvent
