"""Contact enrichment: find public emails/phones for a business and record them with provenance.

Order of checks (ported from guma_os `enrichBusinesses`, with the compliance gates kept):

1. A business whose website domain is suppressed is skipped before any tier runs, so a suppressed
   business can never trigger a paid lookup.
2. Tiers run as a waterfall (`domains/enrichment/tiers.py`): free website scrape, then opt-in RDAP, then
   opt-in Hunter.io only for high scorers with no email yet.
3. Every paid request is written to `provider_usage`, found or not.
4. Each email domain is checked for mail DNS (MX, else A as RFC 5321 allows); a domain that can't
   receive mail marks the contact `invalid`, so it is never promoted.
5. Results go through `ContactService.record`, which blocks suppressed addresses, stores provenance, and
   promotes only observed contacts to `Business.email`/`phone`. The business is then rescored.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import dns.exception
import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.business_discovery.contacts import (
    ContactKind,
    ContactObservation,
    ContactPurpose,
    ValueType,
    VerificationStatus,
)
from app.domains.business_discovery.normalization import is_real_website
from app.domains.enrichment.extract import domain_of
from app.domains.enrichment.tiers import (
    EnrichmentTarget,
    Fetcher,
    HunterTier,
    RdapTier,
    TierStep,
    WebsiteScrapeTier,
    run_waterfall,
)
from app.domains.website_factory.jobs import JobKind
from app.models import Business, FactoryJob, ProviderUsage
from app.services.business_service import BusinessService
from app.services.contact_service import ContactService
from app.services.job_queue import JobQueue
from app.services.providers import providers
from app.services.support import Actor
from app.services.suppression_service import SuppressionService

logger = logging.getLogger("gumaweb.enrichment")

# Tests replace these to keep enrichment off the network.
http_client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=10.0)  # noqa: E731
website_fetcher: Fetcher | None = None  # None: WebsiteScrapeTier uses safe_fetch

PHONE_CONFIDENCE = 0.7  # a number printed on the business's own site


@dataclass(frozen=True)
class TierInfo:
    id: str
    name: str
    billed: bool
    enabled: bool
    note: str


@dataclass
class EnrichmentOutcome:
    business_id: str
    skipped: str | None = None  # why nothing ran, e.g. "domain_suppressed"
    tiers_run: list[str] = field(default_factory=list)
    emails_found: int = 0
    phones_found: int = 0
    guesses_found: int = 0
    blocked: int = 0
    undeliverable: int = 0
    promoted: dict[str, str] = field(default_factory=dict)
    tech_stack: list[str] = field(default_factory=list)
    billed_calls: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EnrichmentService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # --- what is available ----------------------------------------------------------------------
    def hunter_enabled(self) -> bool:
        return bool(self.settings.hunter_api_key) and self.settings.enrich_allow_hunter

    def tiers(self) -> list[TierInfo]:
        s = self.settings
        hunter_note = (f"Paid. Only for businesses scoring at least {s.enrich_paid_min_score} with no email yet."
                       if self.hunter_enabled() else
                       "Off: needs HUNTER_API_KEY and ENRICH_ALLOW_HUNTER=true." if not s.hunter_api_key else
                       "Off: key present, but ENRICH_ALLOW_HUNTER is not true.")
        return [
            TierInfo("website_scrape", WebsiteScrapeTier.name, False, True,
                     "Free. The business's own homepage and /contact page."),
            TierInfo("rdap", RdapTier.name, False, s.enrich_allow_rdap,
                     "Free, opt-in (ENRICH_ALLOW_RDAP). Finds only guesses; never used for outreach."),
            TierInfo("hunter", HunterTier.name, True, self.hunter_enabled(), hunter_note),
        ]

    def _steps(self, client: httpx.Client, business: Business, tier_ids: list[str] | None) -> list[TierStep]:
        s = self.settings
        def has_site(t: EnrichmentTarget) -> bool:
            return bool(t.website)

        steps = [TierStep(WebsiteScrapeTier(website_fetcher), should_try=has_site)]
        if s.enrich_allow_rdap:
            steps.append(TierStep(RdapTier(client, base_url=s.rdap_base_url), should_try=has_site))
        if self.hunter_enabled():
            steps.append(TierStep(
                HunterTier(client, s.hunter_api_key or "", min_confidence=s.hunter_min_confidence),
                should_try=lambda t: (t.score or 0) >= s.enrich_paid_min_score and not business.email,
            ))
        if tier_ids is not None:  # can only narrow what this deployment allows, never add
            steps = [step for step in steps if step.tier.id in tier_ids]
        return steps

    def worth_enriching(self, business: Business) -> bool:
        return is_real_website(business.website) or self.hunter_enabled()

    # --- commands -------------------------------------------------------------------------------
    def enqueue(self, business: Business, actor: Actor, tier_ids: list[str] | None = None, *,
                commit: bool = True) -> FactoryJob:
        if tier_ids is not None:
            known = {t.id for t in self.tiers() if t.enabled}
            unknown = sorted(set(tier_ids) - known)
            if unknown:
                raise ValidationFailedError(f"Unknown or disabled enrichment tier(s): {', '.join(unknown)}")
        payload = {"business_id": str(business.id), "tiers": tier_ids,
                   "requested_by": str(actor.user_id) if actor.user_id else None}
        job = JobQueue(self.db).enqueue(JobKind.ENRICH_BUSINESS, payload, dedupe_key=f"enrich:{business.id}",
                                        priority=150, max_attempts=2)
        if job is None:
            raise ConflictError("Enrichment for this business is already queued or running",
                                code="enrichment_in_progress")
        if commit:
            self.db.commit()
        return job

    def enrich(self, business: Business, tier_ids: list[str] | None = None) -> EnrichmentOutcome:
        outcome = EnrichmentOutcome(business_id=str(business.id))
        suppressions = SuppressionService(self.db)
        domain = domain_of(business.website)
        if domain and suppressions.is_domain_suppressed(domain):
            outcome.skipped = "domain_suppressed"
            logger.info("enrich %s: domain %s is suppressed; no tier called", business.id, domain)
            return outcome

        # A Facebook page or link-in-bio is not the business's own site: never scrape or look it up.
        website = business.website if is_real_website(business.website) else None
        target = EnrichmentTarget(name=business.name, website=website, score=business.score)
        with http_client_factory() as client:
            result = run_waterfall(self._steps(client, business, tier_ids), target)

        for tier, calls in result.billed_calls.items():
            self.db.add(ProviderUsage(provider=tier, operation="domain_search", units=calls,
                                      cost_micros=calls * self.settings.hunter_cost_micros, business_id=business.id))

        deliverable = self._mail_domains_status({f.value for f in result.emails})
        observations = [
            ContactObservation(ContactKind.EMAIL, f.value, f.source, source_ref=f.source_ref,
                               confidence=f.confidence, purpose=ContactPurpose.CONTACT_ENRICHMENT,
                               verification_status=deliverable.get(f.value, VerificationStatus.UNVERIFIED))
            for f in result.emails
        ]
        observations += [ContactObservation(ContactKind.PHONE, f.value, f.source, source_ref=f.source_ref,
                                            confidence=PHONE_CONFIDENCE) for f in result.phones]
        observations += [ContactObservation(ContactKind.EMAIL, f.value, f.source, source_ref=f.source_ref,
                                            value_type=ValueType.PREDICTED, confidence=f.confidence)
                         for f in result.guessed_emails if f.value not in {e.value for e in result.emails}]

        recorded = ContactService(self.db).record(business, observations)
        outcome.tiers_run = result.tiers_run
        outcome.emails_found = len(result.emails)
        outcome.phones_found = len(result.phones)
        outcome.guesses_found = len(result.guessed_emails)
        outcome.blocked = recorded.blocked
        outcome.undeliverable = sum(1 for s in deliverable.values() if s is VerificationStatus.INVALID)
        outcome.promoted = recorded.promoted
        outcome.tech_stack = result.tech_stack
        outcome.billed_calls = result.billed_calls
        if recorded.promoted or recorded.cleared:
            BusinessService(self.db, self.settings).rescore(business)  # contactability changed; commits
        else:
            self.db.commit()
        logger.info("enrich %s: tiers=%s emails=%d phones=%d guesses=%d blocked=%d promoted=%s", business.id,
                    result.tiers_run, outcome.emails_found, outcome.phones_found, outcome.guesses_found,
                    outcome.blocked, outcome.promoted)
        return outcome

    def _mail_domains_status(self, emails: set[str]) -> dict[str, VerificationStatus]:
        """INVALID for addresses whose domain has neither MX nor A records. DNS trouble changes nothing."""
        status: dict[str, VerificationStatus] = {}
        by_domain: dict[str, bool | None] = {}
        for email in emails:
            domain = email.rpartition("@")[2]
            if domain not in by_domain:
                try:
                    by_domain[domain] = bool(providers.dns.mx(domain) or providers.dns.a(domain))
                except (dns.exception.DNSException, OSError):
                    by_domain[domain] = None  # unknown: leave unverified
            if by_domain[domain] is False:
                status[email] = VerificationStatus.INVALID
        return status


def run_enrichment_job(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Factory worker handler for JobKind.ENRICH_BUSINESS."""
    business = db.get(Business, uuid.UUID(payload["business_id"]))
    if business is None:
        return {"skipped": "business_deleted"}
    return EnrichmentService(db, settings).enrich(business, payload.get("tiers")).as_dict()

