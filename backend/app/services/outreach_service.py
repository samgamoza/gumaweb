"""Outreach Engine (13): campaigns, Day 0/3/7/14 sequences, tracking, unsubscribe."""

from __future__ import annotations

import html
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery.enums import BusinessStatus
from app.domains.outreach.enums import CampaignStatus, MessageStatus, OutreachChannel, OutreachEventType
from app.domains.outreach.sequence import DEFAULT_SEQUENCE, render_message, validate_sequence
from app.domains.website_factory.enums import WebsiteStatus
from app.models import (
    Business,
    OutreachCampaign,
    OutreachEvent,
    OutreachMessage,
    OutreachSuppression,
    Website,
)
from app.repositories.repositories import OutreachRepository
from app.schemas.outreach import CampaignCreate, CampaignStats, DispatchResult, LaunchResult
from app.services.notifications import EmailMessage
from app.services.providers import providers
from app.services.support import Actor, EventType, audit, record_event


class OutreachService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repo = OutreachRepository(db)

    def _api(self, path: str) -> str:
        return f"{self.settings.api_public_url.rstrip('/')}{self.settings.api_v1_prefix}{path}"

    def create(self, data: CampaignCreate, actor: Actor) -> OutreachCampaign:
        if data.channel != OutreachChannel.EMAIL:
            raise ValidationFailedError("Only the email channel is available in Phase 1")
        sequence = [s.model_dump() for s in data.sequence] if data.sequence else DEFAULT_SEQUENCE
        try:
            sequence = validate_sequence(sequence)
        except Exception as exc:
            raise ValidationFailedError(f"Invalid sequence: {exc}") from exc
        campaign = self.repo.add(
            OutreachCampaign(name=data.name, channel=data.channel, sequence=sequence,
                             target_filter=data.target_filter.model_dump(exclude_none=True),
                             created_by=actor.user_id)
        )
        audit(self.db, actor, AuditAction.CAMPAIGN_CREATED, "outreach_campaign", campaign.id)
        self.db.commit()
        return campaign

    def launch(self, campaign: OutreachCampaign, actor: Actor) -> LaunchResult:
        """Enroll eligible businesses and schedule every sequence step."""
        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED, CampaignStatus.ACTIVE):
            raise ConflictError(f"Campaign is {campaign.status.value}")
        f = campaign.target_filter or {}
        enrolled_ids = select(OutreachMessage.business_id).where(OutreachMessage.campaign_id == campaign.id)
        suppressed = select(OutreachSuppression.email)
        stmt = (
            select(Business, Website)
            .join(Website, Website.business_id == Business.id)
            .where(
                Website.status == WebsiteStatus.PUBLISHED,
                Website.is_claimed.is_(False),
                Business.status != BusinessStatus.ARCHIVED,
                Business.email.is_not(None),
                Business.email.not_in(suppressed),
                Business.id.not_in(enrolled_ids),
            )
            .order_by(Business.score.desc().nulls_last())
            .limit(int(f.get("limit", 500)))
        )
        if f.get("industry"):
            stmt = stmt.where(Business.industry == f["industry"])
        if f.get("city"):
            stmt = stmt.where(Business.city.ilike(f["city"]))
        if f.get("min_score") is not None:
            stmt = stmt.where(Business.score >= f["min_score"])

        now = datetime.now(UTC)
        businesses = scheduled = 0
        for business, website in self.db.execute(stmt).all():
            businesses += 1
            for step in campaign.sequence:
                token = secrets.token_urlsafe(24)
                variables = {
                    "business_name": business.name,
                    "city": business.city or "your area",
                    "website_url": self._api(f"/public/outreach/click/{token}"),
                    "claim_url": f"{self.settings.frontend_url.rstrip('/')}/claim/{website.subdomain}?ref={token}",
                    "unsubscribe_url": self._api(f"/public/outreach/unsubscribe/{token}"),
                }
                subject, body = render_message(step["subject"], step["body"], variables)
                self.db.add(OutreachMessage(
                    campaign_id=campaign.id, business_id=business.id, website_id=website.id,
                    channel=campaign.channel, step=step["step"], recipient=business.email, subject=subject,
                    body=body, tracking_token=token, scheduled_at=now + timedelta(days=step["day"]),
                ))
                scheduled += 1
        campaign.status = CampaignStatus.ACTIVE
        campaign.started_at = campaign.started_at or now
        audit(self.db, actor, AuditAction.CAMPAIGN_DISPATCHED, "outreach_campaign", campaign.id,
              {"enrolled": businesses, "scheduled": scheduled})
        self.db.commit()
        return LaunchResult(campaign_id=campaign.id, enrolled_businesses=businesses, scheduled_messages=scheduled)

    def dispatch_due(self, campaign: OutreachCampaign | None = None, now: datetime | None = None,
                     batch_size: int = 500) -> DispatchResult:
        """Send messages whose scheduled time has passed. Run by a CronJob or the admin UI."""
        now = now or datetime.now(UTC)
        stmt = (
            select(OutreachMessage)
            .join(OutreachCampaign, OutreachCampaign.id == OutreachMessage.campaign_id)
            .where(OutreachMessage.status == MessageStatus.SCHEDULED, OutreachMessage.scheduled_at <= now,
                   OutreachCampaign.status == CampaignStatus.ACTIVE)
            .order_by(OutreachMessage.scheduled_at)
            .limit(batch_size)
        )
        if campaign is not None:
            stmt = stmt.where(OutreachMessage.campaign_id == campaign.id)
        sent = skipped = failed = 0
        for message in self.db.scalars(stmt).all():
            website = self.db.get(Website, message.website_id) if message.website_id else None
            if website is None or website.is_claimed or self.repo.is_suppressed(message.recipient):
                message.status = MessageStatus.SKIPPED
                skipped += 1
                continue
            try:
                pixel = self._api(f"/public/outreach/open/{message.tracking_token}.gif")
                providers.email.send(EmailMessage(
                    to=message.recipient, subject=message.subject or "", text=message.body,
                    html=f"<div style=\"white-space:pre-wrap;font-family:sans-serif\">{html.escape(message.body)}"
                         f"</div><img src=\"{pixel}\" width=\"1\" height=\"1\" alt=\"\">",
                ))
            except Exception as exc:
                message.status = MessageStatus.FAILED
                message.error = str(exc)[:1000]
                failed += 1
                continue
            message.status = MessageStatus.SENT
            message.sent_at = now
            self._event(message, OutreachEventType.EMAIL_SENT)
            record_event(self.db, EventType.OUTREACH_SENT, "outreach_message", message.id)
            sent += 1
        self._complete_finished_campaigns()
        self.db.commit()
        return DispatchResult(sent=sent, skipped=skipped, failed=failed)

    def _complete_finished_campaigns(self) -> None:
        pending = select(OutreachMessage.campaign_id).where(OutreachMessage.status == MessageStatus.SCHEDULED)
        self.db.execute(
            update(OutreachCampaign)
            .where(OutreachCampaign.status == CampaignStatus.ACTIVE, OutreachCampaign.id.not_in(pending),
                   OutreachCampaign.started_at.is_not(None))
            .values(status=CampaignStatus.COMPLETED)
        )

    # --- Tracking -------------------------------------------------------------------
    def _event(self, message: OutreachMessage, event_type: OutreachEventType) -> None:
        self.db.add(OutreachEvent(business_id=message.business_id, campaign_id=message.campaign_id,
                                  message_id=message.id, channel=message.channel, event_type=event_type))

    def track_open(self, token: str) -> None:
        message = self.repo.message_by_token(token)
        if message:
            self._event(message, OutreachEventType.EMAIL_OPENED)
            self.db.commit()

    def track_click(self, token: str) -> str | None:
        """Record the click and return the destination website URL."""
        message = self.repo.message_by_token(token)
        if message is None or message.website_id is None:
            return None
        website = self.db.get(Website, message.website_id)
        self._event(message, OutreachEventType.LINK_CLICKED)
        self._event(message, OutreachEventType.WEBSITE_VISITED)
        self.db.commit()
        return website.url if website else None

    def unsubscribe(self, token: str) -> bool:
        message = self.repo.message_by_token(token)
        if message is None:
            return False
        if not self.repo.is_suppressed(message.recipient):
            self.db.add(OutreachSuppression(email=message.recipient, reason="unsubscribed"))
        self.db.execute(
            update(OutreachMessage)
            .where(OutreachMessage.recipient == message.recipient,
                   OutreachMessage.status == MessageStatus.SCHEDULED)
            .values(status=MessageStatus.SKIPPED, error="unsubscribed")
        )
        self._event(message, OutreachEventType.UNSUBSCRIBED)
        self.db.commit()
        return True

    def stats(self, campaign: OutreachCampaign) -> CampaignStats:
        counts = dict(self.db.execute(
            select(OutreachEvent.event_type, func.count(func.distinct(OutreachEvent.business_id)))
            .where(OutreachEvent.campaign_id == campaign.id)
            .group_by(OutreachEvent.event_type)
        ).all())
        sent = self.db.scalar(select(func.count(OutreachMessage.id)).where(
            OutreachMessage.campaign_id == campaign.id, OutreachMessage.status == MessageStatus.SENT)) or 0
        return CampaignStats(
            campaign_id=campaign.id,
            outreach_sent=sent,
            opens=counts.get(OutreachEventType.EMAIL_OPENED, 0),
            clicks=counts.get(OutreachEventType.LINK_CLICKED, 0),
            claims=counts.get(OutreachEventType.CLAIM_STARTED, 0),
            conversions=counts.get(OutreachEventType.CLAIM_COMPLETED, 0),
            unsubscribes=counts.get(OutreachEventType.UNSUBSCRIBED, 0),
        )
