"""Health + admin stats tests (real data, honest states)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.main import app
from tests.helpers_seed import purge_docs, seed_doc


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readiness_reports_db_and_subsystems() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["db"] == "ok"
    assert body["status"] == "ok"
    # honest states, never fabricated "ok"
    assert body["embedder"] in ("loaded", "warming")
    assert body["llm"].startswith("loaded") or body["llm"] == "warming"
    assert body["reranker"] in ("loaded", "warming")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_stats_real_counts() -> None:
    seeded = await seed_doc(
        title="Stats Policy",
        content="Some policy content for stats aggregation test.",
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            alice = await _login(client, "alice@demo.dev")
            response = await client.get(
                "/admin/stats", headers={"Authorization": f"Bearer {alice}"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["documents"] >= 1
        assert body["chunks"] >= 1
        assert body["users"] >= 5  # the seeded demo users
        assert isinstance(body["retrieval_events_24h"], int)
    finally:
        await purge_docs(seeded.document_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_detailed_health_honest() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        response = await client.get(
            "/admin/health/detailed", headers={"Authorization": f"Bearer {alice}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert "db_pool" in body and "status" in body["db_pool"]
    assert body["redis"]["status"] in ("memory", "redis")  # resolved limiter backend
    assert body["redis"]["used_for"] == "login_rate_limiting"
    assert isinstance(body["embedder"]["loaded"], bool)
    assert isinstance(body["reranker"]["loaded"], bool)
    assert "configured" in body["langfuse"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_forbidden_for_non_admin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        carol = await _login(client, "carol@demo.dev")
        stats = await client.get("/admin/stats", headers={"Authorization": f"Bearer {carol}"})
        detailed = await client.get(
            "/admin/health/detailed", headers={"Authorization": f"Bearer {carol}"}
        )
    assert stats.status_code == 403
    assert detailed.status_code == 403
