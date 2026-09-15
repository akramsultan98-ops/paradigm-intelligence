"""Outreach tracking (Priority 5).

Deliberately thin. This is not a CRM and must not grow into one: it records what
was done, when, and what happens next, so an Account Manager can build a
relationship with a company over months — including when the event that surfaced
it was already contracted.

Each logged action does two things: appends to ``outreach_log`` (the history) and
updates the denormalised current state on the contact, so a company profile renders
without walking the log.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import OutreachAction, OutreachStatus
from app.models import Company, Contact, Opportunity, OutreachLog

logger = logging.getLogger(__name__)

#: Status each action implies when the caller does not state one. An attempted
#: call is not a conversation, so it does not claim to be.
_IMPLIED_STATUS: dict[OutreachAction, OutreachStatus] = {
    OutreachAction.EMAIL_SENT: OutreachStatus.CONTACTED,
    OutreachAction.CALL_MADE: OutreachStatus.CONTACTED,
    OutreachAction.CALL_ATTEMPTED: OutreachStatus.ATTEMPTED,
    OutreachAction.LINKEDIN_MESSAGE: OutreachStatus.CONTACTED,
    OutreachAction.MEETING_HELD: OutreachStatus.IN_DISCUSSION,
    OutreachAction.PROPOSAL_SENT: OutreachStatus.PROPOSAL_SENT,
    OutreachAction.INTRODUCTION_REQUESTED: OutreachStatus.ATTEMPTED,
    OutreachAction.NOTE: OutreachStatus.NOT_CONTACTED,
}

#: Actions that represent real two-way contact, so they set "last contacted".
#: A note to self does not, and neither does an unanswered call.
_COUNTS_AS_CONTACT = frozenset(
    {
        OutreachAction.EMAIL_SENT,
        OutreachAction.CALL_MADE,
        OutreachAction.LINKEDIN_MESSAGE,
        OutreachAction.MEETING_HELD,
        OutreachAction.PROPOSAL_SENT,
    }
)


@dataclass(slots=True)
class OutreachInput:
    """One outreach action to record."""

    action: OutreachAction
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    status_after: OutreachStatus | None = None
    occurred_at: datetime | None = None
    next_follow_up_on: date | None = None
    note: str | None = None
    logged_by: str | None = None


def log_outreach(
    session: Session, *, company: Company, payload: OutreachInput
) -> OutreachLog:
    """Record an action and roll the contact's current state forward.

    ``status_after`` is honoured when given; otherwise it is implied from the
    action. The note is trimmed to ``None`` when blank, because the database
    rejects an empty string rather than storing meaningless whitespace.
    """
    status = payload.status_after or _IMPLIED_STATUS[payload.action]
    occurred = payload.occurred_at or datetime.now(UTC)
    note = (payload.note or "").strip() or None

    contact: Contact | None = None
    if payload.contact_id is not None:
        contact = session.get(Contact, payload.contact_id)
        if contact is None or contact.company_id != company.id:
            raise ValueError("contact does not belong to this company")

    if payload.opportunity_id is not None:
        opportunity = session.get(Opportunity, payload.opportunity_id)
        if opportunity is None or opportunity.company_id != company.id:
            raise ValueError("opportunity does not belong to this company")

    entry = OutreachLog(
        company_id=company.id,
        contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id,
        action=payload.action,
        status_after=status,
        occurred_at=occurred,
        next_follow_up_on=payload.next_follow_up_on,
        note=note,
        logged_by=payload.logged_by,
    )
    session.add(entry)

    if contact is not None:
        # A NOTE must not silently reset a relationship that has progressed.
        if payload.action is not OutreachAction.NOTE or payload.status_after is not None:
            contact.outreach_status = status
        if payload.action in _COUNTS_AS_CONTACT:
            contact.last_contacted_at = occurred
        if payload.next_follow_up_on is not None:
            contact.next_follow_up_on = payload.next_follow_up_on

    session.flush()
    logger.info(
        "outreach logged",
        extra={
            "company_name": company.name,
            "action": payload.action.value,
            "status_after": status.value,
            "has_contact": contact is not None,
        },
    )
    return entry


def history_for_company(
    session: Session, company_id: object, *, limit: int = 50
) -> list[OutreachLog]:
    """A company's outreach timeline, newest first."""
    return list(
        session.scalars(
            select(OutreachLog)
            .options(joinedload(OutreachLog.contact), joinedload(OutreachLog.opportunity))
            .where(OutreachLog.company_id == company_id)
            .order_by(desc(OutreachLog.occurred_at))
            .limit(limit)
        ).unique().all()
    )


