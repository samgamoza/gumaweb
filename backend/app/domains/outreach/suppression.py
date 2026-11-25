"""Do-not-contact rules (19-security-compliance; ported from guma_os `SuppressionRepository`/`DNCPolicy`).

A suppression is either one email address or a whole domain. Suppressing `acme.ph` blocks every address
at exactly that domain (not its subdomains: `mail.acme.ph` needs its own entry). Values are stored
normalized so lookups are exact matches.
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.domains.business_discovery.normalization import email_domain, normalize_email


class SuppressionKind(StrEnum):
    EMAIL = "email"
    DOMAIN = "domain"


class SuppressionReason(StrEnum):
    UNSUBSCRIBED = "unsubscribed"  # recipient used the unsubscribe link
    REQUESTED = "requested"  # asked us directly (email, phone, complaint) and staff recorded it
    BOUNCED = "bounced"  # hard bounce: the address does not exist
    COMPLAINT = "complaint"  # marked as spam
    LEGAL = "legal"  # regulator, counsel or data-subject request


_DOMAIN_RE = re.compile(r"(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*\.[a-z]{2,63}")


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    domain = value.strip().lower().rstrip(".")
    if domain.startswith("@"):
        domain = domain[1:]
    domain = domain.removeprefix("www.")
    return domain if _DOMAIN_RE.fullmatch(domain) else None


def normalize_suppression(kind: SuppressionKind, value: str) -> str:
    """The stored form of a suppression value. Raises ValueError when it is not a valid email/domain."""
    normalized = normalize_email(value) if kind is SuppressionKind.EMAIL else normalize_domain(value)
    if normalized is None:
        raise ValueError(f"not a valid {kind.value}: {value!r}")
    return normalized


def suppression_keys(email: str | None) -> list[tuple[SuppressionKind, str]]:
    """Every (kind, value) entry that would block this email: the address itself and its domain."""
    normalized = normalize_email(email)
    if normalized is None:
        return []
    keys = [(SuppressionKind.EMAIL, normalized)]
    domain = email_domain(normalized)
    if domain:
        keys.append((SuppressionKind.DOMAIN, domain))
    return keys
