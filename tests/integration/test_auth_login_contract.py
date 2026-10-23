"""Login/refresh contract tests.

The documented contract (QUICKSTART.md) is JSON {email, password}. These tests
verify: JSON login, OAuth2 form compat, error semantics, body-based refresh,
and failed-login rate limiting.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.main import app
from apps.api.app.routers.auth import rate_limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


async def _login(client: AsyncClient, **kwargs):
    return await client.post("/auth/login", **kwargs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_json_login_documented_contract() -> None:
    """QUICKSTART's curl uses JSON {email, password} - it must return a Token."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _login(client, json={"email": "alice@demo.dev", "password": "password123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert body["expires_in"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_form_login_oauth2_compat() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _login(
            client, data={"username": "alice@demo.dev", "password": "password123"}
        )
        assert response.status_code == 200
        # 'email' also works as form identifier
        response2 = await _login(
            client, data={"email": "alice@demo.dev", "password": "password123"}
        )
        assert response2.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_json_login_wrong_password_401_uniform() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wrong = await _login(client, json={"email": "alice@demo.dev", "password": "nope"})
        unknown = await _login(client, json={"email": "ghost@demo.dev", "password": "nope"})
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    # Same message for unknown email and wrong password (no user enumeration)
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Invalid email or password"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_json_login_validation_422() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing_pw = await _login(client, json={"email": "alice@demo.dev"})
        bad_email = await _login(client, json={"email": "not-an-email", "password": "x"})
        empty_form = await _login(client, data={})
    assert missing_pw.status_code == 422
    assert bad_email.status_code == 422
    assert empty_form.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_token_in_body() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await _login(client, json={"email": "alice@demo.dev", "password": "password123"})
        refresh_token = login.json()["refresh_token"]

        response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 200
        assert response.json()["access_token"]

        # Reusing an access token as refresh must fail
        access = login.json()["access_token"]
        bad = await client.post("/auth/refresh", json={"refresh_token": access})
        assert bad.status_code == 401

        # Tampered token must fail
        tampered = await client.post(
            "/auth/refresh", json={"refresh_token": refresh_token[:-3] + "xyz"}
        )
        assert tampered.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_rate_limit_after_repeated_failures() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            response = await _login(client, json={"email": "bob@demo.dev", "password": "wrong"})
            assert response.status_code == 401

        blocked = await _login(client, json={"email": "bob@demo.dev", "password": "password123"})
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

        # A different identifier from the same client is not blocked
        other = await _login(client, json={"email": "alice@demo.dev", "password": "password123"})
        assert other.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_recovers_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.routers.auth import _WINDOW_SECONDS

    clock = {"now": 1000.0}

    def fake_monotonic() -> float:
        return clock["now"]

    monkeypatch.setattr("apps.api.app.routers.auth.time.monotonic", fake_monotonic)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            response = await _login(client, json={"email": "carol@demo.dev", "password": "wrong"})
            assert response.status_code == 401
        blocked = await _login(client, json={"email": "carol@demo.dev", "password": "password123"})
        assert blocked.status_code == 429

        clock["now"] += _WINDOW_SECONDS + 1
        recovered = await _login(
            client, json={"email": "carol@demo.dev", "password": "password123"}
        )
        assert recovered.status_code == 200
