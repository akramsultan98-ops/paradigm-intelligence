"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health
from app.api.router import api_router
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

DESCRIPTION = """\
Corporate event opportunity intelligence for PARADIGM, Egypt.

One job: maintain a ranked list of the 50 corporate sales opportunities most
likely to generate event business.

Every opportunity carries an `assertion_level` of FACT, INFERENCE or PREDICTION.
A predicted event is never presented as confirmed. Nothing is invented — missing
evidence is recorded as UNKNOWN.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger.info(
        "starting PARADIGM INTELLIGENCE",
        extra={
            "version": __version__,
            "environment": settings.app_env,
            "ai_provider": settings.ai_provider,
            "top_n": settings.top_n,
            "min_qualifying_score": settings.min_qualifying_score,
        },
    )
    if settings.ai_provider == "rule_based":
        logger.warning(
            "AI_PROVIDER is rule_based: extraction is a deterministic keyword "
            "matcher, not AI. Do not rank production opportunities on this."
        )
    yield
    logger.info("shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PARADIGM INTELLIGENCE",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
