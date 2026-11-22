"""Appointment availability (pure): weekly opening hours + rules → bookable slots.

All arithmetic happens in the business's IANA timezone (default Asia/Manila);
slots are returned and stored as timezone-aware datetimes (UTC in the DB).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import ValidationFailedError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DEFAULT_WEEKLY_HOURS: dict[str, list[list[str]]] = {
    **{d: [["09:00", "17:00"]] for d in WEEKDAYS[:5]},
    "sat": [["09:00", "12:00"]],
    "sun": [],
}


@dataclass(frozen=True)
class BookingRules:
    timezone: str = "Asia/Manila"
    slot_minutes: int = 30
    buffer_minutes: int = 0
    lead_time_hours: int = 2
    max_days_ahead: int = 30
    weekly_hours: dict[str, list[list[str]]] = field(default_factory=lambda: DEFAULT_WEEKLY_HOURS)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def validate_rules(rules: BookingRules) -> BookingRules:
    try:
        _ = rules.tz
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailedError(f"Unknown timezone '{rules.timezone}'") from exc
    if not 10 <= rules.slot_minutes <= 240:
        raise ValidationFailedError("Slot length must be between 10 and 240 minutes")
    if not 0 <= rules.buffer_minutes <= 120 or not 0 <= rules.lead_time_hours <= 168:
        raise ValidationFailedError("Invalid buffer or lead time")
    if not 1 <= rules.max_days_ahead <= 180:
        raise ValidationFailedError("Booking window must be 1-180 days")
    for day, windows in rules.weekly_hours.items():
        if day not in WEEKDAYS:
            raise ValidationFailedError(f"Unknown weekday '{day}'")
        for window in windows:
            if len(window) != 2 or not all(_HHMM.match(t) for t in window) or window[0] >= window[1]:
                raise ValidationFailedError(f"Invalid opening hours {window} on {day}")
    return rules


def _overlaps(start: datetime, end: datetime, busy: Iterable[tuple[datetime, datetime]], buffer: timedelta) -> bool:
    return any(start < b_end + buffer and b_start - buffer < end for b_start, b_end in busy)


def available_slots(rules: BookingRules, day: date, duration_minutes: int,
                    busy: Iterable[tuple[datetime, datetime]], now: datetime) -> list[datetime]:
    """Start times on `day` (business-local) where a `duration_minutes` service fits."""
    tz = rules.tz
    local_now = now.astimezone(tz)
    if day < local_now.date() or day > local_now.date() + timedelta(days=rules.max_days_ahead):
        return []
    earliest = now + timedelta(hours=rules.lead_time_hours)
    busy = list(busy)
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=rules.slot_minutes)
    buffer = timedelta(minutes=rules.buffer_minutes)
    slots: list[datetime] = []
    for open_at, close_at in rules.weekly_hours.get(WEEKDAYS[day.weekday()], []):
        cursor = datetime.combine(day, time.fromisoformat(open_at), tz)
        window_end = datetime.combine(day, time.fromisoformat(close_at), tz)
        while cursor + duration <= window_end:
            if cursor >= earliest and not _overlaps(cursor, cursor + duration, busy, buffer):
                slots.append(cursor)
            cursor += step
    return slots


def is_bookable(rules: BookingRules, start: datetime, duration_minutes: int,
                busy: Iterable[tuple[datetime, datetime]], now: datetime) -> bool:
    if start.tzinfo is None:
        return False
    local = start.astimezone(rules.tz)
    return any(s == local for s in available_slots(rules, local.date(), duration_minutes, busy, now))
