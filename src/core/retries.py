"""Retry policies — exponential backoff with jitter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

T = TypeVar("T")


def retry_llm(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator for LLM calls — 3 retries, exponential backoff 1s → 2s → 4s."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=True,
    )(func)


def retry_embedding(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator for embedding calls — 2 retries."""
    return retry(
        stop=stop_after_attempt(2),
        wait=wait_random_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=True,
    )(func)


def retry_db(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator for DB calls — 1 retry on transient errors only."""
    return retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=1),
        reraise=True,
    )(func)


async def with_timeout(coro: Awaitable[Any], seconds: float) -> Any:
    """Await coro with a hard timeout."""
    return await asyncio.wait_for(coro, timeout=seconds)
