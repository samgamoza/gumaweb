"""Record contacts with provenance and keep each business's primary email/phone correct.

Called by discovery and enrichment (port plan steps 3-4). It never sends anything: it decides what is
stored, what is blocked, and what may become `Business.email`/`phone`, which outreach reads.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.business_discovery.contacts import (
    ContactKind,
    ContactObservation,
    PolicyDecision,
    ReasonCode,
    ValueType,
    VerificationStatus,
    choose_primary,
    is_promotable,
)
from app.domains.business_discovery.normalization import clean_text, normalize_email, normalize_phone
from app.domains.outreach.suppression import SuppressionKind
from app.models import Business, BusinessContact
from app.services.suppression_service import SuppressionService

# Higher wins when the same value is reported again by a stronger kind of source.
_VALUE_TYPE_STRENGTH = {ValueType.PREDICTED: 0, ValueType.DERIVED: 1, ValueType.OBSERVED: 2,
                        ValueType.USER_SUPPLIED: 3}


@dataclass
class RecordResult:
    created: int = 0
    updated: int = 0
    blocked: int = 0
    invalid: int = 0
    promoted: dict[str, str] = field(default_factory=dict)  # kind -> value newly set on the business
    cleared: list[str] = field(default_factory=list)  # kinds whose primary was removed (now suppressed)


def normalize_contact_value(kind: ContactKind, value: str) -> str | None:
    if kind is ContactKind.EMAIL:
        return normalize_email(value)
    if kind is ContactKind.PHONE:
        return normalize_phone(value)
    cleaned = clean_text(value)
    return cleaned[:320] if cleaned else None


class ContactService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.suppressions = SuppressionService(db)

    def contacts_for(self, business_id: uuid.UUID) -> list[BusinessContact]:
        return list(self.db.scalars(
            select(BusinessContact).where(BusinessContact.business_id == business_id)
            .order_by(BusinessContact.kind, BusinessContact.acquired_at)
        ))

    def record(self, business: Business, observations: list[ContactObservation], *,
               discovery_run_id: uuid.UUID | None = None) -> RecordResult:
        """Store observations (upsert on business+kind+value), apply suppression, then refresh primaries.

        Does not commit: callers commit together with the rest of their unit of work.
        """
        result = RecordResult()
        existing = {(c.kind, c.value): c for c in self.contacts_for(business.id)}
        for obs in observations:
            value = normalize_contact_value(obs.kind, obs.value)
            if value is None:
                result.invalid += 1
                continue
            contact = existing.get((obs.kind, value))
            if contact is None:
                contact = BusinessContact(
                    business_id=business.id, kind=obs.kind, value=value, source=obs.source,
                    source_ref=obs.source_ref, value_type=obs.value_type,
                    verification_status=obs.verification_status, confidence=obs.confidence, purpose=obs.purpose,
                    policy_decision=PolicyDecision.ALLOW, retention_until=obs.retention_until,
                    discovery_run_id=discovery_run_id,
                )
                self.db.add(contact)
                existing[(obs.kind, value)] = contact
                result.created += 1
            else:
                self._merge(contact, obs)
                result.updated += 1
            if self._apply_policy(contact):
                result.blocked += 1
        self.db.flush()
        self._refresh_primaries(business, list(existing.values()), result)
        return result

    @staticmethod
    def _merge(contact: BusinessContact, obs: ContactObservation) -> None:
        """A repeat sighting can only strengthen a record, never weaken it."""
        if _VALUE_TYPE_STRENGTH[obs.value_type] > _VALUE_TYPE_STRENGTH[contact.value_type]:
            contact.value_type = obs.value_type
            contact.source = obs.source
            contact.source_ref = obs.source_ref or contact.source_ref
        contact.confidence = max(contact.confidence, obs.confidence)
        if obs.verification_status is VerificationStatus.INVALID:
            contact.verification_status = VerificationStatus.INVALID
        elif (obs.verification_status is VerificationStatus.VERIFIED
              and contact.verification_status is not VerificationStatus.INVALID):
            contact.verification_status = VerificationStatus.VERIFIED
        contact.source_ref = contact.source_ref or obs.source_ref

    def _apply_policy(self, contact: BusinessContact) -> bool:
        """Block a suppressed email. Returns True when this contact is (now) blocked by suppression."""
        if contact.kind is not ContactKind.EMAIL:
            return False
        match = self.suppressions.match(contact.value)
        if match is None:
            return False
        contact.policy_decision = PolicyDecision.BLOCKED
        contact.reason_code = (ReasonCode.SUPPRESSED_EMAIL if match.kind is SuppressionKind.EMAIL
                               else ReasonCode.SUPPRESSED_DOMAIN).value
        return True

    def _refresh_primaries(self, business: Business, contacts: list[BusinessContact], result: RecordResult) -> None:
        # Never leave a suppressed address as the primary, wherever it originally came from.
        if business.email and self.suppressions.is_suppressed(business.email):
            business.email = None
            result.cleared.append(ContactKind.EMAIL.value)
        for kind, attr in ((ContactKind.EMAIL, "email"), (ContactKind.PHONE, "phone")):
            if getattr(business, attr):
                continue  # keep an existing primary (imported or typed in); enrichment only fills gaps
            best = choose_primary(contacts, kind)
            if best is not None and is_promotable(best):
                setattr(business, attr, best.value)
                result.promoted[kind.value] = best.value
