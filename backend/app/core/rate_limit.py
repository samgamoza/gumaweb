"""Fixed-window rate limiter with a Redis backend and an in-memory fallback."""

from __future__ import annotations

import threading
import time
from typing import Protocol

from app.core.config import get_settings
from app.core.exceptions import RateLimitedError


class RateLimiterBackend(Protocol):
    def hit(self, key: str, window_seconds: int) -> int: ...


class MemoryBackend:
    """Single-process backend for development and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, expires_at = self._counters.get(key, (0, 0.0))
            if now >= expires_at:
                count, expires_at = 0, now + window_seconds
            count += 1
            self._counters[key] = (count, expires_at)
            return count

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


class RedisBackend:
    """Shared backend so limits hold across API replicas."""

    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url)

    def hit(self, key: str, window_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)


class RateLimiter:
    def __init__(self, backend: RateLimiterBackend) -> None:
        self.backend = backend

    def check(self, scope: str, identity: str, limit: int, window_seconds: int = 3600) -> None:
        count = self.backend.hit(f"ratelimit:{scope}:{identity}", window_seconds)
        if count > limit:
            raise RateLimitedError(f"Too many requests for {scope}; try again later")


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        backend: RateLimiterBackend = (
            RedisBackend(settings.redis_url) if settings.redis_url else MemoryBackend()
        )
        _limiter = RateLimiter(backend)
    return _limiter
