"""Shared request dependencies."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.domain.enums import Classification, OpportunityStatus, OpportunityType
from app.services.top50 import OpportunityFilters, SortField

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def opportunity_filters(
    sector: Annotated[str | None, Query(description="Exact configured sector name.")] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    opportunity_status: Annotated[
        OpportunityStatus | None, Query(alias="status")
    ] = None,
    opportunity_type: Annotated[OpportunityType | None, Query(alias="type")] = None,
    classification: Annotated[Classification | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(description="Created at or after.")] = None,
    date_to: Annotated[datetime | None, Query(description="Created at or before.")] = None,
    search: Annotated[
        str | None,
        Query(description="Match company name, contact name or contact email.", max_length=200),
    ] = None,
    sort: Annotated[SortField, Query(description="Sort column.")] = SortField.SCORE,
    order: Annotated[str, Query(pattern="^(asc|desc)$", description="Sort direction.")] = "desc",
    include_test: Annotated[
        bool, Query(description="Include TEST-provenance data. Off by default (spec §37).")
    ] = False,
) -> OpportunityFilters:
    """The filter set offered by the Top 50 view (spec §22)."""
    return OpportunityFilters(
        sector=sector,
        min_score=min_score,
        max_score=max_score,
        status=opportunity_status,
        opportunity_type=opportunity_type,
        classification=classification,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort=sort,
        descending=order == "desc",
        include_test=include_test,
    )


FiltersDep = Annotated[OpportunityFilters, Depends(opportunity_filters)]
