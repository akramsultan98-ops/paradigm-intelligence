"""Structured logging.

Human-readable lines in development, single-line JSON in production so the host
platform can index them.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

#: Attributes the stdlib puts on every LogRecord. Passing any of these through
#: ``extra=`` makes ``logging`` raise ``KeyError`` at the call site, so a stray
#: ``extra={"name": ...}`` is a crash, not a cosmetic problem. ``tests/test_logging.py``
#: guards against reintroducing one.
RESERVED_LOG_RECORD_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record, including any extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in RESERVED_LOG_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str = "INFO", as_json: bool = False, stream: TextIO | None = None
) -> None:
    """Install a single handler on the root logger.

    Defaults to stdout, which is what a server wants — the platform collects it as
    the log stream. The CLI passes stderr instead, so that command output stays
    machine-readable: ``check-sources --json | jq`` has to receive JSON and nothing
    else.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # SQLAlchemy and httpx are chatty at INFO and say nothing we need.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
