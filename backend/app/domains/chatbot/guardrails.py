"""Chatbot guardrails: input limits, lead extraction, and answer post-checks."""

from __future__ import annotations

import re

from app.domains.website_factory.content_quality import fabricated_claims

MAX_MESSAGE_CHARS = 1000
MAX_TURNS_PER_CONVERSATION = 40

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?63|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}\b|\+\d{8,15}\b")
# Trigger phrase is case-insensitive ("My name is..."); the name itself must be capitalized words.
_NAME = re.compile(r"\b(?i:my name is|i am|i'm|this is|ako si)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


def clean_message(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()
    return text[:MAX_MESSAGE_CHARS]


def extract_contact(text: str) -> dict[str, str]:
    """Deterministic lead capture: visitors type their details; no model needed to find them."""
    found: dict[str, str] = {}
    if email := _EMAIL.search(text):
        found["email"] = email.group(0).lower()
    if phone := _PHONE.search(text):
        found["phone"] = phone.group(0)
    if name := _NAME.search(text):
        found["name"] = name.group(1)
    return found


def unsupported_claims(answer: str, knowledge_text: str) -> list[str]:
    """Claims (prices, years, ratings, awards, statistics) in the answer that the knowledge base doesn't contain."""
    known = set(fabricated_claims(knowledge_text))
    return [claim for claim in fabricated_claims(answer) if claim not in known]
