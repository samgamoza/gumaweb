"""Private claim links (A7, owner-triggered publishing): `/start/<token>`.

A qualified lead's site stays a private draft until its owner claims it. Each outreach email carries a fresh link
(only its hash is stored) that opens the full draft preview with a short details form:

* opening the link records the click (the outreach message's `link_clicked`, so the playbook and stats see it);
* the first saved answer records `claim_started`; name, description, address, Facebook page and services update the
  draft at once and re-render the preview;
* phone and email are what verification relies on, so they only show on the draft's contact section and wait in
  the link's `answers` until ownership is proven (`ClaimService._apply_owner_answers`);
* claiming goes through the normal claim checks (`ClaimService.start(from_link=True)`). Claiming with the email (or
  by SMS, the phone) on record is approved at once and **publishes the site at claim**; anyone else, such as someone
  the email was forwarded to, goes to manual review.

The preview is rendered on request from the draft (never written to public storage) and served with `noindex`.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import GumaWebError, NotFoundError
from app.core.security import generate_url_token, hash_token
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery.normalization import normalize_phone, normalize_url
from app.domains.business_profile.enums import ProfileSource
from app.domains.outreach.enums import OutreachEventType
from app.domains.sales import ActivityType
from app.models import Claim, ClaimLink, OutreachMessage, Website
from app.repositories.repositories import WebsiteRepository
from app.schemas.claim import ClaimStart
from app.schemas.start import StartClaim, StartDetails, StartDetailsUpdate, StartInfo
from app.services.claim_service import ClaimService
from app.services.prospect_service import ProspectService
from app.services.support import Actor, audit

DIRECT_FIELDS = ("name", "description", "address", "facebook")  # applied to the draft at once
SERVICE_SECTIONS = {"hero", "services", "about", "faq"}  # generated copy that lists the services
PENDING_FIELDS = ("phone", "email")  # verification relies on these: applied at ownership transfer
_PREVIEWS: OrderedDict[str, dict[str, bytes]] = OrderedDict()  # rendered drafts by content fingerprint
_PREVIEW_CACHE_SIZE = 32


def _renamed(value: Any, old: str, new: str) -> Any:
    """Replace the business name in every string of a content block (copy written with the old name)."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_renamed(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: v if k in ("asset_id", "path", "url") else _renamed(v, old, new) for k, v in value.items()}
    return value


class LinkExpiredError(GumaWebError):
    status_code = 410
    code = "link_expired"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[0]}{'*' * max(1, len(local) - 1)}@{domain}"


def _mask_phone(phone: str | None) -> str | None:
    return f"{'*' * max(0, len(phone) - 4)}{phone[-4:]}" if phone else None


