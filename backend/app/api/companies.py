"""Company endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.config import get_settings
from app.models import Company, Opportunity, Signal
from app.schemas.company import CompanyDetail, CompanyOut
from app.schemas.opportunity import ContactRef
from app.services.contacts import contacts_for_company

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
def company_detail(company_id: uuid.UUID, session: SessionDep) -> CompanyDetail:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")

    payload = CompanyDetail.model_validate(company)
    payload.contacts = [
        ContactRef.model_validate(contact) for contact in contacts_for_company(session, company.id)
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
    return payload
