"""LLM content generation (07): Prompt Builder → LLM Router → Content Validator → Content Cache.

Pipeline per site:
  1. Template copy is produced first (the guaranteed fallback and the structural base).
  2. Qwen (primary) writes the text sections as strict JSON from the business facts only.
  3. DeepSeek (secondary) reviews/rewrites the draft for grammar, concision and unsupported claims.
  4. Each section is schema-validated and quality-gated (readability, spam, fabricated claims);
     accepted sections replace the template copy, rejected ones keep it.
  5. Every model call is cached by a hash of (task, model, prompt version, input) in `ai_generations`,
     so regenerating an unchanged site costs zero tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.agents.base import LLMClient
from app.domains.business_profile.industry_catalog import get_industry
from app.domains.website_factory.content import ContentContext, ContentResult, TemplateContentGenerator
from app.domains.website_factory.content_quality import (
    PROSE_FIELDS,
    collect_text,
    evaluate_section,
    flesch_reading_ease,
)
from app.domains.website_factory.enums import ContentSource

logger = logging.getLogger("gumaweb.ai.content")

PROMPT_VERSION = "content-v2"
AI_SECTIONS = ("hero", "about", "services", "faq", "cta")

SYSTEM_PROMPT = """You write website copy for small local businesses in the Philippines.
Write clear, warm, professional English that sounds like the business itself, not like an advertisement.
Strict rules:
- Use ONLY the facts provided. If something is unknown, do not guess - invite the reader to contact the business.
- Never invent: years in business, awards, certifications, licenses, prices, discounts, statistics,
  staff or client names, ratings, reviews or testimonials.
- No superlatives such as "best", "#1", "world-class", "guaranteed". No exclamation marks.
- Keep the service names exactly as given.
- Respond with a single JSON object and nothing else."""

REVIEW_PROMPT = """You are an editor. Improve this website copy JSON for a local business:
fix grammar, make sentences natural and concise, and REMOVE any statement not supported by the facts
(years, awards, licenses, prices, numbers, ratings, reviews). Keep exactly the same JSON structure, keys
and service names. Respond with the corrected JSON object only.

FACTS:
{facts}

