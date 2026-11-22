"""Social media kit copy: platform bios within each limit, local hashtags, and starter posts.

Every sentence is assembled from PresenceFacts: no invented offers, prices, awards or years in business.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.domains.presence.facts import PresenceFacts, fit, join_names, phone_display, truncate, with_utm

# Character limits of the visible bio/intro field on each platform.
BIO_LIMITS = {"facebook": 101, "instagram": 150, "tiktok": 80, "x": 160}
MAX_HASHTAGS = 8
CAPTION_LIMIT = 2200  # Instagram's caption limit (Facebook's is far higher)


@dataclass(frozen=True)
class Post:
    key: str
    title: str  # for the owner: what this post is
    caption: str
    card_headline: str  # text on the matching image card
    card_subline: str


def _camel(text: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", text))


def hashtags(f: PresenceFacts) -> list[str]:
    tags: list[str] = []
    if f.city:
        tags += [_camel(f.city), _camel(f.city) + f.noun]
    if f.province and f.province != f.city:
        tags.append(_camel(f.province))
    tags += [_camel(name) for name, _ in f.services[:4]]
    tags.append(f.noun)
    seen: set[str] = set()
    result = []
    for tag in tags:
        if tag and len(tag) <= 30 and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append("#" + tag)
    return result[:MAX_HASHTAGS]


def bios(f: PresenceFacts) -> dict[str, str]:
    who = f"{f.industry_label} in {f.place}" if f.place else f.industry_label
    names = [n for n, _ in f.services]
    cta = "Book online below" if f.booking_enabled else "Message us to get started"
    phone = phone_display(f.phone)
    top3, top2 = " · ".join(names[:3]), " · ".join(names[:2])
    result = {}
    for platform, limit in BIO_LIMITS.items():
        if platform == "instagram":  # multi-line bios are the norm on Instagram
            lines = [who, top3, f"📍 {f.place}" if f.place else "", f"📞 {phone}" if phone else "", f"👇 {cta}"]
            candidates = ["\n".join(x for x in lines if x),
                          "\n".join(x for x in [who, top2, f"👇 {cta}"] if x),
                          "\n".join(x for x in [who, f"👇 {cta}"] if x)]
            result[platform] = next((c for c in candidates if len(c) <= limit), truncate(who, limit))
            continue
        result[platform] = fit([f"{who}. {top3}. {cta}.", f"{who}. {top2}. {cta}.", f"{who}. {cta}.", who], limit)
    return result


def _tags(f: PresenceFacts, n: int = 5) -> str:
    return " ".join(hashtags(f)[:n])


def starter_posts(f: PresenceFacts) -> list[Post]:
    """A first week of posts. The owner reviews and publishes them; we never post on their behalf."""
    link = with_utm(f.website_url, "social", "organic", "starter_kit")
    posts = [Post(
        "welcome", "Announce your website",
        f"We're online! 🎉 See everything {f.name} offers{' in ' + f.place if f.place else ''} and get in touch "
        f"through our new website: {link}\n\n{_tags(f)}",
        "We're online!", f.name,
    )]
    for name, description in f.services[:3]:
        desc = description.rstrip(".") + "." if description else ""
        posts.append(Post(
            f"service-{_camel(name).lower()}", f"Spotlight: {name}",
            f"{name} at {f.name}. {desc}\n\nQuestions? Send us a message or visit {link}\n\n{_tags(f, 4)}",
            name, f.name,
        ))
    if f.faq:
        question, answer = f.faq[0]
        posts.append(Post(
            "faq", "Answer a common question",
            f"Q: {question}\nA: {answer}\n\nMore answers on our website: {link}",
            truncate(question, 60), f.name,
        ))
    contact_lines = [x for x in [
        f"📍 {', '.join(p for p in [f.address, f.city] if p)}" if (f.address or f.city) else "",
        f"📞 {phone_display(f.phone)}" if f.phone else "",
        f"✉️ {f.email}" if f.email else "",
    ] if x]
    if contact_lines:
        posts.append(Post(
            "contact", "Tell people how to reach you",
            f"How to reach {f.name}:\n" + "\n".join(contact_lines) + f"\n\n{link}",
            "Get in touch", f.name,
        ))
    if f.booking_enabled:
        posts.append(Post(
            "booking", "Invite online bookings",
            f"You can now book with {f.name} online, any time: {link}\n\nPick a service and a time that suits you.",
            "Book online", f.name,
        ))
    return [Post(p.key, p.title, truncate(p.caption, CAPTION_LIMIT), p.card_headline, p.card_subline) for p in posts]


def social_kit(f: PresenceFacts) -> dict:
    return {
        "bios": bios(f),
        "hashtags": hashtags(f),
        "posts": [asdict(p) for p in starter_posts(f)],
        "services_line": join_names([n for n, _ in f.services[:3]]),
    }
