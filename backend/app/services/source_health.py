"""Source preflight (spec §34: only mark a source active if it actually works).

The registry requires every source to be verified before it is enabled. This turns
that manual check into one command, and — the part that matters when a run returns
nothing — it tells the three failure modes apart:

- **blocked by egress policy**: the network this process is on refuses to connect
  at all. The source may be perfectly healthy; you cannot reach it from here.
- **unreachable / rejected**: the connection was allowed and the publisher said no
  (404, 410, 5xx), or nothing answered.
- **reachable but unusable**: it answered, and what came back is not a usable feed.

Confusing the first with the second is how an afternoon gets lost, so the verdicts
are deliberately distinct.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from app.config import Settings, get_settings
from app.sources.base import SourceConfig
from app.sources.http import FetchClient

logger = logging.getLogger(__name__)

#: Markers the local egress proxy uses when an organisation policy refuses the
#: connection outright. A 403 to CONNECT never reaches the publisher.
_EGRESS_MARKERS = ("ProxyError", "403 Forbidden", "CONNECT", "407")


class Verdict(StrEnum):
    """What to do about a source."""

    #: Works, and is already switched on.
    ACTIVE = "ACTIVE"
    #: Works. Flip `enabled` to true once you have checked its terms of use.
    READY_TO_ENABLE = "READY_TO_ENABLE"
    #: This network will not let us connect. Not the source's fault.
    BLOCKED_BY_EGRESS = "BLOCKED_BY_EGRESS"
    #: Connection allowed, publisher refused or nothing answered.
    UNREACHABLE = "UNREACHABLE"
    #: Answered, but not with anything usable.
    NOT_USABLE = "NOT_USABLE"
    #: Answered with a valid but empty feed.
    EMPTY = "EMPTY"
    #: The registry entry itself is wrong.
    MISCONFIGURED = "MISCONFIGURED"


@dataclass(slots=True)
class SourceHealth:
    """One source's preflight result."""

    key: str
    adapter: str
    source_type: str
    enabled: bool
    verdict: Verdict
    detail: str
    target: str | None = None
    http_status: int | None = None
    items_found: int = 0
    items_recent: int = 0
    sample_titles: list[str] = field(default_factory=list)
    advice: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict in {Verdict.ACTIVE, Verdict.READY_TO_ENABLE}

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "adapter": self.adapter,
            "source_type": self.source_type,
            "enabled": self.enabled,
            "verdict": self.verdict.value,
            "detail": self.detail,
            "target": self.target,
            "http_status": self.http_status,
            "items_found": self.items_found,
            "items_recent": self.items_recent,
            "sample_titles": self.sample_titles,
            "advice": self.advice,
        }


def _probe_settings(settings: Settings) -> Settings:
    """Settings for a probe: one attempt, no backoff.

    A preflight exists to give a fast, unambiguous answer. Retrying triples the
    wait for no new information, and an egress-policy denial must not be retried
    at all.
    """
    return settings.model_copy(
        update={"ingest_max_attempts": 1, "ingest_max_backoff_seconds": 0.0}
    )


def _is_egress_block(error: str | None) -> bool:
    return bool(error) and any(marker in error for marker in _EGRESS_MARKERS)


#: Adapter-specific overrides, because generic advice can be actively misleading:
#: telling someone to check a URL in a browser when a local file is missing sends
#: them to the wrong place entirely.
_LOCAL_ADVICE = {
    Verdict.UNREACHABLE: (
        "The file does not exist. Create it, or point options.path at the right "
        "place. A relative path is resolved from the working directory the command "
        "runs in."
    ),
    Verdict.EMPTY: (
        "The file exists but holds no usable records. Each line must be a JSON "
        "object with at least a 'url'."
    ),
}

_ADVICE = {
    Verdict.ACTIVE: "Nothing to do.",
    Verdict.READY_TO_ENABLE: (
        "Confirm the publisher's terms of use and robots.txt permit automated "
        "access for this purpose, then set enabled: true in config/sources.json."
    ),
    Verdict.BLOCKED_BY_EGRESS: (
        "This network refuses the connection before it reaches the publisher. Run "
        "from a host with outbound HTTPS to this domain, or have the domain added "
        "to the egress allowlist. Do not enable the source on the strength of this "
        "result - it has not been verified either way."
    ),
    Verdict.UNREACHABLE: (
        "The connection was permitted and the publisher did not serve the feed. "
        "Check the URL in a browser; publishers move and retire feed paths."
    ),
    Verdict.NOT_USABLE: (
        "Something answered but it is not a usable feed - commonly an HTML page "
        "where a feed used to be, or a consent/anti-bot interstitial. Find the "
        "real feed URL, or write an adapter for the HTML."
    ),
    Verdict.EMPTY: (
        "A valid but empty feed. Harmless to enable; it will contribute nothing "
        "until the publisher posts."
    ),
    Verdict.MISCONFIGURED: "Fix the registry entry; see the detail above.",
}


