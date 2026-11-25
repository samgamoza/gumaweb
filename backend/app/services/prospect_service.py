"""Sales CRM: record touches on prospects and keep their stage right (docs/SALES_CRM_PLAN.md).

`record()` is the one entry point. Outreach, claims, publishing, billing and the suppression scrub call it in
their own transaction (it never commits). Stage rules live in `app.domains.sales`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domains.business_discovery.contacts import ContactKind, PolicyDecision, ValueType, VerificationStatus
from app.domains.claims.enums import ClaimStatus
from app.domains.outreach.enums import OutreachEventType
from app.domains.sales import (
    AUTO_STAGE,
    BLOCKS_ALL_CHANNELS,
    CONVERTED_STAGES,
    ENGAGEMENT,
    ActivitySource,
    ActivityType,
    ProspectStage,
    auto_advance,
)
from app.domains.sales.priority import ENGAGEMENT_POINTS, ChannelQuality, PriorityInput, score_priority
from app.models import (
    Business,
    BusinessContact,
    Claim,
    Customer,
    OutreachEvent,
    OutreachMessage,
    OutreachSuppression,
    Plan,
    Prospect,
    ProspectActivity,
    Subscription,
    Website,
)
from app.services.suppression_service import SuppressionService

OUTREACH_ACTIVITY = {
    OutreachEventType.EMAIL_SENT: (ActivityType.EMAIL_SENT, "sent"),
    OutreachEventType.EMAIL_OPENED: (ActivityType.EMAIL_OPENED, "opened"),  # first open per message only
    OutreachEventType.LINK_CLICKED: (ActivityType.LINK_CLICKED, "clicked"),  # first click per message only
    OutreachEventType.UNSUBSCRIBED: (ActivityType.UNSUBSCRIBED, "unsubscribed"),
}  # website_visited is skipped (a click is a visit); claim events come from the claims table


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)  # SQLite hands back naive UTC


def _quality(contact: BusinessContact) -> ChannelQuality:
    if contact.value_type is ValueType.USER_SUPPLIED or contact.verification_status is VerificationStatus.VERIFIED:
        return ChannelQuality.CONFIRMED
    if contact.value_type is ValueType.OBSERVED:
        return ChannelQuality.OBSERVED
    if contact.value_type is ValueType.DERIVED:
        return ChannelQuality.LISTED
    return ChannelQuality.GUESSED


def outreach_external_id(message_id: Any, verb: str) -> str:
    return f"outreach:{message_id}:{verb}"


@dataclass
class BackfillResult:
    prospects: int = 0
    activities: int = 0


class ProspectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def for_business(self, business_id: uuid.UUID) -> Prospect | None:
        return self.db.scalar(select(Prospect).where(Prospect.business_id == business_id))

    def record(self, business_id: uuid.UUID, type: ActivityType, *, source: ActivitySource = ActivitySource.SYSTEM,
               data: dict[str, Any] | None = None, actor_user_id: uuid.UUID | None = None,
               external_id: str | None = None, occurred_at: datetime | None = None,
               create: bool = True) -> ProspectActivity | None:
        """Add an activity and apply its automatic stage move. Returns None when nothing was recorded:
        a replay (same `external_id`), or no prospect and `create=False`."""
        if external_id and self.db.scalar(
                select(ProspectActivity.id).where(ProspectActivity.external_id == external_id)):
            return None
        when = _utc(occurred_at)
        prospect = self.for_business(business_id)
        if prospect is None:
            if not create:
                return None
            prospect = Prospect(business_id=business_id, stage=ProspectStage.NEW, stage_changed_at=when)
            self.db.add(prospect)
            self.db.flush()

        data = dict(data or {})
        target = AUTO_STAGE.get(type)
        if type is ActivityType.SUPPRESSED and data.get("blocks_all"):
            target = ProspectStage.DO_NOT_CONTACT
        if target is not None:
            new_stage = auto_advance(prospect.stage, target)
            if new_stage is not prospect.stage:
                data |= {"stage_from": prospect.stage.value, "stage_to": new_stage.value}
                prospect.stage = new_stage
                prospect.stage_changed_at = when
        if type in ENGAGEMENT and (prospect.last_touch_at is None or _utc(prospect.last_touch_at) < when):
            prospect.last_touch_at = when

        activity = ProspectActivity(prospect_id=prospect.id, type=type, source=source, actor_user_id=actor_user_id,
                                    data=data, occurred_at=when, external_id=external_id)
        self.db.add(activity)
        self.db.flush()
        self._rescore(prospect)
        return activity

    # --- Outbound priority (A1) -----------------------------------------------------------------
    def rescore(self, business_id: uuid.UUID) -> Prospect | None:
        """Recompute a prospect's priority score and usable channels (after enrichment, suppression, decay)."""
        prospect = self.for_business(business_id)
        if prospect is not None:
            self._rescore(prospect)
        return prospect

    def rescore_all(self) -> int:
        """Nightly: engagement decays with time, so scores drift even without new activity."""
        count = 0
        for prospect in self.db.scalars(select(Prospect)).all():
            self._rescore(prospect)
            count += 1
        self.db.commit()
        return count

    def _rescore(self, prospect: Prospect) -> None:
        business = self.db.get(Business, prospect.business_id)
        if business is None:
            return
        email, phone = self.channel_quality(business)
        last = dict(self.db.execute(
            select(ProspectActivity.type, func.max(ProspectActivity.occurred_at))
            .where(ProspectActivity.prospect_id == prospect.id,
                   ProspectActivity.type.in_([ActivityType(k) for k in ENGAGEMENT_POINTS]))
            .group_by(ProspectActivity.type)
        ).all())
        now = datetime.now(UTC)
        result = score_priority(PriorityInput(
            opportunity_score=business.score, email=email, phone=phone, now=now,
            last_engagement={t.value: _utc(w) for t, w in last.items()}))
        prospect.score, prospect.score_reasons, prospect.channels = result.score, result.reasons, result.channels
        prospect.reachable = bool(result.channels)
        prospect.scored_at = now
        self.db.flush()

    def channel_quality(self, business: Business) -> tuple[ChannelQuality, ChannelQuality]:
        """The best usable email and phone for a business, judged by provenance. Blocked, invalid and
        suppressed contacts don't count; a primary with no provenance record counts as LISTED."""
        best = {ContactKind.EMAIL: ChannelQuality.NONE, ContactKind.PHONE: ChannelQuality.NONE}
        known: set[tuple[ContactKind, str]] = set()
        for contact in self.db.scalars(select(BusinessContact).where(
                BusinessContact.business_id == business.id,
                BusinessContact.kind.in_([ContactKind.EMAIL, ContactKind.PHONE]))):
            known.add((contact.kind, contact.value))
            if (contact.policy_decision is not PolicyDecision.ALLOW
                    or contact.verification_status is VerificationStatus.INVALID):
                continue
            best[contact.kind] = max(best[contact.kind], _quality(contact))
        suppressions = SuppressionService(self.db)
        if business.email and (ContactKind.EMAIL, business.email) not in known \
                and not suppressions.is_suppressed(business.email):
            best[ContactKind.EMAIL] = max(best[ContactKind.EMAIL], ChannelQuality.LISTED)
        if business.phone and (ContactKind.PHONE, business.phone) not in known:
            best[ContactKind.PHONE] = max(best[ContactKind.PHONE], ChannelQuality.LISTED)
        return best[ContactKind.EMAIL], best[ContactKind.PHONE]

    def ready_query(self, now: datetime | None = None):
        """Prospects the outbound engine may work now, best first (channel opt-outs are checked at send time)."""
        now = now or datetime.now(UTC)
        open_stages = [s for s in ProspectStage if s not in CONVERTED_STAGES and s is not ProspectStage.DO_NOT_CONTACT
                       and s is not ProspectStage.LOST]
        reopened_lost = (Prospect.stage == ProspectStage.LOST) & Prospect.cooldown_until.is_not(None) \
            & (Prospect.cooldown_until <= now)
        open_now = Prospect.stage.in_(open_stages) & (
            Prospect.cooldown_until.is_(None) | (Prospect.cooldown_until <= now))
        return (select(Prospect).where(or_(open_now, reopened_lost), Prospect.reachable.is_(True))
                .order_by(Prospect.score.desc().nulls_last(), Prospect.created_at))

    # --- Hooks called from other services ------------------------------------------------------
    def record_outreach(self, event: OutreachEvent, message: OutreachMessage) -> None:
        mapped = OUTREACH_ACTIVITY.get(event.event_type)
        if mapped is None:
            return
        type_, verb = mapped
        self.record(message.business_id, type_, external_id=outreach_external_id(message.id, verb),
                    occurred_at=event.occurred_at,
                    data={"campaign_id": str(message.campaign_id), "step": message.step, "subject": message.subject})

    def record_suppression(self, entry: OutreachSuppression) -> list[uuid.UUID]:
        """Note a do-not-contact entry on every prospect it matches; close them if it blocks every channel.
        Only existing prospects are touched. Returns the business ids that were noted."""
        from app.services.suppression_scrub import matches  # local: suppression_scrub imports this module

        by_contact = select(BusinessContact.business_id).where(
            BusinessContact.kind == ContactKind.EMAIL, matches(BusinessContact.value, entry.kind, entry.value))
        business_ids = self.db.scalars(
            select(Prospect.business_id).join(Business, Business.id == Prospect.business_id).where(
                or_(matches(Business.email, entry.kind, entry.value), Business.id.in_(by_contact)))
        ).all()
        blocks_all = entry.reason in BLOCKS_ALL_CHANNELS
        noted = []
        for business_id in business_ids:
            if self.record(business_id, ActivityType.SUPPRESSED, create=False, occurred_at=entry.created_at,
                           external_id=f"suppression:{entry.id}:{business_id}",
                           data={"kind": entry.kind.value, "value": entry.value, "reason": entry.reason,
                                 "blocks_all": blocks_all}):
                noted.append(business_id)
        return noted

    # --- Backfill (CLI: backfill-prospects) -----------------------------------------------------
    def backfill(self) -> BackfillResult:
        """Build prospects and timelines from existing history. Idempotent: safe to run any number of times.

        Every past fact goes through `record()` in time order, so stages come out exactly as if the CRM had
        existed all along.
        """
        prospects_before = self._count()
        facts: list[tuple[datetime, int, uuid.UUID, ActivityType, str, dict[str, Any]]] = []

        def add(when: datetime | None, business_id: uuid.UUID, type_: ActivityType, external_id: str,
                data: dict[str, Any] | None = None, order: int = 1) -> None:
            facts.append((_utc(when), order, business_id, type_, external_id, data or {}))

        for website in self.db.scalars(select(Website).where(Website.published_at.is_not(None))):
            add(website.published_at, website.business_id, ActivityType.SITE_PUBLISHED,
                f"website:{website.id}:published", {"url": website.url}, order=0)

        rows = self.db.execute(
            select(OutreachEvent, OutreachMessage).join(OutreachMessage, OutreachMessage.id == OutreachEvent.message_id)
            .where(OutreachEvent.event_type.in_(list(OUTREACH_ACTIVITY)))
        ).all()
        for event, message in rows:
            type_, verb = OUTREACH_ACTIVITY[event.event_type]
            add(event.occurred_at, message.business_id, type_, outreach_external_id(message.id, verb),
                {"campaign_id": str(message.campaign_id), "step": message.step, "subject": message.subject})

        for claim in self.db.scalars(select(Claim)):
            add(claim.created_at, claim.business_id, ActivityType.CLAIM_STARTED, f"claim:{claim.id}:started",
                {"method": claim.method.value})
            decided_at = claim.reviewed_at or claim.verified_at or claim.updated_at
            if claim.status is ClaimStatus.APPROVED:
                add(decided_at, claim.business_id, ActivityType.CLAIM_APPROVED, f"claim:{claim.id}:approved",
                    order=2)
            elif claim.status is ClaimStatus.REJECTED and not (claim.review_notes or "").startswith("Superseded"):
                add(decided_at, claim.business_id, ActivityType.CLAIM_REJECTED, f"claim:{claim.id}:rejected",
                    order=2)

        prices = {plan.code: plan.price_monthly_cents for plan in self.db.scalars(select(Plan))}
        subs = self.db.execute(
            select(Subscription, Customer.business_id).join(Customer, Customer.id == Subscription.customer_id)
            .order_by(Subscription.customer_id, Subscription.created_at)
        ).all()
        previous_paid: dict[uuid.UUID, bool] = {}
        for sub, business_id in subs:
            paid = bool(prices.get(sub.plan_code))
            was_paid = previous_paid.get(sub.customer_id, False)
            if paid:
                add(sub.created_at, business_id, ActivityType.SUBSCRIBED, f"subscription:{sub.id}",
                    {"plan": sub.plan_code.value}, order=3)
            elif was_paid:
                add(sub.created_at, business_id, ActivityType.CHURNED, f"subscription:{sub.id}",
                    {"plan": sub.plan_code.value}, order=3)
            previous_paid[sub.customer_id] = paid

        result = BackfillResult()
        for when, _, business_id, type_, external_id, data in sorted(facts, key=lambda f: (f[0], f[1])):
            if self.record(business_id, type_, external_id=external_id, occurred_at=when, data=data):
                result.activities += 1
        for entry in self.db.scalars(select(OutreachSuppression).order_by(OutreachSuppression.created_at)).all():
            result.activities += len(self.record_suppression(entry))
        self.db.commit()
        result.prospects = self._count() - prospects_before
        return result

    def _count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(Prospect)) or 0
