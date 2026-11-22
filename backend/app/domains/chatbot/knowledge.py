"""Chatbot knowledge base (12-customer-portal AI Chatbot: knowledge_base) and retrieval.

The knowledge base is derived from the business's own website content (FAQ,
services, about, contact) plus owner-written entries. Retrieval is BM25 over
that small per-business corpus - accurate for a few hundred entries, fully
local, no embedding service required. An embedding retriever can replace it
behind the same function signature.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "have", "how", "i",
    "if", "in", "is", "it", "me", "my", "of", "on", "or", "our", "please", "that", "the", "their", "there",
    "this", "to", "us", "we", "what", "when", "where", "which", "who", "will", "with", "you", "your",
    "po", "ba", "ang", "ng", "sa", "mga",  # common Filipino function words
})


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    title: str
    content: str
    section: str | None = None


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


def entries_from_content(name: str, content: dict[str, dict[str, Any]],
                         business: dict[str, Any]) -> list[dict[str, str]]:
    """Turn website sections into Q/A-style knowledge entries."""
    entries: list[dict[str, str]] = []
    for item in content.get("faq", {}).get("items", []):
        if item.get("question") and item.get("answer"):
            entries.append({"title": item["question"], "content": item["answer"], "section": "faq"})
    services = content.get("services", {}).get("items", [])
    if services:
        entries.append({
            "title": f"What services does {name} offer?",
            "content": "; ".join(f"{s['name']}: {s.get('description', '')}".strip() for s in services),
            "section": "services",
        })
        for s in services:
            entries.append({"title": s["name"], "content": s.get("description") or s["name"], "section": "services"})
    about = content.get("about", {})
    if about.get("company_story"):
        entries.append({"title": f"About {name}", "content": about["company_story"], "section": "about"})
    contact_bits = []
    if business.get("phone"):
        contact_bits.append(f"phone +{business['phone']}" if str(business["phone"]).isdigit() else business["phone"])
    if business.get("email"):
        contact_bits.append(f"email {business['email']}")
    location = ", ".join(p for p in (business.get("address"), business.get("city"), business.get("province")) if p)
    if location:
        contact_bits.append(f"located at {location}")
    if contact_bits:
        entries.append({"title": f"How do I contact {name}? Where are you located?",
                        "content": f"You can reach {name} by {'; '.join(contact_bits)}.", "section": "contact"})
    return entries


def bm25_rank(query: str, items: list[KnowledgeItem], k1: float = 1.4,
              b: float = 0.75) -> list[tuple[float, KnowledgeItem]]:
    q_terms = tokenize(query)
    if not q_terms or not items:
        return []
    docs = [tokenize(f"{i.title} {i.title} {i.content}") for i in items]  # titles weigh double
    avg_len = sum(len(d) for d in docs) / len(docs) or 1
    df = Counter(term for d in docs for term in set(d))
    n = len(docs)
    scored = []
    for item, doc in zip(items, docs, strict=True):
        tf = Counter(doc)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avg_len))
        if score > 0:
            scored.append((round(score, 4), item))
    return sorted(scored, key=lambda pair: pair[0], reverse=True)
