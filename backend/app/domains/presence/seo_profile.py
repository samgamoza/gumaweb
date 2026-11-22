"""Local SEO profile: canonical name/address/phone (NAP), consistency checks, keyword targets, citations.

Local rankings depend heavily on the same NAP appearing everywhere the business is listed, so the profile
gives one canonical version and flags where the business's own records disagree.
"""

from __future__ import annotations

import re
from typing import Any

from app.domains.presence.facts import PresenceFacts, phone_display, phone_e164

# Directories worth a listing for a Philippine local business (homepages only: deep links change often).
CITATIONS = [
    ("google", "Google Business Profile", "https://business.google.com",
     "Shows you on Google Maps and in local search results."),
    ("facebook", "Facebook Page", "https://www.facebook.com/pages/create",
     "Where most Filipino customers look a business up first."),
    ("bing", "Bing Places", "https://www.bingplaces.com", "Feeds Bing, DuckDuckGo and Microsoft maps."),
    ("apple", "Apple Business Connect", "https://businessconnect.apple.com",
     "Puts you on Apple Maps for iPhone users."),
    ("foursquare", "Foursquare", "https://foursquare.com", "Its places data is reused by many other apps."),
]


def _norm_address(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def nap(f: PresenceFacts) -> dict[str, Any]:
    address = ", ".join(p for p in [f.address, f.city, f.province, f.postal_code, "Philippines"] if p)
    return {"name": f.name, "address": address if (f.address or f.city) else None,
            "phone_local": phone_display(f.phone), "phone_international": phone_e164(f.phone)}


def consistency(f: PresenceFacts, site_contact: dict[str, Any], normalize_phone) -> list[str]:
    """Where the business's own records disagree. `normalize_phone` is injected (domain stays pure)."""
    issues = []
    site_phone = normalize_phone(site_contact.get("phone")) if site_contact.get("phone") else None
    if f.phone and site_phone and site_phone != f.phone:
        issues.append("The phone number on your website differs from your business record.")
    if f.address and site_contact.get("address") and \
            _norm_address(site_contact["address"]) != _norm_address(f.address):
        issues.append("The address on your website differs from your business record.")
    schema_phone = re.sub(r"\D", "", str(f.schema_markup.get("telephone") or ""))
    if f.phone and schema_phone and schema_phone != f.phone:
        issues.append("The phone number in your search-engine markup differs from your business record.")
    if not f.phone:
        issues.append("Add a phone number: customers and directories expect one.")
    if not f.address:
        issues.append("Add a street address so you can appear in map results.")
    return issues


def keyword_targets(f: PresenceFacts) -> list[dict[str, str]]:
    """Phrases customers type, mapped to the page that should rank for them."""
    place = (f.city or f.province or "").lower()
    targets = []
    if place:
        targets.append({"phrase": f"{f.noun.lower()} {place}", "page": "Home"})
    for name, _ in f.services[:5]:
        phrase = f"{name.lower()} {place}".strip()
        targets.append({"phrase": phrase, "page": "Services"})
    targets.append({"phrase": f"{f.noun.lower()} near me", "page": "Home (needs your Google Business Profile)"})
    seen, unique = set(), []
    for t in targets:
        if t["phrase"] not in seen:
            seen.add(t["phrase"])
            unique.append(t)
    return unique


def citations(f: PresenceFacts) -> list[dict[str, str]]:
    known = {"google": bool(f.google_business_url), "facebook": bool(f.facebook_url)}
    return [{"key": key, "name": name, "url": url, "why": why,
             "status": "listed" if known.get(key) else ("missing" if key in known else "unknown")}
            for key, name, url, why in CITATIONS]


def seo_profile(f: PresenceFacts, *, site_contact: dict[str, Any], audit: dict[str, Any] | None,
                normalize_phone) -> dict[str, Any]:
    audit = audit or {}
    return {
        "nap": nap(f),
        "consistency_issues": consistency(f, site_contact, normalize_phone),
        "keywords": keyword_targets(f),
        "citations": citations(f),
        "site_score": audit.get("score"),
        "content_gaps": (audit.get("content_gaps") or [])[:6],
        "schema_markup": f.schema_markup,
    }
