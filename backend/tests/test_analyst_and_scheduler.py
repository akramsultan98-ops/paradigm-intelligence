"""Analyst intake (spec §5, §37) and the recurring cycle (spec §46)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import Extraction, ExtractionRequest
from app.ai.static import StaticExtractionProvider
from app.config import Settings
from app.domain.enums import IngestMode
from app.models import Company, Opportunity, Signal, Source
from app.services.analyst import ingest_analyst_signal
from app.services.scheduler import Scheduler, run_cycle
from app.services.top50 import OpportunityFilters, get_top_opportunities
from tests.conftest import requires_db

CONTENT = (
    "Elsewedy Electric agreed with Vodafone Business and Cassava Technologies to establish "
    "a data centre venture in Egypt, starting at 20 megawatts and scaling to 200 megawatts. "
    "The Ministry of Communications and Information Technology expects the project to attract "
    "USD 200 million initially and USD 1 billion on completion, according to the report."
)


def _extraction(**overrides) -> Extraction:
    payload = dict(
        company_name="Elsewedy Electric",
        company_sector="Industrial",
        signal_type="JOINT_VENTURE",
        signal_title="Elsewedy Electric forms data centre venture",
        possible_event=True,
        event_type="PARTNER_EVENT",
        event_probability=74,
        commercial_value=82,
        opportunity_window="DAYS_30_60",
        fact="The report states the three parties agreed to establish the venture.",
        inference="A three-party venture of this size would typically be marked publicly.",
        prediction="A signing or launch ceremony may follow. Not confirmed.",
        why_now="The agreement is days old and the first construction phase is imminent.",
        sales_angle="Signing ceremony and groundbreaking production.",
        recommended_services=["EVENT_MANAGEMENT", "STAGING", "BRANDING"],
        recommended_action="CONTACT_COMMUNICATIONS",
        factors={"announcement_scale": "MAJOR", "company_size": "ENTERPRISE",
                 "executive_involvement": True, "stakeholder_count": 8},
        confidence=0.85,
    )
    payload.update(overrides)
    return Extraction.model_validate(payload)


# --------------------------------------------------------------------------
# the static provider
# --------------------------------------------------------------------------

def test_static_provider_labels_the_extractor() -> None:
    """An analyst-entered signal must never look like automated extraction."""
    original = _extraction()
    provider = StaticExtractionProvider(original, extractor="analyst")
    out = provider.extract(
        ExtractionRequest(url="https://a.test/1", content="x")
    )
    assert out is not None
    assert out.extractor == "analyst"
    # The caller's object is not mutated.
    assert original.extractor == "unknown"


# --------------------------------------------------------------------------
# analyst intake through the real pipeline
# --------------------------------------------------------------------------

@requires_db
def test_analyst_signal_runs_the_whole_pipeline(session: Session, db_engine) -> None:
    stats = ingest_analyst_signal(
        url="https://example.test/news/venture",
        title="Elsewedy Electric forms data centre venture",
        content=CONTENT,
        extraction=_extraction(),
        published_at=datetime.now(UTC),
    )
    assert stats.sources_created == 1
    assert stats.signals_created == 1
    assert stats.opportunities_created == 1

    company = session.scalars(select(Company)).one()
    signal = session.scalars(select(Signal)).one()
    opportunity = session.scalars(select(Opportunity)).one()
    assert company.name == "Elsewedy Electric"
    assert signal.company_id == company.id
    assert opportunity.score > 0
    # The three statements are persisted separately.
    assert opportunity.fact and opportunity.inference and opportunity.prediction


@requires_db
def test_analyst_provenance_is_recorded(session: Session, db_engine) -> None:
    ingest_analyst_signal(
        url="https://example.test/news/1", title="T", content=CONTENT,
        extraction=_extraction(), published_at=datetime.now(UTC),
    )
    source = session.scalars(select(Source)).one()
    assert source.ingest_mode is IngestMode.ANALYST
    assert source.adapter_key == "analyst"


@requires_db
def test_analyst_signals_are_deduplicated(session: Session, db_engine) -> None:
    for _ in range(3):
        ingest_analyst_signal(
            url="https://example.test/news/1", title="T", content=CONTENT,
            extraction=_extraction(), published_at=datetime.now(UTC),
        )
    assert len(session.scalars(select(Source)).all()) == 1
    assert len(session.scalars(select(Opportunity)).all()) == 1


@requires_db
def test_analyst_signals_face_the_relevance_gate(session: Session, db_engine) -> None:
    """The analyst path is the same pipeline, filter included."""
    stats = ingest_analyst_signal(
        url="https://example.test/news/thin", title="Hi", content="Too short.",
        extraction=_extraction(), published_at=datetime.now(UTC),
    )
    assert stats.filtered_irrelevant == 1
    assert stats.sources_created == 0


@requires_db
def test_test_provenance_is_excluded_from_the_top_50(session: Session, db_engine) -> None:
    """Spec §37: fixtures must not reach the operational view.

    Scored high enough to qualify on merit, so the exclusion is what keeps it out
    rather than a low score doing it by accident.
    """
    from tests.factories import make_opportunity

    real = make_opportunity(session, score=88, company_name="Real Corp")
    fixture = make_opportunity(
        session, score=95, company_name="Fixture Corp", ingest_mode=IngestMode.TEST
    )

    default_view = get_top_opportunities(session)
    assert [o.id for o in default_view] == [real.id]

    with_test = get_top_opportunities(session, OpportunityFilters(include_test=True))
    # Both present, and the higher-scoring fixture now ranks first.
    assert [o.id for o in with_test] == [fixture.id, real.id]


@requires_db
def test_analyst_data_is_not_treated_as_test_data(session: Session, db_engine) -> None:
    """ANALYST is real, verified input. Only TEST is held back."""
    ingest_analyst_signal(
        url="https://example.test/news/venture", title="Elsewedy forms venture",
        content=CONTENT, extraction=_extraction(), published_at=datetime.now(UTC),
    )
    source = session.scalars(select(Source)).one()
    assert source.ingest_mode is IngestMode.ANALYST
    # Reachable in the ordinary listing, with no include_test needed.
    from app.services.top50 import list_opportunities

    assert len(list_opportunities(session)) == 1


# --------------------------------------------------------------------------
# the scheduler
# --------------------------------------------------------------------------

def test_scheduler_is_off_by_default() -> None:
    scheduler = Scheduler(Settings(postgres_password="t"))
    assert not scheduler.enabled
    assert scheduler.start() is False
    status = scheduler.status()
    assert status["enabled"] is False
    assert status["thread_alive"] is False
    assert status["last_cycle"] is None


@requires_db
def test_scheduler_runs_a_cycle_when_started(db_engine) -> None:
    import time

    settings = Settings(
        postgres_password="paradigm",
        scheduler_enabled=True,
        scheduler_interval_hours=1,
        scheduler_initial_delay_seconds=0,
    )
    scheduler = Scheduler(settings)
    assert scheduler.start() is True
    try:
        for _ in range(100):
            if scheduler.last_cycle is not None:
                break
            time.sleep(0.1)
        assert scheduler.last_cycle is not None
        assert scheduler.status()["thread_alive"] is True
    finally:
        scheduler.stop(timeout=5)
    assert scheduler.status()["thread_alive"] is False


@requires_db
def test_a_cycle_reports_each_stage(db_engine) -> None:
    """No sources configured is a valid, non-failing cycle."""
    result = run_cycle()
    assert result.error is None
    assert result.finished_at is not None
    payload = result.as_dict()
    for stage in ("ingestion", "contacts", "rescore"):
        assert stage in payload


def test_a_failing_stage_does_not_kill_the_thread(monkeypatch) -> None:
    """A failed cycle is recorded, not raised — the loop has to survive it."""
    import app.services.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("ingestion exploded")

    monkeypatch.setattr(pipeline, "run_ingestion", boom)
    result = run_cycle(Settings(postgres_password="t"))
    assert result.error is not None
    assert "ingestion exploded" in result.error
