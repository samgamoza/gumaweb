"""Test doubles for Phase 2 AI components."""

from __future__ import annotations

import json
import struct
import zlib
from typing import Any

from app.agents.base import LLMResponse

GOOD_COPY: dict[str, Any] = {
    "hero": {
        "headline": "Plumbing Help for Homes and Shops in Angeles City",
        "subheadline": "We fix leaks, put in new pipes, and clear drains for homes and shops.",
        "cta_label": "Ask for a Quote",
    },
    "about": {
        "heading": "About Santos Plumbing",
        "company_story": "Santos Plumbing is a local plumbing team in Angeles City. We help homes and shops "
                         "with leaks, new pipes, and blocked drains. Call us and we will tell you what we can do.",
        "mission_statement": "We want every home in town to have water that flows the right way.",
        "service_summary": "We fix leaks, put in pipes, clean drains, and look after water heaters.",
    },
    "services": {
        "intro": "Here is how we can help you.",
        "items": [
            {"name": "Leak Repairs", "description": "We find leaks fast and fix the pipes and taps."},
            {"name": "Gold Plating", "description": "We plate your taps in real gold for you."},
            {"name": "Drain Cleaning", "description": "We clear sinks, toilets, and main drains."},
        ],
    },
    "faq": {"items": [
        {"question": f"Question number {i} about our work?", "answer": f"This is a short and clear answer number {i}."}
        for i in range(1, 11)
    ]},
    "cta": {"heading": "Need a plumber in Angeles City?", "text": "Send us a message and we will call you back.",
            "button_label": "Contact Us"},
}


class FakeLLM:
    """Returns canned JSON; the review call echoes the draft (or a configured rewrite)."""

    def __init__(self, copy: dict[str, Any] | None = None, *, fail: bool = False, raw: str | None = None) -> None:
        self.copy = copy or GOOD_COPY
        self.fail = fail
        self.raw = raw
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, *, model: str, system: str | None = None, temperature: float = 0.3,
                 max_tokens: int = 2048, json_mode: bool = False) -> LLMResponse:
        task = "review" if prompt.startswith("You are an editor") else "content"
        self.calls.append((task, model))
        if self.fail:
            raise ConnectionError("inference server unreachable")
        text = self.raw if self.raw is not None else "```json\n" + json.dumps(self.copy) + "\n```"
        return LLMResponse(text=text, model=model, prompt_tokens=500, completion_tokens=700)


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def get(self, cache_key: str) -> dict[str, Any] | None:
        row = self.rows.get(cache_key)
        return row["response"] if row and row["accepted"] else None

    def save(self, **kwargs: Any) -> None:
        self.rows[kwargs["cache_key"]] = kwargs


def make_png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
