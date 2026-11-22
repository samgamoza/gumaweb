"""`ai_generations` persistence: content cache + token/latency ledger for every model call."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AIGeneration


class AIGenerationStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, cache_key: str) -> dict[str, Any] | None:
        row = self.db.scalar(
            select(AIGeneration).where(AIGeneration.cache_key == cache_key, AIGeneration.accepted.is_(True))
        )
        return row.response if row else None

    def save(self, *, cache_key: str, task: str, model: str, prompt_version: str, request: dict[str, Any],
             response: dict[str, Any] | None, accepted: bool, rejection_reasons: list[str], prompt_tokens: int,
             completion_tokens: int, latency_ms: int) -> None:
        row = AIGeneration(
            cache_key=cache_key, task=task, model=model[:128], prompt_version=prompt_version, request=request,
            response=response, accepted=accepted, rejection_reasons=rejection_reasons,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, latency_ms=latency_ms,
        )
        try:
            with self.db.begin_nested():
                existing = self.db.scalar(select(AIGeneration).where(AIGeneration.cache_key == cache_key))
                if existing is None:
                    self.db.add(row)
                else:  # retried after an invalid response: keep the latest attempt
                    for field in ("response", "accepted", "rejection_reasons", "prompt_tokens",
                                  "completion_tokens", "latency_ms", "model"):
                        setattr(existing, field, getattr(row, field))
        except IntegrityError:  # concurrent worker stored the same key first
            pass
