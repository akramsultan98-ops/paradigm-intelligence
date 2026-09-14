"""Logging guards.

``logging`` raises ``KeyError`` when ``extra=`` carries a key that clashes with a
built-in ``LogRecord`` attribute. That turns a log line into a crash at the call
site, and it is invisible until the branch runs — which is exactly how it was
found. This scans the source so it cannot come back.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from app.logging_config import RESERVED_LOG_RECORD_KEYS, JsonFormatter, configure_logging

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
_EXTRA_KEYS = re.compile(r"extra=\{(.*?)\}", re.S)
_KEY = re.compile(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:')


def _without_comments(source: str) -> str:
    """Drop comment-only lines.

    ``logging_config.py`` documents the hazard in prose, and the scanner would
    otherwise flag that documentation as an offender.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def _extra_keys_in(path: Path) -> set[str]:
    keys: set[str] = set()
    source = _without_comments(path.read_text(encoding="utf-8"))
    for block in _EXTRA_KEYS.findall(source):
        keys.update(_KEY.findall(block))
    return keys


def test_no_logging_call_uses_a_reserved_key() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        clashes = _extra_keys_in(path) & RESERVED_LOG_RECORD_KEYS
        if clashes:
            offenders[str(path.relative_to(APP_ROOT))] = clashes
    assert not offenders, (
        f"these extra= keys clash with LogRecord attributes and will raise: {offenders}"
    )


def test_reserved_set_matches_a_real_log_record() -> None:
    """Keep the list honest against the running interpreter."""
    record = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
    actual = {key for key in vars(record) if not key.startswith("_")}
    missing = actual - RESERVED_LOG_RECORD_KEYS
    assert not missing, f"RESERVED_LOG_RECORD_KEYS is missing: {sorted(missing)}"


def test_a_reserved_key_really_does_raise() -> None:
    """The failure mode this guards against, demonstrated."""
    # error(), not info(): a logger below its threshold never builds the record
    # and so never raises, which would make this test prove nothing.
    with pytest.raises(KeyError):
        logging.getLogger("test.reserved").error("boom", extra={"name": "x"})


def test_json_formatter_includes_extra_fields() -> None:
    import json

    record = logging.LogRecord("app.test", logging.INFO, "p", 1, "hello", None, None)
    record.company_name = "Elsewedy Electric"
    record.score = 88
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["company_name"] == "Elsewedy Electric"
    assert payload["score"] == 88


def test_configure_logging_installs_one_handler() -> None:
    configure_logging("DEBUG", as_json=True)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG
    configure_logging("INFO", as_json=False)
    assert len(logging.getLogger().handlers) == 1
