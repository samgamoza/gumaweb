"""The facts every presence asset is built from. Nothing outside these facts may appear in generated copy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit, urlunsplit

WEEKDAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
                 "sat": "Saturday", "sun": "Sunday"}

# Short nouns for hashtags and keyword targets ("Malolos dentist").
INDUSTRY_NOUNS = {
    "construction": "Contractor", "plumbing": "Plumber", "electrical": "Electrician", "restaurant": "Restaurant",
    "medical_clinic": "Clinic", "dental": "Dentist", "legal": "Lawyer", "accounting": "Accountant",
    "education": "School", "beauty": "Salon", "resort": "Resort", "retail": "Store", "auto_repair": "AutoRepair",
    "general": "Business",
}


@dataclass(frozen=True)
class PresenceFacts:
    name: str
    industry: str
    industry_label: str
    city: str | None
    province: str | None
    address: str | None
    postal_code: str | None
    phone: str | None  # international digits, e.g. 639171234567
    email: str | None
    website_url: str
    tagline: str | None
    about: str | None
    services: list[tuple[str, str]] = field(default_factory=list)  # (name, description)
    faq: list[tuple[str, str]] = field(default_factory=list)
    booking_enabled: bool = False
    weekly_hours: dict[str, list[list[str]]] | None = None  # only when the owner configured them
    palette: dict[str, str] = field(default_factory=dict)
    local_keywords: list[str] = field(default_factory=list)
    facebook_url: str | None = None
    google_business_url: str | None = None
    schema_markup: dict = field(default_factory=dict)

    @property
    def noun(self) -> str:
        return INDUSTRY_NOUNS.get(self.industry, "Business")

    @property
    def place(self) -> str | None:
        return self.city or self.province


def phone_display(digits: str | None) -> str | None:
    """Local Philippine format for people: 639171234567 -> 0917 123 4567; other numbers as +digits."""
    if not digits:
        return None
    if digits.startswith("639") and len(digits) == 12:
        local = "0" + digits[2:]
        return f"{local[:4]} {local[4:7]} {local[7:]}"
    return f"+{digits}"


def phone_e164(digits: str | None) -> str | None:
    return f"+{digits}" if digits else None


def with_utm(url: str, source: str, medium: str, campaign: str) -> str:
    """Tag links so the owner's analytics show which channel brought the visit."""
    parts = urlsplit(url)
    query = "&".join(q for q in [parts.query, urlencode(
        {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign})] if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def fit(candidates: list[str], limit: int) -> str:
    """The first candidate within `limit` characters, else the last one cut at a word boundary."""
    for text in candidates:
        text = re.sub(r"\s+", " ", text).strip()
        if text and len(text) <= limit:
            return text
    return truncate(candidates[-1], limit)


def truncate(text: str, limit: int) -> str:
    # Collapse runs of spaces but keep line breaks: captions and bios use them.
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.strip().splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-·")
    return cut + "…"


def join_names(names: list[str], conj: str = "&") -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {conj} {names[-1]}"


def format_hours(weekly: dict[str, list[list[str]]] | None) -> list[str]:
    """['Monday: 9:00 AM – 5:00 PM', 'Sunday: Closed', ...] or [] when hours are unknown."""
    if not weekly:
        return []
    lines = []
    for key, label in WEEKDAY_NAMES.items():
        ranges = weekly.get(key) or []
        if not ranges:
            lines.append(f"{label}: Closed")
            continue
        lines.append(f"{label}: " + ", ".join(f"{_clock(a)} – {_clock(b)}" for a, b in ranges))
    return lines


def _clock(hhmm: str) -> str:
    hour, minute = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"
