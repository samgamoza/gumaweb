"""Retroactive suppression scrub (ported from guma_os `suppression-scrub.ts`).

Adding a suppression must do more than stop future collection: contact data already stored from earlier
discovery and enrichment has to stop being usable for outreach too. For a newly suppressed email or domain
this job:

1. marks matching `business_contacts` as `blocked` with `SUPPRESSED_EMAIL` / `SUPPRESSED_DOMAIN`. Rows are
   kept, not deleted, so anyone reviewing a business can see the address was there and why it was blocked;
2. skips queued (not yet sent) outreach messages to matching recipients. Sent history is left as it was.

`Business.email` is deliberately left alone. Unlike the guma_os profile it is also the business's own public
address: shown on its generated site, matched during claims, and used for owner notifications. Suppression
means *we* must not market to it, and outreach enforces that at enrollment (`not_suppressed`) and again at
send time. The result reports how many businesses outreach will now skip.

Outreach is already safe before this runs; the job cleans up stored data. It is idempotent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery.contacts import ContactKind, PolicyDecision, ReasonCode
from app.domains.outreach.enums import MessageStatus
from app.domains.outreach.suppression import SuppressionKind, normalize_suppression
from app.models import Business, BusinessContact, OutreachMessage, OutreachSuppression
from app.services.prospect_service import ProspectService
from app.services.support import SYSTEM, audit


@dataclass
class ScrubResult:
    kind: str
    value: str
    skipped: str | None = None  # e.g. "suppression_removed" when it was lifted before the job ran
    contacts_blocked: int = 0
    messages_skipped: int = 0
    businesses_now_skipped_by_outreach: int = 0  # their primary email matches; kept, but never contacted
    prospects_noted: int = 0  # sales CRM prospects that got a "suppressed" activity (closed if it blocks all)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def matches(column: Any, kind: SuppressionKind, value: str) -> ColumnElement[bool]:
    """SQL: this email column is the suppressed address, or is at the suppressed domain."""
    email = func.lower(column)
    if kind is SuppressionKind.EMAIL:
        return email == value
    return email.like(f"%@{value}")  # domain values are validated to [a-z0-9.-]: no LIKE wildcards


def scrub(db: Session, settings: Settings, kind: SuppressionKind, value: str) -> ScrubResult:
    value = normalize_suppression(kind, value)
    result = ScrubResult(kind=kind.value, value=value)
    entry = db.scalar(select(OutreachSuppression).where(
        OutreachSuppression.kind == kind, OutreachSuppression.value == value))
    if entry is None:
        result.skipped = "suppression_removed"
        return result

    reason = (ReasonCode.SUPPRESSED_EMAIL if kind is SuppressionKind.EMAIL else ReasonCode.SUPPRESSED_DOMAIN).value
    result.contacts_blocked = db.execute(
        update(BusinessContact)
        .where(BusinessContact.kind == ContactKind.EMAIL, matches(BusinessContact.value, kind, value),
               BusinessContact.policy_decision != PolicyDecision.BLOCKED)
        .values(policy_decision=PolicyDecision.BLOCKED, reason_code=reason)
        .execution_options(synchronize_session=False)
    ).rowcount or 0

    result.messages_skipped = db.execute(
        update(OutreachMessage)
        .where(OutreachMessage.status == MessageStatus.SCHEDULED, matches(OutreachMessage.recipient, kind, value))
        .values(status=MessageStatus.SKIPPED, error="suppressed")
        .execution_options(synchronize_session=False)
    ).rowcount or 0

    result.businesses_now_skipped_by_outreach = db.scalar(
        select(func.count()).select_from(Business).where(matches(Business.email, kind, value))) or 0
    result.prospects_noted = len(ProspectService(db).record_suppression(entry))

    audit(db, SYSTEM, AuditAction.SUPPRESSION_SCRUBBED, "outreach_suppression", f"{kind.value}:{value}",
          {k: v for k, v in result.as_dict().items() if k not in ("kind", "value", "skipped")})
    db.commit()
    return result


def run_scrub_job(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Factory worker handler for JobKind.SCRUB_SUPPRESSION."""
    return scrub(db, settings, SuppressionKind(payload["kind"]), payload["value"]).as_dict()
