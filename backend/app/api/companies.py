"""Company endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.deps import SessionDep, SettingsDep
from app.config import get_settings
from app.domain.enums import CLOSED_STATUSES, CONFIRMED_EVENT_SIGNALS
from app.models import Company, Opportunity, OutreachLog, Signal
from app.schemas.company import CompanyDetail, CompanyOut, CompanyRelative
from app.schemas.opportunity import ContactRef, OpportunityOut, SignalRef
from app.schemas.outreach import OutreachCreate, OutreachLogOut, OutreachStateOut
from app.services import company_profile
from app.services.contacts import contacts_for_company
from app.services.outreach import (
    OutreachInput,
    company_state,
    history_for_company,
    log_outreach,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut], summary="List companies")
def list_companies(
    session: SessionDep,
    sector: str | None = None,
    search: str | None = Query(default=None, description="Case-insensitive name match."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CompanyOut]:
    query = select(Company)
    if sector:
        query = query.where(Company.sector == sector)
    if search:
        query = query.where(Company.name.ilike(f"%{search}%"))
    query = query.order_by(Company.name).limit(limit).offset(offset)
    return [CompanyOut.model_validate(company) for company in session.scalars(query).all()]


@router.get("/sectors", response_model=list[str], summary="Configured sectors")
def sectors() -> list[str]:
    """The configured priority sectors, for the UI's filter.

    Declared before ``/{company_id}`` on purpose: FastAPI matches routes in
    declaration order, and a literal path registered after a UUID parameter would
    be swallowed by it and fail to parse.
    """
    return get_settings().sectors


@router.get("/{company_id}", response_model=CompanyDetail, summary="Company detail")
def company_detail(
    company_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> CompanyDetail:
    """A lightweight account profile (spec §24).

    Enough to brief an Account Manager before a call — open opportunities, recent
    signals, the contacts we hold, and any event history the sources actually
    show. Not a CRM record.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")

    payload = CompanyDetail.model_validate(company)
    payload.contacts = [
        ContactRef.model_validate(contact) for contact in contacts_for_company(session, company.id)
    ]

    signals = list(
        session.scalars(
            select(Signal)
            .options(joinedload(Signal.source))
            .where(Signal.company_id == company.id)
            .order_by(Signal.published_at.desc().nullslast(), Signal.created_at.desc())
            .limit(20)
        ).unique().all()
    )
    payload.recent_signals = [SignalRef.model_validate(signal) for signal in signals]
    # The only event history we can honestly claim: signals that are themselves
    # announcements of an event this company ran or took part in.
    payload.event_history = [
        SignalRef.model_validate(signal)
        for signal in signals
        if signal.type in CONFIRMED_EVENT_SIGNALS
    ]

    # Every opportunity at this company, past ones included: a past event is
    # account evidence even though it is never ranked as if it were upcoming.
    own = list(
        session.scalars(
            select(Opportunity)
            .options(
                joinedload(Opportunity.company),
                joinedload(Opportunity.signal).joinedload(Signal.source),
                joinedload(Opportunity.primary_contact),
            )
            .where(Opportunity.company_id == company.id)
            .order_by(Opportunity.score.desc())
        ).unique().all()
    )
    payload.opportunities = [OpportunityOut.model_validate(o) for o in own]

    timings = company_profile.timing_counts(own)
    payload.immediate_opportunity_count = timings.immediate
    payload.future_account_opportunity_count = timings.future_account
    payload.historical_opportunity_count = timings.historical

    if company.parent is not None:
        payload.parent = CompanyRelative.model_validate(company.parent)
    payload.subsidiaries = [
        CompanyRelative.model_validate(child) for child in company.subsidiaries
    ]

    payload.signal_count = int(
        session.scalar(select(func.count(Signal.id)).where(Signal.company_id == company.id)) or 0
    )
    payload.opportunity_count = int(
        session.scalar(
            select(func.count(Opportunity.id)).where(Opportunity.company_id == company.id)
        )
        or 0
    )
    payload.qualified_opportunity_count = int(
        session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.company_id == company.id,
                Opportunity.score >= settings.min_qualifying_score,
                Opportunity.status.notin_([s.value for s in CLOSED_STATUSES]),
            )
        )
        or 0
    )
    payload.account_score = session.scalar(
        select(func.max(Opportunity.score)).where(
            Opportunity.company_id == company.id,
            Opportunity.status.notin_([s.value for s in CLOSED_STATUSES]),
        )
    )

    # --- contact intelligence (Priorities 1, 2 and 5) --------------------
    contacts = contacts_for_company(session, company.id)
    payload.relevant_departments = company_profile.relevant_departments(own, contacts)
    payload.contact_intelligence = company_profile.contact_intelligence(
        contacts,
        needed_departments=[
            suggestion.department for suggestion in payload.relevant_departments
        ],
    )

    routing_for = company_profile.routing_opportunity(own)
    payload.routing_opportunity_id = routing_for.id if routing_for is not None else None
    payload.recommended_contacts = company_profile.ranked_for(routing_for, contacts)

    state = company_state(session, company.id)
    payload.outreach = OutreachStateOut(
        status=state.status,
        last_contacted_at=state.last_contacted_at,
        next_follow_up_on=state.next_follow_up_on,
        interactions=state.interactions,
        overdue=state.overdue,
    )
    payload.outreach_history = [
        _log_out(entry) for entry in history_for_company(session, company.id)
    ]
    payload.recommended_first_action = company_profile.recommend_first_action(
        company_name=company.name,
        opportunity=routing_for,
        ranked=payload.recommended_contacts,
        outreach_status=state.status,
    )
    return payload


def _log_out(entry: OutreachLog) -> OutreachLogOut:
    """One log row, with the names it refers to resolved for display."""
    payload = OutreachLogOut.model_validate(entry)
    payload.contact_name = entry.contact.name if entry.contact is not None else None
    payload.opportunity_type = (
        entry.opportunity.type if entry.opportunity is not None else None
    )
    return payload


@router.get(
    "/{company_id}/outreach",
    response_model=list[OutreachLogOut],
    summary="Outreach history",
)
def outreach_history(
    company_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OutreachLogOut]:
    """Everything logged against this company, newest first."""
    if session.get(Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return [
        _log_out(entry) for entry in history_for_company(session, company_id, limit=limit)
    ]


@router.post(
    "/{company_id}/outreach",
    response_model=OutreachLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log an outreach action",
)
def create_outreach(
    company_id: uuid.UUID, payload: OutreachCreate, session: SessionDep
) -> OutreachLogOut:
    """Record what was actually done, and when to come back.

    Company-scoped: an account can be worked before there is a named person to
    attach anything to. Passing a contact or opportunity that belongs to a
    different company is rejected rather than silently stored.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    try:
        entry = log_outreach(
            session,
            company=company,
            payload=OutreachInput(
                action=payload.action,
                contact_id=payload.contact_id,
                opportunity_id=payload.opportunity_id,
                status_after=payload.status_after,
                occurred_at=payload.occurred_at,
                next_follow_up_on=payload.next_follow_up_on,
                note=payload.note,
                logged_by=payload.logged_by,
            ),
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    session.commit()
    session.refresh(entry)
    return _log_out(entry)
