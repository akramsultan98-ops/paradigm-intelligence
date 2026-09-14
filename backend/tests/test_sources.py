"""Source adapter and registry tests.

The recurring theme: one malformed entry or one broken feed must never cost a
whole run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.domain.enums import SourceType
from app.sources import build_adapter, load_source_configs, load_sources
from app.sources.base import RawDocument, SourceConfig
from app.sources.jsonl import JsonlFileSourceAdapter
from app.sources.rss import RssSourceAdapter, _strip_html

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Business Daily</title>
  <item>
    <title>Elsewedy Electric opens new factory</title>
    <link>https://example.test/news/factory</link>
    <description>&lt;p&gt;The group &lt;b&gt;inaugurated&lt;/b&gt; a plant.&lt;/p&gt;</description>
    <pubDate>Wed, 10 Sep 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Older story</title>
    <link>https://example.test/news/old</link>
    <description>Something from a while ago.</description>
    <pubDate>Mon, 06 Jan 2025 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Entry with no link</title>
    <description>Should be skipped.</description>
  </item>
</channel></rss>
"""


# --------------------------------------------------------------------------
# RawDocument
# --------------------------------------------------------------------------

def test_raw_document_requires_a_url() -> None:
    with pytest.raises(ValueError):
        RawDocument(url="  ", title="t", content="c", source_type=SourceType.OTHER)


def test_raw_document_clamps_confidence() -> None:
    def document(confidence: float) -> RawDocument:
        return RawDocument("https://a.test", "t", "c", SourceType.OTHER, confidence=confidence)

    assert document(5.0).confidence == 1.0
    assert document(-1).confidence == 0.0


# --------------------------------------------------------------------------
# RSS
# --------------------------------------------------------------------------

