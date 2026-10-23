"""Login rate limiting: Redis-backed sliding window with in-memory fallback.

Semantics (identical in both backends):
- ``record_failure`` appends a timestamp to a per-(client, identifier) window.
- After ``max_failures`` failures inside ``window_seconds``, the identifier
  is blocked for a full ``window_seconds`` (``blocked_until``), even if the
  old failures start ageing out of the window in the meantime.
- ``is_blocked`` is true while ``blocked_until`` is in the future or the
  window still holds >= ``max_failures`` entries.

Backends:
- :class:`RedisLoginRateLimiter` - sorted sets + a blocked-until key, safe
  across multiple API workers (the reason this module exists). Uses wall
  time because monotonic clocks are not comparable across processes.
- :class:`InMemoryLoginRateLimiter` - the original single-process limiter
  (monotonic clock). Used when Redis is unreachable so login limiting
  degrades to per-process rather than disappearing entirely.

Selection: ``RATE_LIMIT_BACKEND=auto|redis|memory`` (default ``auto``:
try Redis once at first use; on failure log a warning and fall back to
memory for the process lifetime).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Protocol

from apps.api.app.core.config import settings

logger = logging.getLogger(__name__)


class LoginRateLimiter(Protocol):
    """Rate-limiter interface used by the auth endpoints."""

    async def is_blocked(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> bool: ...

    async def record_failure(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> None: ...

    async def reset(self) -> None: ...


class InMemoryLoginRateLimiter:
    """Sliding-window limiter over (client_key, identifier) failed attempts.

    Single-process only: state lives in this API worker's memory. Kept as
    the fallback when Redis is unavailable so limiting degrades instead of
    vanishing.
    """

    def __init__(self, max_failures: int = 5, window_seconds: float = 300.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._blocked_until: dict[tuple[str, str], float] = {}

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        bucket = self._failures.get(key, [])
        cutoff = now - self.window_seconds
        kept = [t for t in bucket if t > cutoff]
        self._failures[key] = kept
        return kept

    async def is_blocked(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> bool:
        now = time.monotonic() if now is None else now
        key = (client_key, identifier)
        until = self._blocked_until.get(key, 0.0)
        if until > now:
            return True
        if until and until <= now:
            self._blocked_until.pop(key, None)
        return len(self._prune(key, now)) >= self.max_failures

    async def record_failure(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> None:
        now = time.monotonic() if now is None else now
        key = (client_key, identifier)
        kept = self._prune(key, now)
        kept.append(now)
        self._failures[key] = kept
        if len(kept) >= self.max_failures:
            self._blocked_until[key] = now + self.window_seconds

    async def reset(self) -> None:
        self._failures.clear()
        self._blocked_until.clear()


class RedisLoginRateLimiter:
    """Multi-worker sliding-window limiter backed by Redis sorted sets.

    Layout (wall-clock epoch seconds; comparable across processes):
    - ``ratelimit:login:f:{client}:{identifier}`` - sorted set of failures,
      score = epoch seconds, self-cleaning via TTL.
    - ``ratelimit:login:b:{client}:{identifier}`` - blocked-until epoch
      timestamp, written when the failure count reaches the threshold.
    """

    def __init__(self, client, *, max_failures: int = 5, window_seconds: float = 300.0) -> None:
        self._redis = client
        self.max_failures = max_failures
        self.window_seconds = window_seconds

    def _keys(self, client_key: str, identifier: str) -> tuple[str, str]:
        safe_client = client_key.replace(":", "%3A")
        safe_ident = identifier.replace(":", "%3A")
        return (
            f"ratelimit:login:f:{safe_client}:{safe_ident}",
            f"ratelimit:login:b:{safe_client}:{safe_ident}",
        )

    async def is_blocked(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> bool:
        now = time.time() if now is None else now
        failures_key, blocked_key = self._keys(client_key, identifier)
        blocked_until = await self._redis.get(blocked_key)
        if blocked_until is not None and float(blocked_until) > now:
            return True
        cutoff = now - self.window_seconds
        pipe = self._redis.pipeline(transaction=True)
        pipe.zremrangebyscore(failures_key, "-inf", cutoff)
        pipe.zcard(failures_key)
        _, count = await pipe.execute()
        return int(count) >= self.max_failures

    async def record_failure(
        self, client_key: str, identifier: str, *, now: float | None = None
    ) -> None:
        now = time.time() if now is None else now
        failures_key, blocked_key = self._keys(client_key, identifier)
        member = f"{now:.6f}:{uuid.uuid4().hex}"  # unique even for equal clocks
        cutoff = now - self.window_seconds

        pipe = self._redis.pipeline(transaction=True)
        pipe.zadd(failures_key, {member: now})
        pipe.zremrangebyscore(failures_key, "-inf", cutoff)
        pipe.zcard(failures_key)
        pipe.expire(failures_key, int(self.window_seconds) + 1)
        results = await pipe.execute()
        count = int(results[2])

        if count >= self.max_failures:
            # Guaranteed cooldown even if old failures age out mid-window.
            ttl = int(self.window_seconds * 2)
            await self._redis.set(blocked_key, now + self.window_seconds, ex=ttl)

    async def reset(self) -> None:
        """Delete every limiter key (test/admin helper; O(keyspace scan))."""
        deleted = 0
        async for key in self._redis.scan_iter(match="ratelimit:login:*"):
            await self._redis.delete(key)
            deleted += 1
        return deleted


_login_limiter: LoginRateLimiter | None = None


async def get_login_limiter() -> LoginRateLimiter:
    """Resolve the process-wide login rate limiter (cached).

    ``auto``/``redis``: try to reach Redis once; on failure fall back to the
    in-memory limiter with a warning (login limiting must never take the
    auth endpoints down with it).
    """
    global _login_limiter
    if _login_limiter is not None:
        return _login_limiter

    backend = settings.rate_limit_backend.lower()
    if backend == "memory":
        _login_limiter = InMemoryLoginRateLimiter(
            max_failures=settings.rate_limit_max_failures,
            window_seconds=settings.rate_limit_window_seconds,
        )
        return _login_limiter

    if backend not in ("auto", "redis"):
        logger.warning("Unknown RATE_LIMIT_BACKEND %r - using memory", backend)

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        await client.ping()
        _login_limiter = RedisLoginRateLimiter(
            client,
            max_failures=settings.rate_limit_max_failures,
            window_seconds=settings.rate_limit_window_seconds,
        )
        logger.info("Login rate limiting: Redis backend (%s)", settings.redis_url)
    except Exception as exc:  # ConnectionError, TimeoutError, OSError, ...
        if backend == "redis":
            logger.error(
                "RATE_LIMIT_BACKEND=redis but Redis is unreachable (%s); "
                "falling back to per-process in-memory limiting",
                exc,
            )
        else:
            logger.warning(
                "Redis unreachable (%s); login rate limiting falls back to "
                "per-process in-memory mode",
                exc,
            )
        _login_limiter = InMemoryLoginRateLimiter(
            max_failures=settings.rate_limit_max_failures,
            window_seconds=settings.rate_limit_window_seconds,
        )
    return _login_limiter


def current_limiter_backend() -> str:
    """Name of the resolved backend ('redis', 'memory', or 'unresolved')."""
    if _login_limiter is None:
        return "unresolved"
    return "redis" if isinstance(_login_limiter, RedisLoginRateLimiter) else "memory"
