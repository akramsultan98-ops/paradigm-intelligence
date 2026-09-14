"""Decay re-scoring and the daily brief."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.enums import BriefChange, Classification, OpportunityStatus
from app.models import Opportunity
from app.services.brief import build_daily_brief
from app.services.rescore import classification_counts, eligible_count, rescore_all
from tests.conftest import requires_db
from tests.factories import make_opportunity

pytestmark = requires_db


# --------------------------------------------------------------------------
# rescore
# --------------------------------------------------------------------------

def test_rescore_leaves_fresh_opportunities_alone(session: Session, db_engine) -> None:
    make_opportunity(session, score=85, signal_age_days=1)
    stats = rescore_all(session)
    assert stats.examined == 1
    assert stats.changed == 0


def test_rescore_decays_an_old_opportunity(session: Session, db_engine) -> None:
    opportunity = make_opportunity(session, score=85, base_score=85, signal_age_days=200)
    original = opportunity.score

    stats = rescore_all(session)
    session.expire_all()
    refreshed = session.get(Opportunity, opportunity.id)

    assert stats.changed == 1
    assert refreshed is not None
    assert refreshed.score < original
    assert float(refreshed.decay_factor) < 1.0
    # The movement is recorded for the brief.
    assert refreshed.previous_score == original
    assert refreshed.score_changed_at is not None


def test_a_decayed_opportunity_drops_out_of_the_top_50(session: Session, db_engine) -> None:
    """Spec §28: a stale opportunity must leave the list on its own."""
    make_opportunity(session, score=80, base_score=80, signal_age_days=400)
    stats = rescore_all(session)
    assert stats.dropped_below_threshold == 1
    assert eligible_count(session) == 0


def test_rescore_ignores_closed_opportunities(session: Session, db_engine) -> None:
    make_opportunity(session, score=90, signal_age_days=300, status=OpportunityStatus.WON)
    assert rescore_all(session).examined == 0


def test_rescore_is_idempotent(session: Session, db_engine) -> None:
    """Running it twice in a day must not decay twice."""
    make_opportunity(session, score=85, base_score=85, signal_age_days=120)
    first = rescore_all(session)
    second = rescore_all(session)
    assert first.changed == 1
    assert second.changed == 0


def test_rescore_recomputes_from_base_score_not_the_decayed_score(
    session: Session, db_engine
) -> None:
    """Compounding decay would sink everything to the floor within days."""
    opportunity = make_opportunity(session, score=90, base_score=90, signal_age_days=60)
    rescore_all(session)
    session.expire_all()
    after_first = session.get(Opportunity, opportunity.id)
    assert after_first is not None
    score_after_first = after_first.score

    rescore_all(session)
    session.expire_all()
    after_second = session.get(Opportunity, opportunity.id)
    assert after_second is not None
    assert after_second.score == score_after_first
    assert after_second.base_score == 90


def test_classification_counts_cover_every_band(session: Session, db_engine) -> None:
    make_opportunity(session, score=96)
    make_opportunity(session, score=75)
    counts = classification_counts(session)
    assert set(counts) == {band.value for band in Classification}
    assert counts["EXCEPTIONAL"] == 1
    assert counts["QUALIFIED"] == 1


# --------------------------------------------------------------------------
# the daily brief
# --------------------------------------------------------------------------

def test_brief_reports_new_opportunities(session: Session, db_engine) -> None:
    make_opportunity(session, score=92, company_name="Fresh Industries")
    old = datetime.now(UTC) - timedelta(days=5)
    make_opportunity(session, score=88, company_name="Older Holdings", created_at=old)

    brief = build_daily_brief(session)
    assert [o.company.name for o in brief.new_opportunities] == ["Fresh Industries"]


def test_brief_identifies_new_hot(session: Session, db_engine) -> None:
    make_opportunity(session, score=93, company_name="Hot Company")
    make_opportunity(session, score=72, company_name="Merely Qualified")
    brief = build_daily_brief(session)
    assert [o.company.name for o in brief.new_hot] == ["Hot Company"]


def test_brief_separates_upgrades_downgrades_and_expiries(
    session: Session, db_engine
) -> None:
    changed_at = datetime.now(UTC) - timedelta(hours=2)
    created = datetime.now(UTC) - timedelta(days=10)

    make_opportunity(session, score=90, previous_score=80, company_name="Rising Corp",
                     created_at=created, score_changed_at=changed_at)
    make_opportunity(session, score=75, previous_score=88, company_name="Falling Corp",
                     created_at=created, score_changed_at=changed_at)
    make_opportunity(session, score=55, previous_score=82, company_name="Expired Corp",
                     created_at=created, score_changed_at=changed_at)

    brief = build_daily_brief(session)
    assert [o.opportunity.company.name for o in brief.upgraded] == ["Rising Corp"]
    assert [o.opportunity.company.name for o in brief.downgraded] == ["Falling Corp"]
    assert [o.opportunity.company.name for o in brief.expired] == ["Expired Corp"]

    # An expiry is reported as expired, not merely as a downgrade.
    assert all(o.change is BriefChange.EXPIRED for o in brief.expired)
    assert brief.expired[0].delta == 55 - 82


def test_brief_changed_list_is_ordered_by_movement(session: Session, db_engine) -> None:
    changed_at = datetime.now(UTC) - timedelta(hours=1)
    created = datetime.now(UTC) - timedelta(days=10)
    make_opportunity(session, score=82, previous_score=80, company_name="Small Move",
                     created_at=created, score_changed_at=changed_at)
    make_opportunity(session, score=95, previous_score=71, company_name="Big Move",
                     created_at=created, score_changed_at=changed_at)

    brief = build_daily_brief(session)
    assert [o.opportunity.company.name for o in brief.changed_opportunities] == [
        "Big Move", "Small Move"
    ]


def test_a_brand_new_opportunity_is_not_also_reported_as_changed(
    session: Session, db_engine
) -> None:
    make_opportunity(session, score=90, previous_score=80, company_name="Brand New",
                     score_changed_at=datetime.now(UTC))
    brief = build_daily_brief(session)
    assert [o.company.name for o in brief.new_opportunities] == ["Brand New"]
    assert brief.changed_opportunities == []


def test_brief_carries_the_current_top_50_and_honest_totals(
    session: Session, db_engine
) -> None:
    for score in (95, 88, 74):
        make_opportunity(session, score=score)
    make_opportunity(session, score=40)

    brief = build_daily_brief(session)
    assert len(brief.top_opportunities) == 3
    assert brief.eligible_total == 3
    assert brief.top_n == 50
    assert brief.qualifying_threshold == 70


def test_brief_window_is_configurable(session: Session, db_engine) -> None:
    make_opportunity(session, score=90, company_name="Two Days Old",
                     created_at=datetime.now(UTC) - timedelta(days=2))
    assert build_daily_brief(session, window_hours=24).new_opportunities == []
    wide = build_daily_brief(session, window_hours=24 * 7)
    assert [o.company.name for o in wide.new_opportunities] == ["Two Days Old"]


def test_brief_on_an_empty_database(session: Session, db_engine) -> None:
    brief = build_daily_brief(session)
    assert brief.new_opportunities == []
    assert brief.top_opportunities == []
    assert brief.eligible_total == 0
    assert brief.generated_at.tzinfo is not None
