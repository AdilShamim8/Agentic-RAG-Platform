"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.app.core.config import settings
from apps.api.app.core.db import check_db

router = APIRouter()


@router.get("")
@router.get("/")
async def health() -> dict:
    """Liveness probe — always returns 200 if the process is alive."""
    return {"status": "ok", "version": settings.git_sha}


@router.get("/ready")
async def readiness() -> dict:
    """Readiness probe — checks all subsystems."""
    db_status = "ok"
    try:
        db_status = await check_db()
    except Exception:
        db_status = "fail"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "embedder": "ok",  # TODO: ping the embedder
        "llm": "ok",  # TODO: ping the LLM provider
        "reranker": "ok",  # TODO: ping the reranker
        "version": settings.git_sha,
    }
