"""Regression: /query and authenticated routes must flow AuthUser (not ORM User) downstream.

Before this fix, routers annotated `AuthUser` but injected the ORM `User`
dependency, so services/agents received a User whose `.permissions`/`.projects`
are async properties (coroutines) — causing "coroutine was never awaited"
RuntimeWarnings and making tool permission checks operate on wrong types.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.deps.auth import AuthUser
from apps.api.app.main import app
from apps.api.app.services.query_service import AgentResult


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_flows_auth_user_into_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_agent(**kwargs) -> AgentResult:
        captured["user"] = kwargs["user"]
        return AgentResult(answer="ok", citations=[], failure=None, confidence="high", cost_usd=0.0)

    monkeypatch.setattr(
        "apps.api.app.services.query_service.run_agent", fake_run_agent, raising=True
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/auth/login", data={"username": "alice@demo.dev", "password": "password123"}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        response = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    user = captured["user"]
    assert isinstance(user, AuthUser), f"run_agent received {type(user)!r}, expected AuthUser"
    assert isinstance(user.id, str) and len(user.id) == 36
    assert user.role_slug == "administrator"
    assert isinstance(user.permissions, frozenset)
    assert "admin" in user.permissions
    assert isinstance(user.projects, frozenset)
    assert isinstance(user.departments, frozenset)
    # Admin must pass the permission helper
    assert user.has_permission("eval") and user.is_admin


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_no_unawaited_coroutine_warnings(
    monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    """The old bug emitted RuntimeWarning('coroutine ... never awaited') on every query."""

    async def fake_run_agent(**kwargs) -> AgentResult:
        return AgentResult(answer="ok", citations=[], failure=None, confidence="high", cost_usd=0.0)

    monkeypatch.setattr(
        "apps.api.app.services.query_service.run_agent", fake_run_agent, raising=True
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/auth/login", data={"username": "alice@demo.dev", "password": "password123"}
        )
        token = login.json()["access_token"]
        response = await client.post(
            "/query",
            json={"query": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    unawaited = [
        w for w in recwarn.list if "never awaited" in str(w.message) and "User." in str(w.message)
    ]
    assert not unawaited, f"unawaited User coroutines leaked: {[str(w.message) for w in unawaited]}"
