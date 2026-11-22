"""Custom domains (Professional plan): ownership verification, serving the website, periodic re-checks."""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, GumaWebError, NotFoundError, ValidationFailedError
from app.domains.billing.entitlements import Feature, has_feature
from app.domains.presence.domains import (
    is_verified,
    normalize_domain,
    verification_record,
    website_records,
)
from app.domains.presence.enums import DomainStatus
from app.models import Business, CustomDomain, Website
from app.services.dns_resolver import DnsError
from app.services.entitlements import plan_for_business, require_feature
from app.services.notifications import EmailMessage
from app.services.providers import providers
from app.services.support import Actor

logger = logging.getLogger("gumaweb.domains")


class DnsUnavailable(GumaWebError):
    status_code = 503
    code = "dns_unavailable"


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=dt.tzinfo or UTC) if dt else None


class DomainService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- Owner operations --------------------------------------------------------------------
    def domains(self, business_id: uuid.UUID) -> Sequence[CustomDomain]:
        return self.db.scalars(select(CustomDomain).where(CustomDomain.business_id == business_id)
                               .order_by(CustomDomain.created_at)).all()

    def get(self, business_id: uuid.UUID, domain_id: uuid.UUID) -> CustomDomain:
        row = self.db.get(CustomDomain, domain_id)
        if row is None or row.business_id != business_id:
            raise NotFoundError("Domain not found")
        return row

    def add(self, business_id: uuid.UUID, raw: str) -> CustomDomain:
        require_feature(self.db, business_id, Feature.CUSTOM_DOMAIN)
        domain = normalize_domain(raw, platform_domain=self.settings.public_site_domain)
        if len(self.domains(business_id)) >= self.settings.max_custom_domains:
            raise ValidationFailedError(f"At most {self.settings.max_custom_domains} domains")
        existing = self.db.scalar(select(CustomDomain).where(CustomDomain.domain == domain))
        if existing:
            if existing.business_id == business_id:
                return existing
            stale = (existing.status != DomainStatus.VERIFIED and _aware(existing.created_at) <
                     datetime.now(UTC) - timedelta(days=self.settings.domain_pending_days))
            if not stale:
                raise ConflictError("That domain is already connected to another GumaWeb account")
            self.db.delete(existing)  # an abandoned, never-verified claim on the name
            self.db.flush()
        row = CustomDomain(business_id=business_id, domain=domain, verification_token=secrets.token_hex(16))
        self.db.add(row)
        self.db.commit()
        return row

    def records(self, row: CustomDomain) -> list[dict[str, Any]]:
        records = [verification_record(row.domain, row.verification_token)]
        records += website_records(row.domain, cname_target=self.settings.custom_domain_cname_target,
                                   ipv4=self.settings.custom_domain_ipv4)
        return [r.as_dict() for r in records]

    def verify(self, row: CustomDomain) -> CustomDomain:
        record = verification_record(row.domain, row.verification_token)
        try:
            values = providers.dns.txt(record.name)
        except DnsError as exc:
            raise DnsUnavailable("We couldn't reach the DNS servers. Please try again in a minute.") from exc
        row.last_checked_at = datetime.now(UTC)
        if is_verified(values, row.verification_token):
            if row.status != DomainStatus.VERIFIED:
                row.status, row.verified_at = DomainStatus.VERIFIED, datetime.now(UTC)
            row.last_error = None
        else:
            row.last_error = (f"No TXT record {record.name} with the value {record.value} yet. "
                              "DNS changes can take up to a few hours to appear.")
        self.db.commit()
        return row

    def set_serving(self, row: CustomDomain, serve: bool, actor: Actor) -> CustomDomain:
        website = self._website(row.business_id)
        if serve:
            require_feature(self.db, row.business_id, Feature.CUSTOM_DOMAIN)
            if row.status != DomainStatus.VERIFIED:
                raise ValidationFailedError("Verify the domain before using it for your website")
            for other in self.domains(row.business_id):  # one canonical address per site
                if other.id != row.id and other.serve_website:
                    other.serve_website = False
                    providers.storage.unpublish_domain(other.domain)
            row.serve_website = True
            website.url = f"{self.settings.custom_domain_scheme}://{row.domain}/"
        else:
            row.serve_website = False
            providers.storage.unpublish_domain(row.domain)
            website.url = self.settings.site_url(website.subdomain)
        self.db.flush()
        self._republish(website, actor)  # canonical URLs, sitemap and the domain copy follow the change
        self.db.commit()
        return row

    def remove(self, row: CustomDomain, actor: Actor) -> None:
        if row.serve_website:
            self.set_serving(row, False, actor)
        from app.services.mail_service import MailService  # local import: mail depends on domains

        MailService(self.db, self.settings).disable_for_domain(row)
        self.db.delete(row)
        self.db.commit()

    # --- Platform ----------------------------------------------------------------------------
    def serving_domains(self, business_id: uuid.UUID) -> list[str]:
        return list(self.db.scalars(select(CustomDomain.domain).where(
            CustomDomain.business_id == business_id, CustomDomain.serve_website.is_(True),
            CustomDomain.status == DomainStatus.VERIFIED)))

    def allows_certificate(self, host: str) -> bool:
        """Caddy on-demand TLS `ask`: only issue certificates for verified domains we serve."""
        host = host.lower().rstrip(".")
        apex = host[4:] if host.startswith("www.") else host
        return bool(self.db.scalar(select(CustomDomain.id).where(
            CustomDomain.domain == apex, CustomDomain.status == DomainStatus.VERIFIED,
            CustomDomain.serve_website.is_(True))))

    def enforce_plan(self, business_id: uuid.UUID, actor: Actor) -> int:
        """After a downgrade, stop serving domains the plan no longer includes."""
        features, _ = plan_for_business(self.db, business_id)
        if has_feature(features, Feature.CUSTOM_DOMAIN):
            return 0
        serving = [d for d in self.domains(business_id) if d.serve_website]
        for row in serving:
            self.set_serving(row, False, actor)
        return len(serving)

    def recheck(self, actor: Actor, now: datetime | None = None) -> dict[str, int]:
        """Hourly maintenance: re-verify domains daily (a removed TXT record means the owner or a new
        domain holder revoked us), and release never-verified claims after the grace period."""
        now = now or datetime.now(UTC)
        stats = {"checked": 0, "failed": 0, "released": 0}
        cutoff = now - timedelta(days=self.settings.domain_pending_days)
        for row in self.db.scalars(select(CustomDomain).where(CustomDomain.status != DomainStatus.VERIFIED,
                                                              CustomDomain.created_at < cutoff)).all():
            self.db.delete(row)
            stats["released"] += 1
        due = now - timedelta(hours=self.settings.domain_recheck_hours)
        rows = self.db.scalars(select(CustomDomain).where(
            CustomDomain.status == DomainStatus.VERIFIED,
            (CustomDomain.last_checked_at.is_(None)) | (CustomDomain.last_checked_at < due)).limit(200)).all()
        for row in rows:
            record = verification_record(row.domain, row.verification_token)
            try:
                values = providers.dns.txt(record.name)
            except DnsError as exc:  # resolver trouble is not evidence the owner revoked us
                logger.warning("DNS recheck of %s failed: %s", row.domain, exc)
                continue
            row.last_checked_at = now
            stats["checked"] += 1
            if not is_verified(values, row.verification_token):
                row.status, row.last_error = DomainStatus.FAILED, "The verification record was removed."
                stats["failed"] += 1
                if row.serve_website:
                    self.set_serving(row, False, actor)
                self._notify_failed(row)
        self.db.commit()
        return stats

    # --- Helpers -----------------------------------------------------------------------------
    def _website(self, business_id: uuid.UUID) -> Website:
        business = self.db.get(Business, business_id)
        if business is None or business.website_record is None:
            raise NotFoundError("This business has no website yet")
        return business.website_record

    def _republish(self, website: Website, actor: Actor) -> None:
        from app.services.publishing_service import PublishingService  # local import: avoids a cycle

        if website.published_at:
            PublishingService(self.db, self.settings).publish(website, actor, force=True)

    def _notify_failed(self, row: CustomDomain) -> None:
        business = self.db.get(Business, row.business_id)
        if business and business.email:
            providers.email.send(EmailMessage(
                to=business.email, subject=f"{row.domain} is no longer connected to your website",
                text=(f"We could no longer find the verification record for {row.domain}, so your website is "
                      f"back on its GumaWeb address. Add the record again and re-verify the domain in your "
                      f"portal to reconnect it."),
            ))
