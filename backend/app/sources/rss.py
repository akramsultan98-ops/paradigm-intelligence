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
import httpx

from app.config import get_settings
from app.sources.base import RawDocument, SourceAdapter, SourceConfig

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

    def __init__(self, config: SourceConfig, client: httpx.Client | None = None):
        super().__init__(config)
        self.feed_url = config.options.get("feed_url")
        if not self.feed_url:
            raise ValueError(f"source {config.key!r}: rss adapter requires options.feed_url")
        self._client = client
        self._settings = get_settings()

    def _get(self, url: str) -> bytes | None:
        settings = self._settings
        headers = {"User-Agent": settings.ingest_user_agent}
        try:
            if self._client is not None:
                response = self._client.get(url, headers=headers)
            else:
                response = httpx.get(
                    url,
                    headers=headers,
                    timeout=settings.ingest_http_timeout,
                    follow_redirects=True,
                )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            logger.error("feed fetch failed", extra={"source": self.key, "error": str(exc)})
            return None

    def fetch(self, since: datetime | None = None) -> Iterator[RawDocument]:
        payload = self._get(self.feed_url)
        if payload is None:
            return

        parsed = feedparser.parse(payload)
        if parsed.get("bozo") and not parsed.entries:
            logger.error(
                "feed did not parse",
                extra={"source": self.key, "error": str(parsed.get("bozo_exception"))[:200]},
            )
            return

        limit = self._settings.ingest_max_docs_per_source
        emitted = 0
        for entry in parsed.entries:
            if emitted >= limit:
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
