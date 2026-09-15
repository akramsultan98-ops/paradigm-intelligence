"""Contact routing (Priority 2).

The requirement in one line: "Do not force every department onto every company."
An exhibition goes to marketing; a town hall goes to HR; a VIP dinner often goes
to the executive office. The same contact list must come out in a different order
for each.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.enums import ContactKind, Department, OpportunityType
from app.scoring.contact_routing import (
    DEFAULT_PREFERENCE,
    DEPARTMENT_RATIONALE,
    ROUTE_PREFERENCES,
    best_route,
    department_fit,
    preferences_for,
    rank_contacts,
)


@dataclass
class FakeContact:
    """The three attributes routing reads. Nothing else is relevant to it."""

    department: Department
    contact_score: int = 50
    contact_kind: ContactKind = ContactKind.NAMED_INDIVIDUAL
    label: str = ""


# --- the route depends on the job ----------------------------------------


def test_an_exhibition_routes_to_marketing_not_hr() -> None:
    assert preferences_for(OpportunityType.EXHIBITION)[0] is Department.MARKETING
    assert department_fit(OpportunityType.EXHIBITION, Department.HR) == 0


def test_an_internal_town_hall_routes_to_hr_not_marketing() -> None:
    assert preferences_for(OpportunityType.TOWN_HALL)[0] is Department.HR
    assert department_fit(OpportunityType.TOWN_HALL, Department.HR) > 0
    assert department_fit(OpportunityType.TOWN_HALL, Department.MARKETING) == 0


def test_a_press_event_routes_to_the_press_office() -> None:
    assert preferences_for(OpportunityType.PRESS_EVENT)[0] is Department.PR


def test_senior_hospitality_routes_to_the_executive_office() -> None:
    assert preferences_for(OpportunityType.VIP_DINNER)[0] is Department.EXECUTIVE_OFFICE


def test_the_same_contacts_rank_differently_for_different_events() -> None:
    """The whole point of the module, in one assertion."""
    contacts = [
        FakeContact(Department.HR, label="hr"),
        FakeContact(Department.MARKETING, label="marketing"),
    ]
    exhibition = best_route(OpportunityType.EXHIBITION, contacts)
    town_hall = best_route(OpportunityType.TOWN_HALL, contacts)
    assert exhibition is not None and town_hall is not None
    assert exhibition.contact.label == "marketing"
    assert town_hall.contact.label == "hr"


# --- nothing is forced onto a company ------------------------------------


def test_an_unlisted_department_still_ranks_rather_than_being_dropped() -> None:
    """A wrong-ish contact beats no contact, but it is labelled as such."""
    ranked = rank_contacts(OpportunityType.EXHIBITION, [FakeContact(Department.HR)])
    assert len(ranked) == 1
    assert ranked[0].department_fit == 0
    assert ranked[0].is_preferred_department is False
    assert "not a usual route" in ranked[0].reason


def test_a_preferred_department_carries_a_reason_a_person_can_read() -> None:
    ranked = rank_contacts(OpportunityType.EXHIBITION, [FakeContact(Department.MARKETING)])
    assert ranked[0].is_preferred_department
    assert ranked[0].reason == DEPARTMENT_RATIONALE[Department.MARKETING]


def test_no_contacts_means_no_route_rather_than_an_invented_one() -> None:
    assert rank_contacts(OpportunityType.EXHIBITION, []) == []
    assert best_route(OpportunityType.EXHIBITION, []) is None


# --- ordering rules ------------------------------------------------------


def test_department_fit_outranks_contact_quality() -> None:
    """A well-evidenced HR contact does not win an exhibition."""
    contacts = [
        FakeContact(Department.HR, contact_score=99, label="hr"),
        FakeContact(Department.MARKETING, contact_score=30, label="marketing"),
    ]
    assert best_route(OpportunityType.EXHIBITION, contacts).contact.label == "marketing"


def test_within_a_department_the_better_evidenced_contact_wins() -> None:
    contacts = [
        FakeContact(Department.MARKETING, contact_score=40, label="weak"),
        FakeContact(Department.MARKETING, contact_score=90, label="strong"),
    ]
    assert best_route(OpportunityType.EXHIBITION, contacts).contact.label == "strong"


def test_a_named_person_beats_a_generic_inbox_at_equal_evidence() -> None:
    contacts = [
        FakeContact(
            Department.MARKETING,
            contact_score=70,
            contact_kind=ContactKind.DEPARTMENT_ROUTE,
            label="inbox",
        ),
        FakeContact(
            Department.MARKETING,
            contact_score=70,
            contact_kind=ContactKind.NAMED_INDIVIDUAL,
            label="person",
        ),
    ]
    assert best_route(OpportunityType.EXHIBITION, contacts).contact.label == "person"


def test_ranks_are_dense_and_start_at_one() -> None:
    contacts = [FakeContact(Department.MARKETING), FakeContact(Department.HR)]
    ranked = rank_contacts(OpportunityType.EXHIBITION, contacts)
    assert [r.rank for r in ranked] == [1, 2]


# --- the fallback --------------------------------------------------------


def test_an_unmapped_type_falls_back_to_the_general_preference() -> None:
    assert preferences_for(OpportunityType.UNKNOWN) == DEFAULT_PREFERENCE


def test_only_unknown_is_left_to_the_fallback() -> None:
    """Every real event type earns its own route; the fallback is for UNKNOWN only."""
    unmapped = {t for t in OpportunityType if t not in ROUTE_PREFERENCES}
    assert unmapped == {OpportunityType.UNKNOWN}


@pytest.mark.parametrize("opportunity_type", list(ROUTE_PREFERENCES))
def test_every_mapped_type_has_explained_departments(
    opportunity_type: OpportunityType,
) -> None:
    """A route with no rationale would show an Account Manager a blank reason."""
    preferences = ROUTE_PREFERENCES[opportunity_type]
    assert preferences, opportunity_type
    assert len(set(preferences)) == len(preferences), "a department listed twice"
    for department in preferences:
        assert DEPARTMENT_RATIONALE.get(department), (opportunity_type, department)
        # Placeholders are not routes.
        assert department not in {Department.OTHER, Department.UNKNOWN}
