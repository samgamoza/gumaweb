"""Claim abuse protection (11-claim-ownership-platform): risk scoring + review policy."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.business_discovery.normalization import email_domain, is_free_email, url_host
from app.domains.claims.enums import VerificationMethod

BASE_RISK = 30

DISPOSABLE_DOMAINS = frozenset(
    {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com",
     "trashmail.com", "sharklasers.com", "getnada.com", "temp-mail.org", "dispostable.com"}
)


@dataclass(frozen=True)
class RiskInput:
    method: VerificationMethod
    claimant_email: str
    claimant_phone: str | None  # normalized digits
    business_email: str | None
    business_phone: str | None  # normalized digits
    business_website: str | None
    recent_claims_from_ip: int
    competing_active_claims: int


@dataclass
class RiskAssessment:
    score: int
    factors: list[str] = field(default_factory=list)


def assess_claim_risk(data: RiskInput) -> RiskAssessment:
    score = BASE_RISK
    factors: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        factors.append(f"{'+' if points >= 0 else ''}{points}: {reason}")

    domain = email_domain(data.claimant_email)
    if data.business_email and data.claimant_email == data.business_email:
        add(-40, "claimant email matches the business email on record")
    elif domain and not is_free_email(data.claimant_email) and domain == email_domain(data.business_email):
        add(-25, "claimant email domain matches business email domain")
    elif domain and domain == url_host(data.business_website):
        add(-25, "claimant email domain matches business website")

    if data.claimant_phone and data.business_phone and data.claimant_phone == data.business_phone:
        add(-30, "claimant phone matches the business phone on record")
    if domain in DISPOSABLE_DOMAINS:
        add(50, "disposable email domain")
    if data.recent_claims_from_ip > 1:
        add(min(40, 15 * (data.recent_claims_from_ip - 1)), "multiple recent claims from the same IP")
    if data.competing_active_claims:
        add(25, "another claim for this business is in progress")
    if data.method == VerificationMethod.BUSINESS_IDENTITY:
        add(30, "document-based verification requires human review")

    return RiskAssessment(score=max(0, min(100, score)), factors=factors)


def requires_manual_review(assessment: RiskAssessment, method: VerificationMethod, threshold: int) -> bool:
    return method == VerificationMethod.BUSINESS_IDENTITY or assessment.score >= threshold
