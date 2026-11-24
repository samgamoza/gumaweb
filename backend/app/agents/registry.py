"""Resolves which agent/generator implementation the pipeline uses."""

from __future__ import annotations

from app.agents.base import LLMClient
from app.agents.business_agents import BusinessProfilerAgent
from app.agents.chat_agent import ChatAgent
from app.agents.content_agent import GenerationStore, LLMContentGenerator, QualityThresholds
from app.agents.llm_client import build_llm_client
from app.core.config import Settings
from app.domains.website_factory.content import ContentGenerator, TemplateContentGenerator


def get_content_generator(settings: Settings, store: GenerationStore | None = None) -> ContentGenerator:
    if not settings.ai_enabled:
        return TemplateContentGenerator()
    return LLMContentGenerator(
        build_llm_client(settings),
        primary_model=settings.llm_primary_model,
        reviewer_model=settings.llm_secondary_model if settings.ai_review_enabled else None,
        store=store,
        thresholds=QualityThresholds(settings.content_min_readability, settings.content_max_spam),
        json_mode=settings.llm_json_mode,
    )


def get_profiler_agent(settings: Settings) -> BusinessProfilerAgent:
    return BusinessProfilerAgent()


def get_background_llm(settings: Settings) -> LLMClient | None:
    """LLM for worker jobs (background profile), or None when AI is disabled."""
    return build_llm_client(settings) if settings.ai_enabled else None


def get_chat_agent(settings: Settings) -> ChatAgent:
    """Website assistant: LLM-grounded when AI is enabled, retrieval-only (FAQ bot) otherwise."""
    if not settings.ai_enabled:
        return ChatAgent(None, None)
    # Interactive profile: on timeout the agent falls back to its retrieval answer.
    llm = build_llm_client(settings, profile="interactive")
    return ChatAgent(llm, settings.llm_primary_model, settings.llm_json_mode)
