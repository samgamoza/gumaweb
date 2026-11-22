"""Quality validation (QA gate before build/publish).

Checks from 09-website-assembly-pipeline: pages_exist, layout_valid,
asset_valid, seo_valid — plus content and contact completeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domains.template_management.manifest import STANDARD_PAGES

PUBLISH_THRESHOLD = 70

# Fields each component needs to render meaningfully.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "hero": ("headline", "subheadline", "cta_label"),
    "about": ("heading", "company_story"),
    "services": ("heading", "items"),
    "faq": ("heading", "items"),
    "cta": ("heading", "button_label"),
    "contact": ("heading",),
}
# Components that intentionally render nothing until real data exists.
OPTIONAL_DATA_COMPONENTS = {"testimonials", "gallery"}

CHECK_WEIGHTS = {
    "pages_exist": 20,
    "layout_valid": 20,
    "content_complete": 25,
    "seo_valid": 20,
    "contact_available": 15,
}


@dataclass
class QualityReport:
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(CHECK_WEIGHTS[name] for name, ok in self.checks.items() if ok)

    @property
    def publishable(self) -> bool:
        return self.score >= PUBLISH_THRESHOLD and self.checks.get("layout_valid", False)

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "publishable": self.publishable, "checks": self.checks, "issues": self.issues}


def validate_site(
    blueprint: dict[str, Any],
    content: dict[str, dict[str, Any]],
    seo: dict[str, Any] | None,
    available_components: set[tuple[str, str]],
) -> QualityReport:
    report = QualityReport()
    pages = {p["slug"] for p in blueprint.get("pages", [])}

    missing_pages = [p for p in STANDARD_PAGES if p not in pages]
    report.checks["pages_exist"] = "home" in pages and len(missing_pages) <= 2
    if missing_pages:
        report.issues.append(f"Missing standard pages: {', '.join(missing_pages)}")

    layout_ok = True
    content_ok = True
    for page in blueprint.get("pages", []):
        for section in page.get("sections", []):
            key = (section["component"], section["variant"])
            if key not in available_components:
                layout_ok = False
                report.issues.append(f"Unknown component {key[0]}/{key[1]} on page '{page['slug']}'")
            if section["component"] in OPTIONAL_DATA_COMPONENTS:
                continue
            block = content.get(section["content_key"], {})
            missing = [f for f in REQUIRED_FIELDS.get(section["component"], ()) if not block.get(f)]
            if missing:
                content_ok = False
                report.issues.append(f"Section '{section['content_key']}' missing: {', '.join(missing)}")
    report.checks["layout_valid"] = layout_ok
    report.checks["content_complete"] = content_ok

    seo_ok = bool(seo)
    if seo:
        title, desc = seo.get("page_title", ""), seo.get("meta_description", "")
        if not 10 <= len(title) <= 60:
            seo_ok = False
            report.issues.append(f"Page title length {len(title)} outside 10-60")
        if not 50 <= len(desc) <= 160:
            seo_ok = False
            report.issues.append(f"Meta description length {len(desc)} outside 50-160")
    else:
        report.issues.append("SEO metadata missing")
    report.checks["seo_valid"] = seo_ok

    business = blueprint.get("business", {})
    contact_ok = bool(business.get("phone") or business.get("email"))
    report.checks["contact_available"] = contact_ok
    if not contact_ok:
        report.issues.append("No phone or email to display")
    return report
