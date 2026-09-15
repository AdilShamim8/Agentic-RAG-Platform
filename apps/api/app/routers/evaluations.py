"""Evaluations endpoints — list experiments, get reports."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user, require_permission

router = APIRouter()


@router.get("/experiments")
async def list_experiments(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    # TODO: query experiments table
    return []


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    # TODO: return full report
    return {"experiment_id": experiment_id, "results": "not implemented yet"}


@router.post("/run")
async def trigger_eval(
    user: Annotated[AuthUser, Depends(require_permission("eval"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    baseline: str = "baseline_5_hybrid_reranked",
    dataset: str = "golden",
) -> dict:
    """Trigger an evaluation run. Admin only."""
    # TODO: enqueue a background job
    return {"status": "queued", "baseline": baseline, "dataset": dataset}
