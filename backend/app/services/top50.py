"""Top 50 selection and opportunity queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.config import Settings, get_settings
from app.domain.enums import (
    CLOSED_STATUSES,
    Classification,
    IngestMode,
    OpportunityStatus,
    OpportunityTiming,
    OpportunityType,
)
from app.models import Company, Contact, Opportunity, Signal, Source


class SortField(StrEnum):
    """Sortable columns offered by the UI (spec §22)."""

    SCORE = "score"
    EVENT_PROBABILITY = "event_probability"
    COMMERCIAL_VALUE = "commercial_value"
    CONTACT_QUALITY = "contact_quality"
    TIMING = "timing_score"
    EVIDENCE = "evidence_score"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    COMPANY = "company"


_SORT_COLUMNS = {
    SortField.SCORE: Opportunity.score,
    SortField.EVENT_PROBABILITY: Opportunity.event_probability,
    SortField.COMMERCIAL_VALUE: Opportunity.commercial_value,
    SortField.CONTACT_QUALITY: Opportunity.contact_quality,
    SortField.TIMING: Opportunity.timing_score,
    SortField.EVIDENCE: Opportunity.evidence_score,
    SortField.CREATED_AT: Opportunity.created_at,
    SortField.UPDATED_AT: Opportunity.updated_at,
}


@dataclass(slots=True)
class OpportunityFilters:
    """Filters offered by the UI (spec §22)."""

    sector: str | None = None
    min_score: int | None = None
    max_score: int | None = None
    status: OpportunityStatus | None = None
    opportunity_type: OpportunityType | None = None
    classification: Classification | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    #: Free-text search across company name, contact name and contact email.
    search: str | None = None
    sort: SortField = SortField.SCORE
    descending: bool = True
    #: Fixture data stays out of the operational view unless explicitly asked for
    #: (spec §37).
    include_test: bool = False
    #: Commercial timing: IMMEDIATE, FUTURE_ACCOUNT or HISTORICAL.
    timing: OpportunityTiming | None = None
    #: Past events are account research, never a live opportunity, so they are
    #: excluded from the ranking unless explicitly requested.
    include_historical: bool = False


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
    if filters.timing is not None:
        query = query.where(Opportunity.timing_class == filters.timing)
    elif not filters.include_historical:
        # Never rank a past event as if it were upcoming.
        query = query.where(Opportunity.timing_class != OpportunityTiming.HISTORICAL)
    if filters.date_from is not None:
        query = query.where(Opportunity.created_at >= filters.date_from)
    if filters.date_to is not None:
        query = query.where(Opportunity.created_at <= filters.date_to)

    if filters.search:
        # Company name, contact name or contact email. EXISTS rather than a join,
        # so a company with three matching contacts still yields one row.
        #
        # Aliased and explicitly correlated to Opportunity: without the alias a
        # sector filter (which joins Company) and this subquery would fight over
        # the same table, and without correlate() SQLAlchemy correlates every
        # table away and the subquery ends up with no FROM clause at all.
        term = f"%{filters.search.strip()}%"
        contact_alias = aliased(Contact)
        company_alias = aliased(Company)
        contact_match = (
            exists()
            .where(
                contact_alias.company_id == Opportunity.company_id,
                or_(contact_alias.name.ilike(term), contact_alias.email.ilike(term)),
            )
            .correlate(Opportunity)
        )
        company_match = (
            exists()
            .where(
                company_alias.id == Opportunity.company_id,
                company_alias.name.ilike(term),
            )
            .correlate(Opportunity)
        )
        query = query.where(or_(company_match, contact_match))

    if not filters.include_test:
        # Provenance lives on the source, reached through the signal.
        signal_alias = aliased(Signal)
        source_alias = aliased(Source)
        query = query.where(
            exists()
            .where(
                signal_alias.id == Opportunity.signal_id,
                source_alias.id == signal_alias.source_id,
                source_alias.ingest_mode != IngestMode.TEST,
            )
            .correlate(Opportunity)
        )
    return query


def apply_sort(
    query: Select[tuple[Opportunity]], filters: OpportunityFilters
) -> Select[tuple[Opportunity]]:
    """Order results, with a deterministic tie-break.

    Sorting by company needs a join; the rest are plain columns. Every ordering
    ends with created_at so the sequence is stable between identical requests.
    """
    if filters.sort is SortField.COMPANY:
        query = query.join(Company, Opportunity.company_id == Company.id)
        column = Company.name
    else:
        column = _SORT_COLUMNS[filters.sort]

    ordering = column.desc() if filters.descending else column.asc()
    # Score is the natural secondary key, but not when it is already the primary.
    tie_breaks = [Opportunity.created_at.asc()]
    if filters.sort is not SortField.SCORE:
        tie_breaks.insert(0, Opportunity.score.desc())
    return query.order_by(ordering, *tie_breaks)


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
    if filters.sort is SortField.SCORE and filters.descending:
        # The canonical ranking: score, then strength of the event case, then age.
        query = query.order_by(
            Opportunity.score.desc(),
            Opportunity.event_probability.desc(),
            Opportunity.created_at.asc(),
        )
    else:
        query = apply_sort(query, filters)
    query = query.limit(settings.top_n)

    return list(session.scalars(query).unique().all())


def list_opportunities(
    session: Session,
    filters: OpportunityFilters | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Opportunity]:
    """All opportunities matching the filters, highest score first."""
    filters = filters or OpportunityFilters()
    query = apply_sort(apply_filters(_base_query(), filters), filters)
    return list(session.scalars(query.limit(limit).offset(offset)).unique().all())


def get_opportunity(session: Session, opportunity_id: object) -> Opportunity | None:
    return session.scalars(_base_query().where(Opportunity.id == opportunity_id)).unique().first()


def count_opportunities(session: Session, filters: OpportunityFilters | None = None) -> int:
    """Total matching rows, for pagination."""
    from sqlalchemy import func

    query = apply_filters(select(func.count(Opportunity.id)), filters or OpportunityFilters())
    return int(session.scalar(query) or 0)
