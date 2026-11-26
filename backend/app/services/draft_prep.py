"""Draft preparation (A7b): polish review + preview images, between "draft built" and "first email".

Queued (`prepare_draft`) when an auto-compiled draft enters the pipeline. A draft the review passes becomes
outreach-ready; the engine only emails ready drafts. One that fails is held with its issues for an operator, who can
fix the content and re-run, or approve it by hand. Images are captured when a capture backend is configured; a
failed capture never holds a draft back (the email just goes without a picture).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.domains.website_factory.enums import ContentSource
from app.domains.website_factory.polish import review_draft
from app.models import DraftPreview, Website
from app.repositories.repositories import WebsiteRepository
from app.services.providers import providers
from app.services.support import Actor

logger = logging.getLogger("gumaweb.drafts")
PREFIX = "_assets/previews"  # object storage keeps non-site files under _assets/


class DraftPrep:
    def __init__(self, db: Session, settings: Settings, now: datetime | None = None) -> None:
        self.db = db
        self.settings = settings
        self.now = now or datetime.now(UTC)
        self.websites = WebsiteRepository(db)

    def for_website(self, website_id) -> DraftPreview | None:
        return self.db.scalar(select(DraftPreview).where(DraftPreview.website_id == website_id))

    def _row(self, website: Website) -> DraftPreview:
        row = self.for_website(website.id)
        if row is None:
            row = DraftPreview(website_id=website.id, token=secrets.token_urlsafe(24), review={})
            self.db.add(row)
            self.db.flush()
        return row

    def prepare(self, website: Website) -> DraftPreview:
        """Review the draft and (if it passes and a backend is set) capture its preview images. Doesn't commit."""
        row = self._row(website)
        business = website.business
        rows = self.websites.content_map(website.id)
        content = {k: r.content for k, r in rows.items()}
        generated = frozenset(k for k, r in rows.items() if r.source == ContentSource.AI)
        contact = content.get("contact") or {}
        profile = business.profile
        facts = " ".join(str(v) for v in (business.name, business.city, business.province, business.address,
                                          business.phone, business.email, business.description,
                                          *(profile.services if profile else [])) if v)
        review = review_draft(website.quality_report, content, known_facts=facts,
                              has_contact=bool(contact.get("phone") or contact.get("email") or business.phone
                                               or business.email),
                              min_readability=self.settings.content_min_readability,
                              max_spam=self.settings.content_max_spam, generated=generated)
        row.review = review.as_dict()
        row.reviewed_at = self.now
        row.ready = review.ready or row.approved_by is not None
        if row.ready:
            self.capture(website, row)
        return row

    def capture(self, website: Website, row: DraftPreview) -> None:
        capture = providers.previews
        if capture.name == "none":
            return
        from app.services.publishing_service import PublishingService  # local: publishing imports claims

        try:
            files = PublishingService(self.db, self.settings).render(website, website.version, preview=True)
            shots = capture.capture(files)
        except Exception as exc:  # a missing browser or a bad page must not hold the draft back
            logger.exception("preview capture failed for %s", website.subdomain)
            row.capture_error = str(exc)[:500]
            return
        for shot in shots:
            ext = "jpg" if shot.mime == "image/jpeg" else "png"
            key = f"{PREFIX}/{website.id}/{shot.kind}-{secrets.token_hex(6)}.{ext}"
            providers.storage.put_object(key, shot.data, shot.mime)
            setattr(row, f"{shot.kind}_key", key)
        row.captured_at = self.now
        row.capture_error = None

    def approve(self, website: Website, actor: Actor) -> DraftPreview:
        """An operator vouches for a held draft: it becomes outreach-ready despite the review."""
        row = self._row(website)
        row.approved_by = actor.user_id
        row.ready = True
        if not row.captured_at:
            self.capture(website, row)
        return row

    def image(self, token: str, kind: str) -> tuple[bytes, str]:
        row = self.db.scalar(select(DraftPreview).where(DraftPreview.token == token))
        key = getattr(row, f"{kind}_key", None) if row is not None and kind in ("desktop", "phone") else None
        if key is None:
            raise NotFoundError("Not found")
        try:
            data = providers.storage.get_object(key)
        except (FileNotFoundError, OSError) as exc:
            raise NotFoundError("Not found") from exc
        return data, "image/jpeg" if key.endswith(".jpg") else "image/png"

    def image_urls(self, row: DraftPreview | None) -> dict[str, str]:
        if row is None:
            return {}
        base = f"{self.settings.api_public_url.rstrip('/')}{self.settings.api_v1_prefix}/public/previews/{row.token}"
        return {kind: f"{base}/{kind}" for kind in ("desktop", "phone") if getattr(row, f"{kind}_key")}


def run_prepare_job(db: Session, settings: Settings, payload: dict) -> dict:
    """Factory worker handler for JobKind.PREPARE_DRAFT."""
    import uuid

    website = db.get(Website, uuid.UUID(payload["website_id"]))
    if website is None:
        return {"skipped": "website deleted"}
    row = DraftPrep(db, settings).prepare(website)
    db.commit()
    return {"ready": row.ready, "images": bool(row.desktop_key), "issues": len(row.review.get("issues", []))}
