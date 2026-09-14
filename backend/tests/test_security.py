"""API key access control (spec §40)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.security import require_api_key
from app.config import Settings
from tests.conftest import requires_db


def _call(settings: Settings, key: str | None = None, auth: str | None = None) -> None:
    require_api_key(settings, key, auth)


def test_open_in_development_when_no_key_is_set() -> None:
    _call(Settings(postgres_password="t", app_env="development"))


@pytest.mark.parametrize("env", ["production", "staging", "prod"])
def test_refused_outside_development_when_no_key_is_set(env: str) -> None:
    """Open access must never be the silent default in production."""
    with pytest.raises(HTTPException) as excinfo:
        _call(Settings(postgres_password="t", app_env=env))
    assert excinfo.value.status_code == 500
    assert "API_KEY" in excinfo.value.detail


def test_missing_key_is_401() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _call(Settings(postgres_password="t", api_key="secret"))
    assert excinfo.value.status_code == 401


def test_wrong_key_is_403() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _call(Settings(postgres_password="t", api_key="secret"), key="wrong")
    assert excinfo.value.status_code == 403


def test_header_and_bearer_both_work() -> None:
    settings = Settings(postgres_password="t", api_key="secret")
    _call(settings, key="secret")
    _call(settings, auth="Bearer secret")
    _call(settings, auth="bearer secret")


def test_whitespace_is_tolerated() -> None:
    _call(Settings(postgres_password="t", api_key="secret"), key="  secret  ")


def test_a_prefix_of_the_key_is_rejected() -> None:
    with pytest.raises(HTTPException):
        _call(Settings(postgres_password="t", api_key="secretkey"), key="secret")


@requires_db
def test_health_stays_open_when_the_api_is_locked(monkeypatch, db_engine) -> None:
    """Probes must not need a credential, or orchestration breaks."""
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    monkeypatch.setenv("API_KEY", "test-secret")
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 200
            # Everything under /api/v1 is gated at the router.
            assert client.get("/api/v1/opportunities/top50").status_code == 401
            assert client.get("/api/v1/brief/daily").status_code == 401
            assert client.post("/api/v1/maintenance/rescore").status_code == 401
            ok = client.get(
                "/api/v1/opportunities/top50", headers={"X-API-Key": "test-secret"}
            )
            assert ok.status_code == 200
    finally:
        monkeypatch.delenv("API_KEY", raising=False)
        get_settings.cache_clear()
