"""Assembling the contact-first company profile (Priorities 1, 2, 4 and 5).

The nine questions this has to answer about any company on the list:

1. Who are they?                       ``CompanyOut`` fields
2. Why are they relevant?              ``why_now`` on the opportunities
3. What events are involved?           the opportunities, each with its timing class
4. Who do we contact?                  ``recommended_contacts``, ranked for the job
5. Which department and role?          ``relevant_departments`` + each contact's own
6. Is the contact verified?            ``email_status`` and ``contact_kind`` per contact
7. Where did the contact come from?    ``source`` on every contact
8. What do we say first?               ``recommended_first_action``
9. When do we follow up?               ``outreach`` state and the log

Everything here is derived from stored rows. Nothing is invented: when there is no
public contact, the honest answer is UNKNOWN, and this module says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.enums import (
    LIVE_TIMINGS,
    ContactKind,
    Department,
    EmailStatus,
    OpportunityTiming,
    OutreachStatus,
)
from app.models import Contact, Opportunity
from app.schemas.outreach import (
    ContactIntelligence,
    DepartmentSuggestion,
    RankedContactOut,
)
from app.scoring.contact_routing import (
    DEPARTMENT_RATIONALE,
    preferences_for,
    rank_contacts,
)

#: Email states that mean "read from a page", as opposed to worked out.
PUBLISHED_EMAIL_STATES = frozenset({EmailStatus.VERIFIED, EmailStatus.PUBLIC})

#: Departments never worth suggesting: they are placeholders, not routes.
_UNROUTABLE = frozenset({Department.OTHER, Department.UNKNOWN})


def contact_intelligence(
    contacts: Sequence[Contact], *, needed_departments: Sequence[Department] = ()
) -> ContactIntelligence:
    """Count what we hold. No claim beyond what the rows support."""
    held = {contact.department for contact in contacts}
    verified_dates = [c.last_verified_at for c in contacts if c.last_verified_at is not None]
    return ContactIntelligence(
        total=len(contacts),
        named_individuals=sum(
            1 for c in contacts if c.contact_kind is ContactKind.NAMED_INDIVIDUAL
        ),
        department_routes=sum(
            1 for c in contacts if c.contact_kind is ContactKind.DEPARTMENT_ROUTE
        ),
        unknown_kind=sum(1 for c in contacts if c.contact_kind is ContactKind.UNKNOWN),
        with_email=sum(1 for c in contacts if c.email),
        with_phone=sum(1 for c in contacts if c.phone),
        with_linkedin=sum(1 for c in contacts if c.linkedin_url),
        with_published_email=sum(
            1 for c in contacts if c.email and c.email_status in PUBLISHED_EMAIL_STATES
        ),
        has_any_route=any(c.email or c.phone or c.linkedin_url for c in contacts),
        last_verified_at=max(verified_dates) if verified_dates else None,
        missing_departments=[
            department
            for department in needed_departments
            if department not in held and department not in _UNROUTABLE
        ],
    )


def needed_departments(
    opportunities: Sequence[Opportunity], *, per_type: int = 3
) -> list[Department]:
    """Departments this company's own events would need, best first.

    Union of the preferred routes for the types of event this company actually
    has. A company with only an exhibition never gets HR suggested at it.
    """
    ordered: list[Department] = []
    live = [o for o in opportunities if o.timing_class in LIVE_TIMINGS] or list(opportunities)
    for opportunity in live:
        for department in preferences_for(opportunity.type)[:per_type]:
            if department not in ordered:
                ordered.append(department)
    return ordered


def relevant_departments(
    opportunities: Sequence[Opportunity], contacts: Sequence[Contact]
) -> list[DepartmentSuggestion]:
    """Which departments to approach at this company, and whether we have them."""
    held = {contact.department for contact in contacts}
    return [
        DepartmentSuggestion(
            department=department,
            why=DEPARTMENT_RATIONALE.get(department, ""),
            have_contact=department in held,
        )
        for department in needed_departments(opportunities)
    ]


def ranked_for(
    opportunity: Opportunity | None, contacts: Sequence[Contact]
) -> list[RankedContactOut]:
    """This company's contacts, ordered for one specific opportunity."""
    if opportunity is None or not contacts:
        return []
    return [
        RankedContactOut(
            contact=ranked.contact,
            rank=ranked.rank,
            department_fit=ranked.department_fit,
            is_preferred_department=ranked.is_preferred_department,
            reason=ranked.reason,
        )
        for ranked in rank_contacts(opportunity.type, contacts)
    ]


