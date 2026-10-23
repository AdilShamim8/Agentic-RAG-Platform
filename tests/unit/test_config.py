"""Settings contract tests.

The API and worker services must be able to construct Settings from exactly the
environment docker-compose.yml provides. These tests document that contract:
required keys, minimum lengths, and rejection of invalid values.
See: docker-compose.yml (api/worker `environment:`), .env.example.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.core.config import Settings

REQUIRED_ENV = {
    "APP_SECRET_KEY": "unit-test-app-secret-key-0123456789abcdef0123456789",
    "JWT_SECRET": "unit-test-jwt-secret-key-0123456789abcdef0123456789abcd",
    "DATABASE_URL": "postgresql+asyncpg://rag:rag@localhost:5432/rag",
}


def _make_settings(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str | None]) -> Settings:
    """Build Settings with REQUIRED_ENV applied, then per-test overrides (None = unset)."""
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "dev")
    for key, value in overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_settings_load_with_compose_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env provided by docker-compose (api/worker) must be sufficient."""
    settings = _make_settings(monkeypatch, {})
    assert settings.app_secret_key == REQUIRED_ENV["APP_SECRET_KEY"]
    assert settings.jwt_secret == REQUIRED_ENV["JWT_SECRET"]
    assert settings.database_url == REQUIRED_ENV["DATABASE_URL"]


def test_settings_missing_app_secret_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must fail loudly when APP_SECRET_KEY is absent (do not weaken the check)."""
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"APP_SECRET_KEY": None})


def test_settings_missing_jwt_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"JWT_SECRET": None})


def test_settings_short_app_secret_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"APP_SECRET_KEY": "too-short-secret"})


def test_settings_short_jwt_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"JWT_SECRET": "too-short-secret"})


def test_settings_invalid_app_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"APP_ENV": "production"})
    with pytest.raises(ValidationError):
        _make_settings(monkeypatch, {"APP_ENV": ""})


def test_settings_valid_app_envs_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in ("dev", "staging", "prod"):
        settings = _make_settings(monkeypatch, {"APP_ENV": env})
        assert settings.app_env == env


def test_cors_origins_list_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_settings(monkeypatch, {})  # establish required env
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test ,")
    settings2 = Settings(_env_file=None)
    assert settings2.cors_origins_list == ["http://a.test", "http://b.test"]