def _finish(health: SourceHealth) -> SourceHealth:
    if health.adapter == "jsonl" and health.verdict in _LOCAL_ADVICE:
        health.advice = _LOCAL_ADVICE[health.verdict]
    else:
        health.advice = _ADVICE[health.verdict]
    return health


def _check_rss(
    config: SourceConfig, client: FetchClient, settings: Settings
) -> SourceHealth:
    import feedparser

    feed_url = config.options.get("feed_url")
    health = SourceHealth(
        key=config.key, adapter=config.adapter, source_type=config.source_type.value,
        enabled=config.enabled, verdict=Verdict.MISCONFIGURED, detail="", target=feed_url,
    )
    if not feed_url:
        health.detail = "options.feed_url is missing"
        return _finish(health)

    result = client.fetch(feed_url, requests_per_minute=config.rate_limit_per_minute)
    health.http_status = result.status

    if not result.ok:
        if _is_egress_block(result.error):
            health.verdict = Verdict.BLOCKED_BY_EGRESS
            health.detail = f"egress policy refused the connection ({result.error})"
        else:
            health.verdict = Verdict.UNREACHABLE
            health.detail = result.error or f"HTTP {result.status}"
        return _finish(health)

    parsed = feedparser.parse(result.content)
    entries = list(parsed.entries or [])
    health.items_found = len(entries)

    if not entries:
        if parsed.get("bozo"):
            health.verdict = Verdict.NOT_USABLE
            health.detail = (
                f"did not parse as RSS/Atom: {str(parsed.get('bozo_exception'))[:120]}"
            )
        else:
            health.verdict = Verdict.EMPTY
            health.detail = "parsed as a feed, but it contains no entries"
        return _finish(health)

    cutoff = datetime.now(UTC) - timedelta(days=settings.ingest_lookback_days)
    recent = 0
    for entry in entries:
        for key in ("published_parsed", "updated_parsed"):
            parsed_date = entry.get(key)
            if parsed_date:
                try:
                    if datetime(*parsed_date[:6], tzinfo=UTC) >= cutoff:
                        recent += 1
                except (TypeError, ValueError):
                    pass
                break
    health.items_recent = recent
    health.sample_titles = [
        (entry.get("title") or "").strip()[:110] for entry in entries[:3]
    ]
    health.verdict = Verdict.ACTIVE if config.enabled else Verdict.READY_TO_ENABLE
    health.detail = (
        f"{len(entries)} entries, {recent} within the last "
        f"{settings.ingest_lookback_days} days"
    )
    return _finish(health)


def _check_contact_page(config: SourceConfig, client: FetchClient) -> SourceHealth:
    from app.sources.contacts import extract_contacts_from_html

    url = config.options.get("url")
    company = config.options.get("company") or config.company_hint
    health = SourceHealth(
        key=config.key, adapter=config.adapter, source_type=config.source_type.value,
        enabled=config.enabled, verdict=Verdict.MISCONFIGURED, detail="", target=url,
    )
    if not url or not company:
        health.detail = "options.url and options.company are both required"
        return _finish(health)

    result = client.fetch(url, requests_per_minute=config.rate_limit_per_minute)
    health.http_status = result.status
    if not result.ok:
        if _is_egress_block(result.error):
            health.verdict = Verdict.BLOCKED_BY_EGRESS
            health.detail = f"egress policy refused the connection ({result.error})"
        else:
            health.verdict = Verdict.UNREACHABLE
            health.detail = result.error or f"HTTP {result.status}"
        return _finish(health)

    contacts = extract_contacts_from_html(
        (result.content or b"").decode("utf-8", "replace"),
        company_name=company, source_url=url,
    )
    health.items_found = len(contacts)
    health.items_recent = len(contacts)
    health.sample_titles = [
        f"{c.name} — {c.job_title or c.department.value}" for c in contacts[:3]
    ]
    if not contacts:
        health.verdict = Verdict.EMPTY
        health.detail = (
            "page fetched, but no contact relevant to event spending was published "
            "on it. Check it is the leadership or press-contact page."
        )
        return _finish(health)
    health.verdict = Verdict.ACTIVE if config.enabled else Verdict.READY_TO_ENABLE
    health.detail = f"{len(contacts)} relevant contacts published on the page"
    return _finish(health)


