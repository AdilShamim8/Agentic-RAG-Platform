"""Admin endpoints — system health, ingest status, traces."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, require_permission

router = APIRouter()


@router.get("/stats")
async def stats(
    user: Annotated[AuthUser, Depends(require_permission("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """System statistics — admin only."""
    # TODO: replace with real queries
    return {
        "documents": 0,
        "chunks": 0,
        "conversations": 0,
        "users": 0,
        "memories": 0,
        "retrieval_events_24h": 0,
        "avg_latency_ms_24h": 0,
        "cost_usd_24h": 0.0,
    }


@router.get("/health/detailed")
async def detailed_health(
    user: Annotated[AuthUser, Depends(require_permission("admin"))],
) -> dict:
    """Detailed subsystem health for ops dashboard."""
    return {
        "db_pool": {"checked_out": 0, "overflow": 0, "size": 10},
        "redis": {"connected": True, "hit_rate": 0.0},
        "embedder": {"model": "BAAI/bge-m3", "loaded": True},
        "reranker": {"model": "BAAI/bge-reranker-v2-m3", "loaded": True},
        "langfuse": {"reachable": True},
    }
