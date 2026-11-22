"""Business email (Professional plan) on a verified custom domain, hosted on the self-hosted mail server.

Passwords are generated here, sent to the mail server and shown to the owner once; GumaWeb never stores
them. Downgrading suspends creating new addresses but never deletes mail: deleting someone's inbox
because a plan changed would destroy their correspondence.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domains.billing.entitlements import Feature, PlanUpgradeRequired, has_feature
from app.domains.presence.enums import DomainStatus, MailboxKind
from app.domains.presence.mail import missing_records, normalize_local_part, parse_zone
from app.models import CustomDomain, Mailbox, MailDomain
from app.services.dns_resolver import DnsError
from app.services.entitlements import plan_for_business
from app.services.mail_provider import EmailUnavailable
from app.services.providers import providers

logger = logging.getLogger("gumaweb.mail")


def _password() -> str:
    return secrets.token_urlsafe(12)  # ~96 bits, typeable


class MailService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _mail_domain(self, row: CustomDomain) -> MailDomain | None:
        return self.db.scalar(select(MailDomain).where(MailDomain.domain_id == row.id))

    def _require(self, business_id: uuid.UUID) -> dict[str, Any]:
        features, plan = plan_for_business(self.db, business_id)
        if not has_feature(features, Feature.BUSINESS_EMAIL):
            raise PlanUpgradeRequired(f"Business email is not included in the {plan} plan")
        return features

    # --- Views ---------------------------------------------------------------------------------
    def records_for(self, row: CustomDomain) -> list[dict[str, Any]]:
        mail = self._mail_domain(row)
        return list(mail.dns_records) if mail else []

    def summary(self, row: CustomDomain) -> dict[str, Any] | None:
        mail = self._mail_domain(row)
        if mail is None:
            return None
        boxes = self.db.scalars(select(Mailbox).where(Mailbox.mail_domain_id == mail.id)
                                .order_by(Mailbox.created_at)).all()
        host = self.settings.mail_client_host
        return {
            "status": mail.status, "dns_missing": mail.dns_missing, "dns_checked_at": mail.dns_checked_at,
            "addresses": [{"id": str(b.id), "address": f"{b.local_part}@{row.domain}", "kind": b.kind.value,
                           "display_name": b.display_name, "forward_to": b.forward_to} for b in boxes],
            "client_settings": {"incoming": f"IMAP {host}, port 993 (SSL/TLS)",
                                "outgoing": f"SMTP {host}, port 465 (SSL/TLS)",
                                "username": "your full email address"},
        }

    # --- Domain lifecycle ----------------------------------------------------------------------
    def enable(self, row: CustomDomain) -> MailDomain:
        self._require(row.business_id)
        if row.status != DomainStatus.VERIFIED:
            raise ValidationFailedError("Verify the domain before setting up email on it")
        existing = self._mail_domain(row)
        if existing:
            return existing
        ref = providers.mail.ensure_domain(row.domain)
        mail = MailDomain(domain_id=row.id, business_id=row.business_id, provider_ref=ref,
                          dns_records=parse_zone(providers.mail.zone(ref)), status="dns_pending",
                          dns_missing=[])
        self.db.add(mail)
        self.db.commit()
        return mail

    def check_dns(self, row: CustomDomain) -> MailDomain:
        mail = self._mail_domain(row)
        if mail is None:
            raise ValidationFailedError("Set up email on this domain first")
        with contextlib.suppress(EmailUnavailable):  # keys rotate: refresh the records when we can
            mail.dns_records = parse_zone(providers.mail.zone(mail.provider_ref))

        def lookup(rtype: str, name: str) -> list:
            return providers.dns.mx(name) if rtype == "MX" else providers.dns.txt(name)

        try:
            mail.dns_missing = missing_records(mail.dns_records, lookup)
        except DnsError as exc:
            raise ValidationFailedError("We couldn't reach the DNS servers. Please try again shortly.") from exc
        mail.dns_checked_at = datetime.now(UTC)
        if mail.status != "suspended":
            mail.status = "active" if not mail.dns_missing else "dns_pending"
        self.db.commit()
        return mail

    def disable_for_domain(self, row: CustomDomain) -> None:
        """Domain removed by its owner: delete its addresses and the domain on the mail server."""
        mail = self._mail_domain(row)
        if mail is None:
            return
        for box in self.db.scalars(select(Mailbox).where(Mailbox.mail_domain_id == mail.id)).all():
            self._delete_remote(box)
        providers.mail.delete_domain(mail.provider_ref)
        self.db.delete(mail)
        self.db.flush()

    def enforce_plan(self, business_id: uuid.UUID) -> int:
        features, _ = plan_for_business(self.db, business_id)
        allowed = has_feature(features, Feature.BUSINESS_EMAIL)
        changed = 0
        for mail in self.db.scalars(select(MailDomain).where(MailDomain.business_id == business_id)).all():
            if not allowed and mail.status != "suspended":
                mail.status, changed = "suspended", changed + 1
            elif allowed and mail.status == "suspended":
                mail.status, changed = ("active" if not mail.dns_missing else "dns_pending"), changed + 1
        self.db.flush()
        return changed

    # --- Addresses -----------------------------------------------------------------------------
    def create_mailbox(self, row: CustomDomain, data: dict[str, Any]) -> dict[str, Any]:
        features = self._require(row.business_id)
        mail = self._mail_domain(row)
        if mail is None:
            raise ValidationFailedError("Set up email on this domain first")
        if mail.status == "suspended":
            raise PlanUpgradeRequired("Business email is suspended on your current plan")
        local = normalize_local_part(data["local_part"])
        kind = MailboxKind(data.get("kind", "mailbox"))
        used = self.db.scalar(select(func.count()).select_from(Mailbox).where(
            Mailbox.business_id == row.business_id, Mailbox.kind == MailboxKind.MAILBOX)) or 0
        if kind == MailboxKind.MAILBOX and used >= int(features.get("mailboxes", 0)):
            raise PlanUpgradeRequired(f"Your plan includes {features.get('mailboxes', 0)} mailboxes")
        if self.db.scalar(select(Mailbox.id).where(Mailbox.mail_domain_id == mail.id, Mailbox.local_part == local)):
            raise ValidationFailedError(f"{local}@{row.domain} already exists")
        password = None
        if kind == MailboxKind.MAILBOX:
            password = _password()
            ref = providers.mail.create_mailbox(mail.provider_ref, local, data.get("display_name"), password,
                                                self.settings.mailbox_quota_mb)
            targets: list[str] = []
        else:
            targets = self._targets(data.get("forward_to") or [], row.domain)
            ref = providers.mail.create_forward(mail.provider_ref, local, targets)
        box = Mailbox(mail_domain_id=mail.id, business_id=row.business_id, local_part=local, kind=kind,
                      display_name=data.get("display_name"), forward_to=targets,
                      quota_mb=self.settings.mailbox_quota_mb, provider_ref=ref)
        self.db.add(box)
        self.db.commit()
        result: dict[str, Any] = {"id": str(box.id), "address": f"{local}@{row.domain}", "kind": kind.value}
        if password:
            result["password"] = password  # shown once; never stored by GumaWeb
        return result

    def reset_password(self, row: CustomDomain, mailbox_id: uuid.UUID) -> dict[str, Any]:
        self._require(row.business_id)
        box = self._box(row, mailbox_id)
        if box.kind != MailboxKind.MAILBOX:
            raise ValidationFailedError("Forwarding addresses have no password")
        password = _password()
        providers.mail.set_password(box.provider_ref, password)
        return {"address": f"{box.local_part}@{row.domain}", "password": password}

    def delete_mailbox(self, row: CustomDomain, mailbox_id: uuid.UUID) -> None:
        box = self._box(row, mailbox_id)
        self._delete_remote(box)
        self.db.delete(box)
        self.db.commit()

    # --- Helpers -------------------------------------------------------------------------------
    def _box(self, row: CustomDomain, mailbox_id: uuid.UUID) -> Mailbox:
        mail = self._mail_domain(row)
        box = self.db.get(Mailbox, mailbox_id)
        if mail is None or box is None or box.mail_domain_id != mail.id:
            raise NotFoundError("Address not found")
        return box

    def _delete_remote(self, box: Mailbox) -> None:
        if box.kind == MailboxKind.MAILBOX:
            providers.mail.delete_mailbox(box.provider_ref)
        else:
            providers.mail.delete_forward(box.provider_ref)

    @staticmethod
    def _targets(raw: list[str], domain: str) -> list[str]:
        if not raw:
            raise ValidationFailedError("Add at least one address to forward to")
        targets = []
        for address in raw[:10]:
            try:
                email = validate_email(address, check_deliverability=False).normalized.lower()
            except EmailNotValidError as exc:
                raise ValidationFailedError(f"{address} is not a valid email address") from exc
            if email.endswith("@" + domain):
                raise ValidationFailedError("Forward to an address outside this domain")
            targets.append(email)
        return sorted(set(targets))