def _check_jsonl(config: SourceConfig) -> SourceHealth:
    raw_path = config.options.get("path")
    health = SourceHealth(
        key=config.key, adapter=config.adapter, source_type=config.source_type.value,
        enabled=config.enabled, verdict=Verdict.MISCONFIGURED, detail="", target=raw_path,
    )
    if not raw_path:
        health.detail = "options.path is missing"
        return _finish(health)

    path = Path(raw_path)
    if not path.is_file():
        health.verdict = Verdict.UNREACHABLE
        health.detail = f"file not found: {path}"
        return _finish(health)

    valid = 0
    titles: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("url"):
            valid += 1
            if len(titles) < 3:
                titles.append(str(record.get("title") or record["url"])[:110])
    health.items_found = valid
    health.items_recent = valid
    health.sample_titles = titles
    if not valid:
        health.verdict = Verdict.EMPTY
        health.detail = "file exists but contains no usable records"
        return _finish(health)
    health.verdict = Verdict.ACTIVE if config.enabled else Verdict.READY_TO_ENABLE
    health.detail = f"{valid} usable records"
    return _finish(health)


def check_source(
    config: SourceConfig,
    client: FetchClient | None = None,
    settings: Settings | None = None,
) -> SourceHealth:
    """Probe one configured source and say what to do about it."""
    settings = settings or get_settings()
    owns_client = client is None
    client = client or FetchClient(_probe_settings(settings))
    try:
        if config.adapter == "rss":
            return _check_rss(config, client, settings)
        if config.adapter == "contact_page":
            return _check_contact_page(config, client)
        if config.adapter == "jsonl":
            return _check_jsonl(config)
        health = SourceHealth(
            key=config.key, adapter=config.adapter, source_type=config.source_type.value,
            enabled=config.enabled, verdict=Verdict.MISCONFIGURED,
            detail=f"unknown adapter {config.adapter!r}",
        )
        return _finish(health)
    except Exception as exc:  # noqa: BLE001 - a probe must never raise
        logger.exception("source health check failed", extra={"source": config.key})
        health = SourceHealth(
            key=config.key, adapter=config.adapter, source_type=config.source_type.value,
            enabled=config.enabled, verdict=Verdict.NOT_USABLE,
            detail=f"{type(exc).__name__}: {exc}"[:200],
        )
        return _finish(health)
    finally:
        if owns_client:
            client.close()


def check_all(
    path: str | Path | None = None,
    *,
    only: list[str] | None = None,
    settings: Settings | None = None,
) -> list[SourceHealth]:
    """Probe every configured source, highest priority first."""
    from app.sources import load_source_configs

    settings = settings or get_settings()
    configs = load_source_configs(path)
    if only:
        wanted = set(only)
        configs = [config for config in configs if config.key in wanted]
    configs.sort(key=lambda config: (-config.priority, config.key))

    results: list[SourceHealth] = []
    with FetchClient(_probe_settings(settings)) as client:
        for config in configs:
            results.append(check_source(config, client, settings))
    return results


def summarize(results: list[SourceHealth]) -> dict[str, object]:
    """Roll results up, and say plainly whether ingestion can work from here."""
    counts: dict[str, int] = {}
    for health in results:
        counts[health.verdict.value] = counts.get(health.verdict.value, 0) + 1

    usable = [health.key for health in results if health.usable]
    blocked = [health.key for health in results if health.verdict is Verdict.BLOCKED_BY_EGRESS]
    # Only network-backed adapters can be blocked by egress, so a local jsonl
    # source must not dilute the verdict on the ones that can.
    network = [health for health in results if health.adapter in {"rss", "contact_page"}]

    if not results:
        conclusion = "No sources are configured."
    elif usable:
        conclusion = (
            f"{len(usable)} source(s) reachable and usable from this host: "
            f"{', '.join(usable)}."
        )
    elif network and len(blocked) == len(network):
        conclusion = (
            f"All {len(network)} network source(s) are blocked by this host's egress "
            "policy, so none could be verified. They may be perfectly healthy; this "
            "network will not connect to them. Run from a host with outbound HTTPS "
            "access, or have these domains allowlisted. Until then automated "
            "ingestion cannot run, and POST /api/v1/ingest/signals (analyst intake) "
            "is the only way to add real signals."
        )
    else:
        conclusion = (
            "No source is currently usable. See each verdict and its advice below."
        )

    return {
        "checked": len(results),
        "usable": usable,
        "blocked_by_egress": blocked,
        "verdicts": counts,
        "conclusion": conclusion,
    }
