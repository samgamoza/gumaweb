"""CRM + lead management (12-customer-portal CRM; 14 Business tier).

Every inbound channel (contact form, booking, chatbot) funnels into one contact
per person per business, deduplicated by email, then phone. Capture happens on
every plan; the CRM screens are plan-gated, so an upgrade reveals history.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domains.business_discovery.normalization import normalize_email, normalize_phone
from app.domains.crm.enums import PIPELINE, ActivityType, ContactSource, ContactStage
from app.models import Contact, ContactActivity

GENERIC_NAMES = {"website visitor", "chat visitor", ""}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection from visitor-supplied text (=, +, -, @, tab, CR)."""
    return f"'{value}" if value and value[0] in FORMULA_PREFIXES else value


class CrmService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _norm(self, email: str | None, phone: str | None) -> tuple[str | None, str | None]:
        return normalize_email(email), normalize_phone(phone, self.settings.default_country_code)

    def find(self, business_id: uuid.UUID, email: str | None, phone: str | None) -> Contact | None:
        for column, value in ((Contact.email, email), (Contact.phone, phone)):
            if value:
                found = self.db.scalar(select(Contact).where(Contact.business_id == business_id, column == value))
                if found:
                    return found
        return None

    # --- Capture (all channels) -----------------------------------------------------------
    def capture(self, business_id: uuid.UUID, *, name: str | None, email: str | None, phone: str | None,
                source: ContactSource, activity: ActivityType, body: str | None,
                data: dict[str, Any] | None = None) -> Contact:
        email, phone = self._norm(email, phone)
        contact = self.find(business_id, email, phone)
        if contact is None:
            contact = Contact(business_id=business_id, name=(name or "").strip()[:200] or "Website visitor",
                              email=email, phone=phone, source=source)
            self.db.add(contact)
        else:  # enrich with newly learned details, never overwrite what the owner set
            if email and not contact.email and not self.find(business_id, email, None):
                contact.email = email
            if phone and not contact.phone and not self.find(business_id, None, phone):
                contact.phone = phone
            if name and contact.name.strip().lower() in GENERIC_NAMES:
                contact.name = name.strip()[:200]
        self._log(contact, activity, body, data or {}, None)
        self.db.flush()
        return contact

    def _log(self, contact: Contact, type_: ActivityType, body: str | None, data: dict[str, Any],
             user_id: uuid.UUID | None) -> ContactActivity:
        now = datetime.now(UTC)
        activity = ContactActivity(type=type_, body=(body or "")[:4000] or None, data=data, created_by=user_id,
                                   occurred_at=now)
        contact.activities.append(activity)
        contact.last_activity_at = now
        return activity

    # --- Owner operations ------------------------------------------------------------------
    def list(self, business_id: uuid.UUID, *, q: str | None, stage: ContactStage | None,
             source: ContactSource | None, page: int, page_size: int) -> tuple[Sequence[Contact], int]:
        stmt = select(Contact).where(Contact.business_id == business_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Contact.name).like(like), Contact.email.like(like),
                                  Contact.phone.like(f"%{q}%")))
        if stage:
            stmt = stmt.where(Contact.stage == stage)
        if source:
            stmt = stmt.where(Contact.source == source)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = self.db.scalars(
            stmt.order_by(Contact.last_activity_at.desc().nulls_last(), Contact.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all()
        return items, total

    def get(self, business_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
        contact = self.db.get(Contact, contact_id)
        if contact is None or contact.business_id != business_id:
            raise NotFoundError("Contact not found")
        return contact

    def create(self, business_id: uuid.UUID, data: dict[str, Any], user_id: uuid.UUID) -> Contact:
        email, phone = self._norm(data.get("email"), data.get("phone"))
        if not (email or phone):
            raise ValidationFailedError("A contact needs an email or phone number")
        if self.find(business_id, email, phone):
            raise ConflictError("A contact with this email or phone already exists", code="duplicate_contact")
        contact = Contact(business_id=business_id, name=data["name"], email=email, phone=phone,
                          source=ContactSource.MANUAL, stage=data.get("stage") or ContactStage.NEW,
                          value_cents=data.get("value_cents"), tags=data.get("tags") or [], notes=data.get("notes"))
        self.db.add(contact)
        self._log(contact, ActivityType.NOTE, "Contact added manually", {}, user_id)
        self.db.commit()
        return contact

    def update(self, contact: Contact, changes: dict[str, Any], user_id: uuid.UUID) -> Contact:
        if "email" in changes or "phone" in changes:
            email, phone = self._norm(changes.get("email", contact.email), changes.get("phone", contact.phone))
            other = self.find(contact.business_id, email, phone)
            if other and other.id != contact.id:
                raise ConflictError("Another contact already uses this email or phone", code="duplicate_contact")
            changes["email"], changes["phone"] = email, phone
        new_stage = changes.get("stage")
        if new_stage and new_stage != contact.stage:
            self._log(contact, ActivityType.STAGE_CHANGE, f"{contact.stage.value} → {new_stage.value}",
                      {"from": contact.stage.value, "to": new_stage.value}, user_id)
        for field, value in changes.items():
            setattr(contact, field, value)
        self.db.commit()
        return contact

    def add_activity(self, contact: Contact, type_: ActivityType, body: str, user_id: uuid.UUID) -> ContactActivity:
        if type_ not in (ActivityType.NOTE, ActivityType.CALL, ActivityType.EMAIL, ActivityType.MEETING):
            raise ValidationFailedError("Only notes, calls, emails and meetings can be logged manually")
        activity = self._log(contact, type_, body, {}, user_id)
        self.db.commit()
        return activity

    def delete(self, contact: Contact) -> None:
        self.db.delete(contact)
        self.db.commit()

    def pipeline(self, business_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = dict(
            (stage, (count, value)) for stage, count, value in self.db.execute(
                select(Contact.stage, func.count(Contact.id), func.coalesce(func.sum(Contact.value_cents), 0))
                .where(Contact.business_id == business_id).group_by(Contact.stage)
            ).all()
        )
        return [{"stage": s.value, "count": rows.get(s, (0, 0))[0], "value_cents": int(rows.get(s, (0, 0))[1])}
                for s in PIPELINE]

    def export_csv(self, business_id: uuid.UUID) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["name", "email", "phone", "stage", "source", "value", "tags", "last_activity", "created"])
        for c in self.db.scalars(select(Contact).where(Contact.business_id == business_id)
                                 .order_by(Contact.created_at)):
            writer.writerow([_csv_safe(c.name), _csv_safe(c.email or ""), _csv_safe(c.phone or ""), c.stage.value,
                             c.source.value, f"{(c.value_cents or 0) / 100:.2f}", _csv_safe(";".join(c.tags or [])),
                             c.last_activity_at.isoformat() if c.last_activity_at else "", c.created_at.isoformat()])
        return buffer.getvalue()
