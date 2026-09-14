"""Command-line interface — the scheduling surface.

Point cron at these. The API exposes the same operations for ad-hoc use, but a
long ingestion run belongs in a scheduled process, not in a request.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.db import check_database, session_scope
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False))


def cmd_ingest(args: argparse.Namespace) -> int:
    from app.services.pipeline import run_ingestion

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

    stats = run_ingestion(only=args.source or None, since=since)
    _print({"command": "ingest", **stats.as_dict()})
    # A run that hit errors exits non-zero so cron surfaces it.
    return 1 if stats.errors else 0


def cmd_discover_contacts(args: argparse.Namespace) -> int:
    from app.services.contact_discovery import run_contact_discovery

    stats = run_contact_discovery(only=args.source or None)
    _print({"command": "discover-contacts", **stats.as_dict()})
    return 1 if stats.errors else 0


def cmd_cycle(_: argparse.Namespace) -> int:
    """The full scheduled refresh: ingest, discover contacts, apply decay."""
    from app.services.scheduler import run_cycle

    result = run_cycle()
    _print({"command": "cycle", **result.as_dict()})
    return 1 if result.error else 0


def cmd_rescore(_: argparse.Namespace) -> int:
    from app.services.rescore import rescore_all

    with session_scope() as session:
        stats = rescore_all(session)
    _print({"command": "rescore", **stats.as_dict()})
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    from app.api.brief import _changed, _ranked
    from app.services.brief import build_daily_brief

    with session_scope() as session:
        brief = build_daily_brief(session, window_hours=args.window_hours)
        payload = {
            "command": "brief",
            "generated_at": brief.generated_at,
            "window_hours": brief.window_hours,
            "qualifying_threshold": brief.qualifying_threshold,
            "top_n": brief.top_n,
            "eligible_total": brief.eligible_total,
            "classification_counts": brief.classification_counts,
            "top_new_opportunities": [
                item.model_dump(mode="json") for item in _ranked(brief.new_opportunities)
            ],
            "current_top_50": [
                item.model_dump(mode="json") for item in _ranked(brief.top_opportunities)
            ],
            "new_hot": [item.model_dump(mode="json") for item in _ranked(brief.new_hot)],
            "upgraded": [item.model_dump(mode="json") for item in _changed(brief.upgraded)],
            "downgraded": [item.model_dump(mode="json") for item in _changed(brief.downgraded)],
            "expired": [item.model_dump(mode="json") for item in _changed(brief.expired)],
        }
    _print(payload)
    return 0


def cmd_sources(_: argparse.Namespace) -> int:
    from app.sources import load_source_configs

    configs = load_source_configs()
    _print(
        {
            "command": "sources",
            "config_path": get_settings().sources_config,
            "count": len(configs),
            "sources": [
                {
                    "key": config.key,
                    "adapter": config.adapter,
                    "source_type": config.source_type.value,
                    "publisher": config.publisher,
                    "enabled": config.enabled,
                    "confidence": config.confidence,
                }
                for config in configs
            ],
        }
    )
    return 0


def cmd_check_sources(args: argparse.Namespace) -> int:
    """Probe every configured source and say which can be enabled.

    This is the verification step ``config/sources.json`` demands, automated. Exits
    non-zero when nothing is usable, so it can gate a deploy.
    """
    from app.services.source_health import check_all, summarize

    results = check_all(only=args.source or None)
    summary = summarize(results)

    if args.json:
        _print({"command": "check-sources", **summary,
                "sources": [r.as_dict() for r in results]})
        return 0 if summary["usable"] else 1

    print(f"Checked {summary['checked']} configured source(s).\n")
    for health in results:
        flag = "OK  " if health.usable else "FAIL"
        state = "enabled" if health.enabled else "disabled"
        print(f"[{flag}] {health.key}  ({health.adapter}, {health.source_type}, {state})")
        print(f"       target:  {health.target or '-'}")
        print(f"       verdict: {health.verdict.value} - {health.detail}")
        if health.sample_titles:
            for title in health.sample_titles:
                print(f"       sample:  {title}")
        print(f"       advice:  {health.advice}")
        print()
    print("SUMMARY")
    for verdict, count in sorted(summary["verdicts"].items()):
        print(f"  {verdict}: {count}")
    print(f"\n{summary['conclusion']}")
    return 0 if summary["usable"] else 1


def cmd_status(_: argparse.Namespace) -> int:
    """Configuration and database summary. Useful as a deployment smoke check."""
    from app.services.rescore import classification_counts, eligible_count

    settings = get_settings()
    payload: dict[str, Any] = {
        "command": "status",
        "environment": settings.app_env,
        "ai_provider": settings.ai_provider,
        "rule_based_fallback": settings.ai_provider == "rule_based",
        "top_n": settings.top_n,
        "min_qualifying_score": settings.min_qualifying_score,
        "sectors": settings.sectors,
        "database_reachable": check_database(),
    }
    payload["relevance_filter_enabled"] = settings.relevance_enabled
    payload["scheduler_enabled"] = settings.scheduler_enabled
    payload["api_authenticated"] = bool(settings.api_key)
    if payload["database_reachable"]:
        from sqlalchemy import func, select

        from app.models import Company, Contact, Opportunity, Signal, Source

        with session_scope() as session:
            payload["eligible_opportunities"] = eligible_count(session)
            payload["classification_counts"] = classification_counts(session)
            payload["counts"] = {
                "companies": int(session.scalar(select(func.count(Company.id))) or 0),
                "contacts": int(session.scalar(select(func.count(Contact.id))) or 0),
                "signals": int(session.scalar(select(func.count(Signal.id))) or 0),
                "sources": int(session.scalar(select(func.count(Source.id))) or 0),
                "opportunities": int(session.scalar(select(func.count(Opportunity.id))) or 0),
            }
            payload["sources_by_provenance"] = {
                mode: int(count)
                for mode, count in session.execute(
                    select(Source.ingest_mode, func.count(Source.id)).group_by(
                        Source.ingest_mode
                    )
                ).all()
            }
    _print(payload)
    return 0 if payload["database_reachable"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paradigm", description="PARADIGM INTELLIGENCE operations."
    )
    parser.add_argument("--log-level", default=None, help="Override LOG_LEVEL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Fetch sources, extract, score.")
    ingest.add_argument(
        "--source", action="append", help="Source key to run. Repeatable. Omit for all enabled."
    )
    ingest.add_argument("--since", help="ISO-8601 lower bound on publication date.")
    ingest.set_defaults(func=cmd_ingest)

    discover = subparsers.add_parser(
        "discover-contacts", help="Read contacts from configured public company pages."
    )
    discover.add_argument(
        "--source", action="append", help="Contact source key. Repeatable."
    )
    discover.set_defaults(func=cmd_discover_contacts)

    cycle = subparsers.add_parser(
        "cycle", help="Full refresh: ingest, discover contacts, apply decay."
    )
    cycle.set_defaults(func=cmd_cycle)

    rescore = subparsers.add_parser("rescore", help="Re-apply score decay.")
    rescore.set_defaults(func=cmd_rescore)

    brief = subparsers.add_parser("brief", help="Print today's daily brief as JSON.")
    brief.add_argument("--window-hours", type=int, default=None)
    brief.set_defaults(func=cmd_brief)

    sources = subparsers.add_parser("sources", help="List configured sources.")
    sources.set_defaults(func=cmd_sources)

    check = subparsers.add_parser(
        "check-sources",
        help="Probe configured sources and report which are usable from this host.",
    )
    check.add_argument("--source", action="append", help="Source key to check. Repeatable.")
    check.add_argument("--json", action="store_true", help="Machine-readable output.")
    check.set_defaults(func=cmd_check_sources)

    status = subparsers.add_parser("status", help="Show configuration and counts.")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    # Diagnostics to stderr, data to stdout, so every command is pipeable.
    configure_logging(
        args.log_level or settings.log_level, settings.log_json, stream=sys.stderr
    )

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        logger.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        logger.exception("command failed")
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
