"""Recurring ingestion (spec §46).

A single background thread on a timer. That is the whole design, and it is
deliberate: the brief rules out queues and extra infrastructure, and at this
volume a thread with a sleep does the job. Anyone who prefers cron can leave the
scheduler off and call the CLI instead — the cycle is the same code either way.

The cycle is ordered so each stage feeds the next:

1. ingest configured sources (new content becomes signals and opportunities)
2. discover contacts (and re-score the companies they belong to)
3. apply decay (so stale opportunities leave the Top 50)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.db import session_scope

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """What one cycle did. Held in memory for the status endpoint."""

    started_at: datetime
    finished_at: datetime | None = None
    ingestion: dict[str, Any] = field(default_factory=dict)
    contacts: dict[str, Any] = field(default_factory=dict)
    rescore: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "ingestion": self.ingestion,
            "contacts": self.contacts,
            "rescore": self.rescore,
            "error": self.error,
        }


def run_cycle(settings: Settings | None = None) -> CycleResult:
    """Run one full refresh. Safe to call concurrently with a request."""
    from app.services.contact_discovery import run_contact_discovery
    from app.services.pipeline import run_ingestion
    from app.services.rescore import rescore_all

    settings = settings or get_settings()
    result = CycleResult(started_at=datetime.now(UTC))
    logger.info("refresh cycle starting")

    try:
        result.ingestion = run_ingestion(settings=settings).as_dict()
        result.contacts = run_contact_discovery(settings=settings).as_dict()
        with session_scope() as session:
            result.rescore = rescore_all(session, settings=settings).as_dict()
    except Exception as exc:  # noqa: BLE001 - a failed cycle must not kill the thread
        result.error = f"{type(exc).__name__}: {exc}"
        logger.exception("refresh cycle failed")
    finally:
        result.finished_at = datetime.now(UTC)

    logger.info("refresh cycle finished", extra=result.as_dict())
    return result


class Scheduler:
    """Runs ``run_cycle`` on an interval in a daemon thread."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: CycleResult | None = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self.settings.scheduler_enabled

    @property
    def last_cycle(self) -> CycleResult | None:
        return self._last

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "interval_hours": self.settings.scheduler_interval_hours,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "cycle_in_progress": self._running,
            "last_cycle": self._last.as_dict() if self._last else None,
        }

    def _loop(self) -> None:
        # Wait before the first cycle so start-up is not competing with a full
        # ingestion run for the database and the network.
        if self._stop.wait(self.settings.scheduler_initial_delay_seconds):
            return
        interval = max(60.0, self.settings.scheduler_interval_hours * 3600.0)
        while not self._stop.is_set():
            self._running = True
            try:
                self._last = run_cycle(self.settings)
            finally:
                self._running = False
            if self._stop.wait(interval):
                return

    def start(self) -> bool:
        """Start the thread. Returns False when disabled or already running."""
        if not self.enabled:
            logger.info("scheduler disabled (SCHEDULER_ENABLED=false)")
            return False
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="paradigm-scheduler", daemon=True
        )
        self._thread.start()
        logger.info(
            "scheduler started",
            extra={
                "interval_hours": self.settings.scheduler_interval_hours,
                "initial_delay_seconds": self.settings.scheduler_initial_delay_seconds,
            },
        )
        return True

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the thread and wait briefly for it to finish."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("scheduler stopped")


#: One scheduler per process, owned by the application lifespan.
scheduler = Scheduler()
