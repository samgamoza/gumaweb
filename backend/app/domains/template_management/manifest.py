"""Template manifests: YAML files in /templates/manifests are the source of truth,
synced into the `templates` table. Components live in /templates/components/<type>/<variant>.html.j2."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.domains.template_management.enums import ComponentType

STANDARD_PAGES = ("home", "about", "services", "faq", "contact")
OPTIONAL_PAGES = ("projects", "gallery", "pricing", "team")


class ManifestError(ValueError):
    pass


@dataclass
class TemplateManifest:
    slug: str
    name: str
    category: str
    version: int
    pages: list[dict[str, Any]]
    theme: dict[str, Any]
    industries: list[str] = field(default_factory=list)
    description: str | None = None
    default: bool = False


@dataclass(frozen=True)
class ComponentDefinition:
    component_type: ComponentType
    variant: str
    template_path: str  # relative to templates_dir

    @property
    def slug(self) -> str:
        return f"{self.component_type.value}-{self.variant}"


def parse_manifest(data: dict[str, Any]) -> TemplateManifest:
    for key in ("slug", "name", "category", "pages", "theme"):
        if key not in data:
            raise ManifestError(f"manifest missing required key '{key}'")
    pages = data["pages"]
    if not isinstance(pages, list) or not pages:
        raise ManifestError("manifest 'pages' must be a non-empty list")
    slugs = [p.get("slug") for p in pages]
    if "home" not in slugs:
        raise ManifestError(f"template {data['slug']} must define a 'home' page")
    for page in pages:
        for section in page.get("sections", []):
            try:
                ComponentType(section["component"])
            except (KeyError, ValueError) as exc:
                raise ManifestError(f"invalid section {section!r} in page {page.get('slug')}") from exc
            section.setdefault("variant", "standard")
    return TemplateManifest(
        slug=data["slug"],
        name=data["name"],
        category=data["category"],
        version=int(data.get("version", 1)),
        pages=pages,
        theme=data["theme"],
        industries=list(data.get("industries", [])),
        description=data.get("description"),
        default=bool(data.get("default", False)),
    )


def load_manifests(templates_dir: Path) -> list[TemplateManifest]:
    manifests = []
    for path in sorted((templates_dir / "manifests").glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            manifests.append(parse_manifest(yaml.safe_load(fh)))
    return manifests


def discover_components(templates_dir: Path) -> list[ComponentDefinition]:
    components = []
    root = templates_dir / "components"
    for path in sorted(root.glob("*/*.html.j2")):
        try:
            component_type = ComponentType(path.parent.name)
        except ValueError:
            continue
        variant = path.name.removesuffix(".html.j2")
        components.append(
            ComponentDefinition(component_type, variant, path.relative_to(templates_dir).as_posix())
        )
    return components
