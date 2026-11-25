"""Outbound priority score (A1): who the engine should work first, and whether it can reach them at all.

Pure rules. score = fit (opportunity score, up to 40) + reachability (up to 30) + engagement (up to 30).
Every point comes with a reason, so operators can see why a prospect is ranked where it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum

from app.domains.sales import CLOSED_STAGES, CONVERTED_STAGES, ProspectStage


class ChannelQuality(IntEnum):
    """How much we trust that a channel reaches the business. Ordered: higher is better."""

    NONE = 0
    GUESSED = 1  # predicted (e.g. a pattern guess): never used to contact
    LISTED = 2  # a public listing, or a primary with no provenance record (e.g. a CSV import)
    OBSERVED = 3  # seen on their own website or a directory entry
    CONFIRMED = 4  # given by the owner, or verified


USABLE = ChannelQuality.LISTED  # the minimum quality the engine may contact

EMAIL_POINTS = {ChannelQuality.CONFIRMED: 20, ChannelQuality.OBSERVED: 16, ChannelQuality.LISTED: 12}
PHONE_POINTS = {ChannelQuality.CONFIRMED: 10, ChannelQuality.OBSERVED: 8, ChannelQuality.LISTED: 8}
ENGAGEMENT_POINTS = {"claim_started": 30, "link_clicked": 20, "email_opened": 10}


@dataclass(frozen=True)
class PriorityInput:
    opportunity_score: int | None
    email: ChannelQuality
    phone: ChannelQuality
    last_engagement: dict[str, datetime] = field(default_factory=dict)  # activity type -> latest occurrence
    now: datetime | None = None


@dataclass(frozen=True)
class Priority:
    score: int
    reasons: list[str]
    channels: list[str]  # channels the engine may use: "email", "phone"


def _decay(age: timedelta) -> float:
    """Engagement counts fully for a week, then fades: half by two weeks, a quarter by a month, then nothing."""
    if age <= timedelta(days=7):
        return 1.0
    if age <= timedelta(days=14):
        return 0.5
    if age <= timedelta(days=30):
        return 0.25
    return 0.0


def score_priority(data: PriorityInput) -> Priority:
    reasons: list[str] = []
    fit = round(0.4 * max(0, min(100, data.opportunity_score or 0)))
    if fit:
        reasons.append(f"fit {fit}: opportunity score {data.opportunity_score}")

    reach = EMAIL_POINTS.get(data.email, 0) + PHONE_POINTS.get(data.phone, 0)
    channels = [name for name, quality in (("email", data.email), ("phone", data.phone)) if quality >= USABLE]
    if data.email >= USABLE:
        reasons.append(f"email {data.email.name.lower()} (+{EMAIL_POINTS[data.email]})")
    if data.phone >= USABLE:
        reasons.append(f"phone {data.phone.name.lower()} (+{PHONE_POINTS[data.phone]})")
    if not channels:
        reasons.append("no usable channel")

    engagement = 0
    if data.now is not None:
        best = ("", 0.0)
        for kind, points in ENGAGEMENT_POINTS.items():
            when = data.last_engagement.get(kind)
            if when is not None:
                value = points * _decay(data.now - when)
                if value > best[1]:
                    best = (kind, value)
        engagement = round(best[1])
        if engagement:
            reasons.append(f"engagement +{engagement}: {best[0].replace('_', ' ')}")

    return Priority(score=min(100, fit + reach + engagement), reasons=reasons, channels=channels)


def is_ready(stage: ProspectStage, channels: list[str], cooldown_until: datetime | None, now: datetime) -> bool:
    """May the outbound engine work this prospect now? (A2 also checks per-channel opt-outs at send time.)"""
    if stage is ProspectStage.DO_NOT_CONTACT or stage in CONVERTED_STAGES or not channels:
        return False
    if stage in CLOSED_STAGES:  # lost: back in play only once its cooldown has passed
        return cooldown_until is not None and cooldown_until <= now
    return cooldown_until is None or cooldown_until <= now
