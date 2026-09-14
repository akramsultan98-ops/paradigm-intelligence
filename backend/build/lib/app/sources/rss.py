"""RSS/Atom adapter.

Covers company newsrooms, business press, industry press and event listings — the
difference between those is the configured ``source_type`` and trust tier, not
the fetch mechanics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import feedparser

from app.config import get_settings
from app.sources.base import RawDocument, SourceAdapter, SourceConfig
from app.sources.http import FetchClient

logger = logging.getLogger(__name__)


def _entry_text(entry: feedparser.FeedParserDict) -> str:
    """Longest available text for an entry.

    Feeds disagree about where the body lives; ``content`` is usually fuller than
    ``summary`` when both are present, so the longest wins.
    """
    candidates: list[str] = []
    for block in entry.get("content") or []:
        value = block.get("value")
        if value:
            candidates.append(value)
    for key in ("summary", "description", "subtitle"):
        value = entry.get(key)
        if value:
            candidates.append(value)
    if not candidates:
        return ""
    return max(candidates, key=len)


def _strip_html(value: str) -> str:
    """Crude tag removal.

    Feed bodies are small and usually lightly marked up; pulling in a parser for
    this would not change the extracted text.
    """
    import html
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None


class RssSourceAdapter(SourceAdapter):
    """Reads one RSS or Atom feed.

    Options:
        ``feed_url`` (required) — the feed address.
    """

    def __init__(self, config: SourceConfig, client: FetchClient | None = None):
        super().__init__(config)
        self.feed_url = config.options.get("feed_url")
        if not self.feed_url:
            raise ValueError(f"source {config.key!r}: rss adapter requires options.feed_url")
        self._settings = get_settings()
        self._owns_client = client is None
        self._client = client or FetchClient(self._settings)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def limit(self) -> int:
        return self.config.max_docs or self._settings.ingest_max_docs_per_source

    def fetch(self, since: datetime | None = None) -> Iterator[RawDocument]:
        result = self._client.fetch(
            self.feed_url, requests_per_minute=self.config.rate_limit_per_minute
        )
        if not result.ok:
            logger.error(
                "feed unavailable",
                extra={"source": self.key, "status": result.status, "error": result.error},
            )
            return

        parsed = feedparser.parse(result.content)
        if parsed.get("bozo") and not parsed.entries:
            logger.error(
                "feed did not parse",
                extra={"source": self.key, "error": str(parsed.get("bozo_exception"))[:200]},
            )
            return

        emitted = 0
        for entry in parsed.entries:
            if emitted >= self.limit:
                break
            link = (entry.get("link") or "").strip()
            if not link:
                continue

            published_at = _entry_date(entry)
            # An undated entry is kept: dropping it would lose real signals from
            # feeds that simply omit dates. It scores lower for exactly that.
            if since and published_at and published_at < since:
                continue

            title = (entry.get("title") or "").strip() or None
            body = _strip_html(_entry_text(entry))
            if not title and not body:
                continue

            try:
                yield RawDocument(
                    url=link,
                    title=title,
                    content=body or (title or ""),
                    source_type=self.source_type,
                    publisher=self.config.publisher or parsed.feed.get("title"),
                    published_at=published_at,
                    company_hint=self.config.company_hint,
                    confidence=self.config.confidence,
                    adapter_key=self.key,
                )
            except ValueError as exc:
                logger.warning(
                    "skipping malformed feed entry",
                    extra={"source": self.key, "error": str(exc)},
                )
                continue
            emitted += 1
