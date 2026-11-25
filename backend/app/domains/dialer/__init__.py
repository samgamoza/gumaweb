"""Outbound dialer seam (parked: see docs/OUTREACH_DIALER_BRIDGE_PLAN.md).

Gumaweb decides *who* is worth calling; a dialer (GumaDial, later) decides whether and when a call may happen
and reports what happened. This module fixes the shape of that conversation so the rest of Gumaweb (the sales
CRM, voice campaigns) can depend on it now. Only `NullDialer` exists until GumaDial ships its Integration API;
then a `GumaDialDialer` is added here and selected with `DIALER_PROVIDER=gumadial`. Nothing else changes.

The types mirror the v1 contract in the plan (§4). Field names stay in Python style; the HTTP adapter maps them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class DialerNotConfiguredError(RuntimeError):
    """Raised when something tries to use the dialer while `DIALER_PROVIDER=none`."""


class CallOutcome(StrEnum):
    """GumaDial's disposition codes, the outcomes a dialer reports back."""

    INTERESTED = "CONNECTED_INTERESTED"
    NOT_INTERESTED = "CONNECTED_NOT_INTERESTED"
    NO_ANSWER = "NO_ANSWER"
    VOICEMAIL = "VOICEMAIL"
    WRONG_NUMBER = "WRONG_NUMBER"
    DO_NOT_CALL = "DO_NOT_CALL"
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"


class PushStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    SUPPRESSED = "suppressed"
    INVALID = "invalid"


@dataclass(frozen=True)
class DialerContact:
    external_ref: str  # "gw:business:<uuid>": how outcomes find their way back
    company_name: str
    phone_e164: str  # always "+<country><number>": use to_e164()
    first_name: str | None = None
    timezone: str | None = "Asia/Manila"
    score: int | None = None  # an ordering hint for the dialer, never permission to call
    dossier: dict[str, Any] = field(default_factory=dict)  # siteUrl, claimUrl, industry, city, reasons


@dataclass(frozen=True)
class PushRowResult:
    external_ref: str
    status: PushStatus


@dataclass(frozen=True)
class DialerEvent:
    """One entry of the outcomes feed. `id` is stable: applying the same event twice must be a no-op."""

    id: str
    kind: str  # "disposition.recorded" | "contact.reviewed" | "suppression.added"
    external_ref: str | None
    occurred_at: datetime
    outcome: CallOutcome | None = None
    notes: str | None = None
    captured_email: str | None = None
    owner_name: str | None = None
    callback_at: datetime | None = None
    phone_e164: str | None = None


@dataclass(frozen=True)
class OutcomePage:
    events: list[DialerEvent]
    next_cursor: str | None


@dataclass(frozen=True)
class DialerHealth:
    provider: str
    connected: bool
    detail: str


class Dialer(Protocol):
    name: str

    def health(self) -> DialerHealth: ...

    def push_batch(self, batch_ref: str, list_name: str, contacts: list[DialerContact]) -> list[PushRowResult]: ...

    def fetch_outcomes(self, cursor: str | None, limit: int = 200) -> OutcomePage: ...

    def push_suppressions(self, phones_e164: list[str], reason: str) -> None: ...


class NullDialer:
    """No dialer connected: Gumaweb works exactly as before; calls are logged by hand in the sales CRM."""

    name = "none"

    def health(self) -> DialerHealth:
        return DialerHealth(self.name, False, "No dialer connected (DIALER_PROVIDER=none).")

    def push_batch(self, batch_ref: str, list_name: str, contacts: list[DialerContact]) -> list[PushRowResult]:
        raise DialerNotConfiguredError("No dialer connected")

    def fetch_outcomes(self, cursor: str | None, limit: int = 200) -> OutcomePage:
        return OutcomePage(events=[], next_cursor=cursor)  # nothing to sync: the outcome job is a no-op

    def push_suppressions(self, phones_e164: list[str], reason: str) -> None:
        return None  # nowhere to forward to; Gumaweb's own suppression list still applies


def to_e164(phone: str | None) -> str | None:
    """Gumaweb stores phones as digits ("639171234567"); dialers need E.164 ("+639171234567")."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def external_ref(business_id: object) -> str:
    return f"gw:business:{business_id}"


def build_dialer(provider: str) -> Dialer:
    if provider == "none":
        return NullDialer()
    raise ValueError(f"Unknown dialer provider: {provider}")
