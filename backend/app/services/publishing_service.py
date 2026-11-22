"""Publishing: Build Website → Upload Artifacts → Generate Metadata → Publish.

DNS: production uses a wildcard record (*.gumaweb.io) + wildcard TLS, so no
per-site DNS call is needed; custom domains (Professional plan) are a Phase 2
step handled by cert-manager.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import GumaWebError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery.enums import BusinessStatus
from app.domains.business_discovery.lifecycle import advance
from app.domains.publishing.enums import DeploymentStatus
from app.domains.publishing.renderer import RenderContext
from app.domains.website_factory.enums import WebsiteStatus
from app.domains.website_factory.jobs import JobKind
from app.models import Deployment, Website
from app.repositories.repositories import WebsiteRepository
from app.services.asset_service import AssetService, extension_for
from app.services.domain_service import DomainService
from app.services.job_queue import JobQueue
from app.services.providers import providers
from app.services.support import Actor, EventType, audit, record_event

logger = logging.getLogger("gumaweb.publishing")


class PublishFailedError(GumaWebError):
    status_code = 502
    code = "publish_failed"


class PublishingService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.websites = WebsiteRepository(db)

    def claim_url(self, website: Website) -> str:
        return f"{self.settings.frontend_url.rstrip('/')}/claim/{website.subdomain}"

    def render(self, website: Website, version: int) -> dict[str, bytes]:
        if not website.blueprint or website.seo is None:
            raise ValidationFailedError("Website has no blueprint; generate it first")
        blueprint = {**website.blueprint, "claim_banner": not website.is_claimed}
        content = {k: row.content for k, row in self.websites.content_map(website.id).items()}
        seo = {
            "page_title": website.seo.page_title,
            "meta_description": website.seo.meta_description,
            "keywords": website.seo.keywords,
            "local_keywords": website.seo.local_keywords,
            "schema_markup": website.seo.schema_markup,
            "pages": website.seo.pages or {},
        }
        return providers.renderer.render(
            RenderContext(
                website_id=str(website.id), blueprint=blueprint, content=content, seo=seo,
                site_url=website.url or self.settings.site_url(website.subdomain),
                api_url=self.settings.api_public_url.rstrip("/"), claim_url=self.claim_url(website),
                version=version, assets=self._bundle_assets(content),
            )
        )

    def _bundle_assets(self, content: dict) -> dict[str, tuple[str, bytes]]:
        """Copy every referenced image into the build, so each site is fully self-contained."""
        refs = []
        for block in content.values():
            if isinstance(block.get("image"), dict):
                refs.append(block["image"].get("asset_id"))
            refs += [i.get("asset_id") for i in block.get("images", []) if isinstance(i, dict)]
        loaded = AssetService(self.db, self.settings).load(r for r in refs if r)
        return {
            asset_id: (f"assets/img/{asset_id}.{extension_for(asset.mime_type)}", data)
            for asset_id, (asset, data) in loaded.items()
        }

    def publish(self, website: Website, actor: Actor, force: bool = False) -> Deployment:
        report = website.quality_report or {}
        if not force and not report.get("publishable"):
            issues = "; ".join(report.get("issues", [])) or "quality report missing"
            raise ValidationFailedError(f"Quality gate failed: {issues}")

        version = website.version + 1
        storage = providers.storage
        deployment = Deployment(website_id=website.id, version=version, storage_backend=storage.name,
                                triggered_by=actor.user_id)
        self.db.add(deployment)
        self.db.flush()
        try:
            files = self.render(website, version)
            result = storage.publish(website.subdomain, version, files)
            for domain in DomainService(self.db, self.settings).serving_domains(website.business_id):
                storage.publish_domain(domain, files)  # same build, served at the owner's domain
        except Exception as exc:
            logger.exception("publish failed for %s", website.subdomain)
            deployment.status = DeploymentStatus.FAILED
            deployment.error = str(exc)[:2000]
            deployment.finished_at = datetime.now(UTC)
            self.db.commit()
            raise PublishFailedError(f"Publishing failed: {exc}") from exc

        now = datetime.now(UTC)
        deployment.status = DeploymentStatus.SUCCEEDED
        deployment.artifact_path = result.artifact_path
        deployment.file_count = result.file_count
        deployment.size_bytes = result.size_bytes
        deployment.finished_at = now
        website.version = version
        website.status = WebsiteStatus.PUBLISHED
        website.published_at = now
        website.artifact_path = result.artifact_path
        website.url = website.url or self.settings.site_url(website.subdomain)
        website.business.status = advance(website.business.status, BusinessStatus.PUBLISHED)
        record_event(self.db, EventType.WEBSITE_PUBLISHED, "website", website.id,
                     {"version": version, "url": website.url})
        # Phase 5: the presence kit is rebuilt from the published facts (copy only; images render lazily).
        JobQueue(self.db).enqueue(JobKind.GENERATE_PRESENCE, {"business_id": str(website.business_id)},
                                  dedupe_key=f"presence:{website.business_id}", priority=120)
        audit(self.db, actor, AuditAction.WEBSITE_PUBLISHED, "website", website.id, {"version": version})
        self.db.flush()
        return deployment

    def unpublish(self, website: Website, actor: Actor) -> None:
        providers.storage.unpublish(website.subdomain)
        website.status = WebsiteStatus.UNPUBLISHED
        record_event(self.db, EventType.WEBSITE_UNPUBLISHED, "website", website.id)
        audit(self.db, actor, AuditAction.WEBSITE_UNPUBLISHED, "website", website.id)
        self.db.flush()
