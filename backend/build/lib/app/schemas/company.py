"""Company responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel
from app.schemas.opportunity import ContactRef, OpportunityOut, SignalRef


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


class CompanyRelative(ORMModel):
    """A parent or subsidiary link (spec §28). A link, never a merge."""

    id: uuid.UUID
    name: str
    sector: str | None = None


class CompanyDetail(CompanyOut):
    """The lightweight company profile. Deliberately not a CRM record."""

    contacts: list[ContactRef] = Field(default_factory=list)
    recent_signals: list[SignalRef] = Field(default_factory=list)
    opportunities: list[OpportunityOut] = Field(default_factory=list)
    parent: CompanyRelative | None = None
    subsidiaries: list[CompanyRelative] = Field(default_factory=list)
    signal_count: int = 0
    opportunity_count: int = 0
    qualified_opportunity_count: int = 0
    #: Best opportunity score currently open at this company.
    account_score: int | None = None
    #: Signals that are themselves past events, which is the only event history
    #: we can honestly claim (spec §24: "when available").
    event_history: list[SignalRef] = Field(default_factory=list)
