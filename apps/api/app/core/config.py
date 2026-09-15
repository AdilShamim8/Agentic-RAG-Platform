"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables. See `.env.example`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General
    app_env: str = "dev"
    app_log_level: str = "INFO"
    app_secret_key: str = Field(..., min_length=32)
    git_sha: str = "dev"

    # Database
    database_url: str
    database_url_sync: str = ""
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_embedding_ttl: int = 86400
    redis_query_ttl: int = 300

    # LLM providers
    openai_api_key: str = ""
    openai_default_model: str = "gpt-4o-mini"
    openai_strong_model: str = "gpt-4o"

    anthropic_api_key: str = ""
    anthropic_default_model: str = "claude-3-5-sonnet-20241022"

    # Embeddings + reranker
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    hf_token: str = ""

    # Auth
    jwt_secret: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Observability
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "agentic-rag-api"
    langfuse_host: str = ""
    langfuse_secret: str = ""
    langfuse_public: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Agent limits
    agent_max_steps: int = 8
    agent_max_retries_per_step: int = 2
    agent_global_timeout_seconds: int = 30
    agent_max_tool_calls: int = 10

    # Retrieval
    retrieval_candidate_count: int = 50
    retrieval_top_k: int = 10
    reranker_top_k: int = 5
    retrieval_similarity_threshold: float = 0.2

    # Memory
    memory_short_term_window: int = 10
    memory_extraction_enabled: bool = True
    memory_max_per_user: int = 500

    # Ingestion
    ingestion_chunk_size: int = 512
    ingestion_chunk_overlap: int = 64
    ingestion_chunk_strategy: str = "structure-aware"
    ingestion_batch_size: int = 100

    # Evaluation
    eval_faithfulness_min: float = 0.85
    eval_hallucination_rate_max: float = 0.10
    eval_smoke_size: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in {"dev", "staging", "prod"}:
            raise ValueError("app_env must be one of: dev, staging, prod")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — use this everywhere, never `Settings()` directly."""
    return Settings()  # type: ignore[call-arg]


# Convenience module-level accessor used throughout the app
settings = get_settings()
