"""URL strategy (10-publication-and-hosting): business-name.gumaweb.io"""

from __future__ import annotations

import re

from app.domains.business_discovery.normalization import slugify

SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

RESERVED_SUBDOMAINS = frozenset(
    {
        "www", "api", "app", "admin", "portal", "dashboard", "mail", "smtp", "imap", "static", "cdn",
        "assets", "media", "docs", "help", "support", "status", "blog", "grafana", "prometheus", "auth",
        "login", "claim", "claims", "billing", "gumaweb", "guma", "ns1", "ns2", "ftp", "test", "staging",
        "verify",  # collides with the portal route /claim/verify
    }
)


def is_valid_subdomain(value: str) -> bool:
    return bool(SUBDOMAIN_RE.match(value)) and value not in RESERVED_SUBDOMAINS


def subdomain_candidates(name: str, city: str | None):
    """Yield candidates in preference order: name, name-city, name-city-2, ..."""
    base = slugify(name, max_length=50)
    if base in RESERVED_SUBDOMAINS:
        base = f"{base}-site"
    yield base
    if city:
        with_city = slugify(f"{base}-{city}", max_length=58)
        yield with_city
    else:
        with_city = base
    for n in range(2, 1000):
        yield f"{with_city[:58]}-{n}"
