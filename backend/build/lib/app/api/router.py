"""API router assembly."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import brief, companies, ingest, opportunities
from app.api.security import require_api_key

# Applied at the router, not per endpoint, so a new route cannot be added
# unprotected by omission. Health probes stay open — they are mounted separately.
api_router = APIRouter(dependencies=[Depends(require_api_key)])
api_router.include_router(opportunities.router)
api_router.include_router(companies.router)
api_router.include_router(brief.router)
api_router.include_router(ingest.router)
