"""Integration test for the /query endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.main import app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_endpoint_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Login first
        login = await client.post(
            "/auth/login", data={"username": "alice@demo.dev", "password": "password123"}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        # Query
        response = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "citations" in data
        assert "trace_id" in data
        assert "confidence" in data


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/query", json={"query": "test"})
        assert response.status_code == 401