@dataclass(slots=True)
class CompanyOutreachState:
    """Company-level roll-up, for the profile header."""

    status: OutreachStatus
    last_contacted_at: datetime | None
    next_follow_up_on: date | None
    interactions: int
    overdue: bool


def company_state(session: Session, company_id: object) -> CompanyOutreachState:
    """Current relationship state for a company.

    The company's status is the furthest-progressed status among its contacts —
    one booked meeting means the account is in discussion, whatever the other
    contacts say.
    """
    progression = list(OutreachStatus)
    contacts = list(
        session.scalars(select(Contact).where(Contact.company_id == company_id)).all()
    )
    entries = list(
        session.scalars(
            select(OutreachLog).where(OutreachLog.company_id == company_id)
        ).all()
    )

    status = OutreachStatus.NOT_CONTACTED
    for contact in contacts:
        if progression.index(contact.outreach_status) > progression.index(status):
            status = contact.outreach_status
    # An action logged against the company with no contact attached still counts.
    for entry in entries:
        if progression.index(entry.status_after) > progression.index(status):
            status = entry.status_after

    last_contacted = max(
        (entry.occurred_at for entry in entries if entry.action in _COUNTS_AS_CONTACT),
        default=None,
    )
    follow_ups = [
        entry.next_follow_up_on for entry in entries if entry.next_follow_up_on is not None
    ]
    next_follow_up = min(follow_ups) if follow_ups else None

    return CompanyOutreachState(
        status=status,
        last_contacted_at=last_contacted,
        next_follow_up_on=next_follow_up,
        interactions=len(entries),
        overdue=next_follow_up is not None and next_follow_up < datetime.now(UTC).date(),
    )


@dataclass(frozen=True, slots=True)
class DueFollowUp:
    """One thing owed a next step."""

    company: Company
    due_on: date
    #: ``None`` for a follow-up promised on the account rather than to a person —
    #: which is the normal case early on, before anybody is named.
    contact: Contact | None


def due_follow_ups(session: Session, *, on: date | None = None) -> list[DueFollowUp]:
    """Everything whose follow-up date has arrived or passed, oldest first.

    Two kinds, and both have to appear. A follow-up promised to a named person is
    held on the contact. A follow-up promised on the account — "come back after the
    show" — has no contact to hold it, so it is read from the account's own most
    recent unattached log entry. Only showing the first kind would silently drop
    exactly the accounts being worked without a named contact yet.
    """
    on = on or datetime.now(UTC).date()

    due = [
        DueFollowUp(company=contact.company, due_on=contact.next_follow_up_on, contact=contact)
        for contact in session.scalars(
            select(Contact)
            .options(joinedload(Contact.company))
            .where(Contact.next_follow_up_on.is_not(None), Contact.next_follow_up_on <= on)
        ).unique().all()
        if contact.next_follow_up_on is not None
    ]

    # The latest account-level promise per company: the most recent unattached entry
    # that set a date is the one that still stands.
    latest: dict[object, OutreachLog] = {}
    for entry in session.scalars(
        select(OutreachLog)
        .options(joinedload(OutreachLog.company))
        .where(OutreachLog.contact_id.is_(None), OutreachLog.next_follow_up_on.is_not(None))
        .order_by(OutreachLog.occurred_at)
    ).unique().all():
        latest[entry.company_id] = entry
    due.extend(
        DueFollowUp(company=entry.company, due_on=entry.next_follow_up_on, contact=None)
        for entry in latest.values()
        if entry.next_follow_up_on is not None and entry.next_follow_up_on <= on
    )

    return sorted(due, key=lambda item: (item.due_on, item.company.name))
