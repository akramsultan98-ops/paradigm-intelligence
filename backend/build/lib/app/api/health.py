"""Health and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.config import get_settings
from app.db import check_database
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    """Is the process up? Deliberately touches nothing external."""
    settings = get_settings()
    return HealthResponse(status="ok", version=__version__, environment=settings.app_env)


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    """Can the process serve traffic?

    Returns 503 when the database is unreachable, so an orchestrator takes the
    instance out of rotation instead of sending it requests that will fail.
    """
    settings = get_settings()
    database_ok = check_database()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if database_ok else "degraded",
        database=database_ok,
        ai_provider=settings.ai_provider,
        rule_based_fallback=settings.ai_provider == "rule_based",
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Convenience alias for ``/health/live``."""
    return liveness()