COPY JSON:
{draft}"""


# --- Output schemas (length limits enforce web-friendly copy) ---------------------------------
class HeroCopy(BaseModel):
    headline: str = Field(min_length=10, max_length=90)
    subheadline: str = Field(min_length=20, max_length=220)
    cta_label: str = Field(min_length=2, max_length=40)


class AboutCopy(BaseModel):
    heading: str = Field(min_length=3, max_length=80)
    company_story: str = Field(min_length=60, max_length=900)
    mission_statement: str = Field(min_length=20, max_length=300)
    service_summary: str = Field(min_length=20, max_length=400)


class ServiceItem(BaseModel):
    name: str = Field(max_length=120)
    description: str = Field(min_length=15, max_length=240)


class ServicesCopy(BaseModel):
    intro: str = Field(min_length=10, max_length=240)
    items: list[ServiceItem] = Field(min_length=1, max_length=30)


class FaqItem(BaseModel):
    question: str = Field(min_length=8, max_length=200)
    answer: str = Field(min_length=15, max_length=600)


class FaqCopy(BaseModel):
    items: list[FaqItem] = Field(min_length=6, max_length=20)


class CtaCopy(BaseModel):
    heading: str = Field(min_length=8, max_length=100)
    text: str = Field(min_length=10, max_length=240)
    button_label: str = Field(min_length=2, max_length=40)


SCHEMAS: dict[str, type[BaseModel]] = {
    "hero": HeroCopy, "about": AboutCopy, "services": ServicesCopy, "faq": FaqCopy, "cta": CtaCopy,
}

SCHEMA_HINTS = {
    "hero": '{"headline": "<= 70 chars, mention the city if known", "subheadline": "1 sentence <= 160 chars", '
            '"cta_label": "2-5 words"}',
    "about": '{"heading": "short", "company_story": "2-3 sentences", "mission_statement": "1 sentence", '
             '"service_summary": "1 sentence"}',
    "services": '{"intro": "1 sentence", "items": [{"name": "<one of the given services, exact>", '
                '"description": "1 sentence <= 140 chars"}]}',
    "faq": '{"items": [{"question": "...", "answer": "1-2 sentences"}]}  (10-12 items; only answer from the facts, '
           'otherwise suggest contacting the business)',
    "cta": '{"heading": "...", "text": "1 sentence", "button_label": "2-4 words"}',
}


class GenerationStore(Protocol):
    """Cache + ledger for model calls (implemented on the ai_generations table)."""

    def get(self, cache_key: str) -> dict[str, Any] | None: ...

    def save(self, *, cache_key: str, task: str, model: str, prompt_version: str, request: dict[str, Any],
             response: dict[str, Any] | None, accepted: bool, rejection_reasons: list[str], prompt_tokens: int,
             completion_tokens: int, latency_ms: int) -> None: ...


@dataclass(frozen=True)
class QualityThresholds:
    min_readability: float = 45.0
    max_spam: int = 10


def _facts(ctx: ContentContext) -> dict[str, Any]:
    spec = get_industry(ctx.industry)
    facts = {
        "business_name": ctx.name, "industry": spec.label, "city": ctx.city, "province": ctx.province,
        "address": ctx.address, "has_phone": bool(ctx.phone), "has_email": bool(ctx.email),
        "services": ctx.services or [n for n, _ in spec.services], "target_audience": ctx.target_audience,
        "brand_tone": ctx.brand_tone,
    }
    return {k: v for k, v in facts.items() if v not in (None, "", [])}


def extract_json(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object in a model response (tolerates code fences / reasoning preambles)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _section(data: dict[str, Any] | None, key: str) -> Any:
    """Models sometimes drop the wrapper key and return the section body directly."""
    if not data:
        return None
    if key in data:
        return data[key]
    return data if set(data) & set(SCHEMAS[key].model_fields) else None


def cache_key(task: str, model: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"task": task, "model": model, "v": PROMPT_VERSION, "in": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class LLMContentGenerator:
    name = "llm"

    def __init__(self, llm: LLMClient, *, primary_model: str, reviewer_model: str | None,
                 store: GenerationStore | None = None, thresholds: QualityThresholds | None = None,
                 json_mode: bool = True) -> None:
        self.llm = llm
        self.primary_model = primary_model
        self.reviewer_model = reviewer_model
        self.store = store
        self.thresholds = thresholds or QualityThresholds()
        self.json_mode = json_mode
        self.fallback = TemplateContentGenerator()

    # --- model calls -----------------------------------------------------------------------
    def _call(self, task: str, model: str, prompt: str, request: dict[str, Any], notes: list[str],
              system: str | None = SYSTEM_PROMPT) -> dict[str, Any] | None:
        key = cache_key(task, model, request)
        if self.store and (cached := self.store.get(key)) is not None:
            notes.append(f"{task}: cache hit")
            return cached
        started = time.perf_counter()
        try:
            response = self.llm.complete(prompt, model=model, system=system, temperature=0.4,
                                         max_tokens=3000, json_mode=self.json_mode)
        except Exception as exc:  # inference server down/timeouts: degrade to template copy
            logger.warning("%s call to %s failed: %s", task, model, exc)
            notes.append(f"{task}: model unavailable ({type(exc).__name__})")
            return None
        latency = int((time.perf_counter() - started) * 1000)
        data = extract_json(response.text)
        if self.store:
            self.store.save(cache_key=key, task=task, model=response.model, prompt_version=PROMPT_VERSION,
                            request=request, response=data, accepted=data is not None,
                            rejection_reasons=[] if data else ["invalid JSON"],
                            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                            latency_ms=latency)
        if data is None:
            notes.append(f"{task}: response was not valid JSON")
        return data

    # --- generation ------------------------------------------------------------------------
    def generate(self, ctx: ContentContext, section_keys: set[str]) -> ContentResult:
        result = self.fallback.generate(ctx, section_keys)
        wanted = [k for k in AI_SECTIONS if k in section_keys]
        if not wanted:
            return result
        facts = _facts(ctx)
        facts_json = json.dumps(facts, ensure_ascii=False, indent=1)
        known = json.dumps(facts, ensure_ascii=False)
        # One focused prompt per section: small local models stay reliable, a bad answer only costs
        # that section, and each section is cached independently.
        for key in wanted:
            prompt = (f"FACTS:\n{facts_json}\n\nWrite the \"{key}\" section of the website. "
                      f"Output JSON with exactly this shape:\n{{\"{key}\": {SCHEMA_HINTS[key]}}}")
            draft = self._call("content", self.primary_model, prompt, {"facts": facts, "section": key},
                               result.notes)
            accepted = self._accept(key, _section(draft, key), ctx, result, known)
            if accepted is None:
                continue
            if self.reviewer_model:  # only spend review tokens on drafts that already pass the gates
                reviewed = self._call(
                    "review", self.reviewer_model,
                    REVIEW_PROMPT.format(facts=known, draft=json.dumps({key: accepted}, ensure_ascii=False)),
                    {"facts": facts, "section": key, "draft": accepted}, result.notes, system=None,
                )
                improved = self._accept(key, _section(reviewed, key), ctx, result, known, label=f"{key} review")
                if improved is not None:
                    accepted = improved
            result.blocks[key] = {**result.blocks[key], **accepted}
            result.sources[key] = ContentSource.AI
        return result

    def _accept(self, key: str, raw: Any, ctx: ContentContext, result: ContentResult,
                known_facts: str, label: str | None = None) -> dict[str, Any] | None:
        label = label or key
        if not isinstance(raw, dict):
            result.notes.append(f"{label}: missing from model output")
            return None
        try:
            parsed = SCHEMAS[key].model_validate(raw).model_dump()
        except ValidationError as exc:
            result.notes.append(f"{label}: schema rejected ({exc.error_count()} errors)")
            return None
        if key == "services":
            # Never let the model add services the business does not offer.
            allowed = {s.lower(): s for s in (ctx.services or [i["name"] for i in result.blocks[key]["items"]])}
            items = [{"name": allowed[i["name"].lower()], "description": i["description"]}
                     for i in parsed["items"] if i["name"].lower() in allowed]
            if not items:
                result.notes.append(f"{label}: no known service names in output")
                return None
            described = {i["name"] for i in items}
            items += [i for i in result.blocks[key]["items"] if i["name"] not in described]
            parsed["items"] = items
        hero_text = f"{parsed.get('headline', '')} {parsed.get('subheadline', '')}".lower()
        if key == "hero" and ctx.city and ctx.city.lower() not in hero_text:
            result.notes.append(f"{label}: local SEO - hero must mention {ctx.city}")
            return None
        # Relative gate: AI prose must read at least as easily as the template copy it would replace
        # (capped at the configured target), so we never swap in something harder to read.
        baseline = flesch_reading_ease(collect_text(result.blocks.get(key, {}), PROSE_FIELDS))
        quality = evaluate_section(key, parsed, min_readability=min(self.thresholds.min_readability, baseline),
                                   max_spam=self.thresholds.max_spam, known_facts=known_facts)
        if not quality.accepted:
            result.notes.append(f"{label}: quality gate - {'; '.join(quality.issues)}")
            return None
        return parsed

