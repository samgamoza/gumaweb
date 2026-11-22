"""Business Intelligence agents (05): Industry, Service, Brand and SEO agents.

Phase 1: one rules-based profiler agent backed by the industry catalog.
Phase 2: split into LLM-backed agents that start from this rules output
(cheap, cached) and only call the model when confidence is low.
"""

from __future__ import annotations

from app.agents.base import AgentResult
from app.domains.business_profile.profiler import ProfileInput, ProfileResult, build_profile


class BusinessProfilerAgent:
    name = "business-profiler"

    def run(self, data: ProfileInput) -> AgentResult[ProfileResult]:
        result = build_profile(data)
        return AgentResult(output=result, agent=self.name, strategy="rules", confidence=result.confidence)
