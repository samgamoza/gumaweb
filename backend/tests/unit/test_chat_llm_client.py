"""Live chat must fail fast when inference is down; batch generation keeps its retries."""

from app.agents.registry import get_background_llm, get_chat_agent
from app.core.config import Settings


def _settings() -> Settings:
    return Settings(ai_enabled=True, llm_timeout_seconds=120.0, llm_chat_timeout_seconds=7.0)


def test_chat_client_has_short_timeout_and_no_retries() -> None:
    client = get_chat_agent(_settings()).llm
    assert client._retries == 0
    assert client._client.timeout.read == 7.0


def test_batch_client_keeps_retries_and_long_timeout() -> None:
    client = get_background_llm(_settings())
    assert client._retries == 2
    assert client._client.timeout.read == 120.0
