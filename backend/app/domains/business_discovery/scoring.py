"""Opportunity scoring (04-business-discovery-engine).

Variables: website missing, domain missing, Facebook presence, contact availability,
industry value. Output: score 0-100 and `generate_candidate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.business_discovery.normalization import is_free_email, is_real_website

WEIGHTS = {
    "website_missing": 35,
    "domain_missing": 10,
    "facebook_presence": 15,
    "phone_available": 10,
    "email_available": 10,
    "industry_value": 20,
}


@dataclass(frozen=True)
class ScoringInput:
    website: str | None
    email: str | None
    phone: str | None
    facebook: str | None
    industry_value: int  # 0-100 from the industry catalog


@dataclass(frozen=True)
class ScoreResult:
    score: int
    generate_candidate: bool
    breakdown: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"score": self.score, "breakdown": self.breakdown, "reasons": self.reasons}


def score_business(data: ScoringInput, threshold: int = 60) -> ScoreResult:
    breakdown: dict[str, int] = {}
    reasons: list[str] = []

    has_website = is_real_website(data.website)
    if not has_website:
        breakdown["website_missing"] = WEIGHTS["website_missing"]
        reasons.append("No owned website")
    # A business email on its own domain implies it already owns a domain.
    has_domain = has_website or (bool(data.email) and not is_free_email(data.email))
    if not has_domain:
        breakdown["domain_missing"] = WEIGHTS["domain_missing"]
        reasons.append("No owned domain")
    if data.facebook:
        breakdown["facebook_presence"] = WEIGHTS["facebook_presence"]
        reasons.append("Active social presence (proves the business is operating)")
    if data.phone:
        breakdown["phone_available"] = WEIGHTS["phone_available"]
    if data.email:
        breakdown["email_available"] = WEIGHTS["email_available"]
    industry_points = round(WEIGHTS["industry_value"] * max(0, min(100, data.industry_value)) / 100)
    if industry_points:
        breakdown["industry_value"] = industry_points

    score = min(100, sum(breakdown.values()))
    contact_available = bool(data.phone or data.email)
    if not contact_available:
        reasons.append("No reachable contact information")
    candidate = score >= threshold and not has_website and contact_available
    return ScoreResult(score=score, generate_candidate=candidate, breakdown=breakdown, reasons=reasons)
