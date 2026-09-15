"""The contact-first company profile (Priorities 1-5), through the API.

These are the nine acceptance questions expressed as tests: open a real company
and be able to answer who they are, why they matter, what events are in play, who
to contact, in which department, whether the contact is verified, where it came
from, what to say first, and when to follow up.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.enums import (
    ContactKind,
    Department,
    EmailStatus,
    OpportunityTiming,
    OpportunityType,
    OutreachAction,
    OutreachStatus,
)
from app.services import company_profile
from tests.conftest import requires_db
from tests.factories import make_company, make_contact, make_opportunity, make_source

pytestmark = requires_db


def _profile(client, company_id) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}")
    assert response.status_code == 200, response.text
    return response.json()


# --- Q1-Q3: who they are, why they matter, what events -------------------


def test_the_profile_carries_the_company_its_signals_and_its_events(
    client, session
) -> None:
    company = make_company(session, "Elsewedy Electric", sector="Industrial")
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=40),
    )
    session.commit()

    body = _profile(client, company.id)
    assert body["name"] == "Elsewedy Electric"
    assert body["sector"] == "Industrial"
    assert body["opportunity_count"] == 1
    assert body["opportunities"][0]["why_now"]
    assert body["recent_signals"]


# --- Q4-Q5: who to contact, and in which department ----------------------


def test_contacts_are_ranked_for_the_companys_own_event_type(client, session) -> None:
    company = make_company(session)
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.TOWN_HALL,
        event_date=date.today() + timedelta(days=60),
    )
    make_contact(
        session,
        company,
        name="Nour Adel",
        job_title="Marketing Manager",
        department=Department.MARKETING,
        email="nour@example.com",
    )
    make_contact(
        session,
        company,
        name="Hala Samir",
        job_title="HR Director",
        department=Department.HR,
        email="hala@example.com",
    )
    session.commit()

    body = _profile(client, company.id)
    ranked = body["recommended_contacts"]
    # An internal town hall is HR's, not marketing's.
    assert ranked[0]["contact"]["name"] == "Hala Samir"
    assert ranked[0]["is_preferred_department"] is True
    assert ranked[0]["reason"]
    assert ranked[1]["department_fit"] == 0
    assert body["routing_opportunity_id"]


def test_only_departments_this_companys_events_need_are_suggested(
    client, session
) -> None:
    """"Do not force every department onto every company." """
    company = make_company(session)
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=45),
    )
    session.commit()

    body = _profile(client, company.id)
    suggested = [entry["department"] for entry in body["relevant_departments"]]
    assert "MARKETING" in suggested
    assert "HR" not in suggested


# --- Q6-Q7: is it verified, and where did it come from -------------------


def test_every_contact_shows_its_kind_status_and_source(client, session) -> None:
    company = make_company(session)
    source = make_source(session, url="https://elsewedyelectric.test/en/media")
    make_contact(
        session,
        company,
        name="Elsewedy Electric Corporate Communications (department route)",
        job_title=None,
        department=Department.CORPORATE_COMMUNICATIONS,
        email="media@example.test",
        contact_kind=ContactKind.DEPARTMENT_ROUTE,
        phone="+20 2 2480 1200",
        source=source,
    )
    session.commit()

    contact = _profile(client, company.id)["contacts"][0]
    assert contact["contact_kind"] == "DEPARTMENT_ROUTE"
    assert contact["email_status"] == "PUBLIC"
    assert contact["phone"] == "+20 2 2480 1200"
    assert contact["source"]["source_url"] == "https://elsewedyelectric.test/en/media"
    assert contact["last_verified_at"]


def test_a_company_with_no_contacts_reports_no_route_rather_than_filling_in(
    client, session
) -> None:
    """The requirement: "If no public contact exists, display UNKNOWN clearly." """
    company = make_company(session)
    make_opportunity(session, company=company)
    session.commit()

    body = _profile(client, company.id)
    assert body["contacts"] == []
    assert body["recommended_contacts"] == []
    assert body["contact_intelligence"]["total"] == 0
    assert body["contact_intelligence"]["has_any_route"] is False
    assert body["contact_intelligence"]["missing_departments"]
    assert "No public contact is on file" in body["recommended_first_action"]


def test_contact_intelligence_counts_kinds_and_routes_honestly(client, session) -> None:
    company = make_company(session)
    make_contact(
        session,
        company,
        name="Named Person",
        email="named@example.test",
        contact_kind=ContactKind.NAMED_INDIVIDUAL,
    )
    make_contact(
        session,
        company,
        name="Press Route",
        job_title=None,
        department=Department.PR,
        email=None,
        email_status=EmailStatus.UNKNOWN,
        contact_kind=ContactKind.DEPARTMENT_ROUTE,
        phone="+20 2 2480 1200",
    )
    session.commit()

    intelligence = _profile(client, company.id)["contact_intelligence"]
    assert intelligence["total"] == 2
    assert intelligence["named_individuals"] == 1
    assert intelligence["department_routes"] == 1
    assert intelligence["with_email"] == 1
    assert intelligence["with_published_email"] == 1
    assert intelligence["with_phone"] == 1
    assert intelligence["has_any_route"] is True


# --- Q8: what to say first ----------------------------------------------


def test_the_first_action_tells_you_to_bid_on_a_biddable_event(client, session) -> None:
    company = make_company(session)
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=60),
    )
    make_contact(session, company, department=Department.MARKETING)
    session.commit()

    action = _profile(client, company.id)["recommended_first_action"]
    assert "still open" in action or "time to bid" in action
    assert "Ahmed Hassan" in action


def test_the_first_action_plays_a_contracted_event_as_a_relationship(
    client, session
) -> None:
    """The business objective, verbatim: an event in 2 weeks is still valuable."""
    company = make_company(session)
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=14),
    )
    make_contact(session, company, department=Department.MARKETING)
    session.commit()

    body = _profile(client, company.id)
    assert body["future_account_opportunity_count"] == 1
    action = body["recommended_first_action"]
    assert "already contracted" in action
    assert "next one" in action


def test_a_past_event_is_offered_as_research_not_as_a_live_job(client, session) -> None:
    company = make_company(session)
    make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.PROJECT_LAUNCH,
        event_date=date.today() - timedelta(days=45),
    )
    make_contact(session, company, department=Department.MARKETING)
    session.commit()

    body = _profile(client, company.id)
    assert body["historical_opportunity_count"] == 1
    assert body["opportunities"][0]["timing_class"] == "HISTORICAL"
    assert body["opportunities"][0]["timing_rationale"]
    assert "already happened" in body["recommended_first_action"]


# --- Q9: when to follow up ----------------------------------------------


def test_logging_outreach_updates_the_profile_and_the_working_list(
    client, session
) -> None:
    company = make_company(session)
    opportunity = make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=14),
    )
    contact = make_contact(session, company, department=Department.MARKETING)
    session.commit()

    follow_up = date.today() + timedelta(days=21)
    created = client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={
            "action": OutreachAction.EMAIL_SENT.value,
            "contact_id": str(contact.id),
            "opportunity_id": str(opportunity.id),
            "status_after": OutreachStatus.NURTURE.value,
            "next_follow_up_on": follow_up.isoformat(),
            "note": "Show is contracted. Asked about the 2027 calendar.",
            "logged_by": "account.manager",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["contact_name"] == contact.name
    assert created.json()["opportunity_type"] == "EXHIBITION"

    body = _profile(client, company.id)
    assert body["outreach"]["status"] == "NURTURE"
    assert body["outreach"]["next_follow_up_on"] == follow_up.isoformat()
    assert body["outreach"]["interactions"] == 1
    assert body["outreach"]["overdue"] is False
    assert body["outreach_history"][0]["note"].startswith("Show is contracted")
    assert body["contacts"][0]["next_follow_up_on"] == follow_up.isoformat()
    # And the first action now picks up from where the relationship is.
    assert "is being nurtured for a future cycle" in body["recommended_first_action"]


def test_the_follow_up_list_shows_who_is_owed_a_call(client, session) -> None:
    company = make_company(session, "Overdue Industries")
    contact = make_contact(session, company)
    session.commit()

    client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={
            "action": OutreachAction.CALL_MADE.value,
            "contact_id": str(contact.id),
            "next_follow_up_on": (date.today() - timedelta(days=3)).isoformat(),
            "note": "Asked to call back after their board meeting.",
        },
    )

    response = client.get("/api/v1/outreach/follow-ups")
    assert response.status_code == 200
    [due] = response.json()
    assert due["company_name"] == "Overdue Industries"
    assert due["days_overdue"] == 3
    assert due["contact"]["name"] == contact.name


def test_an_account_worked_without_a_named_contact_still_appears(client, session) -> None:
    """The case this feature exists for, through the API."""
    company = make_company(session, "Contracted Already Holdings")
    session.commit()

    client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={
            "action": "NOTE",
            "status_after": "NURTURE",
            "next_follow_up_on": (date.today() - timedelta(days=1)).isoformat(),
            "note": "Event is contracted elsewhere. Revisit for next year's calendar.",
        },
    )

    [due] = client.get("/api/v1/outreach/follow-ups").json()
    assert due["company_name"] == "Contracted Already Holdings"
    assert due["contact"] is None
    assert due["days_overdue"] == 1


def test_the_follow_up_list_can_look_ahead_without_changing_anything(
    client, session
) -> None:
    """"What is owed by Friday" — a read, not a reschedule."""
    company = make_company(session, "Later Holdings")
    session.commit()
    promised = date.today() + timedelta(days=10)
    client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={
            "action": "NOTE",
            "next_follow_up_on": promised.isoformat(),
            "note": "Come back after their board meeting.",
        },
    )

    assert client.get("/api/v1/outreach/follow-ups").json() == []

    ahead = client.get(
        "/api/v1/outreach/follow-ups",
        params={"as_of": (promised + timedelta(days=2)).isoformat()},
    ).json()
    assert [entry["company_name"] for entry in ahead] == ["Later Holdings"]
    assert ahead[0]["days_overdue"] == 2
    # And the promise itself is untouched.
    assert client.get("/api/v1/outreach/follow-ups").json() == []


def test_outreach_history_endpoint_mirrors_the_profile(client, session) -> None:
    company = make_company(session)
    session.commit()
    client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={"action": OutreachAction.NOTE.value, "note": "Left a voicemail."},
    )
    response = client.get(f"/api/v1/companies/{company.id}/outreach")
    assert response.status_code == 200
    assert [entry["note"] for entry in response.json()] == ["Left a voicemail."]


# --- integrity through the API -----------------------------------------


def test_logging_against_another_companys_contact_is_rejected(client, session) -> None:
    company = make_company(session, "Alpha Industries")
    other = make_company(session, "Beta Holdings")
    stranger = make_contact(session, other)
    session.commit()

    response = client.post(
        f"/api/v1/companies/{company.id}/outreach",
        json={
            "action": OutreachAction.EMAIL_SENT.value,
            "contact_id": str(stranger.id),
        },
    )
    assert response.status_code == 422
    assert "does not belong" in response.text


def test_outreach_on_an_unknown_company_is_a_404(client) -> None:
    response = client.post(
        "/api/v1/companies/00000000-0000-0000-0000-000000000000/outreach",
        json={"action": OutreachAction.NOTE.value, "note": "Nobody."},
    )
    assert response.status_code == 404


# --- the routing choice itself -----------------------------------------


def test_routing_prefers_a_live_opportunity_over_a_past_one(session) -> None:
    """A past event does not decide who to call today."""
    company = make_company(session)
    past = make_opportunity(
        session,
        company=company,
        score=95,
        opportunity_type=OpportunityType.TOWN_HALL,
        event_date=date.today() - timedelta(days=30),
    )
    live = make_opportunity(
        session,
        company=company,
        score=70,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() + timedelta(days=45),
    )
    assert past.timing_class is OpportunityTiming.HISTORICAL
    chosen = company_profile.routing_opportunity([past, live])
    assert chosen is not None and chosen.id == live.id


def test_routing_falls_back_to_a_past_event_when_it_is_all_there_is(session) -> None:
    company = make_company(session)
    past = make_opportunity(
        session,
        company=company,
        opportunity_type=OpportunityType.EXHIBITION,
        event_date=date.today() - timedelta(days=30),
    )
    chosen = company_profile.routing_opportunity([past])
    assert chosen is not None and chosen.id == past.id


def test_no_opportunities_means_no_routing_and_an_account_opening(session) -> None:
    ranked: list = []
    action = company_profile.recommend_first_action(
        company_name="Quiet Holdings", opportunity=None, ranked=ranked
    )
    assert company_profile.routing_opportunity([]) is None
    assert "No live event" in action


def test_every_outreach_status_reads_as_a_sentence() -> None:
    """"is already nurture" is not English, and an Account Manager reads this."""
    for status in OutreachStatus:
        action = company_profile.recommend_first_action(
            company_name="Some Company",
            opportunity=None,
            ranked=[],
            outreach_status=status,
        )
        assert action.startswith(("Some Company ", "No live event is on file")), status
        # A raw enum value leaking into prose is the bug this guards.
        assert "_" not in action, status
        if status is not OutreachStatus.NOT_CONTACTED:
            assert company_profile._STATUS_PHRASE[status] in action
