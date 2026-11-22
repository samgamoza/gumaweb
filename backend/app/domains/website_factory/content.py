"""Content generation (07-content-generation-engine).

`ContentGenerator` is the seam between the pipeline and copywriting strategies:
- `TemplateContentGenerator` composes copy deterministically from the industry
  catalog (zero inference cost, reproducible, always available).
- `agents.content_agent.LLMContentGenerator` (Phase 2) asks a local Qwen model
  for copy, has DeepSeek review it, and accepts each section only if it passes
  the quality gates - falling back to the template copy per section.

Integrity rule: generated copy must not invent facts (years in business, awards,
reviews, prices). Testimonials/gallery stay empty until real data exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domains.business_profile.industry_catalog import COMMON_FAQ, get_industry
from app.domains.website_factory.enums import ContentSource


@dataclass(frozen=True)
class ContentContext:
    name: str
    industry: str
    city: str | None
    province: str | None
    address: str | None
    phone: str | None
    email: str | None
    facebook: str | None
    services: list[str]
    target_audience: str | None
    brand_tone: str | None


@dataclass
class ContentResult:
    blocks: dict[str, dict[str, Any]]
    sources: dict[str, ContentSource]  # provenance per section
    notes: list[str] = field(default_factory=list)  # why AI copy was rejected, cache hits, ...


class ContentGenerator(Protocol):
    name: str

    def generate(self, ctx: ContentContext, section_keys: set[str]) -> ContentResult: ...


def _join(items: list[str]) -> str:
    items = [i.lower() for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


class TemplateContentGenerator:
    name = "template-v1"

    def generate(self, ctx: ContentContext, section_keys: set[str]) -> ContentResult:
        blocks = self.blocks(ctx, section_keys)
        return ContentResult(blocks=blocks, sources=dict.fromkeys(blocks, ContentSource.TEMPLATE))

    def blocks(self, ctx: ContentContext, section_keys: set[str]) -> dict[str, dict[str, Any]]:
        spec = get_industry(ctx.industry)
        service_lookup = dict(spec.services)
        services = ctx.services or [n for n, _ in spec.services]
        where = f" in {ctx.city}" if ctx.city else ""
        audience = ctx.target_audience or spec.target_audience
        builders = {
            "hero": lambda: {
                "headline": f"Trusted {spec.label} Services{where}",
                "subheadline": f"{ctx.name} serves {audience} with {_join(services[:3])}.",
                "cta_label": "Request a Free Consultation" if spec.category != "restaurant" else "Visit Us Today",
                "cta_target": "contact",
            },
            "about": lambda: {
                "heading": f"About {ctx.name}",
                "company_story": (
                    f"{ctx.name} is a {spec.label.lower()} business{where} serving {audience}. "
                    f"We focus on {_join(services[:3])}, delivered with care and attention to detail."
                ),
                "mission_statement": f"To provide {audience}{where} with reliable {spec.label.lower()} services.",
                "service_summary": f"Our services include {_join(services)}.",
            },
            "services": lambda: {
                "heading": "Our Services",
                "intro": f"What {ctx.name} can do for you.",
                "items": [
                    {"name": s, "description": service_lookup.get(s, f"Professional {s.lower()} services.")}
                    for s in services
                ],
            },
            "faq": lambda: {"heading": "Frequently Asked Questions", "items": self._faq(ctx, spec, services)},
            "cta": lambda: {
                "heading": f"Ready to work with {ctx.name}?",
                "text": "Get in touch today and tell us what you need.",
                "button_label": "Contact Us",
                "button_target": "contact",
            },
            "contact": lambda: {
                "heading": "Contact Us",
                "intro": "Send us a message and we will get back to you.",
                "phone": ctx.phone,
                "email": ctx.email,
                "address": ctx.address,
                "city": ctx.city,
                "province": ctx.province,
                "facebook": ctx.facebook,
                "show_form": True,
            },
            "testimonials": lambda: {"heading": "What Our Customers Say", "items": []},
            "gallery": lambda: {"heading": "Gallery", "images": []},
        }
        return {key: builders[key]() for key in section_keys if key in builders}

    @staticmethod
    def _faq(ctx: ContentContext, spec: Any, services: list[str]) -> list[dict[str, str]]:
        values = {
            "name": ctx.name,
            "city": ctx.city or "our area",
            "province_suffix": f", {ctx.province}" if ctx.province else "",
            "service_list": _join(services),
        }
        entries = [*spec.faq, *COMMON_FAQ]
        return [{"question": q.format(**values), "answer": a.format(**values)} for q, a in entries]
