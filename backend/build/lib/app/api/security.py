"""Access control (spec §40).

A single shared API key, supplied as ``X-API-Key`` (or a bearer token). That is
the right weight for V1: the product is an internal dashboard for one sales team,
and per-user accounts would be scope the brief explicitly rules out.

When ``API_KEY`` is unset the API is open and says so loudly at startup. That
keeps local development frictionless without ever being the silent default in
production: ``require_api_key`` refuses to run open in a non-development
environment.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _extract(api_key_header: str | None, authorization: str | None) -> str | None:
    if api_key_header:
        return api_key_header.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """Reject requests without the configured key.

    No key configured means open access, which is fine in development and a
    mistake anywhere else — so it is refused outright outside development rather
    than quietly allowed.
    """
    expected = (settings.api_key or "").strip()

    if not expected:
        if settings.app_env.lower() not in {"development", "dev", "test", "local"}:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "API_KEY is not configured. Set it, or run with APP_ENV=development.",
            )
        return

    supplied = _extract(x_api_key, authorization)
    if not supplied:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing API key. Send it as the X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Constant-time comparison: a plain == leaks key material through timing.
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid API key.")
