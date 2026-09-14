"""Company responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel
from app.schemas.opportunity import ContactRef


class CompanyOut(ORMModel):
    id: uuid.UUID
    name: str
    normalized_name: str
    domain: str | None = None
    website: str | None = None
    sector: str | None = None
    city: str | None = None
    description: str | None = None
    size_band: str
    event_potential_score: int | None = None
    created_at: datetime
    updated_at: datetime


class CompanyDetail(CompanyOut):
    contacts: list[ContactRef] = Field(default_factory=list)
    signal_count: int = 0
    opportunity_count: int = 0