def routing_opportunity(opportunities: Sequence[Opportunity]) -> Opportunity | None:
    """The opportunity contact routing should be computed against.

    The best-scoring live one. A past event does not decide who to call today, so
    historical opportunities are used only when there is nothing else — in which
    case the call is about the account, not the event.
    """
    live = [o for o in opportunities if o.timing_class in LIVE_TIMINGS]
    pool = live or list(opportunities)
    if not pool:
        return None
    return max(pool, key=lambda o: o.score)


@dataclass(frozen=True, slots=True)
class _Timings:
    immediate: int
    future_account: int
    historical: int


def timing_counts(opportunities: Sequence[Opportunity]) -> _Timings:
    return _Timings(
        immediate=sum(
            1 for o in opportunities if o.timing_class is OpportunityTiming.IMMEDIATE
        ),
        future_account=sum(
            1 for o in opportunities if o.timing_class is OpportunityTiming.FUTURE_ACCOUNT
        ),
        historical=sum(
            1 for o in opportunities if o.timing_class is OpportunityTiming.HISTORICAL
        ),
    )


def _contact_clause(ranked: Sequence[RankedContactOut]) -> str:
    """How to open, given who we actually have."""
    if not ranked:
        return (
            "No public contact is on file yet — find the department route on the "
            "company's own site before calling"
        )
    best = ranked[0].contact
    where = best.department.value.replace("_", " ").lower()
    if best.contact_kind is ContactKind.NAMED_INDIVIDUAL:
        who = f"{best.name}"
        if best.job_title:
            who = f"{best.name} ({best.job_title})"
        return f"Approach {who} in {where}"
    if best.contact_kind is ContactKind.DEPARTMENT_ROUTE:
        return f"Use the published {where} route ({best.name}) and ask for the events owner"
    return f"Start with the {where} contact on file and confirm who owns events"


def recommend_first_action(
    *,
    company_name: str,
    opportunity: Opportunity | None,
    ranked: Sequence[RankedContactOut],
    outreach_status: OutreachStatus = OutreachStatus.NOT_CONTACTED,
) -> str:
    """One sentence: what to do next at this company.

    Built from the timing class, the contact we hold and whether the relationship
    has already started. Deliberately blunt — an Account Manager reads this
    between calls.
    """
    opening = _contact_clause(ranked)

    if outreach_status is not OutreachStatus.NOT_CONTACTED:
        state = outreach_status.value.replace("_", " ").lower()
        return (
            f"{company_name} is already {state}. {opening}, and pick up from the "
            "last note in the outreach history."
        )

    if opportunity is None:
        return (
            f"No live event is on file for {company_name}. {opening}, and introduce "
            "Paradigm as an events partner for the next cycle."
        )

    event = opportunity.type.value.replace("_", " ").lower()
    if opportunity.timing_class is OpportunityTiming.IMMEDIATE:
        return (
            f"{opening}. Reference the {event} directly and ask whether production "
            "and on-site support are still open — there is time to bid."
        )
    if opportunity.timing_class is OpportunityTiming.FUTURE_ACCOUNT:
        return (
            f"{opening}. Assume the {event} is already contracted: congratulate them "
            "on it, ask who handles the annual calendar, and position Paradigm for "
            "the next one."
        )
    return (
        f"{opening}. The {event} has already happened, so treat this as account "
        "research: reference it as evidence they run events and ask what is coming up."
    )
