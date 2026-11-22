"""WebsiteFactory application service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.customers.content_policy import referenced_assets, validate_section_update
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.domains.website_factory.jobs import JobKind
from app.domains.website_factory.quality import REQUIRED_FIELDS
from app.models import Business, Deployment, Website
from app.repositories.repositories import BusinessRepository, WebsiteRepository
from app.schemas.website import BatchResult, GenerateBatchRequest, GenerateWebsiteRequest, RegenerateWebsiteRequest
from app.services.asset_service import AssetService
from app.services.job_queue import JobQueue
from app.services.publishing_service import PublishingService
from app.services.support import Actor, audit
from app.workflows.website_generation import WebsiteGenerationWorkflow


class WebsiteService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.websites = WebsiteRepository(db)
        self.businesses = BusinessRepository(db)
        self.workflow = WebsiteGenerationWorkflow(db, settings)
        self.publishing = PublishingService(db, settings)

    def generate(self, req: GenerateWebsiteRequest, actor: Actor) -> Website:
        business = self.businesses.get_or_404(req.business_id)
        if self.websites.by_business(business.id):
            raise ConflictError("Website already exists for this business; use regenerate")
        website = self.workflow.run(business, template_slug=req.template_slug)
        audit(self.db, actor, AuditAction.WEBSITE_GENERATED, "website", website.id)
        if req.publish:
            self.publishing.publish(website, actor)
        self.db.commit()
        return website

    def regenerate(self, website: Website, req: RegenerateWebsiteRequest, actor: Actor) -> Website:
        self.workflow.run(website.business, template_slug=req.template_slug, reset_content=req.reset_content)
        audit(self.db, actor, AuditAction.WEBSITE_GENERATED, "website", website.id, {"regenerate": True})
        if req.publish or website.status == WebsiteStatus.PUBLISHED:
            self.publishing.publish(website, actor)
        self.db.commit()
        return website

    def publish(self, website: Website, actor: Actor, force: bool = False) -> Deployment:
        deployment = self.publishing.publish(website, actor, force=force)
        self.db.commit()
        return deployment

    def unpublish(self, website: Website, actor: Actor) -> Website:
        self.publishing.unpublish(website, actor)
        self.db.commit()
        return website

    def list(self, status: WebsiteStatus | None, page: int, page_size: int):
        stmt = (
            select(Website)
            .options(joinedload(Website.business), joinedload(Website.template))
            .order_by(Website.created_at.desc())
        )
        if status:
            stmt = stmt.where(Website.status == status)
        return self.websites.paginate(stmt, page, page_size)

    def update_content(self, website: Website, section_key: str, updates: dict[str, Any], actor: Actor,
                       source: ContentSource, republish: bool) -> Website:
        clean = validate_section_update(section_key, updates)
        AssetService(self.db, self.settings).ensure_usable(website.business_id, referenced_assets(clean))
        row = self.websites.content_map(website.id).get(section_key)
        if row is None:
            raise ValidationFailedError(f"Website has no '{section_key}' section")
        merged = {**row.content, **clean}
        missing = [f for f in REQUIRED_FIELDS.get(section_key, ()) if not merged.get(f)]
        if missing:
            raise ValidationFailedError(f"Required fields cannot be empty: {', '.join(missing)}")
        row.content = merged
        row.source = source
        row.updated_by = actor.user_id
        self.workflow.validate(website)
        audit(self.db, actor, AuditAction.CONTENT_UPDATED, "website", website.id,
              {"section": section_key, "fields": sorted(clean)})
        if republish and website.status == WebsiteStatus.PUBLISHED:
            self.publishing.publish(website, actor)
        self.db.commit()
        return website

    def enqueue_batch(self, req: GenerateBatchRequest) -> BatchResult:
        """Factory batch: queue generation jobs; workers do the (possibly AI-heavy) work."""
        if req.business_ids:
            ids = list(dict.fromkeys(req.business_ids))
        else:
            has_site = select(Website.business_id)
            ids = list(self.db.scalars(
                select(Business.id)
                .where(Business.generate_candidate.is_(True), Business.id.not_in(has_site))
                .order_by(Business.score.desc().nulls_last())
                .limit(req.limit)
            ))
        queue = JobQueue(self.db)
        enqueued = 0
        for business_id in ids:
            job = queue.enqueue(JobKind.GENERATE_WEBSITE, {"business_id": str(business_id), "publish": req.publish},
                                dedupe_key=f"generate:{business_id}", priority=req.priority)
            enqueued += job is not None
        self.db.commit()
        return BatchResult(enqueued=enqueued, skipped=len(ids) - enqueued)

    def for_business(self, business: Business) -> Website | None:
        return self.websites.by_business(business.id)

    def get_or_404(self, website_id: uuid.UUID) -> Website:
        return self.websites.get_or_404(website_id)
