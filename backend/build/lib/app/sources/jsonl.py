"""Local newline-delimited JSON adapter.

For analyst-supplied material and for fixtures: a researcher drops documents in a
file, the pipeline treats them like any other source. This is also how the
integration tests exercise ingestion without a network.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.sources.base import RawDocument, SourceAdapter, SourceConfig

logger = logging.getLogger(__name__)


def _parse_date(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.warning("unparseable published_at", extra={"value": value[:40]})
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class JsonlFileSourceAdapter(SourceAdapter):
    """Reads documents from a ``.jsonl`` file.

    Options:
        ``path`` (required) — file path, absolute or relative to the working
        directory.

    Each line is an object with ``url`` and ``content``, plus any of ``title``,
    ``publisher``, ``published_at``, ``company_hint``.
    """

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        raw_path = config.options.get("path")
        if not raw_path:
            raise ValueError(f"source {config.key!r}: jsonl adapter requires options.path")
        self.path = Path(raw_path)

    def fetch(self, since: datetime | None = None) -> Iterator[RawDocument]:
        if not self.path.is_file():
            logger.error("jsonl source missing", extra={"source": self.key, "path": str(self.path)})
            return

        limit = self.config.max_docs or get_settings().ingest_max_docs_per_source
        emitted = 0
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if emitted >= limit:
                    break
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    # One bad line must not cost the whole file.
                    logger.warning(
                        "skipping unparseable jsonl line",
                        extra={"source": self.key, "line": line_number, "error": str(exc)},
                    )
                    continue
                if not isinstance(record, dict):
                    continue

                published_at = _parse_date(record.get("published_at"))
                if since and published_at and published_at < since:
                    continue

                try:
                    yield RawDocument(
                        url=str(record.get("url", "")),
                        title=record.get("title"),
                        content=str(record.get("content") or record.get("title") or ""),
                        source_type=self.source_type,
                        publisher=record.get("publisher") or self.config.publisher,
                        published_at=published_at,
                        company_hint=record.get("company_hint") or self.config.company_hint,
                        confidence=float(record.get("confidence", self.config.confidence)),
                        adapter_key=self.key,
                    )
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "skipping malformed jsonl record",
                        extra={"source": self.key, "line": line_number, "error": str(exc)},
                    )
                    continue
                emitted += 1
