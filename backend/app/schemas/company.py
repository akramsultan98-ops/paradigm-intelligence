"""Company responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel
from app.schemas.opportunity import ContactRef, OpportunityOut, SignalRef
from app.schemas.outreach import (
    ContactIntelligence,
    DepartmentSuggestion,
    OutreachLogOut,
    OutreachStateOut,
    RankedContactOut,
)


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
    """The contact-first account profile. Deliberately not a CRM record.

    Ordered the way an Account Manager reads it: who the company is, why it is a
    target, what events are in play, then who to contact and what to say. The
    contact block is first-class rather than an afterthought, because a target
    nobody can reach is not a target.
    """

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

    # --- contact intelligence (Priorities 1 and 2) ----------------------
    #: What we hold, counted honestly. ``has_any_route`` false means UNKNOWN.
    contact_intelligence: ContactIntelligence = Field(default_factory=ContactIntelligence)
    #: This company's contacts ranked for its best live opportunity — who to call
    #: first, and why that department.
    recommended_contacts: list[RankedContactOut] = Field(default_factory=list)
    #: Which departments matter for the events this company actually has. Derived
    #: from its own opportunity types, so nothing is forced onto every company.
    relevant_departments: list[DepartmentSuggestion] = Field(default_factory=list)
    #: The opportunity the routing above was computed for, when there is one.
    routing_opportunity_id: uuid.UUID | None = None

    # --- timing (Priority 4) -------------------------------------------
    #: Opportunities still worth bidding for.
    immediate_opportunity_count: int = 0
    #: Events likely already contracted, valuable as account relationships.
    future_account_opportunity_count: int = 0
    #: Past events. Research only, never ranked as if upcoming.
    historical_opportunity_count: int = 0

    # --- outreach workflow (Priority 5) --------------------------------
    outreach: OutreachStateOut | None = None
    outreach_history: list[OutreachLogOut] = Field(default_factory=list)
    #: What to do next, in one sentence. Derived from timing, contact state and
    #: outreach history — never a generic template.
    recommended_first_action: str | None = None
