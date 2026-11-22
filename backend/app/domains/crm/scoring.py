"""Lead intelligence (20-roadmap Phase 4 `lead_intelligence`): explainable lead scoring.

Deterministic and transparent on purpose: an owner can see *why* a lead is hot
("booked an appointment, asked for a price today"), and the score costs nothing
to recompute on every touch. Signals: channel, contactability, buying intent in
the visitor's own words, engagement, recency, deal value and pipeline stage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domains.crm.enums import ActivityType, ContactSource, ContactStage

HOT_THRESHOLD = 70
WARM_THRESHOLD = 40

SOURCE_POINTS = {
    ContactSource.BOOKING: 25, ContactSource.PHONE: 20, ContactSource.CHATBOT: 15,
    ContactSource.CONTACT_FORM: 15, ContactSource.MANUAL: 10,
}
INBOUND = {ActivityType.FORM_SUBMISSION, ActivityType.BOOKING, ActivityType.CHAT, ActivityType.CALL}

# Buying-intent phrases in English and Filipino/Taglish ("magkano" = how much, "kailan" = when).
_INTENT = re.compile(
    r"\b(price|prices|pricing|quote|quotation|estimate|how much|magkano|cost|rates?|book|booking|appointment|"
    r"schedule|available|availability|today|tomorrow|asap|urgent|emergency|kailan|ngayon|bukas)\b",
    re.I,
)


@dataclass(frozen=True)
class Touch:
    type: ActivityType
    body: str | None
    occurred_at: datetime


@dataclass
class LeadScore:
    score: int
    temperature: str  # hot | warm | cold | customer | closed
    reasons: list[str] = field(default_factory=list)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def score_lead(*, source: ContactSource, stage: ContactStage, has_email: bool, has_phone: bool,
               touches: Iterable[Touch], value_cents: int | None, now: datetime | None = None) -> LeadScore:
    now = now or datetime.now(UTC)
    if stage == ContactStage.WON:
        return LeadScore(100, "customer", ["Won: already a customer"])
    if stage == ContactStage.LOST:
        return LeadScore(0, "closed", ["Marked as lost"])

    reasons: list[str] = []
    score = SOURCE_POINTS.get(source, 10)
    reasons.append(f"+{score} came in via {source.value.replace('_', ' ')}")

    if has_phone:
        score += 10
        reasons.append("+10 has a phone number")
    if has_email:
        score += 5
        reasons.append("+5 has an email address")

    inbound = [t for t in touches if t.type in INBOUND]
    intents = {m.lower() for t in inbound if t.body for m in _INTENT.findall(t.body)}
    if intents:
        points = min(15, 5 * len(intents))
        score += points
        reasons.append(f"+{points} buying intent ({', '.join(sorted(intents)[:3])})")
    if any(t.type == ActivityType.BOOKING for t in inbound) and source != ContactSource.BOOKING:
        score += 10
        reasons.append("+10 booked an appointment")
    if len(inbound) >= 4:
        score += 15
        reasons.append(f"+15 reached out {len(inbound)} times")
    elif len(inbound) >= 2:
        score += 10
        reasons.append(f"+10 reached out {len(inbound)} times")

    if inbound:
        age = now - max(_aware(t.occurred_at) for t in inbound)
        if age <= timedelta(days=2):
            score += 15
            reasons.append("+15 active in the last 2 days")
        elif age <= timedelta(days=7):
            score += 8
            reasons.append("+8 active this week")
        elif age > timedelta(days=30):
            score -= 10
            reasons.append("-10 no contact in over 30 days")

    if stage == ContactStage.QUALIFIED:
        score += 10
        reasons.append("+10 marked qualified")
    if value_cents:
        score += 5
        reasons.append("+5 has a deal value")

    score = max(0, min(100, score))
    temperature = "hot" if score >= HOT_THRESHOLD else "warm" if score >= WARM_THRESHOLD else "cold"
    return LeadScore(score, temperature, reasons)
