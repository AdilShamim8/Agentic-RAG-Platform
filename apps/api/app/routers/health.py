"""Health endpoints — liveness + readiness.

Previously /ready hardcoded "ok" for embedder/llm/reranker regardless of
actual state. Now:
- liveness: always 200 while the process lives
- readiness: real DB round-trip (503 when down), honest subsystem states
  (loaded / warming) for the model-backed components - constructing them
  on every probe would download GB-scale models or spend provider tokens,
  so readiness reports whether each singleton is already warm
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from apps.api.app.core.config import settings
from apps.api.app.core.db import check_db

router = APIRouter()


@router.get("")
@router.get("/")
async def health() -> dict:
    """Liveness probe — always returns 200 if the process is alive."""
    return {"status": "ok", "version": settings.git_sha}


def _embedder_state() -> str:
    from src.retrieval.embedders import _embedder

    return "loaded" if _embedder is not None else "warming"


def _reranker_state() -> str:
    from src.reranking.base import _reranker

    return "loaded" if _reranker is not None else "warming"


def _llm_state() -> str:
    from src.llm.provider import _llm

    if _llm is None:
        return "warming"
    provider = type(_llm).__name__
    return f"loaded ({provider})" if "Mock" not in provider else "loaded (mock)"


@router.get("/ready")
async def readiness() -> JSONResponse:
    """Readiness probe — checks subsystems and fails (503) when the DB is down."""
    db_status = "ok"
    try:
        db_status = await check_db()
    except Exception:
        db_status = "fail"

    body = {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "embedder": _embedder_state(),
        "llm": _llm_state(),
        "reranker": _reranker_state(),
        "version": settings.git_sha,
    }
    status_code = 200 if db_status == "ok" else 503
    return JSONResponse(body, status_code=status_code)
