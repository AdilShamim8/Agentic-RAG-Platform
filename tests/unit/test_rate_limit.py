"""Rate-limiter backend tests.

The Redis backend is exercised against a minimal in-process double that
implements exactly the commands the limiter uses (sorted sets, TTL'd string
keys, transactional pipelines). This keeps the tests hermetic - no Redis
server, no fakeredis dependency - while pinning the semantics that must
match the in-memory backend exactly:

- blocked only after max_failures failures within the window
- the blocked-until cooldown outlives failures ageing out of the window
- separate (client, identifier) pairs are independent
- reset clears everything
"""

from __future__ import annotations

import pytest

from apps.api.app.core import rate_limit
from apps.api.app.core.config import settings
from apps.api.app.core.rate_limit import (
    InMemoryLoginRateLimiter,
    RedisLoginRateLimiter,
    get_login_limiter,
)


class FakePipe:
    def __init__(self, store: FakeRedis) -> None:
        self._store = store
        self._ops: list[tuple[str, tuple]] = []

    def zadd(self, key: str, mapping: dict) -> FakePipe:
        self._ops.append(("zadd", (key, mapping)))
        return self

    def zremrangebyscore(self, key: str, lo: str, hi: float) -> FakePipe:
        self._ops.append(("zrem", (key, lo, hi)))
        return self

    def zcard(self, key: str) -> FakePipe:
        self._ops.append(("zcard", (key,)))
        return self

    def expire(self, key: str, ttl: int) -> FakePipe:
        self._ops.append(("expire", (key, ttl)))
        return self

    async def execute(self) -> list:
        results = []
        for op, args in self._ops:
            if op == "zadd":
                key, mapping = args
                self._store.zsets.setdefault(key, []).extend(mapping.items())
                results.append(True)
            elif op == "zrem":
                key, _, hi = args
                bucket = self._store.zsets.get(key, [])
                self._store.zsets[key] = [(m, s) for (m, s) in bucket if s > hi]
                results.append(True)
            elif op == "zcard":
                (key,) = args
                results.append(len(self._store.zsets.get(key, [])))
            elif op == "expire":
                results.append(True)
        self._ops.clear()
        return results


class FakeRedis:
    """Just enough Redis for RedisLoginRateLimiter (sorted sets + strings)."""

    def __init__(self) -> None:
        self.zsets: dict[str, list[tuple[str, float]]] = {}
        self.strings: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> FakePipe:
        return FakePipe(self)

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: float, ex: int | None = None) -> bool:
        self.strings[key] = str(value)
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> int:
        n = 0
        for store in (self.strings, self.zsets, self.ttls):
            if key in store:
                del store[key]
                n += 1
        return n

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.strings) + list(self.zsets):
            if key.startswith(prefix):
                yield key


def _redis_limiter() -> RedisLoginRateLimiter:
    return RedisLoginRateLimiter(FakeRedis(), max_failures=5, window_seconds=300.0)


# --- shared semantics --------------------------------------------------------


@pytest.mark.parametrize(
    "make_limiter",
    [lambda: InMemoryLoginRateLimiter(5, 300.0), _redis_limiter],
    ids=["memory", "redis"],
)
@pytest.mark.asyncio
async def test_blocks_after_max_failures_within_window(make_limiter) -> None:
    limiter = make_limiter()
    for i in range(4):
        await limiter.record_failure("1.2.3.4", "alice@demo.dev", now=1000.0 + i)
        assert not await limiter.is_blocked("1.2.3.4", "alice@demo.dev", now=1000.0 + i)
    await limiter.record_failure("1.2.3.4", "alice@demo.dev", now=1004.0)
    assert await limiter.is_blocked("1.2.3.4", "alice@demo.dev", now=1005.0)


@pytest.mark.parametrize(
    "make_limiter",
    [lambda: InMemoryLoginRateLimiter(5, 300.0), _redis_limiter],
    ids=["memory", "redis"],
)
@pytest.mark.asyncio
async def test_cooldown_outlives_aged_out_failures(make_limiter) -> None:
    """5 failures at t=1000 block until t=1300 even though the failures
    have aged out of the window by then."""
    limiter = make_limiter()
    for _ in range(5):
        await limiter.record_failure("1.2.3.4", "bob@demo.dev", now=1000.0)
    # Failures age out of the 300s window at t>1300, but the cooldown
    # written at the 5th failure runs to t=1300.
    assert await limiter.is_blocked("1.2.3.4", "bob@demo.dev", now=1299.0)
    assert not await limiter.is_blocked("1.2.3.4", "bob@demo.dev", now=1301.0)


@pytest.mark.parametrize(
    "make_limiter",
    [lambda: InMemoryLoginRateLimiter(5, 300.0), _redis_limiter],
    ids=["memory", "redis"],
)
@pytest.mark.asyncio
async def test_identifiers_are_independent(make_limiter) -> None:
    limiter = make_limiter()
    for _ in range(5):
        await limiter.record_failure("1.2.3.4", "carol@demo.dev", now=1000.0)
    assert await limiter.is_blocked("1.2.3.4", "carol@demo.dev", now=1001.0)
    assert not await limiter.is_blocked("1.2.3.4", "dave@demo.dev", now=1001.0)
    assert not await limiter.is_blocked("5.6.7.8", "carol@demo.dev", now=1001.0)


@pytest.mark.parametrize(
    "make_limiter",
    [lambda: InMemoryLoginRateLimiter(5, 300.0), _redis_limiter],
    ids=["memory", "redis"],
)
@pytest.mark.asyncio
async def test_reset_clears_state(make_limiter) -> None:
    limiter = make_limiter()
    for _ in range(5):
        await limiter.record_failure("1.2.3.4", "erin@demo.dev", now=1000.0)
    assert await limiter.is_blocked("1.2.3.4", "erin@demo.dev", now=1001.0)
    await limiter.reset()
    assert not await limiter.is_blocked("1.2.3.4", "erin@demo.dev", now=1001.0)


# --- factory -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(rate_limit, "_login_limiter", None)
    limiter = await get_login_limiter()
    assert isinstance(limiter, InMemoryLoginRateLimiter)


@pytest.mark.asyncio
async def test_factory_auto_falls_back_when_redis_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis.asyncio as aioredis

    def unreachable(*args, **kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(settings, "rate_limit_backend", "auto")
    monkeypatch.setattr(rate_limit, "_login_limiter", None)
    monkeypatch.setattr(aioredis, "from_url", unreachable)
    limiter = await get_login_limiter()
    assert isinstance(limiter, InMemoryLoginRateLimiter)


@pytest.mark.asyncio
async def test_factory_redis_backend_with_working_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis.asyncio as aioredis

    store = FakeRedis()

    def fake_from_url(*args, **kwargs):
        return store

    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(rate_limit, "_login_limiter", None)
    monkeypatch.setattr(aioredis, "from_url", fake_from_url)
    limiter = await get_login_limiter()
    assert isinstance(limiter, RedisLoginRateLimiter)
    assert rate_limit.current_limiter_backend() == "redis"


@pytest.mark.asyncio
async def test_factory_caches_the_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(rate_limit, "_login_limiter", None)
    first = await get_login_limiter()
    second = await get_login_limiter()
    assert first is second
