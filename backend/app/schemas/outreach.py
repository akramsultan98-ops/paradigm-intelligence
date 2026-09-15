"""Contact intelligence and outreach responses (Priorities 1, 2 and 5).

This is the layer that turns a scored opportunity into something an Account
Manager can act on: who to approach, why them, what to say first, and what was
said last.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    Department,
    OpportunityType,
    OutreachAction,
    OutreachStatus,
)
from app.schemas.common import ORMModel
from app.schemas.opportunity import ContactRef


class RankedContactOut(BaseModel):
    """A contact positioned for one specific opportunity.

    The ranking is the point: the same company's contacts come out in a different
    order for an exhibition than for a town hall.
    """

    contact: ContactRef
    rank: int
    #: 0 means this department is not a usual route for this kind of event. Not a
    #: rejection — it simply ranks below the ones that are.
    department_fit: int
    is_preferred_department: bool
    #: Why this department, in an Account Manager's terms.
    reason: str


class DepartmentSuggestion(BaseModel):
    """Where to aim when no contact is known yet.

    Advisory only, and never written to the company: it says which department to
    look for, it does not invent a person to look for.
    """

    department: Department
    why: str
    #: True when we already hold a contact in this department.
    have_contact: bool = False


class ContactIntelligence(BaseModel):
    """What we actually know about how to reach this company.

    Counts, not claims. ``has_any_route`` is the honest headline: when it is
    false, the profile says UNKNOWN rather than filling the space.
    """

    total: int = 0
    named_individuals: int = 0
    department_routes: int = 0
    unknown_kind: int = 0
    with_email: int = 0
    with_phone: int = 0
    with_linkedin: int = 0
    #: Contacts whose email is PUBLIC or VERIFIED — i.e. read from a page, not
    #: worked out from a pattern.
    with_published_email: int = 0
    has_any_route: bool = False
    #: Oldest and newest verification dates across the contacts we hold.
    last_verified_at: datetime | None = None
    #: Departments we hold nothing for but which this company's events would need.
    missing_departments: list[Department] = Field(default_factory=list)


class OutreachLogOut(ORMModel):
    """One recorded interaction."""

    id: uuid.UUID
    action: OutreachAction
    status_after: OutreachStatus
    occurred_at: datetime
    next_follow_up_on: date | None = None
    note: str | None = None
    logged_by: str | None = None
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    #: Denormalised for display, so the timeline reads without extra lookups.
    contact_name: str | None = None
    opportunity_type: OpportunityType | None = None


class OutreachStateOut(BaseModel):
    """Company-level relationship state, for the profile header."""

    status: OutreachStatus
    last_contacted_at: datetime | None = None
    next_follow_up_on: date | None = None
    interactions: int = 0
    overdue: bool = False


class OutreachCreate(BaseModel):
    """Log an interaction against a company.

    Company-scoped rather than contact-scoped on purpose: an Account Manager can
    work an account before there is a named person to attach anything to.
    """

    action: OutreachAction
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    #: Omit to let the action imply it (an attempted call is not a conversation).
    status_after: OutreachStatus | None = None
    occurred_at: datetime | None = None
    next_follow_up_on: date | None = None
    note: str | None = Field(default=None, max_length=4000)
    logged_by: str | None = Field(default=None, max_length=120)

    model_config = ConfigDict(extra="forbid")


class FollowUpDue(BaseModel):
    """Something owed a next step, for the working list.

    ``contact`` is ``None`` when the follow-up was promised on the account rather
    than to a named person — the normal case before anybody is named, and one the
    list must not hide.
    """

    company_id: uuid.UUID
    company_name: str
    next_follow_up_on: date
    days_overdue: int
    contact: ContactRef | None = None
