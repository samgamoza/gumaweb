"""Client for self-hosted, OpenAI-compatible inference servers (vLLM in guma-ai, Ollama in dev)."""

from __future__ import annotations

import time

import httpx

from app.agents.base import AIDisabledError, LLMClient, LLMResponse
from app.core.config import Settings


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0,
                 retries: int = 2) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)
        self._retries = retries

    def complete(self, prompt: str, *, model: str, system: str | None = None, temperature: float = 0.3,
                 max_tokens: int = 2048, json_mode: bool = False) -> LLMResponse:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        body: dict[str, object] = {"model": model, "messages": messages, "temperature": temperature,
                                   "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(self._retries + 1):
            try:
                response = self._client.post("/chat/completions", json=body)
                if response.status_code >= 500 and attempt < self._retries:
                    raise httpx.HTTPStatusError("server error", request=response.request, response=response)
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt >= self._retries:
                    raise
                time.sleep(2**attempt)
        data = response.json()
        usage = data.get("usage") or {}
        return LLMResponse(
            text=data["choices"][0]["message"]["content"] or "",
            model=data.get("model", model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )


class DisabledLLMClient:
    def complete(self, prompt: str, *, model: str, system: str | None = None, temperature: float = 0.3,
                 max_tokens: int = 2048, json_mode: bool = False) -> LLMResponse:
        raise AIDisabledError("AI is disabled (set AI_ENABLED=true and LLM_BASE_URL)")


def build_llm_client(settings: Settings) -> LLMClient:
    if not settings.ai_enabled:
        return DisabledLLMClient()
    return OpenAICompatibleClient(settings.llm_base_url, settings.llm_api_key, settings.llm_timeout_seconds)
