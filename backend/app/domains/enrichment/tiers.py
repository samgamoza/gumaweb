"""Enrichment tiers and the waterfall that runs them (ported from guma_os enrichment.ts, rdap.ts, hunter.ts).

* `website_scrape` (free, always on): the business's own homepage, then `/contact` if no email was found.
  Every fetch goes through `safe_fetch` (SSRF-hardened, size-capped).
* `rdap` (free, opt-in): domain registration data. Almost always a registrar proxy since ICANN's 2018
  redaction, so anything it finds is a *guess* and is stored as `predicted` (never promoted, never contacted).
* `hunter` (paid, opt-in, needs a key): Hunter.io domain search, or company-name search when there is no
  website. Only offered for high-scoring businesses the free tiers missed.

A tier never raises: network errors, refusals and odd responses all mean "found nothing here", so one bad
site can't break a batch. The waterfall stops at the first tier that finds a real email; phones and
guesses keep accumulating across tiers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.net import SafeFetchResult, UnsafeUrlError, safe_fetch
from app.domains.enrichment.extract import detect_tech_stack, domain_of, extract_contacts, is_plausible_email

Fetcher = Callable[[str], SafeFetchResult]


@dataclass(frozen=True)
class Found:
    value: str
    source: str  # tier id
    source_ref: str | None = None  # the page URL / API record it came from
    confidence: float = 0.9


@dataclass
class EnrichmentResult:
    emails: list[Found] = field(default_factory=list)
    phones: list[Found] = field(default_factory=list)
    guessed_emails: list[Found] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    tiers_run: list[str] = field(default_factory=list)
    billed_calls: dict[str, int] = field(default_factory=dict)  # tier id -> paid requests made

    def merge(self, other: EnrichmentResult) -> None:
        for mine, theirs in ((self.emails, other.emails), (self.phones, other.phones),
                             (self.guessed_emails, other.guessed_emails)):
            known = {f.value for f in mine}
            for found in theirs:
                if found.value not in known:
                    known.add(found.value)
                    mine.append(found)
        self.tech_stack.extend(t for t in other.tech_stack if t not in self.tech_stack)
        for tier, calls in other.billed_calls.items():
            self.billed_calls[tier] = self.billed_calls.get(tier, 0) + calls


@dataclass(frozen=True)
class EnrichmentTarget:
    name: str
    website: str | None
    score: int | None = None


class EnrichmentTier(Protocol):
    id: str
    name: str
    billed: bool

    def enrich(self, target: EnrichmentTarget) -> EnrichmentResult: ...


@dataclass
class TierStep:
    tier: EnrichmentTier
    should_try: Callable[[EnrichmentTarget], bool] | None = None


def run_waterfall(steps: list[TierStep], target: EnrichmentTarget) -> EnrichmentResult:
    """Run tiers in order until one finds a real email. Guesses never stop the waterfall."""
    result = EnrichmentResult()
    for step in steps:
        if result.emails:
            break
        if step.should_try is not None and not step.should_try(target):
            continue
        try:
            found = step.tier.enrich(target)
        except Exception:  # noqa: BLE001 - defense in depth: tiers are written not to raise
            found = EnrichmentResult()
        result.tiers_run.append(step.tier.id)
        result.merge(found)
    return result


# --- website scrape -------------------------------------------------------------------------------


def contact_page_url(website: str) -> str | None:
    try:
        parts = urlsplit(website if "://" in website else f"https://{website}")
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "/contact", "", ""))


class WebsiteScrapeTier:
    id = "website_scrape"
    name = "Website scrape (mailto, tel, schema.org)"
    billed = False

    def __init__(self, fetch: Fetcher | None = None, *, try_contact_page: bool = True) -> None:
        self.fetch: Fetcher = fetch or (lambda url: safe_fetch(url, timeout=6.0))
        self.try_contact_page = try_contact_page

    def _page(self, url: str) -> EnrichmentResult:
        try:
            response = self.fetch(url)
        except (UnsafeUrlError, httpx.HTTPError, ValueError):
            return EnrichmentResult()
        content_type = response.headers.get("content-type", "")
        if not response.ok or (content_type and "html" not in content_type.lower()):
            return EnrichmentResult()
        contacts = extract_contacts(response.text)
        return EnrichmentResult(
            emails=[Found(e, self.id, response.url) for e in contacts.emails],
            phones=[Found(p, self.id, response.url) for p in contacts.phones],
            tech_stack=detect_tech_stack(response.text, dict(response.headers)),
        )

    def enrich(self, target: EnrichmentTarget) -> EnrichmentResult:
        if not target.website:
            return EnrichmentResult()
        url = target.website if "://" in target.website else f"https://{target.website}"
        result = self._page(url)
        if result.emails or not self.try_contact_page:
            return result
        contact = contact_page_url(url)
        if contact and contact.rstrip("/") != url.rstrip("/"):
            result.merge(self._page(contact))
        return result


# --- RDAP -----------------------------------------------------------------------------------------

RDAP_GUESS_CONFIDENCE = 0.2  # registrar-proxy noise far more often than a real contact


class RdapTier:
    id = "rdap"
    name = "Domain registration lookup (RDAP)"
    billed = False

    def __init__(self, client: httpx.Client, *, base_url: str = "https://rdap.org/domain", timeout: float = 6.0):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def enrich(self, target: EnrichmentTarget) -> EnrichmentResult:
        domain = domain_of(target.website)
        if not domain:
            return EnrichmentResult()
        url = f"{self.base_url}/{domain}"
        try:
            # rdap.org answers with a redirect to the authoritative registry: a fixed, same-purpose hop.
            response = self.client.get(url, timeout=self.timeout, follow_redirects=True)
            body = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return EnrichmentResult()
        entities = body.get("entities") if isinstance(body, dict) else None
        guesses: list[Found] = []
        for entity in entities if isinstance(entities, list) else []:
            vcard = entity.get("vcardArray") if isinstance(entity, dict) else None
            props = vcard[1] if isinstance(vcard, list) and len(vcard) > 1 and isinstance(vcard[1], list) else []
            for prop in props:
                if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "email" and isinstance(prop[3], str):
                    email = prop[3].strip().lower()
                    if is_plausible_email(email) and email not in {g.value for g in guesses}:
                        guesses.append(Found(email, self.id, url, RDAP_GUESS_CONFIDENCE))
        return EnrichmentResult(guessed_emails=guesses)


# --- Hunter.io ------------------------------------------------------------------------------------


class HunterTier:
    id = "hunter"
    name = "Hunter.io (paid email finder)"
    billed = True

    def __init__(self, client: httpx.Client, api_key: str, *, min_confidence: int = 50, timeout: float = 8.0,
                 endpoint: str = "https://api.hunter.io/v2/domain-search") -> None:
        if not api_key:
            raise ValueError("Hunter enrichment needs HUNTER_API_KEY")
        self.client = client
        self.api_key = api_key
        self.min_confidence = min_confidence
        self.timeout = timeout
        self.endpoint = endpoint

    def enrich(self, target: EnrichmentTarget) -> EnrichmentResult:
        domain = domain_of(target.website)
        if not domain and not target.name:
            return EnrichmentResult()
        params: dict[str, Any] = {"api_key": self.api_key, "limit": 10}
        params.update({"domain": domain} if domain else {"company": target.name})
        billed = EnrichmentResult(billed_calls={self.id: 1})
        try:
            response = self.client.get(self.endpoint, params=params, timeout=self.timeout)
            body = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return billed  # the request may still have been billed
        data = body.get("data") if isinstance(body, dict) else None
        items = data.get("emails") if isinstance(data, dict) else None
        emails: list[Found] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip().lower()
            confidence = item.get("confidence") if isinstance(item.get("confidence"), int | float) else 0
            if value and confidence >= self.min_confidence and is_plausible_email(value) \
                    and value not in {e.value for e in emails}:
                ref = f"hunter:domain:{domain}" if domain else f"hunter:company:{target.name}"
                emails.append(Found(value, self.id, ref, min(1.0, confidence / 100)))
        billed.emails = emails
        return billed
