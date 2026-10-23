"""Per-event cost persistence tests (retrieval_events.cost_usd).

/query must write a retrieval_events row per run - query, chunk ids,
scores, latency, trace id, and the provider cost - and /admin/stats must
report the real 24h cost sum instead of a hardcoded 0.0.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.experiment import RetrievalEvent


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/auth/login", json={"email": "alice@demo.dev", "password": "password123"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_persists_retrieval_event_with_cost() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        response = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    trace_id = response.json()["trace_id"]
    reported_cost = response.json()["metadata"]["cost_usd"]

    async with session_scope() as session:
        event = (
            await session.scalars(
                select(RetrievalEvent)
                .where(RetrievalEvent.trace_id == trace_id)
                .order_by(RetrievalEvent.created_at.desc())
                .limit(1)
            )
        ).first()

    assert event is not None, "the query must write a retrieval_events row"
    assert event.query == "What is our remote work policy?"
    assert event.user_id == uuid.UUID("03087f39-f7df-4bb9-a9cb-07cbd5a60db5")  # alice
    assert event.latency_ms >= 0
    assert isinstance(event.retrieved_chunk_ids, list)
    assert isinstance(event.scores, list)
    assert len(event.scores) == len(event.retrieved_chunk_ids)
    # The persisted per-event cost matches what the API reported.
    assert event.cost_usd == pytest.approx(reported_cost, abs=1e-8)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_stats_reports_real_cost_sum() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client)
        # One query to guarantee at least one billed event exists.
        queried = await client.post(
            "/query",
            json={"query": "How do I contact HR?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert queried.status_code == 200
        stats = await client.get("/admin/stats", headers={"Authorization": f"Bearer {token}"})

    assert stats.status_code == 200
    body = stats.json()
    assert body["retrieval_events_24h"] >= 1

    # The reported cost is the sum of the persisted per-event costs.
    from datetime import UTC, datetime, timedelta

    since = datetime.now(UTC) - timedelta(hours=24)
    async with session_scope() as session:
        rows = (
            await session.scalars(
                select(RetrievalEvent)
                .where(RetrievalEvent.created_at >= since)
                .order_by(RetrievalEvent.created_at.desc())
                .limit(5000)
            )
        ).all()
    expected = round(sum(e.cost_usd for e in rows), 6)
    assert body["cost_usd_24h"] == expected
