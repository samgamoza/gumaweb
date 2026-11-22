"""Analytics: privacy-preserving site events, leads, and platform KPIs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.analytics.enums import SiteEventType
from app.domains.analytics.kpis import PlatformKpis, rate
from app.domains.billing.enums import PlanCode, SubscriptionStatus
from app.domains.business_discovery.enums import BusinessStatus
from app.domains.claims.enums import ClaimStatus
from app.domains.crm.enums import ActivityType, ContactSource
from app.domains.outreach.enums import MessageStatus, OutreachEventType
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.models import (
    AIGeneration,
    Business,
    Claim,
    Customer,
    Deployment,
    Lead,
    MediaAsset,
    OutreachEvent,
    OutreachMessage,
    Plan,
    SiteEvent,
    Subscription,
    Template,
    Website,
    WebsiteContent,
)
from app.repositories.repositories import WebsiteRepository
from app.schemas.analytics import DailyCount, PlatformOverview, SiteEventIn, WebsiteAnalytics
from app.services.crm_service import CrmService


class AnalyticsService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.websites = WebsiteRepository(db)

    def _visitor_hash(self, ip: str | None, user_agent: str | None) -> str:
        # Daily-rotating salted hash: counts unique visitors without storing IPs (privacy compliance).
        raw = f"{self.settings.jwt_secret_key}|{date.today().isoformat()}|{ip}|{user_agent}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _published_site(self, subdomain: str) -> Website:
        website = self.websites.by_subdomain(subdomain)
        if website is None or website.status != WebsiteStatus.PUBLISHED:
            raise NotFoundError("Site not found")
        return website

    def record_site_event(self, subdomain: str, event: SiteEventIn, ip: str | None, user_agent: str | None) -> None:
        website = self._published_site(subdomain)
        self.db.add(SiteEvent(website_id=website.id, event_type=event.event_type, path=event.path,
                              referrer=event.referrer, visitor_hash=self._visitor_hash(ip, user_agent)))
        self.db.commit()

    def record_lead(self, subdomain: str, name: str, email: str | None, phone: str | None, message: str,
                    ip: str | None) -> Website:
        website = self._published_site(subdomain)
        if not (email or phone):
            raise ValidationFailedError("Please provide an email address or phone number")
        contact = CrmService(self.db, self.settings).capture(
            website.business_id, name=name, email=email, phone=phone, source=ContactSource.CONTACT_FORM,
            activity=ActivityType.FORM_SUBMISSION, body=message[:2000],
        )
        self.db.add(Lead(website_id=website.id, contact_id=contact.id, name=name[:200], email=email, phone=phone,
                         message=message[:2000], ip_hash=self._visitor_hash(ip, None)))
        self.db.add(SiteEvent(website_id=website.id, event_type=SiteEventType.CONTACT_SUBMIT, path="/contact/"))
        self.db.commit()
        return website

    def overview(self) -> PlatformOverview:
        def count(stmt) -> int:
            return self.db.scalar(stmt) or 0

        mrr = count(
            select(func.sum(Plan.price_monthly_cents))
            .select_from(Subscription)
            .join(Plan, Plan.code == Subscription.plan_code)
            .where(Subscription.status == SubscriptionStatus.ACTIVE)
        )
        kpis = PlatformKpis(
            businesses=count(select(func.count(Business.id)).where(Business.status != BusinessStatus.ARCHIVED)),
            generate_candidates=count(select(func.count(Business.id)).where(Business.generate_candidate.is_(True))),
            generated_sites=count(select(func.count(Website.id))),
            published_sites=count(select(func.count(Website.id)).where(Website.status == WebsiteStatus.PUBLISHED)),
            claimed_sites=count(select(func.count(Website.id)).where(Website.is_claimed.is_(True))),
            paid_sites=count(select(func.count(Customer.id)).where(Customer.plan != PlanCode.FREE)),
            monthly_recurring_revenue_cents=mrr,
            pending_claims=count(select(func.count(Claim.id)).where(Claim.status == ClaimStatus.MANUAL_REVIEW)),
        )
        events = dict(self.db.execute(
            select(OutreachEvent.event_type, func.count(func.distinct(OutreachEvent.business_id)))
            .group_by(OutreachEvent.event_type)
        ).all())
        funnel = {
            "outreach_sent": count(select(func.count(OutreachMessage.id))
                                   .where(OutreachMessage.status == MessageStatus.SENT)),
            "opens": events.get(OutreachEventType.EMAIL_OPENED, 0),
            "clicks": events.get(OutreachEventType.LINK_CLICKED, 0),
            "claims_started": count(select(func.count(Claim.id))),
            "claims_completed": count(select(func.count(Claim.id)).where(Claim.status == ClaimStatus.APPROVED)),
        }
        since = datetime.now(UTC) - timedelta(days=30)
        views = count(select(func.count(SiteEvent.id)).where(
            SiteEvent.event_type == SiteEventType.PAGE_VIEW, SiteEvent.occurred_at >= since))
        return PlatformOverview(kpis=kpis.as_dict(), funnel=funnel, page_views_30d=views)

    def timeseries(self, days: int = 30) -> list[dict[str, object]]:
        """Daily factory + acquisition counts (bucketed in Python to stay database-portable)."""
        since = datetime.now(UTC) - timedelta(days=days - 1)
        start = since.date()
        series = {start + timedelta(days=i): dict.fromkeys(
            ("discovered", "generated", "published", "claims_started", "claims_completed", "page_views", "leads"), 0)
            for i in range(days)}

        def bucket(metric: str, stmt) -> None:
            for (ts,) in self.db.execute(stmt).all():
                if ts is not None and ts.date() in series:
                    series[ts.date()][metric] += 1

        bucket("discovered", select(Business.created_at).where(Business.created_at >= since))
        bucket("generated", select(Website.generated_at).where(Website.generated_at >= since))
        bucket("published", select(Deployment.finished_at).where(
            Deployment.finished_at >= since, Deployment.version == 1, Deployment.status == "succeeded"))
        bucket("claims_started", select(Claim.created_at).where(Claim.created_at >= since))
        bucket("claims_completed", select(Claim.verified_at).where(
            Claim.verified_at >= since, Claim.status == ClaimStatus.APPROVED))
        bucket("page_views", select(SiteEvent.occurred_at).where(
            SiteEvent.occurred_at >= since, SiteEvent.event_type == SiteEventType.PAGE_VIEW))
        bucket("leads", select(Lead.created_at).where(Lead.created_at >= since))
        return [{"day": day.isoformat(), **counts} for day, counts in sorted(series.items())]

    def template_performance(self) -> list[dict[str, object]]:
        rows = self.db.execute(
            select(
                Template.slug, Template.name, Template.category,
                func.count(Website.id),
                func.sum(case((Website.status == WebsiteStatus.PUBLISHED, 1), else_=0)),
                func.sum(case((Website.is_claimed.is_(True), 1), else_=0)),
                func.avg(Website.quality_score),
            )
            .select_from(Template)
            .outerjoin(Website, Website.template_id == Template.id)
            .group_by(Template.slug, Template.name, Template.category)
            .order_by(func.count(Website.id).desc(), Template.slug)
        ).all()
        return [
            {"slug": slug, "name": name, "category": category, "sites": sites or 0, "published": int(pub or 0),
             "claimed": int(claimed or 0), "claim_rate": rate(int(claimed or 0), int(pub or 0)),
             "avg_quality": round(float(quality), 1) if quality is not None else None}
            for slug, name, category, sites, pub, claimed, quality in rows
        ]

    def industry_breakdown(self) -> list[dict[str, object]]:
        rows = self.db.execute(
            # Group on the raw column (a bound COALESCE default appears as two different parameters
            # in SELECT and GROUP BY, which PostgreSQL rejects); label NULLs below.
            select(
                Business.industry,
                func.count(Business.id),
                func.sum(case((Business.generate_candidate.is_(True), 1), else_=0)),
                func.count(Website.id),
                func.sum(case((Website.is_claimed.is_(True), 1), else_=0)),
                func.avg(Business.score),
            )
            .select_from(Business)
            .outerjoin(Website, Website.business_id == Business.id)
            .where(Business.status != BusinessStatus.ARCHIVED)
            .group_by(Business.industry)
            .order_by(func.count(Business.id).desc())
        ).all()
        return [
            {"industry": industry or "unclassified", "businesses": total, "candidates": int(cand or 0),
             "sites": sites or 0, "claimed": int(claimed or 0),
             "avg_score": round(float(score), 1) if score is not None else None}
            for industry, total, cand, sites, claimed, score in rows
        ]

    def ai_usage(self) -> dict[str, object]:
        rows = self.db.execute(
            select(AIGeneration.task, AIGeneration.model, func.count(AIGeneration.id),
                   func.sum(case((AIGeneration.accepted.is_(True), 1), else_=0)),
                   func.sum(AIGeneration.prompt_tokens), func.sum(AIGeneration.completion_tokens),
                   func.avg(AIGeneration.latency_ms))
            .group_by(AIGeneration.task, AIGeneration.model)
        ).all()
        by_model = [
            {"task": task, "model": model, "calls": calls, "accepted": int(acc or 0),
             "prompt_tokens": int(pt or 0), "completion_tokens": int(ct or 0),
             "avg_latency_ms": round(float(lat or 0))}
            for task, model, calls, acc, pt, ct, lat in rows
        ]
        sources = dict(self.db.execute(
            select(WebsiteContent.source, func.count(WebsiteContent.id)).group_by(WebsiteContent.source)
        ).all())
        ai_sections = sources.get(ContentSource.AI, 0)
        generated_sections = ai_sections + sources.get(ContentSource.TEMPLATE, 0)
        sites = self.db.scalar(select(func.count(Website.id))) or 0
        total_tokens = sum(m["prompt_tokens"] + m["completion_tokens"] for m in by_model)
        assets = self.db.execute(
            select(func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.usage_count), 0))
            .where(MediaAsset.source == "generated")
        ).one()
        return {
            "enabled": self.settings.ai_enabled,
            "models": by_model,
            "ai_section_share": rate(ai_sections, generated_sections),
            "tokens_total": total_tokens,
            "tokens_per_site": round(total_tokens / sites) if sites else 0,
            "library_images": assets[0],
            "library_image_uses": int(assets[1]),
        }

    def website_stats(self, website_id: uuid.UUID, days: int = 30) -> WebsiteAnalytics:
        self.websites.get_or_404(website_id)
        since = datetime.now(UTC) - timedelta(days=days)
        rows = self.db.execute(
            select(SiteEvent.occurred_at).where(
                SiteEvent.website_id == website_id, SiteEvent.event_type == SiteEventType.PAGE_VIEW,
                SiteEvent.occurred_at >= since)
        ).scalars().all()
        per_day: dict[date, int] = {}
        for ts in rows:
            per_day[ts.date()] = per_day.get(ts.date(), 0) + 1
        totals = dict(self.db.execute(
            select(SiteEvent.event_type, func.count()).where(
                SiteEvent.website_id == website_id, SiteEvent.occurred_at >= since)
            .group_by(SiteEvent.event_type)
        ).all())
        leads = self.db.scalar(select(func.count(Lead.id)).where(
            Lead.website_id == website_id, Lead.created_at >= since)) or 0
        return WebsiteAnalytics(
            website_id=website_id, days=days,
            page_views=[DailyCount(day=d, count=c) for d, c in sorted(per_day.items())],
            totals={str(k): v for k, v in totals.items()}, leads=leads,
        )