class ClaimLinkService:
    def __init__(self, db: Session, settings: Settings, now: datetime | None = None) -> None:
        self.db = db
        self.settings = settings
        self.now = now or datetime.now(UTC)
        self.websites = WebsiteRepository(db)

    # --- Issue / resolve ---------------------------------------------------------------------------
    def start_url(self, token: str) -> str:
        return f"{self.settings.frontend_url.rstrip('/')}/start/{token}"

    def preview_url(self, token: str) -> str:
        return f"{self.settings.api_public_url.rstrip('/')}{self.settings.api_v1_prefix}/public/start/{token}/site/"

    def issue(self, website: Website, message_id: uuid.UUID | None = None) -> tuple[ClaimLink, str]:
        """A fresh link for this draft (doesn't commit). Returns the link and its token, which is never stored."""
        token = generate_url_token()
        link = ClaimLink(business_id=website.business_id, website_id=website.id, message_id=message_id,
                         token_hash=hash_token(token),
                         expires_at=self.now + timedelta(days=self.settings.claim_link_ttl_days), answers={})
        self.db.add(link)
        self.db.flush()
        return link, token

    def resolve(self, token: str) -> tuple[ClaimLink, Website]:
        link = self.db.scalar(select(ClaimLink).where(ClaimLink.token_hash == hash_token(token)))
        website = self.db.get(Website, link.website_id) if link else None
        if link is None or website is None:
            raise NotFoundError("This link isn't valid")
        if _utc(link.expires_at) < self.now and not website.is_claimed:
            raise LinkExpiredError("This link has expired. Reply to our email and we'll send you a new one.")
        return link, website

    # --- Owner actions -----------------------------------------------------------------------------
    def open(self, token: str) -> StartInfo:
        """The owner opened the link: count it (the first open is the click) and describe the draft."""
        link, website = self.resolve(token)
        first = link.first_opened_at is None
        link.open_count = (link.open_count or 0) + 1
        link.last_opened_at = self.now
        if first:
            link.first_opened_at = self.now
            message = self.db.get(OutreachMessage, link.message_id) if link.message_id else None
            if message is not None:  # same events as a tracked click: stats, timeline, playbook
                from app.services.outreach_service import OutreachService  # local: outreach imports this module

                outreach = OutreachService(self.db, self.settings)
                outreach._event(message, OutreachEventType.LINK_CLICKED)
                outreach._event(message, OutreachEventType.WEBSITE_VISITED)
            else:
                ProspectService(self.db).record(website.business_id, ActivityType.LINK_CLICKED,
                                                external_id=f"claimlink:{link.id}:opened", occurred_at=self.now)
        self.db.commit()
        return self.info(token, link, website)

    def info(self, token: str, link: ClaimLink, website: Website) -> StartInfo:
        business = website.business
        pending = (link.answers or {}).get("pending") or {}
        profile = business.profile
        return StartInfo(
            business_name=business.name, industry=business.industry, city=business.city,
            province=business.province, status="claimed" if website.is_claimed else "ready",
            expires_at=link.expires_at, preview_url=self.preview_url(token),
            masked_email=_mask_email(business.email), masked_phone=_mask_phone(business.phone),
            details=StartDetails(name=business.name, description=business.description, address=business.address,
                                 facebook=business.facebook, services=list(profile.services) if profile else [],
                                 phone=pending.get("phone"), email=pending.get("email")),
            pending_claim=self._pending_claim(website),
        )

    def save_details(self, token: str, data: StartDetailsUpdate, actor: Actor) -> StartInfo:
        from app.workflows.website_generation import WebsiteGenerationWorkflow  # local: heavy import

        link, website = self.resolve(token)
        if website.is_claimed:
            raise NotFoundError("This website has already been claimed")
        business = website.business
        old_name = business.name
        changes = data.model_dump(exclude_unset=True)
        if "facebook" in changes:
            changes["facebook"] = normalize_url(changes["facebook"]) if changes["facebook"] else None
        if changes.get("phone"):
            changes["phone"] = normalize_phone(changes["phone"], self.settings.default_country_code)
        if changes.get("email"):
            changes["email"] = changes["email"].lower()

        if link.form_started_at is None:
            link.form_started_at = self.now
            ProspectService(self.db).record(website.business_id, ActivityType.CLAIM_STARTED,
                                            external_id=f"claimlink:{link.id}:form", occurred_at=self.now,
                                            data={"via": "claim_link"})
        for field in DIRECT_FIELDS:
            if field in changes and (changes[field] or field != "name"):
                setattr(business, field, changes[field] or None)
        workflow = WebsiteGenerationWorkflow(self.db, self.settings)
        if data.services is not None:
            profile = workflow.profiles.ensure(business)
            profile.services = [s.strip() for s in data.services if s.strip()][:12]
            profile.source = ProfileSource.MANUAL  # owner-supplied: never re-profiled over
        pending = {**((link.answers or {}).get("pending") or {}),
                   **{k: changes[k] for k in PENDING_FIELDS if k in changes}}
        link.answers = {**(link.answers or {}), "pending": pending,
                        "fields": sorted(set((link.answers or {}).get("fields", [])) | set(changes))}

        contact = self.websites.content_map(website.id).get("contact")
        if contact:
            synced = {k: changes[k] for k in ("address", "facebook", *PENDING_FIELDS) if k in changes}
            contact.content = {**contact.content, **synced}
        if data.services is not None:
            workflow.rewrite_template_sections(website, SERVICE_SECTIONS)
        if business.name != old_name:
            for row in self.websites.content_map(website.id).values():
                row.content = _renamed(row.content, old_name, business.name)
        workflow.refresh_business_facts(website)
        audit(self.db, actor, AuditAction.BUSINESS_UPDATED, "business", business.id,
              {"fields": sorted(changes), "by": "claim_link"})
        self.db.commit()
        return self.info(token, link, website)

    def claim(self, token: str, data: StartClaim, actor: Actor) -> Claim:
        link, website = self.resolve(token)
        message = self.db.get(OutreachMessage, link.message_id) if link.message_id else None
        start = ClaimStart(subdomain=website.subdomain, claimant_name=data.claimant_name,
                           claimant_email=data.claimant_email, claimant_phone=data.claimant_phone,
                           method=data.method, ref=message.tracking_token if message else None)
        return ClaimService(self.db, self.settings).start(start, actor, from_link=True)

    def _pending_claim(self, website: Website) -> str | None:
        from app.domains.claims.enums import ClaimStatus

        status = self.db.scalar(select(Claim.status).where(
            Claim.business_id == website.business_id,
            Claim.status.in_([ClaimStatus.PENDING_VERIFICATION, ClaimStatus.MANUAL_REVIEW]))
            .order_by(Claim.created_at.desc()).limit(1))
        return status.value if status else None

    # --- Preview -----------------------------------------------------------------------------------
    def preview_file(self, token: str, path: str) -> tuple[bytes, str]:
        """One file of the rendered draft. Relative links in the build resolve under the same prefix."""
        from app.services.publishing_service import PublishingService  # local: publishing imports claims

        _, website = self.resolve(token)
        files = self._rendered(website, PublishingService(self.db, self.settings))
        key = path.lstrip("/")
        if key == "" or key.endswith("/"):
            key += "index.html"
        data = files.get(key) or files.get(f"{key}/index.html")
        if data is None or key in ("robots.txt", "sitemap.xml", "site.json"):
            raise NotFoundError("Not found")
        return data, mimetypes.guess_type(key)[0] or "application/octet-stream"

    def _rendered(self, website: Website, publishing: Any) -> dict[str, bytes]:
        content = {k: row.content for k, row in sorted(self.websites.content_map(website.id).items())}
        seo = website.seo
        fingerprint = hashlib.sha256(json.dumps(
            [str(website.id), website.blueprint, content, seo.page_title if seo else None,
             seo.meta_description if seo else None, seo.pages if seo else None],
            sort_keys=True, default=str).encode()).hexdigest()
        if fingerprint in _PREVIEWS:
            _PREVIEWS.move_to_end(fingerprint)
            return _PREVIEWS[fingerprint]
        files = publishing.render(website, website.version, preview=True)
        _PREVIEWS[fingerprint] = files
        while len(_PREVIEWS) > _PREVIEW_CACHE_SIZE:
            _PREVIEWS.popitem(last=False)
        return files
