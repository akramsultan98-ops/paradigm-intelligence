"""Top 50 selection and opportunity queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.domain.enums import (
    CLOSED_STATUSES,
    Classification,
    OpportunityStatus,
    OpportunityType,
)
from app.models import Company, Opportunity, Signal


@dataclass(slots=True)
class OpportunityFilters:
    """Filters offered by the UI (spec §29)."""

    sector: str | None = None
    min_score: int | None = None
    max_score: int | None = None
    status: OpportunityStatus | None = None
    opportunity_type: OpportunityType | None = None
    classification: Classification | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _base_query() -> Select[tuple[Opportunity]]:
    # The UI shows company, signal, source and contact on every row, so they are
    # eager-loaded: fifty rows would otherwise be two hundred queries.
    return select(Opportunity).options(
        joinedload(Opportunity.company),
        joinedload(Opportunity.signal).joinedload(Signal.source),
        joinedload(Opportunity.primary_contact),
    )


def apply_filters(
    query: Select[tuple[Opportunity]], filters: OpportunityFilters
) -> Select[tuple[Opportunity]]:
    if filters.sector:
        query = query.join(Company, Opportunity.company_id == Company.id).where(
            Company.sector == filters.sector
        )
    if filters.min_score is not None:
        query = query.where(Opportunity.score >= filters.min_score)
    if filters.max_score is not None:
        query = query.where(Opportunity.score <= filters.max_score)
    if filters.status is not None:
        query = query.where(Opportunity.status == filters.status)
    if filters.opportunity_type is not None:
        query = query.where(Opportunity.type == filters.opportunity_type)
    if filters.classification is not None:
        query = query.where(Opportunity.classification == filters.classification)
    if filters.date_from is not None:
        query = query.where(Opportunity.created_at >= filters.date_from)
    if filters.date_to is not None:
        query = query.where(Opportunity.created_at <= filters.date_to)
    return query


def get_top_opportunities(
    session: Session,
    filters: OpportunityFilters | None = None,
    settings: Settings | None = None,
) -> list[Opportunity]:
    """The Top 50.

    Three rules, all from spec §12:

    - Only scores at or above ``MIN_QUALIFYING_SCORE`` are eligible.
    - Ranking is by score, so a new opportunity displaces an existing one only by
      being stronger. Nothing is included for being recent.
    - Fewer than ``TOP_N`` qualifiers means a shorter list. Remaining slots are
      never filled with weak leads.

    Ties break on event probability, then on age, so the order is stable between
    runs rather than arbitrary.
    """
    settings = settings or get_settings()
    filters = filters or OpportunityFilters()

    floor = settings.min_qualifying_score
    if filters.min_score is not None:
        floor = max(floor, filters.min_score)

    query = apply_filters(_base_query(), filters).where(
        Opportunity.score >= floor,
        Opportunity.status.notin_([status.value for status in CLOSED_STATUSES]),
    )
    query = query.order_by(
        Opportunity.score.desc(),
        Opportunity.event_probability.desc(),
        Opportunity.created_at.asc(),
    ).limit(settings.top_n)

    return list(session.scalars(query).unique().all())


def list_opportunities(
    session: Session,
    filters: OpportunityFilters | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Opportunity]:
    """All opportunities matching the filters, highest score first."""
    query = apply_filters(_base_query(), filters or OpportunityFilters())
    query = (
        query.order_by(Opportunity.score.desc(), Opportunity.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(query).unique().all())


def get_opportunity(session: Session, opportunity_id: object) -> Opportunity | None:
    return session.scalars(_base_query().where(Opportunity.id == opportunity_id)).unique().first()
