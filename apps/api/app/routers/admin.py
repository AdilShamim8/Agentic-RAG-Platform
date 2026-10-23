"""Admin endpoints — system stats and detailed health (admin only).

Previously /stats returned hardcoded zeros and /health/detailed claimed
"connected: true" for subsystems that are not even wired up. Now /stats
runs real aggregate queries and /health/detailed reports actual state:
the DB pool status from the live engine, model singletons as loaded/
warming, langfuse configured/unconfigured, and Redis marked honestly as
"not wired" (no Redis client exists in the codebase yet).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.core.db import get_engine, get_session
from apps.api.app.deps.auth import AuthUser, require_permission
from apps.api.app.models.conversation import Conversation
from apps.api.app.models.document import Document, DocumentChunk
from apps.api.app.models.experiment import RetrievalEvent
from apps.api.app.models.memory import Memory
from apps.api.app.models.user import User

router = APIRouter()


@router.get("/stats")
async def stats(
    user: AuthUser = Depends(require_permission("admin")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """System statistics — admin only (real aggregates)."""
    since = datetime.now(UTC) - timedelta(hours=24)

    documents = await session.scalar(
        select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
    )
    chunks = await session.scalar(select(func.count()).select_from(DocumentChunk))
    conversations = await session.scalar(select(func.count()).select_from(Conversation))
    users = await session.scalar(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )
    memories = await session.scalar(
        select(func.count()).select_from(Memory).where(Memory.deleted_at.is_(None))
    )
    events = await session.scalars(
        select(RetrievalEvent)
        .where(RetrievalEvent.created_at >= since)
        .order_by(RetrievalEvent.created_at.desc())
        .limit(5000)
    )
    event_rows = list(events)
    avg_latency = (
        round(sum(e.latency_ms for e in event_rows) / len(event_rows)) if event_rows else 0
    )
    return {
        "documents": int(documents or 0),
        "chunks": int(chunks or 0),
        "conversations": int(conversations or 0),
        "users": int(users or 0),
        "memories": int(memories or 0),
        "retrieval_events_24h": len(event_rows),
        "avg_latency_ms_24h": avg_latency,
        "cost_usd_24h": 0.0,  # cost accounting is not persisted per event yet (known gap)
    }


@router.get("/health/detailed")
async def detailed_health(
    user: AuthUser = Depends(require_permission("admin")),
) -> dict:
    """Detailed subsystem health for ops dashboards (honest states only)."""
    engine = get_engine()
    pool = engine.pool
    pool_status = pool.status() if hasattr(pool, "status") else "unknown"

    from apps.api.app.core.rate_limit import current_limiter_backend
    from src.reranking.base import _reranker
    from src.retrieval.embedders import _embedder

    return {
        "db_pool": {"status": pool_status},
        "redis": {
            # First real Redis consumer; more (caches, queues) to follow.
            "status": current_limiter_backend(),
            "used_for": "login_rate_limiting",
            "url_configured": bool(settings.redis_url),
        },
        "embedder": {
            "model": settings.embedding_model,
            "loaded": _embedder is not None,
        },
        "reranker": {
            "model": settings.reranker_model,
            "loaded": _reranker is not None,
        },
        "langfuse": {
            "configured": bool(settings.otel_exporter_otlp_endpoint),
            "host": settings.langfuse_host or None,
        },
    }
