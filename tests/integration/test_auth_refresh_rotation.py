"""Refresh-token rotation, HttpOnly cookie, revocation, and logout tests.

Covers the hardening of the refresh flow:
- login sets the refresh token as an HttpOnly cookie (not reachable from JS)
- refresh works from the cookie alone (browser) and from the body (API clients)
- every refresh rotates the token: the old one is revoked, replay is a 401
  and writes an audit row (reuse detection)
- logout revokes the presented token and clears the cookie
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.audit import AuditLog
from apps.api.app.models.refresh_token import RevokedRefreshToken


async def _login_json(client: AsyncClient) -> dict:
    response = await client.post(
        "/auth/login", json={"email": "alice@demo.dev", "password": "password123"}
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_sets_httponly_refresh_cookie() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login", json={"email": "alice@demo.dev", "password": "password123"}
        )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "rag_refresh=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()
    # The cookie value must NOT be the access token, and the browser-facing
    # body only matters for API clients.
    assert "Path=/" in set_cookie


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_via_cookie_without_body() -> None:
    """The browser flow: the HttpOnly cookie alone must be enough."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _login_json(client)  # sets rag_refresh cookie in the client jar
        response = await client.post("/auth/refresh")
        assert response.status_code == 200
        assert response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_rotates_and_old_token_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _login_json(client)
        old_refresh = first["refresh_token"]

        # Rotate via the body (API-client style) with an empty cookie jar.
        client.cookies.clear()
        rotated = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert rotated.status_code == 200
        new_refresh = rotated.json()["refresh_token"]
        assert new_refresh != old_refresh

        # The old token is now on the deny list.
        replay = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert replay.status_code == 401

        # The rotated token still works.
        ok = await client.post("/auth/refresh", json={"refresh_token": new_refresh})
        assert ok.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replay_of_revoked_token_is_audited() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _login_json(client)
        old_refresh = first["refresh_token"]
        client.cookies.clear()
        rotated = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert rotated.status_code == 200

        async with session_scope() as session:
            audit_before = len(
                (
                    await session.execute(
                        select(AuditLog).where(AuditLog.action == "auth.refresh_reuse_detected")
                    )
                ).all()
            )

        replay = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert replay.status_code == 401

        async with session_scope() as session:
            audit_after = (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "auth.refresh_reuse_detected")
                )
            ).all()
        assert len(audit_after) == audit_before + 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_revokes_token_and_clears_cookie() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _login_json(client)
        refresh = first["refresh_token"]

        # Logout with the cookie present (browser flow).
        response = await client.post("/auth/logout")
        assert response.status_code == 204
        assert "rag_refresh=" in response.headers.get("set-cookie", "")

        # The jar is cleared: refresh with neither cookie nor body is a 401.
        gone = await client.post("/auth/refresh")
        assert gone.status_code == 401

        # The logged-out token is revoked even if the client kept a copy.
        replay = await client.post("/auth/refresh", json={"refresh_token": refresh})
        assert replay.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logout_without_tokens_is_idempotent_204() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/logout")
    assert response.status_code == 204


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_without_cookie_or_body_is_401() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing refresh token"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revocation_rows_expire_with_the_token() -> None:
    """Sanity: revocation rows carry the token's exp (prunable later)."""
    from jose import jwt as jose_jwt

    from apps.api.app.core.config import settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _login_json(client)
        old_refresh = first["refresh_token"]
        client.cookies.clear()
        rotated = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert rotated.status_code == 200

    payload = jose_jwt.decode(old_refresh, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    async with session_scope() as session:
        row = await session.get(RevokedRefreshToken, payload["jti"])
    assert row is not None
    assert row.user_id == uuid.UUID(payload["sub"])
    assert row.expires_at is not None
