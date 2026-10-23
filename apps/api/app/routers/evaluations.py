"""Evaluations endpoints — list experiments, get reports, trigger runs.

Previously all TODO stubs (empty list / "not implemented yet" / fake
"queued"). Now: real queries over the experiments/evaluations tables, and
POST /run executes the deterministic evaluation runner in-process,
persisting an Experiment row and per-metric Evaluation rows. LLM-judge
rubric scores are not produced by this runner (mock-provider honesty);
see docs/reviews/llm_judge_methodology.md.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, require_permission
from apps.api.app.models.experiment import Evaluation, Experiment
from evals.fixtures import all_fixture_chunk_ids
from evals.run import BASELINE_NAMES, run_experiment

router = APIRouter()


@router.get("/experiments")
async def list_experiments(
    user: Annotated[AuthUser, Depends(require_permission("eval"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    rows = await session.scalars(
        select(Experiment).order_by(Experiment.created_at.desc()).limit(100)
    )
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "dataset_version": e.dataset_version,
            "model": e.model,
            "retriever": e.retriever,
            "reranker": e.reranker,
            "prompt_version": e.prompt_version,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    user: Annotated[AuthUser, Depends(require_permission("eval"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        pk = uuid.UUID(experiment_id)
    except ValueError as exc:
        raise HTTPException(404, "Experiment not found") from exc

    experiment = await session.get(Experiment, pk)
    if experiment is None:
        raise HTTPException(404, "Experiment not found")

    metric_rows = await session.scalars(
        select(Evaluation).where(Evaluation.experiment_id == pk).order_by(Evaluation.metric_name)
    )
    metrics = [
        {
            "query_id": m.query_id,
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
        }
        for m in metric_rows
    ]
    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "dataset_version": experiment.dataset_version,
        "model": experiment.model,
        "embedding_model": experiment.embedding_model,
        "retriever": experiment.retriever,
        "reranker": experiment.reranker,
        "prompt_version": experiment.prompt_version,
        "parameters": experiment.parameters,
        "created_at": experiment.created_at.isoformat(),
        "metrics": metrics,
    }


@router.post("/run", status_code=202)
async def trigger_eval(
    user: Annotated[AuthUser, Depends(require_permission("eval"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    dataset: str = "evals/datasets/golden_smoke.jsonl",
    baselines: str = "baseline_6_agentic",
) -> dict:
    """Run an evaluation in-process and persist the results.

    The runner is deterministic; provider mode (real/mock) is decided by the
    environment and recorded in the Experiment row.
    """
    requested = [b.strip() for b in baselines.split(",") if b.strip()]
    if not requested or any(b not in BASELINE_NAMES for b in requested):
        raise HTTPException(422, f"baselines must be from {BASELINE_NAMES}")

    experiment = Experiment(
        id=uuid.uuid4(),
        name=f"api-{dataset.rsplit('/', 1)[-1]}-{baselines}",
        dataset_version="sha256-pending",  # replaced below
        model=f"{settings.openai_default_model} ({'mock' if (settings.openai_api_key or '').startswith('sk-test') or not settings.openai_api_key else 'real'})",
        embedding_model=settings.embedding_model,
        chunking=settings.ingestion_chunk_strategy,
        retriever=",".join(requested),
        reranker=settings.reranker_model,
        prompt_version="v1",
        parameters={"dataset": dataset, "baselines": requested},
    )
    session.add(experiment)
    await session.flush()

    from evals.run import ExperimentConfig  # local import: avoids cycle at module load

    config = ExperimentConfig(name=experiment.name, dataset=dataset, baselines=requested)
    report = await run_experiment(config, all_fixture_chunk_ids())

    experiment.dataset_version = report["dataset_sha256"]
    for baseline, summary in report["summary_by_baseline"].items():
        for metric_name, value in summary.items():
            if value is None or not isinstance(value, (int, float)):
                continue
            session.add(
                Evaluation(
                    experiment_id=experiment.id,
                    query_id=f"summary:{baseline}",
                    metric_name=metric_name,
                    metric_value=float(value),
                )
            )

    return {
        "status": "completed",
        "experiment_id": str(experiment.id),
        "provider": report["provider"],
        "summary_by_baseline": report["summary_by_baseline"],
        "limitations": report["limitations"],
    }
