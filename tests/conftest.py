"""Global test configuration and fixtures."""

from __future__ import annotations

import os

# Provide standard default test environment variables if not already set
os.environ.setdefault("APP_SECRET_KEY", "test-secret-please-change-me-to-64-chars-aaaaaaaaaaaa")
os.environ.setdefault("JWT_SECRET", "test-secret-please-change-me-to-64-chars-aaaaaaaaaaaa")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://rag:rag@localhost:5432/rag")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("HF_TOKEN", "hf_test")
os.environ.setdefault("APP_ENV", "dev")
