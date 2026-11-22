"""Google Business Profile pack: listing copy, categories, hours and first posts, ready to paste.

We never create or edit the listing ourselves: that requires the owner's Google account (and Google's
API approval). Instead the pack follows Google's listing guidelines, which matter because violations
get profiles suspended: the real-world name only (no keywords or locations), a description without
links, phone numbers or promotional language, and post text without phone numbers.
"""

from __future__ import annotations

import re

from app.domains.presence.facts import PresenceFacts, format_hours, join_names, truncate, with_utm

DESCRIPTION_LIMIT = 750
SERVICE_DESCRIPTION_LIMIT = 300
POST_LIMIT = 1500

# Google Business Profile category names (primary first). "general" has none: the owner must choose.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "construction": ("Construction company", "General contractor", "Roofing contractor"),
    "plumbing": ("Plumber",),
    "electrical": ("Electrician",),
    "restaurant": ("Restaurant", "Filipino restaurant"),
    "medical_clinic": ("Medical clinic", "Doctor"),
    "dental": ("Dentist", "Dental clinic"),
    "legal": ("Law firm", "Lawyer"),
    "accounting": ("Accountant", "Accounting firm"),
    "education": ("School", "Tutoring service"),
    "beauty": ("Beauty salon", "Spa"),
    "resort": ("Resort hotel", "Hotel"),
    "retail": ("Store",),
    "auto_repair": ("Auto repair shop", "Car repair and maintenance service"),
    "general": (),
}

_URL = re.compile(r"(https?://|www\.)\S+|\b\S+\.(com|ph|net|org|io)\b", re.I)
_PHONE = re.compile(r"(\+?\d[\d\s-]{7,}\d)")
_PROMO = re.compile(r"\b(sale|discount|promo|% ?off|cheapest|best|no\.? ?1|number one|free|limited time)\b", re.I)

CHECKLIST = [
    ("claim", "Create or claim your profile at business.google.com"),
    ("verify", "Verify the profile (Google offers phone, email, video or postcard)"),
    ("categories", "Set the primary and additional categories"),
    ("description", "Paste the business description"),
    ("hours", "Add your opening hours"),
    ("photos", "Upload the logo, cover image and real photos of your business"),
    ("services", "Add your services"),
    ("website", "Add your website link"),
    ("first_post", "Publish your first update"),
]


def description_issues(text: str) -> list[str]:
    issues = []
    if len(text) > DESCRIPTION_LIMIT:
        issues.append(f"Longer than {DESCRIPTION_LIMIT} characters")
    if _URL.search(text):
        issues.append("Contains a link (not allowed in the description)")
    if _PHONE.search(text):
        issues.append("Contains a phone number (not allowed in the description)")
    if m := _PROMO.search(text):
        issues.append(f"Promotional wording (\"{m.group(0)}\") is not allowed in the description")
    return issues


def name_issues(name: str, city: str | None, services: list[str]) -> list[str]:
    """Keyword-stuffed names are a common reason for suspension."""
    issues = []
    lowered = name.lower()
    if city and city.lower() in lowered:
        issues.append(f"The name contains the city (\"{city}\"). Use it only if it is part of your real, "
                      "signed business name.")
    if any(sep in name for sep in (" - ", " | ", " / ")):
        issues.append("The name contains a separator, which usually signals added keywords.")
    if any(s.lower() in lowered for s in services if len(s) > 3):
        issues.append("The name contains a service keyword. Use it only if it is part of your real business name.")
    return issues


def _clean_description(f: PresenceFacts) -> str:
    names = [n.lower() for n, _ in f.services[:5]]
    about = (f.about or "").strip()
    opener = f"{f.name} is a {f.industry_label.lower()}{' in ' + f.place if f.place else ''}."
    # The about story usually introduces the business already; repeating it reads like filler.
    parts = [about] if f.name.lower() in about.lower() else [opener, about]
    if names and sum(n in about.lower() for n in names) < max(1, len(names) // 2):
        parts.append(f"We offer {join_names(names, 'and')}.")
    parts.append("Book an appointment online through our website." if f.booking_enabled else
                 "Send us a message through our website to get started.")
    text = " ".join(p.strip() for p in parts if p and p.strip())
    # Drop whole sentences that break the guidelines (deleting just the offending words leaves
    # fragments like "Call or visit for the !"), and repeats (the about story often restates the opener).
    sentences, seen = [], set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        key = re.sub(r"\W+", "", sentence.lower())
        if not key or key in seen or _URL.search(sentence) or _PHONE.search(sentence) or _PROMO.search(sentence):
            continue
        seen.add(key)
        sentences.append(sentence)
    return truncate(" ".join(sentences), DESCRIPTION_LIMIT)


def google_business_pack(f: PresenceFacts) -> dict:
    categories = CATEGORIES.get(f.industry, ())
    description = _clean_description(f)
    website = with_utm(f.website_url, "google", "organic", "gbp")
    posts = [{
        "key": "welcome",
        "text": truncate(f"Welcome to {f.name}! Visit our website to see our services"
                         f"{' and book online' if f.booking_enabled else ''}.", POST_LIMIT),
        "button": "Book" if f.booking_enabled else "Learn more",
    }]
    for name, desc in f.services[:2]:
        posts.append({"key": f"service-{len(posts)}",
                      "text": truncate(_PHONE.sub("", f"{name}: {desc}".strip()), POST_LIMIT),
                      "button": "Learn more"})
    hours = format_hours(f.weekly_hours)
    return {
        "name": f.name,
        "name_issues": name_issues(f.name, f.city, [n for n, _ in f.services]),
        "primary_category": categories[0] if categories else None,
        "additional_categories": list(categories[1:]),
        "description": description,
        "description_issues": description_issues(description),
        "website": website,
        "phone": f.phone,
        "address": ", ".join(p for p in [f.address, f.city, f.province, f.postal_code] if p) or None,
        "hours": hours,
        "hours_missing": not hours,
        "services": [{"name": n, "description": truncate(d or n, SERVICE_DESCRIPTION_LIMIT)}
                     for n, d in f.services],
        "posts": posts,
        "checklist": [{"key": k, "label": label} for k, label in CHECKLIST],
    }
