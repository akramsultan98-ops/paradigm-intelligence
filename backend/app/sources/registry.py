"""Adapter registry and configuration loading."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings
from app.domain.enums import SourceType
from app.sources.base import SourceAdapter, SourceConfig
from app.sources.jsonl import JsonlFileSourceAdapter
from app.sources.rss import RssSourceAdapter

logger = logging.getLogger(__name__)

#: Adapter name → class. Adding a retrieval mechanism means one entry here.
ADAPTERS: dict[str, type[SourceAdapter]] = {
    "rss": RssSourceAdapter,
    "jsonl": JsonlFileSourceAdapter,
}


def build_adapter(config: SourceConfig) -> SourceAdapter:
    """Instantiate the adapter named by ``config.adapter``."""
    try:
        adapter_cls = ADAPTERS[config.adapter]
    except KeyError:
        raise ValueError(
            f"source {config.key!r}: unknown adapter {config.adapter!r}. "
            f"Known adapters: {sorted(ADAPTERS)}"
        ) from None
    return adapter_cls(config)


def _parse_entry(entry: dict, index: int) -> SourceConfig:
    key = str(entry.get("key") or "").strip()
    if not key:
        raise ValueError(f"source entry #{index}: 'key' is required")
    adapter = str(entry.get("adapter") or "").strip()
    if not adapter:
        raise ValueError(f"source {key!r}: 'adapter' is required")

    raw_type = str(entry.get("source_type") or SourceType.OTHER.value).strip().upper()
    try:
        source_type = SourceType(raw_type)
    except ValueError:
        raise ValueError(
            f"source {key!r}: unknown source_type {raw_type!r}. "
            f"Valid values: {[t.value for t in SourceType]}"
        ) from None

    confidence = float(entry.get("confidence", 0.5))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"source {key!r}: confidence must be between 0 and 1")

    return SourceConfig(
        key=key,
        adapter=adapter,
        source_type=source_type,
        publisher=entry.get("publisher"),
        enabled=bool(entry.get("enabled", True)),
        confidence=confidence,
        company_hint=entry.get("company_hint"),
        options=dict(entry.get("options") or {}),
    )


def load_source_configs(path: str | Path | None = None) -> list[SourceConfig]:
    """Read and validate the source registry.

    A missing file is not an error — a fresh deployment has no sources yet, and
    the ingestion command should say "nothing configured" rather than crash.
    Duplicate keys *are* an error, since they would make runs ambiguous.
    """
    settings = get_settings()
    config_path = Path(path or settings.sources_config)
    if not config_path.is_file():
        logger.warning("no source registry found", extra={"path": str(config_path)})
        return []

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path} is not valid JSON: {exc}") from exc

    entries = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError(f"{config_path}: expected a 'sources' array")

    configs: list[SourceConfig] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"source entry #{index}: expected an object")
        config = _parse_entry(entry, index)
        if config.key in seen:
            raise ValueError(f"duplicate source key {config.key!r}")
        seen.add(config.key)
        configs.append(config)
    return configs


def load_sources(
    path: str | Path | None = None, *, only: list[str] | None = None
) -> list[SourceAdapter]:
    """Build every enabled adapter, or just the ones named in ``only``.

    An adapter that fails to construct (a missing ``feed_url``, say) is logged
    and skipped rather than aborting the run — one misconfigured feed should not
    stop the others from being ingested.
    """
    adapters: list[SourceAdapter] = []
    wanted = set(only) if only else None

    for config in load_source_configs(path):
        if wanted is not None and config.key not in wanted:
            continue
        if not config.enabled and wanted is None:
            logger.info("source disabled, skipping", extra={"source": config.key})
            continue
        try:
            adapters.append(build_adapter(config))
        except ValueError as exc:
            logger.error("source misconfigured, skipping", extra={"error": str(exc)})

    if wanted:
        missing = wanted - {adapter.key for adapter in adapters}
        for key in sorted(missing):
            logger.error("requested source not found in registry", extra={"source": key})
    return adapters
