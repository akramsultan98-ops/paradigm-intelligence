"""Top 50 selection.

Spec §12 has three rules and they are all load-bearing: a 70-point floor, ranking
by strength rather than recency, and never padding the list.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.enums import (
    Classification,
    OpportunityStatus,
    OpportunityTiming,
    OpportunityType,
)
from app.services.top50 import OpportunityFilters, get_top_opportunities, list_opportunities
from tests.conftest import requires_db
from tests.factories import make_opportunity

pytestmark = requires_db


def test_only_qualifying_opportunities_are_eligible(session: Session, settings) -> None:
    make_opportunity(session, score=95)
    make_opportunity(session, score=70)
    make_opportunity(session, score=69)
    make_opportunity(session, score=10)

    scores = [o.score for o in get_top_opportunities(session, settings=settings)]
    assert scores == [95, 70]
    assert all(score >= settings.min_qualifying_score for score in scores)


def test_the_list_is_ranked_by_score(session: Session, settings) -> None:
    for score in (72, 96, 84, 91, 78):
        make_opportunity(session, score=score)
    scores = [o.score for o in get_top_opportunities(session, settings=settings)]
    assert scores == [96, 91, 84, 78, 72]


def test_a_new_opportunity_only_displaces_a_stronger_one_by_being_stronger(
    session: Session,
) -> None:
    """Ranking by score, not recency: nothing gets in for being new."""
    tight = Settings(postgres_password="t", top_n=2)
    make_opportunity(session, score=90, company_name="Alpha Industries")
    make_opportunity(session, score=85, company_name="Beta Holdings")

    # A weaker newcomer must not enter a full list.
    make_opportunity(session, score=75, company_name="Gamma Trading")
    names = [o.company.name for o in get_top_opportunities(session, settings=tight)]
    assert names == ["Alpha Industries", "Beta Holdings"]

    # A stronger newcomer displaces the weakest incumbent.
    make_opportunity(session, score=99, company_name="Delta Energy")
    names = [o.company.name for o in get_top_opportunities(session, settings=tight)]
    assert names == ["Delta Energy", "Alpha Industries"]


def test_a_short_list_is_not_padded(session: Session, settings) -> None:
    """A 3-row Top 50 is a correct Top 50."""
    for score in (88, 80, 74):
        make_opportunity(session, score=score)
    for score in (65, 40, 12):
        make_opportunity(session, score=score)

    top = get_top_opportunities(session, settings=settings)
    assert len(top) == 3
    assert len(top) < settings.top_n


def test_top_n_is_respected(session: Session) -> None:
    for index in range(8):
        make_opportunity(session, score=95 - index)
    limited = Settings(postgres_password="t", top_n=5)
    assert len(get_top_opportunities(session, settings=limited)) == 5


def test_closed_opportunities_leave_the_list(session: Session, settings) -> None:
    make_opportunity(session, score=99, status=OpportunityStatus.WON)
    make_opportunity(session, score=98, status=OpportunityStatus.LOST)
    live = make_opportunity(session, score=80, status=OpportunityStatus.CONTACTED)
    nurture = make_opportunity(session, score=79, status=OpportunityStatus.NURTURE)

    ids = {o.id for o in get_top_opportunities(session, settings=settings)}
    assert ids == {live.id, nurture.id}


def test_ties_break_deterministically(session: Session, settings) -> None:
    """Stable order between runs, not arbitrary order."""
    make_opportunity(session, score=80, company_name="First Mover")
    make_opportunity(session, score=80, company_name="Second Mover")
    first = [o.id for o in get_top_opportunities(session, settings=settings)]
    second = [o.id for o in get_top_opportunities(session, settings=settings)]
    assert first == second


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------

def test_sector_filter(session: Session, settings) -> None:
    make_opportunity(session, score=90, sector="Banking", company_name="Bank One")
    make_opportunity(session, score=95, sector="Technology", company_name="Tech One")
    results = get_top_opportunities(
        session, OpportunityFilters(sector="Banking"), settings=settings
    )
    assert [o.company.sector for o in results] == ["Banking"]


def test_min_score_filter_cannot_lower_the_threshold(session: Session, settings) -> None:
    """A permissive filter must not smuggle a sub-threshold lead into the Top 50."""
    make_opportunity(session, score=60)
    make_opportunity(session, score=90)
    results = get_top_opportunities(
        session, OpportunityFilters(min_score=10), settings=settings
    )
    assert [o.score for o in results] == [90]


def test_min_score_filter_can_raise_the_threshold(session: Session, settings) -> None:
    make_opportunity(session, score=75)
    make_opportunity(session, score=92)
    results = get_top_opportunities(
        session, OpportunityFilters(min_score=90), settings=settings
    )
    assert [o.score for o in results] == [92]


def test_status_and_type_filters(session: Session, settings) -> None:
    make_opportunity(session, score=90, status=OpportunityStatus.NEW,
                     opportunity_type=OpportunityType.CONFERENCE)
    make_opportunity(session, score=88, status=OpportunityStatus.CONTACTED,
                     opportunity_type=OpportunityType.PRODUCT_LAUNCH)

    by_status = get_top_opportunities(
        session, OpportunityFilters(status=OpportunityStatus.NEW), settings=settings
    )
    assert [o.status for o in by_status] == [OpportunityStatus.NEW]

    by_type = get_top_opportunities(
        session,
        OpportunityFilters(opportunity_type=OpportunityType.PRODUCT_LAUNCH),
        settings=settings,
    )
    assert [o.type for o in by_type] == [OpportunityType.PRODUCT_LAUNCH]


def test_classification_filter(session: Session, settings) -> None:
    make_opportunity(session, score=96)
    make_opportunity(session, score=75)
    results = get_top_opportunities(
        session, OpportunityFilters(classification=Classification.EXCEPTIONAL), settings=settings
    )
    assert [o.classification for o in results] == [Classification.EXCEPTIONAL]


def test_date_filters(session: Session, settings) -> None:
    now = datetime.now(UTC)
    make_opportunity(session, score=90, created_at=now - timedelta(days=30),
                     company_name="Old Company")
    make_opportunity(session, score=88, created_at=now - timedelta(hours=1),
                     company_name="New Company")

    recent = get_top_opportunities(
        session, OpportunityFilters(date_from=now - timedelta(days=2)), settings=settings
    )
    assert [o.company.name for o in recent] == ["New Company"]

    old = get_top_opportunities(
        session, OpportunityFilters(date_to=now - timedelta(days=2)), settings=settings
    )
    assert [o.company.name for o in old] == ["Old Company"]


def test_list_opportunities_includes_sub_threshold_rows(session: Session) -> None:
    """The full list is for analysis; the Top 50 is the product."""
    make_opportunity(session, score=90)
    make_opportunity(session, score=20)
    assert len(list_opportunities(session)) == 2


def test_list_opportunities_paginates(session: Session) -> None:
    for index in range(5):
        make_opportunity(session, score=90 - index)
    page = list_opportunities(session, limit=2, offset=2)
    assert [o.score for o in page] == [88, 87]


def test_empty_database_returns_an_empty_list(session: Session, settings) -> None:
    assert get_top_opportunities(session, settings=settings) == []


# --- timing (Priority 4) -------------------------------------------------


def test_a_past_event_is_not_ranked_as_if_it_were_upcoming(
    session: Session, settings
) -> None:
    """The rule the timing work exists for. A high score does not resurrect it."""
    make_opportunity(
        session,
        score=95,
        company_name="Already Happened Industries",
        event_date=date.today() - timedelta(days=30),
    )
    make_opportunity(
        session,
        score=75,
        company_name="Still Biddable Holdings",
        event_date=date.today() + timedelta(days=45),
    )

    ranked = get_top_opportunities(session, settings=settings)
    assert [o.company.name for o in ranked] == ["Still Biddable Holdings"]


def test_past_events_are_available_when_explicitly_asked_for(
    session: Session, settings
) -> None:
    """Account research is a real use; it just is not the ranking."""
    make_opportunity(
        session,
        score=95,
        company_name="Research Only",
        event_date=date.today() - timedelta(days=30),
    )
    ranked = get_top_opportunities(
        session, OpportunityFilters(include_historical=True), settings=settings
    )
    assert [o.company.name for o in ranked] == ["Research Only"]


def test_timing_can_be_filtered_directly(session: Session, settings) -> None:
    make_opportunity(
        session, score=90, company_name="Bid Now", event_date=date.today() + timedelta(days=60)
    )
    make_opportunity(
        session,
        score=88,
        company_name="Build The Account",
        event_date=date.today() + timedelta(days=10),
    )

    immediate = get_top_opportunities(
        session,
        OpportunityFilters(timing=OpportunityTiming.IMMEDIATE),
        settings=settings,
    )
    assert [o.company.name for o in immediate] == ["Bid Now"]

    future = get_top_opportunities(
        session,
        OpportunityFilters(timing=OpportunityTiming.FUTURE_ACCOUNT),
        settings=settings,
    )
    assert [o.company.name for o in future] == ["Build The Account"]
