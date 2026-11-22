from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.template_management.manifest import (
    ManifestError,
    discover_components,
    load_manifests,
    parse_manifest,
)
from app.domains.template_management.resolver import TemplateCandidate, select_template
from app.models import Template, TemplateComponent
from app.repositories.repositories import TemplateComponentRepository, TemplateRepository
from app.schemas.template import TemplateCreate, TemplateSyncResult, TemplateUpdate
from app.services.support import Actor, audit


class TemplateService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.templates = TemplateRepository(db)
        self.components = TemplateComponentRepository(db)

    def list(self, category: str | None = None) -> Sequence[Template]:
        return self.templates.all(category)

    def _validate(self, payload: dict) -> None:
        try:
            parse_manifest(payload)
        except ManifestError as exc:
            raise ValidationFailedError(str(exc)) from exc

    def _clear_other_defaults(self, template: Template) -> None:
        self.db.execute(
            update(Template)
            .where(Template.category == template.category, Template.id != template.id)
            .values(is_default=False)
        )

    def create(self, data: TemplateCreate, actor: Actor) -> Template:
        if self.templates.by_slug(data.slug):
            raise ConflictError(f"Template '{data.slug}' already exists")
        self._validate(data.model_dump())
        template = self.templates.add(Template(**data.model_dump()))
        if template.is_default:
            self._clear_other_defaults(template)
        audit(self.db, actor, AuditAction.TEMPLATE_CREATED, "template", template.id)
        self.db.commit()
        return template

    def update(self, template: Template, data: TemplateUpdate, actor: Actor) -> Template:
        changes = data.model_dump(exclude_unset=True)
        merged = {
            "slug": template.slug, "name": template.name, "category": template.category,
            "pages": template.pages, "theme": template.theme, **changes,
        }
        self._validate(merged)
        for field, value in changes.items():
            setattr(template, field, value)
        if changes.get("is_default"):
            self._clear_other_defaults(template)
        audit(self.db, actor, AuditAction.TEMPLATE_UPDATED, "template", template.id, {"fields": list(changes)})
        self.db.commit()
        return template

    def sync_from_disk(self, actor: Actor) -> TemplateSyncResult:
        """Upsert manifests and the component registry from /templates (idempotent)."""
        created = updated = 0
        for manifest in load_manifests(self.settings.templates_dir):
            template = self.templates.by_slug(manifest.slug)
            values = {
                "name": manifest.name, "category": manifest.category, "version": manifest.version,
                "description": manifest.description, "pages": manifest.pages, "theme": manifest.theme,
                "industries": manifest.industries, "is_default": manifest.default,
            }
            if template is None:
                self.templates.add(Template(slug=manifest.slug, **values))
                created += 1
            else:
                for field, value in values.items():
                    setattr(template, field, value)
                updated += 1
        components = discover_components(self.settings.templates_dir)
        for definition in components:
            component = self.components.by_slug(definition.slug)
            if component is None:
                self.components.add(
                    TemplateComponent(
                        slug=definition.slug, component_type=definition.component_type,
                        variant=definition.variant, template_path=definition.template_path,
                        name=f"{definition.component_type.value.title()} - {definition.variant.title()}",
                    )
                )
            else:
                component.template_path = definition.template_path
        audit(self.db, actor, AuditAction.TEMPLATES_SYNCED, "template", None,
              {"created": created, "updated": updated})
        self.db.commit()
        return TemplateSyncResult(templates_created=created, templates_updated=updated,
                                  components_registered=len(components))

    def select_for(self, industry: str, category: str, requested_slug: str | None = None,
                   variety_seed: int | None = None) -> Template:
        active = {t.slug: t for t in self.templates.active()}
        candidates = [
            TemplateCandidate(t.slug, t.category, t.version, t.is_default, tuple(t.industries or ()))
            for t in active.values()
        ]
        chosen = select_template(candidates, industry, category, requested_slug, variety_seed)
        if chosen is None:
            if requested_slug:
                raise NotFoundError(f"Active template '{requested_slug}' not found")
            raise ValidationFailedError("No active templates available; run template sync first")
        return active[chosen.slug]
