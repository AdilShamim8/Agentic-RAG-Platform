"""Rate-limiter backend tests.

The Redis backend is exercised against the shared in-process FakeRedis
(tests/fakes.py) so the tests stay hermetic - no Redis server, no extra
dependency - while pinning the semantics that must match the in-memory
backend exactly:

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
from tests.fakes import FakeRedis


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
