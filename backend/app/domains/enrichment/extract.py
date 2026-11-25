"""Pure extraction of public contacts and tech signals from a fetched web page. No I/O.

Ported from guma_os `adapter-maps/src/enrichment.ts` (extractContacts, extractJsonLdContacts) and
`domain-signals.ts` (domainOf, detectTechStack). Additions: HTML entities are decoded first, so
`info&#64;shop.ph` and `mailto:info%40shop.ph` are found too.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

EMAIL_RE = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+")
MAILTO_RE = re.compile(r"""href=["']mailto:([^"'?]+)""", re.IGNORECASE)
TEL_RE = re.compile(r"""href=["']tel:([^"']+)["']""", re.IGNORECASE)
JSON_LD_RE = re.compile(r"""<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
                        re.IGNORECASE | re.DOTALL)
MAX_JSON_LD_BLOCKS = 5  # a pathological page with hundreds of blocks must not cost real CPU

# Local parts that belong to infrastructure, not a business contact.
GENERIC_LOCAL_PARTS = frozenset({"noreply", "no-reply", "donotreply", "do-not-reply", "postmaster", "webmaster",
                                 "abuse", "mailer-daemon", "hostmaster"})
# Domains whose "emails" are tracker/CDN/template artifacts picked up from scripts, not real contacts.
BLOCKED_DOMAINS = ("sentry.io", "wixpress.com", "example.com", "example.org", "w3.org", "schema.org",
                   "sentry-next.wixpress.com", "domain.com", "email.com", "yourdomain.com")
ASSET_SUFFIX_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$", re.IGNORECASE)  # "logo@2x.png" srcset artifacts
ORG_TYPES = frozenset({"organization", "localbusiness", "corporation"})
MIN_PHONE_DIGITS = 7


@dataclass
class PageContacts:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)


def is_plausible_email(raw: str) -> bool:
    email = raw.strip().lower()
    local, at, domain = email.rpartition("@")
    if not at or not local or not domain or "." not in domain:
        return False
    if local in GENERIC_LOCAL_PARTS:
        return False
    if any(domain == d or domain.endswith(f".{d}") for d in BLOCKED_DOMAINS):
        return False
    return not ASSET_SUFFIX_RE.search(domain)


def _clean_phone(raw: str) -> str | None:
    phone = re.sub(r"[^\d+]", "", raw)
    return phone if sum(c.isdigit() for c in phone) >= MIN_PHONE_DIGITS else None


def _add_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _org_nodes(parsed: Any) -> Iterable[dict[str, Any]]:
    roots = parsed if isinstance(parsed, list) else [parsed]
    for root in roots:
        if not isinstance(root, dict):
            continue
        graph = root.get("@graph")
        for node in graph if isinstance(graph, list) else [root]:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types] if types else []
            if any(isinstance(t, str) and t.lower() in ORG_TYPES for t in types):
                yield node


def extract_json_ld_contacts(page: str) -> PageContacts:
    """Email/phone from schema.org Organization/LocalBusiness JSON-LD. Malformed blocks are skipped."""
    found = PageContacts()
    for index, match in enumerate(JSON_LD_RE.finditer(page)):
        if index >= MAX_JSON_LD_BLOCKS:
            break
        try:
            parsed = json.loads(match.group(1))
        except (ValueError, RecursionError):
            continue
        for node in _org_nodes(parsed):
            points = node.get("contactPoint")
            points = points if isinstance(points, list) else [points] if isinstance(points, dict) else []
            for candidate in [node, *points]:
                if not isinstance(candidate, dict):
                    continue
                email = candidate.get("email")
                if isinstance(email, str):
                    email = email.strip().lower().removeprefix("mailto:")
                    if is_plausible_email(email):
                        _add_unique(found.emails, [email])
                phone = candidate.get("telephone")
                if isinstance(phone, str) and (cleaned := _clean_phone(phone)):
                    _add_unique(found.phones, [cleaned])
    return found


def extract_contacts(page: str) -> PageContacts:
    """Emails and phones from mailto:/tel: links, plain-text addresses and JSON-LD on one page."""
    found = PageContacts()
    decoded = html.unescape(page)
    for match in MAILTO_RE.finditer(decoded):
        email = unquote(match.group(1)).strip().lower()
        if is_plausible_email(email):
            _add_unique(found.emails, [email])
    for match in EMAIL_RE.finditer(decoded):
        email = match.group(0).lower().rstrip(".")
        if is_plausible_email(email):
            _add_unique(found.emails, [email])
    for match in TEL_RE.finditer(decoded):
        if cleaned := _clean_phone(unquote(match.group(1))):
            _add_unique(found.phones, [cleaned])
    json_ld = extract_json_ld_contacts(page)
    _add_unique(found.emails, json_ld.emails)
    _add_unique(found.phones, json_ld.phones)
    return found


def domain_of(website: str | None) -> str | None:
    """Bare host without `www.` from a website URL, or None when missing/unparseable."""
    if not website:
        return None
    try:
        host = urlsplit(website if "://" in website else f"http://{website}").hostname
    except ValueError:
        return None
    return host.removeprefix("www.") if host else None


_SIGNATURES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("wordpress", (re.compile(r"wp-content/", re.I), re.compile(r"wp-includes/", re.I),
                   re.compile(r"""name=["']generator["']\s+content=["']WordPress""", re.I))),
    ("shopify", (re.compile(r"cdn\.shopify\.com", re.I), re.compile(r"Shopify\.theme", re.I))),
    ("wix", (re.compile(r"static\.wixstatic\.com", re.I), re.compile(r"wix\.com", re.I))),
    ("squarespace", (re.compile(r"static1\.squarespace\.com", re.I), re.compile(r"squarespace\.com/static", re.I))),
)


def detect_tech_stack(page: str, headers: Mapping[str, str] | None = None) -> list[str]:
    """Shallow CMS/framework signature (a digital-maturity signal, not a contact). Never raises."""
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    found: list[str] = []
    for tech, patterns in _SIGNATURES:
        header_hit = (
            (tech == "shopify" and ("x-shopify-stage" in lowered or "shopify" in lowered.get("server", "").lower()))
            or (tech == "wix" and any(k.startswith("x-wix-") for k in lowered))
        )
        if header_hit or any(p.search(page) for p in patterns):
            found.append(tech)
    powered_by = lowered.get("x-powered-by", "").lower()
    if powered_by and not any(t in powered_by for t in found):
        found.append(f"header:{powered_by}")
    return found
