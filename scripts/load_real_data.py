#!/usr/bin/env python3
"""Load the curated real dataset in ``data/real/`` through the analyst intake API.

Why a script rather than a fixture loader: these entries go through exactly the
same pipeline an automated source would, so they are relevance-filtered, scored
and timed by the production code. They carry ANALYST provenance because a person
read the cited page and wrote the digest.

Usage (with the API running):

    python scripts/load_real_data.py --base-url http://127.0.0.1:8000

Idempotent: re-running updates the same signals rather than duplicating them,
because dedupe is on the source URL and the signal's dedupe key.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "real"


def _post(base_url: str, path: str, payload: dict, api_key: str | None) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            **({"X-API-Key": api_key} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise SystemExit(f"{path} failed with {error.code}: {body}") from error


def load_signals(base_url: str, api_key: str | None) -> None:
    for path in sorted(DATA_DIR.glob("signals-*.json")):
        payload = json.loads(path.read_text())
        print(f"\n{path.name}: {len(payload['signals'])} signals")
        for entry in payload["signals"]:
            name = entry["extraction"]["company_name"]
            result = _post(base_url, "/api/v1/ingest/signals", entry, api_key)
            created = result["opportunities_created"] + result["opportunities_updated"]
            if created:
                verdict = "opportunity"
            elif result["filtered_irrelevant"]:
                verdict = "filtered"
            elif result["duplicates_skipped"]:
                verdict = "duplicate"
            elif result["no_event_implication"]:
                verdict = "no event"
            else:
                verdict = "no result"
            errors = f" {result['errors']}" if result["errors"] else ""
            print(f"  {verdict:11} {name[:44]:44}{errors}")


def load_contacts(base_url: str, api_key: str | None) -> None:
    for path in sorted(DATA_DIR.glob("contacts-*.json")):
        payload = json.loads(path.read_text())
        print(f"\n{path.name}: {len(payload['contacts'])} contact routes")
        result = _post(
            base_url, "/api/v1/ingest/contacts", {"contacts": payload["contacts"]}, api_key
        )
        print(f"  {json.dumps(result)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY") or None)
    parser.add_argument("--signals-only", action="store_true")
    parser.add_argument("--contacts-only", action="store_true")
    args = parser.parse_args(argv)

    if not args.contacts_only:
        load_signals(args.base_url, args.api_key)
    if not args.signals_only:
        load_contacts(args.base_url, args.api_key)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
