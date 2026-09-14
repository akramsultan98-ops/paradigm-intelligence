"""API router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import brief, companies, ingest, opportunities

api_router = APIRouter()
api_router.include_router(opportunities.router)
api_router.include_router(companies.router)
api_router.include_router(brief.router)
api_router.include_router(ingest.router)
