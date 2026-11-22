"""Business Intelligence Engine (05): sparse record -> structured profile."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.business_profile.industry_catalog import classify

_TONE_VOICE = {
    "professional": "Clear, confident and credible.",
    "dependable": "Straightforward, reassuring and practical.",
    "warm": "Welcoming, friendly and appetizing.",
    "caring": "Gentle, reassuring and trustworthy.",
    "authoritative": "Precise, formal and trustworthy.",
    "encouraging": "Positive, supportive and clear.",
    "friendly": "Approachable, upbeat and helpful.",
    "inviting": "Relaxed, vivid and welcoming.",
}


@dataclass(frozen=True)
class ProfileInput:
    name: str
    city: str | None
    province: str | None
    industry_hint: str | None = None
    description: str | None = None


@dataclass
class ProfileResult:
    industry: str
    category: str
    services: list[str]
    keywords: list[str]
    local_keywords: list[str]
    target_audience: str
    brand_tone: str
    brand_voice: str
    tagline: str
    confidence: float
    recommended_template_category: str
    extra: dict[str, object] = field(default_factory=dict)


def build_profile(data: ProfileInput) -> ProfileResult:
    spec, confidence = classify(data.name, data.industry_hint, data.description)
    services = [name for name, _ in spec.services]
    label = spec.label.lower()
    keywords = [label, *[s.lower() for s in services[:4]]]
    local_keywords: list[str] = []
    if data.city:
        local_keywords += [f"{label} in {data.city}", f"{services[0].lower()} {data.city}"]
    if data.province:
        local_keywords.append(f"{label} {data.province}")
    local_keywords.append(f"{label} near me")
    where = f" in {data.city}" if data.city else ""
    return ProfileResult(
        industry=spec.key,
        category=spec.category,
        services=services,
        keywords=keywords,
        local_keywords=local_keywords,
        target_audience=spec.target_audience,
        brand_tone=spec.brand_tone,
        brand_voice=_TONE_VOICE.get(spec.brand_tone, _TONE_VOICE["friendly"]),
        tagline=f"{spec.label}{where}",
        confidence=confidence,
        recommended_template_category=spec.category,
    )
