"""Which contact to approach, given what the opportunity is (Priority 2).

The right route depends on the job. A press event is the PR office's; a town hall
or a team-building day is HR's; a VIP dinner is often the executive office's, not
marketing's. Ranking every contact by generic seniority would send an Account
Manager to the wrong person with the right title.

Departments not listed for a type are not rejected — they simply rank below the
ones that are. Nothing is forced onto a company that does not have it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.enums import ContactKind, Department, OpportunityType

#: Ordered preferred departments per opportunity type, best first.
ROUTE_PREFERENCES: dict[OpportunityType, tuple[Department, ...]] = {
    # Trade shows and conferences: marketing owns the spend, events runs it.
    OpportunityType.EXHIBITION: (
        Department.MARKETING, Department.EVENTS, Department.CORPORATE_COMMUNICATIONS,
        Department.PR, Department.PROCUREMENT,
    ),
    OpportunityType.CONFERENCE: (
        Department.EVENTS, Department.MARKETING, Department.CORPORATE_COMMUNICATIONS,
        Department.PR, Department.PROCUREMENT,
    ),
    OpportunityType.ROADSHOW: (
        Department.MARKETING, Department.EVENTS, Department.BUSINESS_DEVELOPMENT,
    ),
    # Brand moments: marketing first, press office close behind.
    OpportunityType.PRODUCT_LAUNCH: (
        Department.MARKETING, Department.PR, Department.CORPORATE_COMMUNICATIONS,
        Department.EVENTS,
    ),
    OpportunityType.PRESS_EVENT: (
        Department.PR, Department.CORPORATE_COMMUNICATIONS, Department.COMMUNICATIONS,
        Department.MARKETING,
    ),
    OpportunityType.MEDIA_EVENT: (
        Department.PR, Department.CORPORATE_COMMUNICATIONS, Department.COMMUNICATIONS,
        Department.MARKETING,
    ),
    OpportunityType.AWARDS: (
        Department.MARKETING, Department.CORPORATE_COMMUNICATIONS, Department.PR,
        Department.HR,
    ),
    # Project milestones: corporate comms owns the ceremony, procurement the contract.
    OpportunityType.GROUNDBREAKING: (
        Department.CORPORATE_COMMUNICATIONS, Department.PR, Department.MARKETING,
        Department.PROCUREMENT,
    ),
    OpportunityType.PROJECT_LAUNCH: (
        Department.CORPORATE_COMMUNICATIONS, Department.MARKETING, Department.PROCUREMENT,
    ),
    OpportunityType.PROJECT_KICKOFF: (
        Department.CORPORATE_COMMUNICATIONS, Department.PROCUREMENT, Department.MARKETING,
    ),
    OpportunityType.PROJECT_COMPLETION_EVENT: (
        Department.CORPORATE_COMMUNICATIONS, Department.MARKETING, Department.PR,
    ),
    # Customer and channel events: marketing with commercial input.
    OpportunityType.CUSTOMER_EVENT: (
        Department.MARKETING, Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    OpportunityType.CLIENT_APPRECIATION: (
        Department.MARKETING, Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    OpportunityType.PARTNER_EVENT: (
        Department.MARKETING, Department.CORPORATE_COMMUNICATIONS,
        Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    OpportunityType.DEALER_EVENT: (
        Department.MARKETING, Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    OpportunityType.DISTRIBUTOR_EVENT: (
        Department.MARKETING, Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    OpportunityType.TECHNICAL_DAY: (
        Department.MARKETING, Department.BUSINESS_DEVELOPMENT, Department.EVENTS,
    ),
    # Internal and people events: HR owns these, not marketing.
    OpportunityType.TOWN_HALL: (
        Department.HR, Department.CORPORATE_COMMUNICATIONS, Department.COMMUNICATIONS,
    ),
    OpportunityType.TEAM_BUILDING: (
        Department.HR, Department.CORPORATE_COMMUNICATIONS, Department.EVENTS,
    ),
    OpportunityType.TRAINING_EVENT: (
        Department.HR, Department.MARKETING, Department.EVENTS,
    ),
    OpportunityType.CORPORATE_CELEBRATION: (
        Department.CORPORATE_COMMUNICATIONS, Department.HR, Department.MARKETING,
        Department.EVENTS,
    ),
    OpportunityType.ANNIVERSARY: (
        Department.MARKETING, Department.CORPORATE_COMMUNICATIONS, Department.HR,
        Department.EVENTS,
    ),
    # Senior hospitality: often the executive office, not marketing.
    OpportunityType.EXECUTIVE_MEETING: (
        Department.EXECUTIVE_OFFICE, Department.CORPORATE_COMMUNICATIONS,
        Department.MARKETING,
    ),
    OpportunityType.ROUNDTABLE: (
        Department.CORPORATE_COMMUNICATIONS, Department.EXECUTIVE_OFFICE,
        Department.MARKETING, Department.EVENTS,
    ),
    OpportunityType.VIP_DINNER: (
        Department.EXECUTIVE_OFFICE, Department.CORPORATE_COMMUNICATIONS,
        Department.MARKETING, Department.EVENTS,
    ),
    OpportunityType.BUSINESS_DINNER: (
        Department.EXECUTIVE_OFFICE, Department.MARKETING, Department.EVENTS,
    ),
    OpportunityType.BUSINESS_LUNCH: (
        Department.EXECUTIVE_OFFICE, Department.MARKETING, Department.EVENTS,
    ),
    OpportunityType.HOSPITALITY: (
        Department.MARKETING, Department.EXECUTIVE_OFFICE, Department.EVENTS,
    ),
    OpportunityType.DELEGATION_EVENT: (
        Department.CORPORATE_COMMUNICATIONS, Department.EXECUTIVE_OFFICE,
        Department.PR, Department.EVENTS,
    ),
    OpportunityType.ANNUAL_MEETING: (
        Department.CORPORATE_COMMUNICATIONS, Department.EXECUTIVE_OFFICE,
        Department.MARKETING,
    ),
    OpportunityType.SEMINAR: (
        Department.MARKETING, Department.EVENTS, Department.HR,
    ),
    OpportunityType.WORKSHOP: (
        Department.MARKETING, Department.EVENTS, Department.HR,
    ),
}

#: Used when the opportunity type is unknown or unmapped.
DEFAULT_PREFERENCE: tuple[Department, ...] = (
    Department.MARKETING, Department.CORPORATE_COMMUNICATIONS, Department.EVENTS,
    Department.PR, Department.COMMUNICATIONS, Department.BUSINESS_DEVELOPMENT,
    Department.PROCUREMENT, Department.EXECUTIVE_OFFICE, Department.HR,
)

#: Readable department names. Title-casing the enum gives "Pr" and
#: "Hr", which read as typos in text an Account Manager sees.
DEPARTMENT_LABEL: dict[Department, str] = {
    Department.MARKETING: "Marketing",
    Department.CORPORATE_COMMUNICATIONS: "Corporate communications",
    Department.COMMUNICATIONS: "Communications",
    Department.PR: "PR",
    Department.EVENTS: "Events",
    Department.PROCUREMENT: "Procurement",
    Department.BUSINESS_DEVELOPMENT: "Business development",
    Department.HR: "HR",
    Department.EXECUTIVE_OFFICE: "The executive office",
    Department.OTHER: "This department",
    Department.UNKNOWN: "An unidentified department",
}


def department_label(department: Department) -> str:
    return DEPARTMENT_LABEL.get(department, department.value.replace("_", " ").title())


#: Why each department is the route, in an Account Manager's terms.
DEPARTMENT_RATIONALE: dict[Department, str] = {
    Department.MARKETING: "Marketing usually holds the budget for this kind of activity.",
    Department.EVENTS: "A dedicated events function runs this directly.",
    Department.CORPORATE_COMMUNICATIONS: (
        "Corporate communications owns ceremonies and milestone moments."
    ),
    Department.COMMUNICATIONS: "Communications coordinates this type of activity.",
    Department.PR: "The press office owns media-facing events.",
    Department.PROCUREMENT: (
        "Procurement controls vendor registration and the contract, even when "
        "another team specifies the work."
    ),
    Department.BUSINESS_DEVELOPMENT: (
        "Business development owns the customer and channel relationships behind this."
    ),
    Department.HR: "HR owns internal and people-facing events.",
    Department.EXECUTIVE_OFFICE: (
        "The executive office arranges senior hospitality and delegations."
    ),
    Department.OTHER: "Not a typical route for this activity.",
    Department.UNKNOWN: "Department unknown.",
}


class _ContactLike(Protocol):
    department: Department
    contact_score: int
    contact_kind: ContactKind


@dataclass(frozen=True, slots=True)
class RankedContact:
    """A contact, positioned for this specific opportunity."""

    contact: object
    rank: int
    department_fit: int
    reason: str

    @property
    def is_preferred_department(self) -> bool:
        return self.department_fit > 0


def preferences_for(opportunity_type: OpportunityType) -> tuple[Department, ...]:
    return ROUTE_PREFERENCES.get(opportunity_type, DEFAULT_PREFERENCE)


def department_fit(opportunity_type: OpportunityType, department: Department) -> int:
    """How well a department fits this opportunity type. 0 means not a listed route.

    Higher is better, so it sorts naturally alongside contact score.
    """
    preferences = preferences_for(opportunity_type)
    if department not in preferences:
        return 0
    return len(preferences) - preferences.index(department)


def rank_contacts(
    opportunity_type: OpportunityType, contacts: Sequence[_ContactLike]
) -> list[RankedContact]:
    """Order a company's contacts for this opportunity.

    Sorted by department fit first, then by contact quality, then by whether it is
    a named person rather than a generic route — a named marketing manager beats a
    generic marketing inbox, but both beat a well-evidenced HR contact when the job
    is an exhibition.
    """
    scored = sorted(
        contacts,
        key=lambda contact: (
            -department_fit(opportunity_type, contact.department),
            -contact.contact_score,
            0 if contact.contact_kind is ContactKind.NAMED_INDIVIDUAL else 1,
        ),
    )
    ranked: list[RankedContact] = []
    for position, contact in enumerate(scored, start=1):
        fit = department_fit(opportunity_type, contact.department)
        if fit > 0:
            reason = DEPARTMENT_RATIONALE.get(contact.department, "")
        else:
            reason = (
                f"{department_label(contact.department)} is not a usual route for this "
                "activity — use only if there is no better contact."
            )
        ranked.append(RankedContact(contact, position, fit, reason))
    return ranked


def best_route(
    opportunity_type: OpportunityType, contacts: Sequence[_ContactLike]
) -> RankedContact | None:
    """The single contact to approach first, or ``None`` when there is nobody."""
    ranked = rank_contacts(opportunity_type, contacts)
    return ranked[0] if ranked else None
