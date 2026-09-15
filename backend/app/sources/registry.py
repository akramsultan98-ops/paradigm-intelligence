"""Adapter registry and configuration loading."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings
from app.domain.enums import SourceType
from app.sources.base import SourceAdapter, SourceConfig
from app.sources.contacts import ContactPageAdapter, ContactSourceAdapter
from app.sources.jsonl import JsonlFileSourceAdapter
from app.sources.rss import RssSourceAdapter

logger = logging.getLogger(__name__)

#: Document adapters: name → class. Adding a retrieval mechanism means one entry.
ADAPTERS: dict[str, type[SourceAdapter]] = {
    "rss": RssSourceAdapter,
    "jsonl": JsonlFileSourceAdapter,
}

#: Contact adapters. A separate table because they yield people, not documents,
#: and so satisfy a different contract.
CONTACT_ADAPTERS: dict[str, type[ContactSourceAdapter]] = {
    "contact_page": ContactPageAdapter,
}

#: Every adapter name the registry recognises.
ALL_ADAPTER_NAMES = frozenset(ADAPTERS) | frozenset(CONTACT_ADAPTERS)


def build_adapter(config: SourceConfig) -> SourceAdapter:
    """Instantiate the document adapter named by ``config.adapter``."""
    try:
        adapter_cls = ADAPTERS[config.adapter]
    except KeyError:
        raise ValueError(
            f"source {config.key!r}: unknown adapter {config.adapter!r}. "
            f"Known adapters: {sorted(ALL_ADAPTER_NAMES)}"
        ) from None
    return adapter_cls(config)


def build_contact_adapter(config: SourceConfig) -> ContactSourceAdapter:
    """Instantiate the contact adapter named by ``config.adapter``."""
    try:
        adapter_cls = CONTACT_ADAPTERS[config.adapter]
    except KeyError:
        raise ValueError(
            f"contact source {config.key!r}: unknown adapter {config.adapter!r}. "
            f"Known contact adapters: {sorted(CONTACT_ADAPTERS)}"
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

    rate_limit = float(entry.get("rate_limit_per_minute", 20.0))
    if rate_limit <= 0:
        raise ValueError(f"source {key!r}: rate_limit_per_minute must be positive")

    priority = int(entry.get("priority", 50))
    if not 0 <= priority <= 100:
        raise ValueError(f"source {key!r}: priority must be between 0 and 100")

    max_docs = entry.get("max_docs")
    if max_docs is not None:
        max_docs = int(max_docs)
        if max_docs < 1:
            raise ValueError(f"source {key!r}: max_docs must be at least 1")

    return SourceConfig(
        key=key,
        adapter=adapter,
        source_type=source_type,
        publisher=entry.get("publisher"),
        enabled=bool(entry.get("enabled", True)),
        confidence=confidence,
        company_hint=entry.get("company_hint"),
        priority=priority,
        rate_limit_per_minute=rate_limit,
        max_docs=max_docs,
        notes=entry.get("notes"),
        options=dict(entry.get("options") or {}),
    )


def apply_enabled_allowlist(
    configs: list[SourceConfig], enabled: list[str]
) -> list[SourceConfig]:
    """Override each config's ``enabled`` flag from an explicit allowlist.

    ``enabled`` empty means "the registry file decides", which is what a fresh
    deployment gets, and the registry ships everything off.

    A non-empty allowlist is authoritative in *both* directions: the named keys are
    switched on and every other source is switched off, whatever the file says.
    That is the point — it makes the set of live sources one reviewable value rather
    than a flag per entry that can be left switched on by accident.

    An unknown key is an error, not a no-op. A typo would otherwise mean "ingest
    nothing", reported as a successful run with no documents, which is the single
    most expensive way for this to fail.
    """
    if not enabled:
        return configs

    wanted = {key.strip() for key in enabled if key.strip()}
    known = {config.key for config in configs}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(
            f"SOURCES_ENABLED names source(s) that are not in the registry: "
            f"{', '.join(unknown)}. Known keys: {', '.join(sorted(known))}"
        )

    for config in configs:
        config.enabled = config.key in wanted
    return configs


def load_source_configs(path: str | Path | None = None) -> list[SourceConfig]:
    """Read and validate the source registry.

    A missing file is not an error — a fresh deployment has no sources yet, and
    the ingestion command should say "nothing configured" rather than crash.
    Duplicate keys *are* an error, since they would make runs ambiguous.

    ``SOURCES_ENABLED`` is applied here rather than in the callers, so that
    ingestion, contact discovery, the preflight and the ``sources`` listing all
    agree on which sources are live.
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
    return apply_enabled_allowlist(configs, settings.sources_enabled)


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
        # Contact sources live in the same registry but are a different contract;
        # load_contact_sources() handles those.
        if config.adapter in CONTACT_ADAPTERS:
            continue
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

    # Highest priority first: whichever source reports a signal first is the one
    # it gets attributed to, so official channels should get the chance.
    adapters.sort(key=lambda adapter: (-adapter.config.priority, adapter.key))
    return adapters


def load_contact_sources(
    path: str | Path | None = None, *, only: list[str] | None = None
) -> list[ContactSourceAdapter]:
    """Build every enabled contact adapter, or just the ones named in ``only``."""
    adapters: list[ContactSourceAdapter] = []
    wanted = set(only) if only else None

    for config in load_source_configs(path):
        if config.adapter not in CONTACT_ADAPTERS:
            continue
        if wanted is not None and config.key not in wanted:
            continue
        if not config.enabled and wanted is None:
            logger.info("contact source disabled, skipping", extra={"source": config.key})
            continue
        try:
            adapters.append(build_contact_adapter(config))
        except ValueError as exc:
            logger.error("contact source misconfigured, skipping", extra={"error": str(exc)})

    adapters.sort(key=lambda adapter: (-adapter.config.priority, adapter.key))
    return adapters
