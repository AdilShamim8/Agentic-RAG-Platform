"""Evaluations API tests: list/get/trigger with real persistence."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.experiment import Evaluation, Experiment


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with session_scope() as session:
        await session.execute(delete(Evaluation))
        await session.execute(delete(Experiment))


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_trigger_eval_persists_experiment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dave = await _login(client, "dave@demo.dev")  # professor: has eval permission
        response = await client.post(
            "/evaluations/run",
            params={
                "dataset": "evals/datasets/golden_smoke.jsonl",
                "baselines": "baseline_6_agentic",
            },
            headers={"Authorization": f"Bearer {dave}"},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["provider"] in ("mock", "real")
    assert "baseline_6_agentic" in body["summary_by_baseline"]

    experiment_id = body["experiment_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dave = await _login(client, "dave@demo.dev")
        listing = await client.get(
            "/evaluations/experiments", headers={"Authorization": f"Bearer {dave}"}
        )
        assert any(e["id"] == experiment_id for e in listing.json())

        detail = await client.get(
            f"/evaluations/experiments/{experiment_id}", headers={"Authorization": f"Bearer {dave}"}
        )
        assert detail.status_code == 200
        metric_names = {m["metric_name"] for m in detail.json()["metrics"]}
        assert {"behavior_compliance", "recall_at_k"} <= metric_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evaluations_require_permission() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        carol = await _login(client, "carol@demo.dev")  # employee: no eval permission
        listing = await client.get(
            "/evaluations/experiments", headers={"Authorization": f"Bearer {carol}"}
        )
        assert listing.status_code == 403
        trigger = await client.post(
            "/evaluations/run",
            params={
                "dataset": "evals/datasets/golden_smoke.jsonl",
                "baselines": "baseline_6_agentic",
            },
            headers={"Authorization": f"Bearer {carol}"},
        )
        assert trigger.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_trigger_eval_rejects_unknown_baseline() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dave = await _login(client, "dave@demo.dev")
        response = await client.post(
            "/evaluations/run",
            params={
                "dataset": "evals/datasets/golden_smoke.jsonl",
                "baselines": "baseline_99_nothing",
            },
            headers={"Authorization": f"Bearer {dave}"},
        )
    assert response.status_code == 422
