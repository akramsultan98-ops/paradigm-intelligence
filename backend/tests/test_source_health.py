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
