"""SEO audit (12-customer-portal "SEO Dashboard": seo_score, content_gaps).

Scores a site on technical SEO and content completeness and turns every
failing check into a concrete, owner-actionable content gap. Keyword rankings
need search-engine data (Search Console) and arrive in a later phase.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Check:
    key: str
    weight: int
    passed: bool
    message: str  # shown when the check fails
    section: str | None = None
    impact: str = "medium"  # high | medium | low


def audit_site(*, blueprint: dict[str, Any], content: dict[str, dict[str, Any]], seo: dict[str, Any],
               business: dict[str, Any], custom_domain: bool = False) -> dict[str, Any]:
    pages = {p["slug"] for p in blueprint.get("pages", [])}
    page_meta = seo.get("pages") or {}
    titles = [m.get("title") for m in page_meta.values() if m.get("title")]
    services = content.get("services", {}).get("items", [])
    faq = content.get("faq", {}).get("items", [])
    about = content.get("about", {}).get("company_story", "") or ""
    gallery = content.get("gallery", {}).get("images", [])
    testimonials = content.get("testimonials", {}).get("items", [])
    schema = seo.get("schema_markup") or {}

    checks = [
        Check("title_length", 10, 30 <= len(seo.get("page_title", "")) <= 60,
              "Homepage title should be 30-60 characters.", impact="high"),
        Check("meta_description", 10, 120 <= len(seo.get("meta_description", "")) <= 160,
              "Homepage description should be 120-160 characters.", impact="high"),
        Check("unique_page_titles", 8, len(titles) == len(set(titles)) and len(titles) >= len(pages),
              "Every page needs its own title and description.", impact="medium"),
        Check("local_business_schema", 10, {"telephone", "address"} <= schema.keys(),
              "Add your phone number and address so search engines can show your business details.",
              section="contact", impact="high"),
        Check("local_keywords", 6, len(seo.get("local_keywords", [])) >= 3,
              "Mention your city and service area to rank in local searches.", impact="medium"),
        Check("address", 8, bool(business.get("address")),
              "Add your street address - customers and maps need it.", section="contact", impact="high"),
        Check("email", 4, bool(business.get("email")),
              "Add an email address so customers can reach you in writing.", section="contact", impact="low"),
        Check("services_depth", 8, len(services) >= 4,
              "List at least 4 services with a short description each.", section="services", impact="high"),
        Check("about_story", 8, len(about) >= 200,
              "Tell your story in the About section (at least a few sentences about who you are).",
              section="about", impact="medium"),
        Check("faq_depth", 6, len(faq) >= 10,
              "Answer at least 10 common customer questions in the FAQ.", section="faq", impact="medium"),
        Check("photos", 10, len(gallery) >= 3,
              "Upload at least 3 real photos of your work, products or premises.", section="gallery",
              impact="high"),
        Check("testimonials", 6, len(testimonials) >= 2,
              "Add at least 2 testimonials from real customers (with their permission).",
              section="testimonials", impact="medium"),
        Check("faq_page", 2, "faq" in pages, "Include an FAQ page.", impact="low"),
        Check("custom_domain", 4, custom_domain,
              "Use your own domain name (Professional plan) to build brand authority.", impact="low"),
    ]
    # Only judge sections this site's template can actually show.
    components = {s["component"] for p in blueprint.get("pages", []) for s in p.get("sections", [])}
    checks = [c for c in checks if c.section in (None, "contact", "about") or c.section in components]
    total = sum(c.weight for c in checks)
    score = round(100 * sum(c.weight for c in checks if c.passed) / total)
    order = {"high": 0, "medium": 1, "low": 2}
    gaps = sorted(
        ({"key": c.key, "message": c.message, "impact": c.impact, "section": c.section}
         for c in checks if not c.passed),
        key=lambda g: order[g["impact"]],
    )
    return {
        "score": score,
        "checks": [{**asdict(c), "passed": c.passed} for c in checks],
        "content_gaps": gaps,
    }
