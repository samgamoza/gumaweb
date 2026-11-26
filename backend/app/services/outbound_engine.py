"""Outbound engine (A2): enroll ready prospects in playbooks and run their follow-ups, unattended.

One pass (`tick`) runs as a queued job about once a minute while `OUTBOUND_ENGINE_ENABLED` is on (single flight via
its dedupe key), or on demand from the admin API / CLI. Each pass:

1. **Enrolls** ready prospects (best priority score first) up to the daily enrollment cap. Eligible: ready
   (`ProspectService.ready_query`), an unclaimed site that is live (earlier flow) or a private draft, and no
   manual campaign has messages queued for them. A draft's emails carry a fresh private claim link (A7,
   `claim_link_service`).
2. **Advances** every active enrollment: stops it when the prospect converted or closed, completes it when every
   step fired or was skipped or its time ran out, otherwise applies the step rules (`domains/sales/playbooks.py`).

Guardrails: quiet hours and the weekly touch cap defer a message (it goes out on a later pass); at most one message
per prospect per pass; suppression is checked again at send time; a channel the prospect can't be reached on skips
its step. Every email is an outreach message of the playbook's campaign, so open/click tracking, unsubscribe,
the C1 timeline and stage moves all work unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.outreach.enums import CampaignStatus, MessageStatus, OutreachChannel, OutreachEventType
from app.domains.outreach.sequence import render_message
from app.domains.sales import CLOSED_STAGES, CONVERTED_STAGES, ActivityType
from app.domains.sales.playbooks import DEFAULT_PLAYBOOK, Facts, decide, in_quiet_hours
from app.domains.website_factory.enums import WebsiteStatus
from app.models import (
    Business,
    OutreachCampaign,
    OutreachEvent,
    OutreachMessage,
    Playbook,
    PlaybookEnrollment,
    Prospect,
    ProspectActivity,
    ProspectTask,
    Website,
)
from app.models.sales import EnrollmentStatus
from app.services.claim_service import CLAIMABLE_DRAFT_STATES
from app.services.lead_compiler import day_start
from app.services.outreach_service import OutreachService
from app.services.prospect_service import ProspectService

logger = logging.getLogger("gumaweb.outbound")
TOUCH_TYPES = (ActivityType.EMAIL_SENT,)  # SMS joins with its gateway (A4)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class OutboundEngine:
    def __init__(self, db: Session, settings: Settings, now: datetime | None = None) -> None:
        self.db = db
        self.settings = settings
        self.now = now or datetime.now(UTC)
        self.outreach = OutreachService(db, settings)
        self.stats: dict[str, int] = {"enrolled": 0, "sent": 0, "failed": 0, "skipped": 0, "deferred": 0,
                                      "tasks": 0, "stopped": 0, "completed": 0}

    # --- Playbooks ---------------------------------------------------------------------------------
    def ensure_default_playbook(self) -> Playbook:
        playbook = self.db.scalar(select(Playbook).where(Playbook.name == DEFAULT_PLAYBOOK["name"]))
        if playbook is not None:
            return playbook
        campaign = OutreachCampaign(name=f"Playbook: {DEFAULT_PLAYBOOK['name']}", channel=OutreachChannel.EMAIL,
                                    status=CampaignStatus.ACTIVE, sequence=[],
                                    target_filter={"playbook": DEFAULT_PLAYBOOK["name"]})
        self.db.add(campaign)
        self.db.flush()
        playbook = Playbook(name=DEFAULT_PLAYBOOK["name"], steps=DEFAULT_PLAYBOOK["steps"],
                            max_days=DEFAULT_PLAYBOOK["max_days"], campaign_id=campaign.id)
        self.db.add(playbook)
        self.db.flush()
        return playbook

    # --- One pass ----------------------------------------------------------------------------------
    def tick(self) -> dict[str, int]:
        playbook = self.ensure_default_playbook()
        if playbook.active:
            self.enroll(playbook)
        active = self.db.execute(
            select(PlaybookEnrollment, Playbook).join(Playbook, Playbook.id == PlaybookEnrollment.playbook_id)
            .where(PlaybookEnrollment.status == EnrollmentStatus.ACTIVE, Playbook.active.is_(True))
            .order_by(PlaybookEnrollment.enrolled_at)
        ).all()
        for enrollment, book in active:
            self.advance(enrollment, book)
        self.db.commit()
        logger.info("outbound tick: %s", self.stats)
        return self.stats

    def enroll(self, playbook: Playbook) -> int:
        enrolled_today = self.db.scalar(select(func.count()).select_from(PlaybookEnrollment).where(
            PlaybookEnrollment.playbook_id == playbook.id,
            PlaybookEnrollment.enrolled_at >= day_start(self.now))) or 0
        room = self.settings.outbound_daily_enrollment_limit - enrolled_today
        if room <= 0:
            return 0
        already = select(PlaybookEnrollment.prospect_id).where(PlaybookEnrollment.playbook_id == playbook.id)
        # A live unclaimed site (earlier flow) or a private draft, which emails reach by a private claim link.
        claimable = select(Website.business_id).where(
            Website.status.in_([WebsiteStatus.PUBLISHED, *CLAIMABLE_DRAFT_STATES]), Website.is_claimed.is_(False))
        manual_queue = exists().where(OutreachMessage.business_id == Prospect.business_id,
                                      OutreachMessage.status == MessageStatus.SCHEDULED)
        stmt = (ProspectService(self.db).ready_query(self.now)
                .where(Prospect.id.not_in(already), Prospect.business_id.in_(claimable), ~manual_queue)
                .limit(room))
        count = 0
        for prospect in self.db.scalars(stmt).all():
            self.db.add(PlaybookEnrollment(playbook_id=playbook.id, prospect_id=prospect.id, enrolled_at=self.now,
                                           steps_done={}))
            count += 1
        self.db.flush()
        self.stats["enrolled"] += count
        return count

    def advance(self, enrollment: PlaybookEnrollment, playbook: Playbook) -> None:
        prospect = self.db.get(Prospect, enrollment.prospect_id)
        if prospect is None or prospect.stage in CONVERTED_STAGES or prospect.stage in CLOSED_STAGES:
            self._finish(enrollment, EnrollmentStatus.STOPPED, f"stage:{prospect.stage.value if prospect else 'gone'}")
            return
        enrolled_at = _utc(enrollment.enrolled_at)
        if self.now > enrolled_at + timedelta(days=playbook.max_days):
            self._finish(enrollment, EnrollmentStatus.COMPLETED, "expired")
            return

        done: dict[str, dict[str, Any]] = dict(enrollment.steps_done or {})
        facts = self._facts(prospect, enrolled_at, done)
        business = self.db.get(Business, prospect.business_id)
        website = self.db.scalar(select(Website).where(Website.business_id == prospect.business_id))
        quiet = in_quiet_hours(self.now, self.settings.outbound_quiet_hours_start,
                               self.settings.outbound_quiet_hours_end)
        touches = self.db.scalar(select(func.count()).select_from(ProspectActivity).where(
            ProspectActivity.prospect_id == prospect.id, ProspectActivity.type.in_(TOUCH_TYPES),
            ProspectActivity.occurred_at >= self.now - timedelta(days=7))) or 0
        touched = False
        for index, step in enumerate(playbook.steps):
            key = step["key"]
            if key in done:
                continue
            decision = decide(step, facts)
            if decision.action == "wait":
                continue
            if decision.action == "skip":
                done[key] = self._outcome("skipped", reason=decision.reason)
                self.stats["skipped"] += 1
                continue
            channel = step["channel"]
            if channel == "sms":
                done[key] = self._outcome("skipped", reason="sms_unavailable")
                self.stats["skipped"] += 1
            elif channel == "call_task":
                done[key] = self._call_task(step, prospect, business)
            elif "email" not in (prospect.channels or []) or website is None:
                done[key] = self._outcome("skipped", reason="no email channel")
                self.stats["skipped"] += 1
            elif quiet or touched or touches >= self.settings.outbound_max_touches_per_week:
                self.stats["deferred"] += 1  # not recorded: tried again on a later pass
            else:
                done[key] = self._email(playbook, step, index, business, website)
                if done[key]["status"] == "sent":
                    touches += 1
                    touched = True
        enrollment.steps_done = done
        if all(step["key"] in done for step in playbook.steps):
            self._finish(enrollment, EnrollmentStatus.COMPLETED, "all_steps")

    # --- Pieces ------------------------------------------------------------------------------------
    def _facts(self, prospect: Prospect, enrolled_at: datetime, done: dict[str, dict[str, Any]]) -> Facts:
        firsts = dict(self.db.execute(
            select(ProspectActivity.type, func.min(ProspectActivity.occurred_at))
            .where(ProspectActivity.prospect_id == prospect.id, ProspectActivity.occurred_at >= enrolled_at,
                   ProspectActivity.type.in_([ActivityType.EMAIL_OPENED, ActivityType.LINK_CLICKED,
                                              ActivityType.CLAIM_STARTED]))
            .group_by(ProspectActivity.type)
        ).all())
        message_ids = {key: o["message_id"] for key, o in done.items() if o.get("message_id")}
        opened = set()
        if message_ids:
            opened_ids = {str(i) for i in self.db.scalars(select(OutreachEvent.message_id).where(
                OutreachEvent.message_id.in_([uuid.UUID(m) for m in message_ids.values()]),
                OutreachEvent.event_type == OutreachEventType.EMAIL_OPENED))}
            opened = {key for key, mid in message_ids.items() if str(mid) in opened_ids}
        click, claim = firsts.get(ActivityType.LINK_CLICKED), firsts.get(ActivityType.CLAIM_STARTED)
        return Facts(now=self.now, enrolled_at=enrolled_at, done=done, opened_refs=frozenset(opened),
                     first_click_at=_utc(click) if click else None,
                     first_claim_start_at=_utc(claim) if claim else None,
                     engaged=bool(firsts), score=prospect.score)

    def _outcome(self, status: str, **extra: Any) -> dict[str, Any]:
        return {"status": status, "at": self.now.isoformat(), **{k: v for k, v in extra.items() if v is not None}}

    def _email(self, playbook: Playbook, step: dict[str, Any], index: int, business: Business,
               website: Website) -> dict[str, Any]:
        campaign = self.db.get(OutreachCampaign, playbook.campaign_id) if playbook.campaign_id else None
        if campaign is None:
            self.stats["skipped"] += 1
            return self._outcome("skipped", reason="playbook has no campaign")
        message = self.outreach.send_now(campaign, business, website, step=index, subject=step["subject"],
                                         body=step["body"], now=self.now)
        if message is None:
            self.stats["skipped"] += 1
            return self._outcome("skipped", reason="suppressed or claimed")
        if message.status is MessageStatus.FAILED:
            self.stats["failed"] += 1
            return self._outcome("failed", message_id=str(message.id), reason=(message.error or "")[:200])
        self.stats["sent"] += 1
        return self._outcome("sent", message_id=str(message.id))

    def _call_task(self, step: dict[str, Any], prospect: Prospect, business: Business) -> dict[str, Any]:
        if "phone" not in (prospect.channels or []):
            self.stats["skipped"] += 1
            return self._outcome("skipped", reason="no phone channel")
        title = render_message(step["title"], "", {"business_name": business.name,
                                                   "city": business.city or ""})[0][:200]
        task = ProspectTask(prospect_id=prospect.id, title=title, due_at=self.now,
                            assignee_user_id=prospect.owner_user_id)
        self.db.add(task)
        self.db.flush()
        self.stats["tasks"] += 1
        return self._outcome("sent", task_id=str(task.id))

    def _finish(self, enrollment: PlaybookEnrollment, status: EnrollmentStatus, reason: str) -> None:
        enrollment.status = status
        enrollment.stop_reason = reason
        enrollment.finished_at = self.now
        self.stats["stopped" if status is EnrollmentStatus.STOPPED else "completed"] += 1


def run_outbound_job(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Factory worker handler for JobKind.RUN_OUTBOUND. `force` runs even while the engine is switched off."""
    if not settings.outbound_engine_enabled and not payload.get("force"):
        return {"skipped": "disabled"}
    return OutboundEngine(db, settings).tick()
