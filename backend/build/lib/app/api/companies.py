"""Company endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.deps import SessionDep, SettingsDep
from app.config import get_settings
from app.domain.enums import CLOSED_STATUSES, CONFIRMED_EVENT_SIGNALS
from app.models import Company, Opportunity, Signal
from app.schemas.company import CompanyDetail, CompanyOut, CompanyRelative
from app.schemas.opportunity import ContactRef, OpportunityOut, SignalRef
from app.services.contacts import contacts_for_company
from app.services.top50 import OpportunityFilters, list_opportunities

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

    opportunities = list_opportunities(
        session, OpportunityFilters(), limit=50, offset=0
    )
    own = [o for o in opportunities if o.company_id == company.id]
    payload.opportunities = [OpportunityOut.model_validate(o) for o in own]

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
    return payload
