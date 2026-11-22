"""Custom domains: normalization, ownership verification records, and the DNS records owners must add."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass

from app.core.exceptions import ValidationFailedError

VERIFY_LABEL = "_gumaweb"
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# Special-use and internal names that can never be a customer's public domain.
_RESERVED_TLDS = {"local", "localhost", "test", "example", "invalid", "internal", "lan", "home", "corp", "onion"}
DOMAIN_PATTERN = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}"


@dataclass(frozen=True)
class DnsRecord:
    type: str
    name: str  # fully qualified
    value: str
    purpose: str
    priority: int | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def normalize_domain(raw: str, *, platform_domain: str) -> str:
    """'https://WWW.BellaVista.ph/about' -> 'bellavista.ph'. Raises on anything we can't serve."""
    text = raw.strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in text or ":" in text:
        raise ValidationFailedError("Enter just the domain name, like yourbusiness.ph")
    text = text.rstrip(".")
    if text.startswith("www."):
        text = text[4:]  # we serve the bare domain and its www. form together
    try:
        text = text.encode("idna").decode("ascii")  # internationalized names -> punycode
    except UnicodeError as exc:
        raise ValidationFailedError("That domain name is not valid") from exc
    try:
        ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        raise ValidationFailedError("Enter a domain name, not an IP address")
    labels = text.split(".")
    if len(text) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise ValidationFailedError("That domain name is not valid")
    if labels[-1] in _RESERVED_TLDS or labels[-1].isdigit():
        raise ValidationFailedError("That domain can't be used on the public internet")
    platform = platform_domain.lower().strip(".")
    if text == platform or text.endswith("." + platform):
        raise ValidationFailedError(f"Your {platform} address is already included; enter your own domain")
    return text


def verification_record(domain: str, token: str) -> DnsRecord:
    return DnsRecord("TXT", f"{VERIFY_LABEL}.{domain}", f"gumaweb-verify={token}",
                     "Proves you own the domain")


def is_verified(txt_values: list[str], token: str) -> bool:
    return f"gumaweb-verify={token}" in {v.strip().strip('"') for v in txt_values}


def website_records(domain: str, *, cname_target: str, ipv4: str | None) -> list[DnsRecord]:
    """Point the domain at GumaWeb. The bare domain can't be a CNAME, so it uses an A record."""
    records = [DnsRecord("CNAME", f"www.{domain}", cname_target, "Serves your website at www")]
    if ipv4:
        records.insert(0, DnsRecord("A", domain, ipv4, "Serves your website at the bare domain"))
    return records