def _rss_adapter(body: str = FEED, status: int = 200) -> RssSourceAdapter:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body.encode())

    config = SourceConfig(
        key="test-feed",
        adapter="rss",
        source_type=SourceType.BUSINESS_PUBLICATION,
        publisher="Example Business Daily",
        confidence=0.8,
        options={"feed_url": "https://example.test/feed"},
    )
    return RssSourceAdapter(config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_rss_adapter_parses_entries() -> None:
    documents = list(_rss_adapter().fetch())
    # Three items, but one has no link and is skipped.
    assert len(documents) == 2
    first = documents[0]
    assert first.url == "https://example.test/news/factory"
    assert first.title == "Elsewedy Electric opens new factory"
    assert "inaugurated" in first.content
    assert "<b>" not in first.content
    assert first.published_at == datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    assert first.source_type is SourceType.BUSINESS_PUBLICATION
    assert first.confidence == 0.8
    assert first.adapter_key == "test-feed"


def test_rss_adapter_respects_since() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    urls = [document.url for document in _rss_adapter().fetch(since)]
    assert urls == ["https://example.test/news/factory"]


def test_rss_adapter_survives_an_http_error() -> None:
    """A dead feed yields nothing; it does not raise."""
    assert list(_rss_adapter(status=500).fetch()) == []


def test_rss_adapter_survives_unparseable_content() -> None:
    assert list(_rss_adapter(body="this is not xml at all").fetch()) == []


def test_rss_adapter_requires_a_feed_url() -> None:
    with pytest.raises(ValueError, match="feed_url"):
        RssSourceAdapter(SourceConfig(key="x", adapter="rss", source_type=SourceType.OTHER))


def test_strip_html_removes_scripts() -> None:
    assert "alert" not in _strip_html("<p>Hi</p><script>alert(1)</script>")


# --------------------------------------------------------------------------
# JSONL
# --------------------------------------------------------------------------

def test_jsonl_adapter_reads_records_and_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_text(
        json.dumps({"url": "https://a.test/1", "title": "One",
                    "content": "Body one", "published_at": "2026-09-10T08:00:00Z",
                    "company_hint": "Example Corp"})
        + "\n"
        + "{not valid json}\n"
        + "\n"
        + json.dumps({"no_url": True}) + "\n"
        + json.dumps({"url": "https://a.test/2", "title": "Two", "content": "Body two"}) + "\n",
        encoding="utf-8",
    )
    adapter = JsonlFileSourceAdapter(
        SourceConfig(key="local", adapter="jsonl", source_type=SourceType.COMPANY,
                     options={"path": str(path)})
    )
    documents = list(adapter.fetch())
    assert [d.url for d in documents] == ["https://a.test/1", "https://a.test/2"]
    assert documents[0].company_hint == "Example Corp"
    assert documents[1].published_at is None


def test_jsonl_adapter_handles_a_missing_file(tmp_path: Path) -> None:
    adapter = JsonlFileSourceAdapter(
        SourceConfig(key="local", adapter="jsonl", source_type=SourceType.OTHER,
                     options={"path": str(tmp_path / "nope.jsonl")})
    )
    assert list(adapter.fetch()) == []


def test_jsonl_adapter_requires_a_path() -> None:
    with pytest.raises(ValueError, match="path"):
        JsonlFileSourceAdapter(SourceConfig(key="x", adapter="jsonl", source_type=SourceType.OTHER))


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def _write_registry(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": entries}), encoding="utf-8")
    return path


def test_registry_loads_and_validates(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [
        {"key": "a", "adapter": "rss", "source_type": "COMPANY", "confidence": 0.9,
         "options": {"feed_url": "https://a.test/feed"}},
        {"key": "b", "adapter": "jsonl", "source_type": "OTHER", "enabled": False,
         "options": {"path": "x.jsonl"}},
    ])
    configs = load_source_configs(path)
    assert [c.key for c in configs] == ["a", "b"]
    assert configs[0].source_type is SourceType.COMPANY
    # Only the enabled one is built.
    assert [a.key for a in load_sources(path)] == ["a"]
    # Naming a source explicitly overrides its disabled flag.
    assert [a.key for a in load_sources(path, only=["b"])] == ["b"]


def test_registry_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [
        {"key": "a", "adapter": "jsonl", "source_type": "OTHER", "options": {"path": "x"}},
        {"key": "a", "adapter": "jsonl", "source_type": "OTHER", "options": {"path": "y"}},
    ])
    with pytest.raises(ValueError, match="duplicate source key"):
        load_source_configs(path)


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        ({"adapter": "rss", "source_type": "COMPANY"}, "'key' is required"),
        ({"key": "a", "source_type": "COMPANY"}, "'adapter' is required"),
        ({"key": "a", "adapter": "rss", "source_type": "MADE_UP"}, "unknown source_type"),
        ({"key": "a", "adapter": "rss", "source_type": "COMPANY", "confidence": 3}, "confidence"),
    ],
)
def test_registry_rejects_bad_entries(tmp_path: Path, entry: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_source_configs(_write_registry(tmp_path, [entry]))


def test_registry_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_source_configs(path)


def test_missing_registry_is_not_an_error(tmp_path: Path) -> None:
    """A fresh deployment has no sources yet; that is not a crash."""
    assert load_source_configs(tmp_path / "absent.json") == []


def test_one_misconfigured_source_does_not_block_the_others(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, [
        {"key": "broken", "adapter": "rss", "source_type": "COMPANY", "options": {}},
        {"key": "fine", "adapter": "jsonl", "source_type": "OTHER", "options": {"path": "x"}},
    ])
    assert [a.key for a in load_sources(path)] == ["fine"]


def test_unknown_adapter_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown adapter"):
        build_adapter(SourceConfig(key="x", adapter="nope", source_type=SourceType.OTHER))


def test_shipped_registry_is_valid() -> None:
    """The committed config/sources.json must parse."""
    path = Path(__file__).resolve().parents[2] / "config" / "sources.json"
    configs = load_source_configs(path)
    assert configs
    # No live feed is enabled by default: nothing is claimed about sources whose
    # terms have not been checked.
    assert all(not config.enabled for config in configs)
