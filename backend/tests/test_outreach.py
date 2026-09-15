"""Outreach tracking (Priority 5).

What has to hold: an Account Manager can record what was actually done, see it
again later, and be reminded when to come back — including on an account whose
event is already contracted, which is the case the whole feature exists for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.enums import (
    ContactKind,
    Department,
    OpportunityTiming,
    OpportunityType,
    OutreachAction,
    OutreachStatus,
)
from app.services.outreach import (
    OutreachInput,
    company_state,
    due_follow_ups,
    history_for_company,
    log_outreach,
)
from tests.conftest import requires_db
from tests.factories import make_company, make_contact, make_opportunity

pytestmark = requires_db


def _log(session, company, **kwargs):
    return log_outreach(session, company=company, payload=OutreachInput(**kwargs))


# --- recording an action -------------------------------------------------


def test_an_email_moves_the_contact_to_contacted(session) -> None:
    company = make_company(session)
    contact = make_contact(session, company)

    entry = _log(
        session,
        company,
        action=OutreachAction.EMAIL_SENT,
        contact_id=contact.id,
        note="Introduced Paradigm, asked who owns the events calendar.",
        logged_by="account.manager",
    )

    assert entry.status_after is OutreachStatus.CONTACTED
    assert contact.outreach_status is OutreachStatus.CONTACTED
    assert contact.last_contacted_at is not None


def test_an_unanswered_call_is_attempted_not_contacted(session) -> None:
    """Claiming contact that did not happen would corrupt the working list."""
    company = make_company(session)
    contact = make_contact(session, company)

    _log(session, company, action=OutreachAction.CALL_ATTEMPTED, contact_id=contact.id)

    assert contact.outreach_status is OutreachStatus.ATTEMPTED
    assert contact.last_contacted_at is None


def test_a_note_does_not_undo_a_relationship_that_has_progressed(session) -> None:
    company = make_company(session)
    contact = make_contact(session, company)

    _log(session, company, action=OutreachAction.MEETING_HELD, contact_id=contact.id)
    assert contact.outreach_status is OutreachStatus.IN_DISCUSSION

    _log(
        session,
        company,
        action=OutreachAction.NOTE,
        contact_id=contact.id,
        note="Their agency handles this year's show.",
    )
    assert contact.outreach_status is OutreachStatus.IN_DISCUSSION


def test_an_explicit_status_is_honoured_over_the_implied_one(session) -> None:
    company = make_company(session)
    contact = make_contact(session, company)

    _log(
        session,
        company,
        action=OutreachAction.NOTE,
        contact_id=contact.id,
        status_after=OutreachStatus.NURTURE,
        note="Event is contracted elsewhere; revisit for next year's calendar.",
    )
    assert contact.outreach_status is OutreachStatus.NURTURE


def test_an_account_can_be_worked_before_a_person_is_known(session) -> None:
    """The case that matters: a company with no named contact yet."""
    company = make_company(session)
    entry = _log(
        session,
        company,
        action=OutreachAction.EMAIL_SENT,
        note="Sent to the published press inbox.",
    )
    assert entry.contact_id is None
    assert company_state(session, company.id).status is OutreachStatus.CONTACTED


def test_a_blank_note_is_stored_as_nothing(session) -> None:
    """The database rejects an empty string rather than storing whitespace."""
    company = make_company(session)
    entry = _log(session, company, action=OutreachAction.NOTE, note="   ")
    assert entry.note is None


# --- integrity ----------------------------------------------------------


def test_a_contact_from_another_company_is_refused(session) -> None:
    company = make_company(session, "Alpha Industries")
    other = make_company(session, "Beta Holdings")
    stranger = make_contact(session, other)

    with pytest.raises(ValueError, match="contact does not belong"):
        _log(session, company, action=OutreachAction.EMAIL_SENT, contact_id=stranger.id)


def test_an_opportunity_from_another_company_is_refused(session) -> None:
    company = make_company(session, "Alpha Industries")
    elsewhere = make_opportunity(session, company_name="Beta Holdings")

    with pytest.raises(ValueError, match="opportunity does not belong"):
        _log(
            session,
            company,
            action=OutreachAction.NOTE,
            opportunity_id=elsewhere.id,
            note="Wrong company.",
        )


# --- reading it back ----------------------------------------------------


def test_history_is_newest_first(session) -> None:
    company = make_company(session)
    now = datetime.now(UTC)
    for days, note in ((10, "oldest"), (1, "newest"), (5, "middle")):
        _log(
            session,
            company,
            action=OutreachAction.NOTE,
            occurred_at=now - timedelta(days=days),
            note=note,
        )
    assert [entry.note for entry in history_for_company(session, company.id)] == [
        "newest",
        "middle",
        "oldest",
    ]


def test_company_status_is_the_furthest_progressed_contact(session) -> None:
    """One booked meeting means the account is in discussion, whatever else says."""
    company = make_company(session)
    quiet = make_contact(session, company, name="Mona Farid", email="mona@example.com")
    engaged = make_contact(
        session,
        company,
        name="Youssef Kamal",
        email="youssef@example.com",
        department=Department.EVENTS,
    )

    _log(session, company, action=OutreachAction.CALL_ATTEMPTED, contact_id=quiet.id)
    _log(session, company, action=OutreachAction.MEETING_HELD, contact_id=engaged.id)

    state = company_state(session, company.id)
    assert state.status is OutreachStatus.IN_DISCUSSION
    assert state.interactions == 2
    assert state.last_contacted_at is not None


def test_state_reports_the_earliest_follow_up_and_whether_it_is_overdue(session) -> None:
    company = make_company(session)
    today = datetime.now(UTC).date()
    _log(
        session,
        company,
        action=OutreachAction.EMAIL_SENT,
        next_follow_up_on=today + timedelta(days=14),
        note="Later.",
    )
    _log(
        session,
        company,
        action=OutreachAction.NOTE,
        next_follow_up_on=today - timedelta(days=2),
        note="Sooner, and already late.",
    )

    state = company_state(session, company.id)
    assert state.next_follow_up_on == today - timedelta(days=2)
    assert state.overdue is True


def test_an_untouched_company_reports_not_contacted(session) -> None:
    company = make_company(session)
    state = company_state(session, company.id)
    assert state.status is OutreachStatus.NOT_CONTACTED
    assert state.interactions == 0
    assert state.overdue is False


# --- the working list ---------------------------------------------------


def test_due_follow_ups_lists_today_and_earlier_only(session) -> None:
    company = make_company(session)
    today = date.today()
    due = make_contact(session, company, name="Due Today", email="due@example.com")
    overdue = make_contact(
        session,
        company,
        name="Overdue Person",
        email="overdue@example.com",
        department=Department.EVENTS,
    )
    later = make_contact(
        session,
        company,
        name="Later Person",
        email="later@example.com",
        department=Department.PR,
    )
    due.next_follow_up_on = today
    overdue.next_follow_up_on = today - timedelta(days=9)
    later.next_follow_up_on = today + timedelta(days=9)
    session.flush()

    names = [contact.name for contact in due_follow_ups(session, on=today)]
    assert names == ["Overdue Person", "Due Today"]


def test_a_contracted_event_still_supports_relationship_building(session) -> None:
    """Priority 5's closing requirement, end to end.

    An event two weeks out is FUTURE_ACCOUNT, and the account can still be worked:
    logged, statused, and scheduled for the follow-up that matters.
    """
    company = make_company(session, "Elsewedy Electric")
    opportunity = make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=14),
    )
    assert opportunity.timing_class is OpportunityTiming.FUTURE_ACCOUNT

    contact = make_contact(
        session,
        company,
        name="Elsewedy Electric Corporate Communications (department route)",
        job_title=None,
        department=Department.CORPORATE_COMMUNICATIONS,
        email="media@example.com",
        contact_kind=ContactKind.DEPARTMENT_ROUTE,
    )
    _log(
        session,
        company,
        action=OutreachAction.EMAIL_SENT,
        contact_id=contact.id,
        opportunity_id=opportunity.id,
        status_after=OutreachStatus.NURTURE,
        next_follow_up_on=date.today() + timedelta(days=30),
        note="This show is contracted. Asked to be considered for the 2027 calendar.",
    )

    state = company_state(session, company.id)
    assert state.status is OutreachStatus.NURTURE
    assert state.next_follow_up_on == date.today() + timedelta(days=30)
    assert contact.next_follow_up_on == date.today() + timedelta(days=30)
