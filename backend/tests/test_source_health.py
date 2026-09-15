"""Source preflight tests (spec §34).

The distinction these protect is the one that costs an afternoon when it is wrong:
"this network will not let me connect" versus "this source is broken".
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.domain.enums import SourceType
from app.services.source_health import (
    Verdict,
    check_source,
    summarize,
)
from app.sources.base import SourceConfig
from app.sources.http import FetchClient

FEED = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>'
    b"<item><title>Company signs major contract</title>"
    b"<link>https://a.test/1</link><pubDate>Wed, 10 Sep 2026 08:00:00 GMT</pubDate>"
    b"</item></channel></rss>"
)


@pytest.fixture
def settings() -> Settings:
    return Settings(postgres_password="t", ingest_default_rate_limit_per_minute=100_000)


def _client(handler, settings: Settings) -> FetchClient:
    return FetchClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _rss_config(**kwargs) -> SourceConfig:
    options = kwargs.pop("options", {"feed_url": "https://a.test/feed"})
    return SourceConfig(
        key="test-feed", adapter="rss", source_type=SourceType.BUSINESS_PUBLICATION,
        rate_limit_per_minute=100_000, options=options, **kwargs,
    )


# --------------------------------------------------------------------------
# the verdict that matters most
# --------------------------------------------------------------------------

def test_egress_block_is_not_reported_as_a_broken_source(settings: Settings) -> None:
    """A 403 to CONNECT never reaches the publisher, so the source is unverified —
    not broken. Conflating the two sends someone to fix the wrong thing."""
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("403 Forbidden")

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.verdict is Verdict.BLOCKED_BY_EGRESS
    assert not health.usable
    assert "egress" in health.detail
    assert "allowlist" in health.advice
    # And it must never suggest enabling on the strength of an unverified result.
    assert "Do not enable" in health.advice


def test_a_real_rejection_is_unreachable_not_egress(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.verdict is Verdict.UNREACHABLE
    assert health.http_status == 404


# --------------------------------------------------------------------------
# working sources
# --------------------------------------------------------------------------

def test_a_working_disabled_feed_is_ready_to_enable(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEED)

    health = check_source(_rss_config(enabled=False), _client(handler, settings), settings)
    assert health.verdict is Verdict.READY_TO_ENABLE
    assert health.usable
    assert health.items_found == 1
    assert health.sample_titles == ["Company signs major contract"]
    # The advice must include the terms-of-use check, not just "switch it on".
    assert "terms of use" in health.advice


def test_a_working_enabled_feed_is_active(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEED)

    health = check_source(_rss_config(enabled=True), _client(handler, settings), settings)
    assert health.verdict is Verdict.ACTIVE
    assert health.usable


def test_recent_entry_count_is_reported(settings: Settings) -> None:
    """An ancient feed is technically fine and practically useless."""
    old = FEED.replace(b"Wed, 10 Sep 2026", b"Mon, 06 Jan 2020")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=old)

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.items_found == 1
    assert health.items_recent == 0


# --------------------------------------------------------------------------
# unusable responses
# --------------------------------------------------------------------------

def test_html_where_a_feed_should_be(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!doctype html><html><body>Consent</body></html>")

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.verdict is Verdict.NOT_USABLE
    assert not health.usable


def test_a_valid_but_empty_feed(settings: Settings) -> None:
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=empty)

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.verdict is Verdict.EMPTY


def test_a_missing_feed_url_is_misconfigured(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEED)

    health = check_source(_rss_config(options={}), _client(handler, settings), settings)
    assert health.verdict is Verdict.MISCONFIGURED


# --------------------------------------------------------------------------
# adapter-specific advice
# --------------------------------------------------------------------------

def test_a_missing_local_file_gets_local_advice(tmp_path: Path, settings: Settings) -> None:
    """Telling someone to check a URL in a browser is useless for a missing file."""
    config = SourceConfig(
        key="local", adapter="jsonl", source_type=SourceType.OTHER,
        options={"path": str(tmp_path / "absent.jsonl")},
    )
    health = check_source(config, settings=settings)
    assert health.verdict is Verdict.UNREACHABLE
    assert "file does not exist" in health.advice
    assert "browser" not in health.advice


def test_a_usable_local_file(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_text(
        json.dumps({"url": "https://a.test/1", "title": "One"}) + "\n" + "{bad}\n",
        encoding="utf-8",
    )
    config = SourceConfig(key="local", adapter="jsonl", source_type=SourceType.OTHER,
                          enabled=False, options={"path": str(path)})
    health = check_source(config, settings=settings)
    assert health.verdict is Verdict.READY_TO_ENABLE
    assert health.items_found == 1


def test_contact_page_health(settings: Settings) -> None:
    fixture = (Path(__file__).parent / "fixtures_leadership.html").read_bytes()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=fixture)

    config = SourceConfig(
        key="leadership", adapter="contact_page", source_type=SourceType.COMPANY,
        enabled=False, rate_limit_per_minute=100_000,
        options={"url": "https://a.test/team", "company": "Example Corp"},
    )
    health = check_source(config, _client(handler, settings), settings)
    assert health.verdict is Verdict.READY_TO_ENABLE
    assert health.items_found >= 3


def test_contact_page_with_no_relevant_contacts(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body><p>Nothing here.</p></body></html>")

    config = SourceConfig(
        key="leadership", adapter="contact_page", source_type=SourceType.COMPANY,
        rate_limit_per_minute=100_000,
        options={"url": "https://a.test/team", "company": "Example Corp"},
    )
    health = check_source(config, _client(handler, settings), settings)
    assert health.verdict is Verdict.EMPTY


def test_an_unknown_adapter_is_misconfigured(settings: Settings) -> None:
    config = SourceConfig(key="x", adapter="telepathy", source_type=SourceType.OTHER)
    health = check_source(config, settings=settings)
    assert health.verdict is Verdict.MISCONFIGURED


def test_a_probe_never_raises(settings: Settings) -> None:
    """A preflight that crashes is worse than one that reports a failure."""
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xfe\x00\x00 not text")

    health = check_source(_rss_config(), _client(handler, settings), settings)
    assert health.verdict in set(Verdict)


# --------------------------------------------------------------------------
# the summary an operator actually reads
# --------------------------------------------------------------------------

def _health(key: str, verdict: Verdict, adapter: str = "rss"):
    from app.services.source_health import SourceHealth

    return SourceHealth(
        key=key, adapter=adapter, source_type="OTHER", enabled=False,
        verdict=verdict, detail="",
    )


def test_summary_when_everything_is_egress_blocked() -> None:
    results = [_health("a", Verdict.BLOCKED_BY_EGRESS), _health("b", Verdict.BLOCKED_BY_EGRESS)]
    summary = summarize(results)
    assert summary["usable"] == []
    assert len(summary["blocked_by_egress"]) == 2
    assert "egress policy" in summary["conclusion"]
    assert "ingest/signals" in summary["conclusion"]


def test_a_local_source_does_not_dilute_the_egress_verdict() -> None:
    """A missing local file must not mask that every network source is blocked."""
    results = [
        _health("a", Verdict.BLOCKED_BY_EGRESS),
        _health("b", Verdict.BLOCKED_BY_EGRESS),
        _health("local", Verdict.UNREACHABLE, adapter="jsonl"),
    ]
    assert "egress policy" in summarize(results)["conclusion"]


def test_summary_when_a_source_works() -> None:
    results = [_health("good", Verdict.READY_TO_ENABLE), _health("bad", Verdict.UNREACHABLE)]
    summary = summarize(results)
    assert summary["usable"] == ["good"]
    assert "good" in summary["conclusion"]


def test_summary_with_no_sources() -> None:
    assert "No sources are configured" in summarize([])["conclusion"]


def test_the_shipped_registry_is_probeable(settings: Settings) -> None:
    """Every committed entry must produce a verdict, not an exception."""
    from app.sources import load_source_configs

    html = (Path(__file__).parent / "fixtures_leadership.html").read_bytes()
    path = Path(__file__).resolve().parents[2] / "config" / "sources.json"
    for config in load_source_configs(path):
        # Serve each adapter the shape of content it would really get.
        body = html if config.adapter == "contact_page" else FEED
        health = check_source(
            config,
            _client(lambda _, body=body: httpx.Response(200, content=body), settings),
            settings,
        )
        assert health.verdict in set(Verdict), config.key
        assert health.advice


# --------------------------------------------------------------------------
# enable-sources: writing the allowlist into an env file
# --------------------------------------------------------------------------
# This runs against production env files holding database passwords, so the one
# behaviour that matters is that it changes the single key it was asked to.


def test_env_upsert_appends_a_missing_key(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text("# config\nPOSTGRES_PASSWORD=secret\n", encoding="utf-8")

    assert _upsert_env_line(path, "SOURCES_ENABLED", "a,b") == "added"
    assert path.read_text() == "# config\nPOSTGRES_PASSWORD=secret\nSOURCES_ENABLED=a,b\n"


def test_env_upsert_replaces_an_existing_key_in_place(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text(
        "POSTGRES_PASSWORD=secret\nSOURCES_ENABLED=old\nAPI_KEY=k\n", encoding="utf-8"
    )

    assert _upsert_env_line(path, "SOURCES_ENABLED", "new") == "updated"
    assert path.read_text() == "POSTGRES_PASSWORD=secret\nSOURCES_ENABLED=new\nAPI_KEY=k\n"


def test_env_upsert_replaces_an_exported_form(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text("export SOURCES_ENABLED=old\n", encoding="utf-8")
    assert _upsert_env_line(path, "SOURCES_ENABLED", "new") == "updated"
    assert path.read_text() == "SOURCES_ENABLED=new\n"


def test_env_upsert_is_idempotent(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text("SOURCES_ENABLED=a,b\n", encoding="utf-8")
    assert _upsert_env_line(path, "SOURCES_ENABLED", "a,b") == "unchanged"
    assert path.read_text() == "SOURCES_ENABLED=a,b\n"


def test_env_upsert_leaves_every_other_line_byte_identical(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    original = (
        "# leading comment\n"
        "\n"
        "POSTGRES_PASSWORD=p@ss w0rd#with=signs\n"
        "SOURCES_ENABLED=stale\n"
        "\n"
        "# trailing comment\n"
        "API_KEY=\n"
    )
    path.write_text(original, encoding="utf-8")
    _upsert_env_line(path, "SOURCES_ENABLED", "fresh")

    assert path.read_text() == original.replace("stale", "fresh")


def test_env_upsert_does_not_match_a_similarly_named_key(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text("SOURCES_ENABLED_EXTRA=keep\n", encoding="utf-8")
    assert _upsert_env_line(path, "SOURCES_ENABLED", "a") == "added"
    assert path.read_text() == "SOURCES_ENABLED_EXTRA=keep\nSOURCES_ENABLED=a\n"


def test_env_upsert_creates_the_file_when_absent(tmp_path: Path) -> None:
    from app.cli import _upsert_env_line

    path = tmp_path / "new.env"
    assert _upsert_env_line(path, "SOURCES_ENABLED", "a") == "added"
    assert path.read_text() == "SOURCES_ENABLED=a\n"


def test_env_upsert_adds_a_newline_before_appending(tmp_path: Path) -> None:
    """A file that does not end in a newline must not get two keys on one line."""
    from app.cli import _upsert_env_line

    path = tmp_path / ".env"
    path.write_text("API_KEY=k", encoding="utf-8")
    _upsert_env_line(path, "SOURCES_ENABLED", "a")
    assert path.read_text() == "API_KEY=k\nSOURCES_ENABLED=a\n"


def test_enable_sources_selects_only_the_usable_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The safety property: a broken source can never reach the allowlist.

    Including one that is currently enabled and has since stopped working — the
    command drops it and says so, rather than carrying it forward.
    """
    from app import cli
    from app.services.source_health import SourceHealth, Verdict

    results = [
        SourceHealth("good", "rss", "COMPANY", False, Verdict.READY_TO_ENABLE, "12 entries"),
        SourceHealth("already-on", "rss", "COMPANY", True, Verdict.ACTIVE, "8 entries"),
        SourceHealth("blocked", "rss", "COMPANY", False, Verdict.BLOCKED_BY_EGRESS, "403"),
        SourceHealth("gone", "rss", "COMPANY", False, Verdict.UNREACHABLE, "HTTP 404"),
        SourceHealth("html", "rss", "COMPANY", False, Verdict.NOT_USABLE, "not a feed"),
        SourceHealth("empty", "rss", "COMPANY", False, Verdict.EMPTY, "no entries"),
        SourceHealth("bad-entry", "rss", "COMPANY", False, Verdict.MISCONFIGURED, "no url"),
        # Enabled, but no longer working: must be dropped, not carried over.
        SourceHealth("was-working", "rss", "COMPANY", True, Verdict.UNREACHABLE, "HTTP 500"),
    ]
    monkeypatch.setattr(
        "app.services.source_health.check_all", lambda **_: results, raising=True
    )

    env_path = tmp_path / ".env"
    env_path.write_text("POSTGRES_PASSWORD=secret\n", encoding="utf-8")
    exit_code = cli.main(
        ["enable-sources", "--write-env", str(env_path), "--quiet"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "SOURCES_ENABLED=already-on,good"
    assert env_path.read_text() == (
        "POSTGRES_PASSWORD=secret\nSOURCES_ENABLED=already-on,good\n"
    )


def test_enable_sources_writes_nothing_when_nothing_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty allowlist would switch everything off; refuse instead."""
    from app import cli
    from app.services.source_health import SourceHealth, Verdict

    monkeypatch.setattr(
        "app.services.source_health.check_all",
        lambda **_: [
            SourceHealth("blocked", "rss", "COMPANY", False, Verdict.BLOCKED_BY_EGRESS, "403")
        ],
        raising=True,
    )
    env_path = tmp_path / ".env"
    env_path.write_text("SOURCES_ENABLED=keep-me\n", encoding="utf-8")

    assert cli.main(["enable-sources", "--write-env", str(env_path)]) == 1
    assert env_path.read_text() == "SOURCES_ENABLED=keep-me\n"
