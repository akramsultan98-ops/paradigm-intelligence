"""Settings parsing.

Mostly one thing: list settings written as comma-separated environment variables.
pydantic-settings JSON-decodes any complex-typed field from the environment before
validators run, so a documented value like ``SECTORS=Technology,Banking`` — and even
a single-value ``CORS_ORIGINS=http://localhost:3000`` — raised ``SettingsError`` at
import time and took the process down with it. Every one of these fields is set by
``docker-compose.yml`` or ``.env.example``, so this is a startup crash, not a
cosmetic bug, and it is worth a test per field.
"""

from __future__ import annotations

import pytest

from app.config import Settings

BASE = {"postgres_password": "t"}


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(**BASE)


@pytest.mark.parametrize(
    ("variable", "attribute", "raw", "expected"),
    [
        ("SECTORS", "sectors", "Technology,Banking", ["Technology", "Banking"]),
        ("SECTORS", "sectors", "Oil & Gas", ["Oil & Gas"]),
        (
            "CORS_ORIGINS",
            "cors_origins",
            "http://localhost:3000",
            ["http://localhost:3000"],
        ),
        (
            "CORS_ORIGINS",
            "cors_origins",
            "http://a.test,https://b.test",
            ["http://a.test", "https://b.test"],
        ),
        ("SOURCES_ENABLED", "sources_enabled", "a-source,b-source", ["a-source", "b-source"]),
    ],
)
def test_comma_separated_list_settings_parse_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, variable: str, attribute: str, raw: str, expected: list[str]
) -> None:
    settings = _settings(monkeypatch, **{variable: raw})
    assert getattr(settings, attribute) == expected


@pytest.mark.parametrize("variable", ["SECTORS", "CORS_ORIGINS", "SOURCES_ENABLED"])
def test_surrounding_whitespace_and_empty_entries_are_dropped(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    settings = _settings(monkeypatch, **{variable: " one , , two "})
    attribute = variable.lower()
    assert getattr(settings, attribute) == ["one", "two"]


def test_an_empty_value_is_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose passes SOURCES_ENABLED through unconditionally, usually empty."""
    assert _settings(monkeypatch, SOURCES_ENABLED="").sources_enabled == []


def test_sources_enabled_defaults_to_nothing() -> None:
    """A deployment that says nothing ingests nothing. That is the safe default."""
    assert Settings(**BASE).sources_enabled == []
