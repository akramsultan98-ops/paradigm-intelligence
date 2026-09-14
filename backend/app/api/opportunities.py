"""Opportunity endpoints, including the Top 50."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import FiltersDep, SessionDep, SettingsDep
from app.models import Opportunity
from app.schemas.opportunity import (
    ContactRef,
    OpportunityDetail,
    OpportunityOut,
    OpportunityStatusUpdate,
    Top50Response,
)
from app.services.contacts import contacts_for_company
from app.services.rescore import eligible_count
from app.services.top50 import get_opportunity, get_top_opportunities, list_opportunities

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _ranked(opportunities: list[Opportunity], offset: int = 0) -> list[OpportunityOut]:
    """Attach 1-based ranks.

    Rank is a property of a result set, not of the row, so it is assigned here
    rather than stored — a filtered list has its own ranking.
    """
    items: list[OpportunityOut] = []
    for index, opportunity in enumerate(opportunities, start=offset + 1):
        item = OpportunityOut.model_validate(opportunity)
        item.rank = index
        items.append(item)
    return items


@router.get("/top50", response_model=Top50Response, summary="The Top 50 opportunities")
def top50(
    session: SessionDep, settings: SettingsDep, filters: FiltersDep
) -> Top50Response:
    """The ranked Top 50.

    Fewer than ``top_n`` rows is a correct result: only opportunities scoring at
    or above the qualifying threshold are eligible, and remaining slots are never
    filled with weak leads.
    """
    opportunities = get_top_opportunities(session, filters, settings)
    return Top50Response(
        generated_at=datetime.now(UTC),
        qualifying_threshold=settings.min_qualifying_score,
        top_n=settings.top_n,
        returned=len(opportunities),
        eligible_total=eligible_count(session, settings),
        items=_ranked(opportunities),
    )


@router.get("", response_model=list[OpportunityOut], summary="List opportunities")
def list_all(
    session: SessionDep,
    filters: FiltersDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OpportunityOut]:
    """Every opportunity matching the filters, including those below the threshold."""
    return _ranked(list_opportunities(session, filters, limit=limit, offset=offset), offset)


@router.get("/{opportunity_id}", response_model=OpportunityDetail, summary="Opportunity detail")
def detail(opportunity_id: uuid.UUID, session: SessionDep) -> OpportunityDetail:
    opportunity = get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "opportunity not found")

    payload = OpportunityDetail.model_validate(opportunity)
    payload.contacts = [
        ContactRef.model_validate(contact)
        for contact in contacts_for_company(session, opportunity.company_id)
    ]
    return payload


@router.patch(
    "/{opportunity_id}", response_model=OpportunityOut, summary="Update opportunity status"
)
def update_status(
    opportunity_id: uuid.UUID, payload: OpportunityStatusUpdate, session: SessionDep
) -> OpportunityOut:
    """Move an opportunity through the pipeline.

    Status is the only mutable field. Scores are derived from evidence and are not
    editable by hand — a hand-edited score would make the ranking meaningless.
    """
    opportunity = get_opportunity(session, opportunity_id)
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "opportunity not found")

    opportunity.status = payload.status
    session.commit()
    session.refresh(opportunity)
    return OpportunityOut.model_validate(opportunity)
