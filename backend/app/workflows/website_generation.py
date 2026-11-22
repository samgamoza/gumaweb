"""Website Assembly Pipeline (09):

Business Profile → Template Selection → Component Selection → Content Injection
→ Image Assignment → SEO Generation → Quality Validation → (Build/Publish)

Each step is a method. In Phase 2 the pipeline runs inside factory workers
(app.workers.factory_worker) because AI content makes it long-running; the API
enqueues jobs instead of blocking a request.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.registry import get_content_generator
from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.business_discovery.enums import BusinessStatus
from app.domains.business_discovery.lifecycle import advance
from app.domains.business_profile.industry_catalog import get_industry
from app.domains.publishing.subdomain import subdomain_candidates
from app.domains.seo.audit import audit_site
from app.domains.seo.generator import SeoInput, generate_page_meta, generate_seo
from app.domains.template_management.enums import TemplateStatus
from app.domains.website_factory.blueprint import (
    BlueprintBusiness,
    BlueprintTemplate,
    build_blueprint,
    content_keys,
)
from app.domains.website_factory.content import ContentContext
from app.domains.website_factory.enums import ContentSource, WebsiteStatus
from app.domains.website_factory.images import asset_seed
from app.domains.website_factory.quality import validate_site
from app.models import Business, BusinessProfile, SeoMetadata, Template, Website, WebsiteContent
from app.repositories.repositories import WebsiteRepository
from app.services.ai_store import AIGenerationStore
from app.services.asset_service import AssetService
from app.services.business_service import ProfileService
from app.services.providers import providers
from app.services.support import EventType, record_event
from app.services.template_service import TemplateService

REGENERABLE_SOURCES = (ContentSource.TEMPLATE, ContentSource.AI)


class WebsiteGenerationWorkflow:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.websites = WebsiteRepository(db)
        self.templates = TemplateService(db, settings)
        self.profiles = ProfileService(db, settings)
        self.assets = AssetService(db, settings)
        self.content_generator = get_content_generator(settings, AIGenerationStore(db))

    def run(self, business: Business, *, template_slug: str | None = None,
            reset_content: bool = False) -> Website:
        if business.status == BusinessStatus.ARCHIVED:
            raise ValidationFailedError("Archived businesses cannot be generated")
        profile = self.profiles.ensure(business)
        website = self.websites.by_business(business.id)
        template = self._choose_template(business, profile, website, template_slug)
        profile.recommended_template = template.slug

        website = website or self._allocate_website(business)
        website.template_id = template.id
        website.template = template
        website.blueprint = self._build_blueprint(business, profile, template, website)
        notes = self._inject_content(website, business, profile, reset_content)
        self._assign_images(website, profile, template)
        self._generate_seo(website, business, profile)
        self.validate(website)
        website.quality_report = {**(website.quality_report or {}), "content_notes": notes,
                                  "content_generator": self.content_generator.name}

        website.generated_at = datetime.now(UTC)
        business.status = advance(business.status, BusinessStatus.GENERATED)
        record_event(self.db, EventType.WEBSITE_GENERATED, "website", website.id,
                     {"business_id": str(business.id), "template": template.slug,
                      "generator": self.content_generator.name})
        self.db.flush()
        return website

    def refresh_business_facts(self, website: Website) -> None:
        """Rebuild blueprint + SEO after business details change, keeping content."""
        business = website.business
        profile = self.profiles.ensure(business)
        template = website.template or self.templates.select_for(profile.industry, profile.category)
        website.blueprint = self._build_blueprint(business, profile, template, website)
        self._generate_seo(website, business, profile)
        self.validate(website)
        self.db.flush()

    # --- Steps ----------------------------------------------------------------------
    def _choose_template(self, business: Business, profile: BusinessProfile, website: Website | None,
                         requested: str | None) -> Template:
        # Regeneration keeps the site's look unless an operator explicitly asks for another template.
        if not requested and website and website.template and website.template.status == TemplateStatus.ACTIVE:
            return website.template
        return self.templates.select_for(profile.industry, profile.category, requested,
                                         variety_seed=asset_seed(str(business.id)))

    def _allocate_website(self, business: Business) -> Website:
        for candidate in subdomain_candidates(business.slug, business.city):
            if not self.websites.subdomain_taken(candidate):
                website = Website(
                    business=business, subdomain=candidate, url=self.settings.site_url(candidate),
                    status=WebsiteStatus.DRAFT,
                )
                return self.websites.add(website)
        raise ConflictError("Unable to allocate a subdomain")

    def _build_blueprint(self, business: Business, profile: BusinessProfile, template: Template,
                         website: Website) -> dict:
        spec = get_industry(profile.industry)
        return build_blueprint(
            subdomain=website.subdomain,
            business=BlueprintBusiness(
                name=business.name, industry=profile.industry, industry_label=spec.label,
                city=business.city, province=business.province, address=business.address,
                phone=business.phone, email=business.email, facebook=business.facebook,
            ),
            template=BlueprintTemplate(
                slug=template.slug, version=template.version, category=template.category,
                pages=template.pages, theme=template.theme,
            ),
            services=list(profile.services),
            brand_tone=profile.brand_tone,
            claimed=website.is_claimed,
        )

    def _inject_content(self, website: Website, business: Business, profile: BusinessProfile,
                        reset: bool) -> list[str]:
        ctx = ContentContext(
            name=business.name, industry=profile.industry, city=business.city, province=business.province,
            address=business.address, phone=business.phone, email=business.email, facebook=business.facebook,
            services=list(profile.services), target_audience=profile.target_audience,
            brand_tone=profile.brand_tone,
        )
        existing = self.websites.content_map(website.id)
        keys = content_keys(website.blueprint or {})
        # Only ask the generator for sections we would actually overwrite (saves tokens).
        regenerate = {k for k in keys if reset or k not in existing or existing[k].source in REGENERABLE_SOURCES}
        result = self.content_generator.generate(ctx, regenerate)
        for key, block in result.blocks.items():
            row = existing.get(key)
            source = result.sources.get(key, ContentSource.TEMPLATE)
            if row is None:
                self.db.add(WebsiteContent(website=website, section_key=key, content=block, source=source))
            else:
                image = row.content.get("image") if isinstance(row.content, dict) else None
                row.content = {**block, **({"image": image} if image else {})}
                row.source = source
        self.db.flush()
        return result.notes

    def _assign_images(self, website: Website, profile: BusinessProfile, template: Template) -> None:
        """Image Assignment: decorative hero artwork from the shared library (owner photos take precedence)."""
        hero = self.websites.content_map(website.id).get("hero")
        if hero is None or (hero.content.get("image") or {}).get("source") == "upload":
            return
        asset = self.assets.library_image(
            industry=profile.industry, category="hero", palette=(template.theme or {}).get("palette", {}),
            style=template.slug, variety_seed=str(website.business_id),
        )
        hero.content = {**hero.content, "image": {"asset_id": str(asset.id), "alt": "", "source": "library"}}
        self.db.flush()

    def _generate_seo(self, website: Website, business: Business, profile: BusinessProfile) -> None:
        seo = generate_seo(
            SeoInput(
                name=business.name, industry=profile.industry, city=business.city, province=business.province,
                address=business.address, phone=business.phone, email=business.email,
                facebook=business.facebook, services=list(profile.services), keywords=list(profile.keywords),
                local_keywords=list(profile.local_keywords), site_url=website.url or "",
            )
        )
        content = {k: row.content for k, row in self.websites.content_map(website.id).items()}
        seo["pages"] = generate_page_meta(
            (website.blueprint or {}).get("pages", []), content, business.name, profile.industry, business.city,
            seo["page_title"], seo["meta_description"],
        )
        if website.seo is None:
            website.seo = SeoMetadata(**seo)
        else:
            for field, value in seo.items():
                setattr(website.seo, field, value)
        self.db.flush()

    def validate(self, website: Website) -> None:
        content = {k: row.content for k, row in self.websites.content_map(website.id).items()}
        seo = website.seo
        report = validate_site(
            website.blueprint or {},
            content,
            {"page_title": seo.page_title, "meta_description": seo.meta_description} if seo else None,
            providers.renderer.available_components(),
        )
        notes = (website.quality_report or {}).get("content_notes", [])
        website.quality_score = report.score
        website.quality_report = {**report.as_dict(), "content_notes": notes}
        if seo is not None:
            business = website.business
            seo.audit = audit_site(
                blueprint=website.blueprint or {}, content=content,
                seo={"page_title": seo.page_title, "meta_description": seo.meta_description,
                     "local_keywords": seo.local_keywords, "schema_markup": seo.schema_markup, "pages": seo.pages},
                business={"address": business.address, "email": business.email, "phone": business.phone},
            )
        if website.status != WebsiteStatus.PUBLISHED:
            website.status = WebsiteStatus.BLUEPRINT_READY if report.checks["layout_valid"] else WebsiteStatus.FAILED
