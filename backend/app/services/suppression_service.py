"""Do-not-contact list: record, remove and check suppressions (email or whole domain).

Adding one also queues a retroactive scrub of stored contacts and queued messages (`suppression_scrub.py`).

Every check, in Python or SQL, goes through this module so the "email or its domain" rule is applied the
same way everywhere: outreach enrollment, dispatch, unsubscribe and contact enrichment.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.outreach.suppression import (
    SuppressionKind,
    SuppressionReason,
    normalize_suppression,
    suppression_keys,
)
from app.domains.website_factory.jobs import JobKind
from app.models import OutreachSuppression
from app.services.job_queue import JobQueue
from app.services.support import Actor, audit


def not_suppressed(email_column: Any) -> ColumnElement[bool]:
    """SQL condition: this email column is neither suppressed itself nor at a suppressed domain.

    Portable across PostgreSQL and SQLite. Domain values are validated to [a-z0-9.-], so they can't carry
    LIKE wildcards.
    """
    email = func.lower(email_column)
    exact = exists().where(OutreachSuppression.kind == SuppressionKind.EMAIL, OutreachSuppression.value == email)
    at_domain = exists().where(
        OutreachSuppression.kind == SuppressionKind.DOMAIN,
        email.like(literal("%@").concat(OutreachSuppression.value)),
    )
    return and_(~exact, ~at_domain)


class SuppressionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def match(self, email: str | None) -> OutreachSuppression | None:
        """The suppression blocking this email (an exact address match wins over its domain), or None."""
        keys = suppression_keys(email)
        if not keys:
            return None
        clause = or_(*(and_(OutreachSuppression.kind == k, OutreachSuppression.value == v) for k, v in keys))
        found = self.db.scalars(select(OutreachSuppression).where(clause)).all()
        return min(found, key=lambda s: 0 if s.kind is SuppressionKind.EMAIL else 1) if found else None

    def is_suppressed(self, email: str | None) -> bool:
        return self.match(email) is not None

    def is_domain_suppressed(self, domain: str | None) -> bool:
        try:
            value = normalize_suppression(SuppressionKind.DOMAIN, domain or "")
        except ValueError:
            return False
        return self._get(SuppressionKind.DOMAIN, value) is not None

    def list(self, kind: SuppressionKind | None = None) -> Sequence[OutreachSuppression]:
        stmt = select(OutreachSuppression).order_by(OutreachSuppression.created_at.desc(), OutreachSuppression.value)
        if kind is not None:
            stmt = stmt.where(OutreachSuppression.kind == kind)
        return self.db.scalars(stmt).all()

    def add(self, kind: SuppressionKind, value: str, reason: SuppressionReason | str, actor: Actor, *,
            note: str | None = None, commit: bool = True) -> tuple[OutreachSuppression, bool]:
        """Idempotent on (kind, value). Returns (entry, created)."""
        normalized = self._normalize(kind, value)
        existing = self._get(kind, normalized)
        if existing is not None:
            return existing, False
        entry = OutreachSuppression(kind=kind, value=normalized, reason=str(reason), note=note,
                                    created_by=actor.user_id)
        self.db.add(entry)
        audit(self.db, actor, AuditAction.SUPPRESSION_ADDED, "outreach_suppression", f"{kind.value}:{normalized}",
              {"reason": str(reason)})
        # Retroactive scrub of already-stored contacts and queued messages (services/suppression_scrub.py).
        JobQueue(self.db).enqueue(JobKind.SCRUB_SUPPRESSION, {"kind": kind.value, "value": normalized},
                                  dedupe_key=f"scrub:{kind.value}:{normalized}"[:255], priority=50)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return entry, True

    def remove(self, kind: SuppressionKind, value: str, actor: Actor, *, commit: bool = True) -> bool:
        normalized = self._normalize(kind, value)
        existing = self._get(kind, normalized)
        if existing is None:
            return False
        self.db.delete(existing)
        audit(self.db, actor, AuditAction.SUPPRESSION_REMOVED, "outreach_suppression", f"{kind.value}:{normalized}",
              {"reason": existing.reason})
        if commit:
            self.db.commit()
        return True

    def _get(self, kind: SuppressionKind, value: str) -> OutreachSuppression | None:
        return self.db.scalar(
            select(OutreachSuppression).where(OutreachSuppression.kind == kind, OutreachSuppression.value == value)
        )

    @staticmethod
    def _normalize(kind: SuppressionKind, value: str) -> str:
        try:
            return normalize_suppression(kind, value)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
