"""Content quality rules (07-content-generation-engine: Review Pipeline + Quality Rules).

Deterministic checks applied to every AI-written section before it is accepted:
readability, spam score, and fabricated-claim detection. A section that fails
falls back to template copy - a site is never published with unvetted AI text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SPAM_TERMS = (
    "best in the world", "#1", "number one", "guaranteed", "guarantee", "100%", "act now", "limited time",
    "click here", "buy now", "risk-free", "risk free", "cheapest", "unbeatable", "miracle", "once in a lifetime",
    "world-class", "world class", "best in town", "lowest price",
)

# Claims we cannot know from a directory record: GumaWeb never states them on an owner's behalf.
_FABRICATION_PATTERNS = {
    "years_in_business": re.compile(r"\b(since\s+(19|20)\d{2}|\d+\+?\s+years?\s+(of\s+)?(experience|in business|serving))", re.I),
    "awards": re.compile(r"\b(award[- ]winning|awarded|certified|accredited|licensed|iso\s?\d{3,5})\b", re.I),
    "prices": re.compile(r"(₱|php\s?\d|\$\s?\d|\bpesos?\b|\d+\s?%\s?off|\bfree\b(?!\s+(consultation|estimate|quote|inspection)))", re.I),
    "ratings": re.compile(r"\b(\d(\.\d)?\s?stars?|five[- ]star|5[- ]star|rated|reviews?\b|testimonials?)", re.I),
    "statistics": re.compile(r"\b\d{2,}[\d,]*\+?\s+(clients|customers|projects|patients|students|homes|happy)\b", re.I),
}


@dataclass
class SectionQuality:
    readability: float
    spam_score: int
    issues: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.issues


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups) - (1 if word.endswith("e") and len(groups) > 1 else 0)
    return max(1, count)


def flesch_reading_ease(text: str) -> float:
    sentences = max(1, len(re.findall(r"[.!?]+", text)) or 1)
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return 100.0
    syllables = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words)), 1)


def spam_score(text: str) -> int:
    lowered = text.lower()
    score = 15 * sum(lowered.count(term) for term in _SPAM_TERMS)
    score += 5 * text.count("!")
    letters = [c for c in text if c.isalpha()]
    if letters:
        caps_ratio = sum(c.isupper() for c in letters) / len(letters)
        if caps_ratio > 0.3:
            score += 30
    return min(100, score)


def fabricated_claims(text: str) -> list[str]:
    return [name for name, pattern in _FABRICATION_PATTERNS.items() if pattern.search(text)]


# Readability is only meaningful for running prose - not headlines, labels or button text.
PROSE_FIELDS = frozenset({"company_story", "mission_statement", "service_summary", "answer", "description",
                          "intro", "subheadline", "text"})
MIN_WORDS_FOR_READABILITY = 25


def collect_text(value: Any, fields: frozenset[str] | None = None, _key: str | None = None) -> str:
    """Flatten copy into text; each field becomes its own sentence so headlines don't merge."""
    if isinstance(value, str):
        if fields is not None and _key not in fields:
            return ""
        text = value.strip()
        return text if not text or text[-1] in ".!?" else f"{text}."
    if isinstance(value, dict):
        return " ".join(filter(None, (collect_text(v, fields, k) for k, v in value.items())))
    if isinstance(value, list):
        return " ".join(filter(None, (collect_text(v, fields, _key) for v in value)))
    return ""


def evaluate_section(key: str, block: dict[str, Any], *, min_readability: float, max_spam: int,
                     known_facts: str = "") -> SectionQuality:
    """`known_facts` is the source data; a "claim" that appears verbatim in it is a fact, not a fabrication."""
    text = collect_text(block)
    prose = collect_text(block, PROSE_FIELDS)
    quality = SectionQuality(readability=flesch_reading_ease(prose), spam_score=spam_score(text))
    if not text.strip():
        quality.issues.append("empty")
        return quality
    if len(prose.split()) >= MIN_WORDS_FOR_READABILITY and quality.readability < min_readability:
        quality.issues.append(f"readability {quality.readability} < {min_readability}")
    if quality.spam_score > max_spam:
        quality.issues.append(f"spam score {quality.spam_score} > {max_spam}")
    for claim in fabricated_claims(text):
        if claim not in fabricated_claims(known_facts):
            quality.issues.append(f"unsupported claim: {claim}")
    if key == "faq":
        answers = [i.get("answer", "").strip().lower() for i in block.get("items", [])]
        if len(set(answers)) < len(answers):
            quality.issues.append("duplicate FAQ answers")
    return quality
