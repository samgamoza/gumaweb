"""Core KPIs (14-monetization) and funnel math."""

from __future__ import annotations

from dataclasses import asdict, dataclass


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass(frozen=True)
class PlatformKpis:
    businesses: int
    generate_candidates: int
    generated_sites: int
    published_sites: int
    claimed_sites: int
    paid_sites: int
    monthly_recurring_revenue_cents: int
    pending_claims: int

    @property
    def claim_rate(self) -> float:
        return rate(self.claimed_sites, self.published_sites)

    @property
    def paid_conversion_rate(self) -> float:
        return rate(self.paid_sites, self.claimed_sites)

    @property
    def average_revenue_per_business_cents(self) -> int:
        return self.monthly_recurring_revenue_cents // self.paid_sites if self.paid_sites else 0

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "claim_rate": self.claim_rate,
            "paid_conversion_rate": self.paid_conversion_rate,
            "average_revenue_per_business_cents": self.average_revenue_per_business_cents,
        }
