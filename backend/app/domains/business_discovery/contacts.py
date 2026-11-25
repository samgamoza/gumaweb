"""Contact points with provenance (ported from guma_os `profile.ts` provenance entries).

Every email/phone/owner name we learn about a business is kept as its own record saying where it came
from, when, how sure we are, and whether policy allowed it. Only one of them becomes the business's
primary contact (`Business.email` / `Business.phone`), which is what outreach uses.

The rule that matters most: a value we *guessed* (`predicted`, e.g. an RDAP or name-pattern email) or
*computed* (`derived`) is stored for review but is never promoted, so outreach can never send to it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ContactKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    OWNER = "owner"  # a named person (e.g. from a chamber-of-commerce listing); never auto-contacted


class ValueType(StrEnum):
    OBSERVED = "observed"  # seen directly at the source (on the business's own site, in a directory)
    DERIVED = "derived"  # computed from other facts
    PREDICTED = "predicted"  # guessed (registrant data, name patterns); never trusted for outreach
    USER_SUPPLIED = "user_supplied"  # typed in by staff or the owner


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"  # independently confirmed (e.g. the owner claimed with it, mailbox check)
    INVALID = "invalid"  # confirmed wrong (bounce, disconnected number)


class ContactPurpose(StrEnum):
    """Why it was collected: ties acquisition to a legitimate basis instead of leaving it implicit."""

    LEAD_QUALIFICATION = "lead_qualification"
    CONTACT_ENRICHMENT = "contact_enrichment"
    COMPLIANCE_CHECK = "compliance_check"
    TECHNICAL_VERIFICATION = "technical_verification"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REDACTED = "redacted"
    BLOCKED = "blocked"


class ReasonCode(StrEnum):
    SUPPRESSED_EMAIL = "SUPPRESSED_EMAIL"
    SUPPRESSED_DOMAIN = "SUPPRESSED_DOMAIN"
    LOW_CONFIDENCE_GUESS = "LOW_CONFIDENCE_GUESS"
    INVALID_FORMAT = "INVALID_FORMAT"


PROMOTABLE_VALUE_TYPES = frozenset({ValueType.OBSERVED, ValueType.USER_SUPPLIED})
PROMOTABLE_KINDS = frozenset({ContactKind.EMAIL, ContactKind.PHONE})


class ContactLike(Protocol):
    kind: ContactKind
    value: str
    value_type: ValueType
    verification_status: VerificationStatus
    policy_decision: PolicyDecision
    confidence: float
    acquired_at: datetime | None


def is_promotable(contact: ContactLike) -> bool:
    """May this contact become the business's primary email/phone (and so receive outreach)?"""
    return (
        contact.kind in PROMOTABLE_KINDS
        and contact.value_type in PROMOTABLE_VALUE_TYPES
        and contact.policy_decision is PolicyDecision.ALLOW
        and contact.verification_status is not VerificationStatus.INVALID
    )


def choose_primary(contacts: Iterable[ContactLike], kind: ContactKind) -> ContactLike | None:
    """The best promotable contact of `kind`: verified first, then user-supplied, then confidence, then oldest."""
    eligible = [c for c in contacts if c.kind is kind and is_promotable(c)]
    if not eligible:
        return None

    def rank(c: ContactLike) -> tuple[int, int, float, float]:
        acquired = c.acquired_at.timestamp() if c.acquired_at else float("inf")
        return (
            0 if c.verification_status is VerificationStatus.VERIFIED else 1,
            0 if c.value_type is ValueType.USER_SUPPLIED else 1,
            -c.confidence,
            acquired,
        )

    return min(eligible, key=rank)


@dataclass(frozen=True)
class ContactObservation:
    """One contact as reported by a discovery or enrichment source, before it is stored."""

    kind: ContactKind
    value: str
    source: str  # provider id, e.g. "website_scrape", "osm", "hunter", "csv_import"
    value_type: ValueType = ValueType.OBSERVED
    confidence: float = 1.0
    source_ref: str | None = None  # where exactly: a URL, a place id, a record id
    purpose: ContactPurpose = ContactPurpose.CONTACT_ENRICHMENT
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    retention_until: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
