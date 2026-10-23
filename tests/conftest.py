"""Global test configuration and fixtures."""

from __future__ import annotations

import os

import pytest

# Provide standard default test environment variables if not already set
os.environ.setdefault("APP_SECRET_KEY", "test-secret-please-change-me-to-64-chars-aaaaaaaaaaaa")
os.environ.setdefault("JWT_SECRET", "test-secret-please-change-me-to-64-chars-aaaaaaaaaaaa")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://rag:rag@localhost:5432/rag")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("HF_TOKEN", "hf_test")
os.environ.setdefault("APP_ENV", "dev")
# Deterministic offline embedder for tests/CI (no Hugging Face downloads).
# Override with a real model name to exercise the local/OpenAI embedders.
os.environ.setdefault("EMBEDDING_MODEL", "test-hashed-bag")


@pytest.fixture(autouse=True)
async def _fresh_db_engine():
    """Dispose the global engine after each test.

    pytest-asyncio gives every test a fresh event loop, but core.db caches a
    global engine whose pooled connections are bound to the loop that created
    them. Without disposal, a later test reuses a connection from a dead loop
    ("RuntimeError: Event loop is closed" / unawaited Connection._cancel).
    """
    yield
    from apps.api.app.core import db

    if db._engine is not None:
        try:
            await db._engine.dispose()
        finally:
            db._engine = None
            db._session_maker = None
