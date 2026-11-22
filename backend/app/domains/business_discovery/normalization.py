"""Normalize + deduplicate stage of the discovery pipeline (Crawl → Normalize → Deduplicate)."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "opc", "enterprise", "enterprises", "and", "the",
}
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.com.ph", "ymail.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com", "mail.com",
}
_SOCIAL_HOSTS = ("facebook.com", "fb.com", "instagram.com", "tiktok.com", "linktr.ee")


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def normalize_name_key(name: str) -> str:
    """Canonical comparison key: 'ABC Construction, Inc.' -> 'abc construction'."""
    tokens = re.findall(r"[a-z0-9]+", _ascii(name).lower())
    meaningful = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(meaningful or tokens)


def normalize_phone(phone: str | None, default_country_code: str = "63") -> str | None:
    """Return digits in international format without '+', e.g. '639171234567'."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = default_country_code + digits[1:]
    elif len(digits) <= 10 and not digits.startswith(default_country_code):
        digits = default_country_code + digits
    return digits if 8 <= len(digits) <= 15 else None


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) else None


def email_domain(email: str | None) -> str | None:
    return email.rsplit("@", 1)[1] if email and "@" in email else None


def is_free_email(email: str | None) -> bool:
    domain = email_domain(email)
    return bool(domain and domain in _FREE_EMAIL_DOMAINS)


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def url_host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host or None


def is_real_website(url: str | None) -> bool:
    """A Facebook page or link-in-bio is not an owned website."""
    host = url_host(url)
    return bool(host) and not any(host == s or host.endswith("." + s) for s in _SOCIAL_HOSTS)


def slugify(value: str, max_length: int = 63) -> str:
    """DNS-label-safe slug (RFC 1123): lowercase alnum and hyphens, max 63 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(value).lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "business"


def build_dedupe_key(name: str, city: str | None, phone: str | None) -> str:
    """Records with the same canonical name+city (or name+phone) are the same business."""
    city_key = normalize_name_key(city) if city else ""
    return f"{normalize_name_key(name)}|{city_key}|{phone or ''}"[:255]
