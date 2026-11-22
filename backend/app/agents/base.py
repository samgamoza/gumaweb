"""Agent contracts (17-ai-infrastructure).

Every agent has a deterministic strategy and a typed input/output, so call sites
are identical whether rules or a local model (Qwen / DeepSeek via vLLM or
Ollama) produce the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class AgentResult(Generic[OutputT]):
    output: OutputT
    agent: str
    strategy: str  # "rules" | "llm"
    model: str | None = None
    confidence: float | None = None


class Agent(Protocol[InputT, OutputT]):
    name: str

    def run(self, data: InputT) -> AgentResult[OutputT]: ...


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    """Minimal chat-completion contract satisfied by any OpenAI-compatible server
    (vLLM, Ollama, llama.cpp server, TGI)."""

    def complete(self, prompt: str, *, model: str, system: str | None = None, temperature: float = 0.3,
                 max_tokens: int = 2048, json_mode: bool = False) -> LLMResponse: ...


class AIDisabledError(RuntimeError):
    pass
