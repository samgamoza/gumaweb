"""SEO generation: titles, descriptions, local keywords, schema.org markup,
robots.txt and sitemap.xml (07 + 10)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from xml.sax.saxutils import escape

from app.domains.business_profile.industry_catalog import get_industry


@dataclass(frozen=True)
class SeoInput:
    name: str
    industry: str
    city: str | None
    province: str | None
    address: str | None
    phone: str | None
    email: str | None
    facebook: str | None
    services: list[str]
    keywords: list[str]
    local_keywords: list[str]
    site_url: str


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def generate_seo(data: SeoInput) -> dict[str, Any]:
    spec = get_industry(data.industry)
    where = f" in {data.city}" if data.city else ""
    title = _truncate(f"{data.name} | {spec.label}{where}", 60)
    services = ", ".join(s.lower() for s in data.services[:3])
    description = _truncate(
        f"{data.name} offers {services}{where}. Contact us today for inquiries and quotations.", 160
    )
    if len(description) < 50:
        description = _truncate(f"{description} Professional {spec.label.lower()} services you can trust.", 160)

    local_keywords = list(dict.fromkeys(data.local_keywords))
    if data.city:
        local_keywords += [f"{s.lower()} {data.city}" for s in data.services[:3]]
    local_keywords = list(dict.fromkeys(local_keywords))

    schema: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": spec.schema_type,
        "name": data.name,
        "url": data.site_url,
    }
    if data.phone:
        schema["telephone"] = "+" + data.phone if data.phone.isdigit() else data.phone
    if data.email:
        schema["email"] = data.email
    if data.city or data.address:
        schema["address"] = {
            "@type": "PostalAddress",
            **({"streetAddress": data.address} if data.address else {}),
            **({"addressLocality": data.city} if data.city else {}),
            **({"addressRegion": data.province} if data.province else {}),
            "addressCountry": "PH",
        }
    if data.facebook:
        schema["sameAs"] = [data.facebook]
    if data.services:
        schema["makesOffer"] = [
            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": s}} for s in data.services
        ]

    result = {
        "page_title": title,
        "meta_description": description,
        "keywords": list(dict.fromkeys(data.keywords)),
        "local_keywords": local_keywords,
        "schema_markup": schema,
    }
    result["seo_score"] = score_seo(result)
    return result


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    end = text.find(". ")
    return text if end == -1 else text[: end + 1]


def generate_page_meta(pages: list[dict[str, Any]], content: dict[str, dict[str, Any]], name: str,
                       industry: str, city: str | None, home_title: str, home_description: str) -> dict[str, Any]:
    """Unique title + description per page (duplicate titles/descriptions dilute local SEO)."""
    label = get_industry(industry).label
    where = f" in {city}" if city else ""
    services = [i.get("name", "") for i in content.get("services", {}).get("items", [])][:4]
    describe = {
        "about": _first_sentence(content.get("about", {}).get("company_story"))
        or f"Learn about {name}, a {label.lower()} business{where}.",
        "services": f"{name} offers {', '.join(s.lower() for s in services)}{where}. Contact us for details."
        if services else f"Services offered by {name}{where}.",
        "faq": f"Answers to common questions about {name}: services, location, hours, and how to get a quote.",
        "contact": f"Contact {name}{where}. Call, email, or send a message and we will get back to you.",
    }
    meta: dict[str, Any] = {"home": {"title": home_title, "description": home_description}}
    for page in pages:
        slug = page["slug"]
        if slug == "home":
            continue
        title = _truncate(f"{page.get('title') or slug.title()} | {name}", 60)
        description = _truncate(describe.get(slug, f"{page.get('title', slug.title())} - {name}{where}."), 160)
        if len(description) < 50:
            description = _truncate(f"{description} {label} services{where}.", 160)
        meta[slug] = {"title": title, "description": description}
    return meta


def faq_schema(items: list[dict[str, str]]) -> dict[str, Any] | None:
    """schema.org FAQPage - eligible for rich results on the FAQ page."""
    entries = [i for i in items if i.get("question") and i.get("answer")]
    if not entries:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": i["question"], "acceptedAnswer": {"@type": "Answer", "text": i["answer"]}}
            for i in entries
        ],
    }


def score_seo(seo: dict[str, Any]) -> int:
    score = 0
    if 30 <= len(seo["page_title"]) <= 60:
        score += 25
    elif seo["page_title"]:
        score += 10
    if 120 <= len(seo["meta_description"]) <= 160:
        score += 25
    elif 50 <= len(seo["meta_description"]) <= 160:
        score += 15
    score += min(15, 3 * len(seo["keywords"]))
    score += min(20, 4 * len(seo["local_keywords"]))
    schema = seo["schema_markup"]
    score += 15 if {"telephone", "address"} <= schema.keys() else 5 if schema else 0
    return min(100, score)


def robots_txt(site_url: str) -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {site_url.rstrip('/')}/sitemap.xml\n"


def sitemap_xml(site_url: str, page_paths: list[str], lastmod: date | None = None) -> str:
    base = site_url.rstrip("/") + "/"
    lastmod_str = (lastmod or date.today()).isoformat()
    urls = "".join(
        f"  <url><loc>{escape(base + path)}</loc><lastmod>{lastmod_str}</lastmod></url>\n" for path in page_paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )
