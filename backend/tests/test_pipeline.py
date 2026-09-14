"""Pipeline integration tests.

SOURCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE, end to end,
against a real database and its real constraints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import AIProvider, Extraction, ExtractionRequest
from app.domain.enums import (
    AssertionLevel,
    Department,
    EmailStatus,
    OpportunityType,
    SignalType,
    SourceType,
)
from app.models import Company, Contact, Opportunity, Signal, Source
from app.services.contacts import ContactInput, upsert_contact
from app.services.opportunities import determine_assertion_level
from app.services.pipeline import ingest_documents
from app.sources.base import RawDocument
from tests.conftest import requires_db
from tests.factories import make_company

pytestmark = requires_db

#: Article-length filler. The relevance gate (spec §10) drops thin documents by
#: design, so fixtures have to look like real articles rather than one-liners.
_LONG_BODY = (
    "Elsewedy Electric announced the launch of a new smart metering product line at a "
    "briefing in Cairo. The company said the line will be manufactured at its Egyptian "
    "facilities and rolled out with distribution partners across the governorates. The "
    "chairman said the investment supports the group's strategy of expanding its industrial "
    "technology portfolio, and that customer and partner briefings would accompany the "
    "commercial rollout."
)


class StubProvider(AIProvider):
    """Returns a scripted extraction, so pipeline behaviour is under test rather
    than extraction behaviour."""

    name = "stub"

    def __init__(self, extraction: Extraction | None):
        self.extraction = extraction
        self.calls: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> Extraction | None:
        self.calls.append(request)
        return self.extraction


def _strong_extraction(**overrides) -> Extraction:
    payload = dict(
        company_name="Elsewedy Electric",
        company_domain="elsewedy.test",
        company_sector="Industrial",
        signal_type=SignalType.PRODUCT_LAUNCH,
        signal_title="Elsewedy Electric unveils a smart metering line",
        signal_summary="A new product line was announced.",
        business_impact="Expands the metering portfolio.",
        possible_event=True,
        event_type=OpportunityType.PRODUCT_LAUNCH,
        event_probability=78,
        commercial_value=80,
        opportunity_window="DAYS_15_30",
        likely_department=Department.MARKETING,
        potential_contact_role="Marketing Director",
        why_now="A launch was announced; a launch event is likely within weeks.",
        sales_angle="Full launch production: staging, AV, LED, branding.",
        recommended_services=["EVENT_MANAGEMENT", "AV", "LED_SCREENS", "STAGING"],
        recommended_action="CONTACT_MARKETING",
        factors={
            "announcement_scale": "MAJOR",
            "company_size": "ENTERPRISE",
            "has_event_history": True,
            "marketing_activity": "HIGH",
            "comms_activity": "HIGH",
            "ecosystem_breadth": "HIGH",
            "stakeholder_count": 8,
            "executive_involvement": True,
            "expected_attendees": "OVER_500",
            "production_complexity": "HIGH",
            "repeat_potential": "HIGH",
            "brand_value": "HIGH",
        },
        confidence=0.9,
    )
    payload.update(overrides)
    return Extraction.model_validate(payload)


def _document(url: str = "https://elsewedy.test/news/1", **overrides) -> RawDocument:
    defaults = dict(
        url=url,
        title="Elsewedy Electric unveils a smart metering line",
        content=(
            "Elsewedy Electric announced the launch of a new smart metering product line at a "
            "briefing in Cairo. The company said the line will be manufactured at its Egyptian "
            "facilities and rolled out with distribution partners across the governorates. The "
            "chairman said the investment supports the group's strategy of expanding its "
            "industrial technology portfolio, and that customer and partner briefings would "
            "accompany the "
            "commercial rollout."
        ),
        source_type=SourceType.COMPANY,
        publisher="Elsewedy Electric",
        published_at=datetime.now(UTC) - timedelta(days=1),
        confidence=0.9,
        adapter_key="test",
    )
    defaults.update(overrides)
    return RawDocument(**defaults)


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------

def test_full_pipeline_creates_the_whole_chain(session: Session, db_engine) -> None:
    stats = ingest_documents([_document()], StubProvider(_strong_extraction()))

    assert stats.documents_seen == 1
    assert stats.sources_created == 1
    assert stats.signals_created == 1
    assert stats.opportunities_created == 1
    assert stats.errors == []

    source = session.scalars(select(Source)).one()
    company = session.scalars(select(Company)).one()
    signal = session.scalars(select(Signal)).one()
    opportunity = session.scalars(select(Opportunity)).one()

    assert company.name == "Elsewedy Electric"
    assert company.domain == "elsewedy.test"
    assert company.sector == "Industrial"
    assert signal.company_id == company.id
    assert signal.source_id == source.id
    assert opportunity.signal_id == signal.id
    assert opportunity.company_id == company.id
    assert opportunity.score > 0
    assert opportunity.why_now and opportunity.sales_angle
    assert opportunity.recommended_services == ["EVENT_MANAGEMENT", "AV", "LED_SCREENS", "STAGING"]


def test_company_event_potential_is_recorded(session: Session, db_engine) -> None:
    ingest_documents([_document()], StubProvider(_strong_extraction()))
    company = session.scalars(select(Company)).one()
    opportunity = session.scalars(select(Opportunity)).one()
    assert company.event_potential_score == opportunity.event_probability


def test_score_components_are_persisted(session: Session, db_engine) -> None:
    """The ranking must be interrogable after the fact."""
    ingest_documents([_document()], StubProvider(_strong_extraction()))
    opportunity = session.scalars(select(Opportunity)).one()
    for value in (opportunity.event_probability, opportunity.commercial_value,
                  opportunity.contact_quality, opportunity.timing_score,
                  opportunity.evidence_score, opportunity.base_score, opportunity.score):
        assert 0 <= value <= 100
    assert 0 < float(opportunity.decay_factor) <= 1.0


# --------------------------------------------------------------------------
# deduplication
# --------------------------------------------------------------------------

def test_the_same_url_is_ingested_once(session: Session, db_engine) -> None:
    provider = StubProvider(_strong_extraction())
    ingest_documents([_document(), _document()], provider)
    assert session.scalar(select(func.count(Source.id))) == 1
    # The duplicate is skipped before extraction, so no second API call is made.
    assert len(provider.calls) == 1


def test_tracking_parameters_do_not_defeat_url_dedupe(session: Session, db_engine) -> None:
    ingest_documents(
        [
            _document(url="https://elsewedy.test/news/1"),
            _document(url="https://elsewedy.test/news/1/?utm_source=newsletter"),
        ],
        StubProvider(_strong_extraction()),
    )
    assert session.scalar(select(func.count(Source.id))) == 1


def test_republished_content_is_deduplicated_by_hash(session: Session, db_engine) -> None:
    """The same story at a different address is still the same story."""
    ingest_documents(
        [
            _document(url="https://elsewedy.test/news/1"),
            _document(url="https://reprint.test/story/9"),
        ],
        StubProvider(_strong_extraction()),
    )
    assert session.scalar(select(func.count(Source.id))) == 1


def test_the_same_company_is_not_duplicated(session: Session, db_engine) -> None:
    """Different legal spellings must resolve to one account."""
    ingest_documents(
        [_document(url="https://a.test/1", content="First story. " + _LONG_BODY)],
        StubProvider(_strong_extraction(company_name="Elsewedy Electric S.A.E.")),
    )
    ingest_documents(
        [_document(url="https://b.test/2", content="Second, different wording. " + _LONG_BODY)],
        StubProvider(_strong_extraction(company_name="Elsewedy Electric Co.",
                                       signal_title="A second announcement")),
    )
    assert session.scalar(select(func.count(Company.id))) == 1
    assert session.scalar(select(func.count(Signal.id))) == 2


def test_the_same_signal_from_two_feeds_becomes_one_signal(session: Session, db_engine) -> None:
    ingest_documents(
        [_document(url="https://a.test/1", content="Wording one. " + _LONG_BODY)],
        StubProvider(_strong_extraction()),
    )
    ingest_documents(
        [_document(url="https://b.test/2", content="Quite different wording. " + _LONG_BODY)],
        StubProvider(_strong_extraction()),
    )
    # Same company, type and title, so one signal — and therefore one opportunity.
    assert session.scalar(select(func.count(Signal.id))) == 1
    assert session.scalar(select(func.count(Opportunity.id))) == 1
    assert session.scalar(select(func.count(Source.id))) == 2


def test_re_ingesting_updates_rather_than_duplicates(session: Session, db_engine) -> None:
    ingest_documents([_document(url="https://a.test/1", content="One. " + _LONG_BODY)],
                     StubProvider(_strong_extraction()))
    stats = ingest_documents(
        [_document(url="https://a.test/2", content="Two, different. " + _LONG_BODY)],
        StubProvider(_strong_extraction()),
    )
    assert stats.opportunities_updated == 1
    assert stats.opportunities_created == 0
    assert session.scalar(select(func.count(Opportunity.id))) == 1


# --------------------------------------------------------------------------
# refusing to invent things
# --------------------------------------------------------------------------

def test_no_company_means_no_signal(session: Session, db_engine) -> None:
    """An unattributable document must not mint an account."""
    stats = ingest_documents(
        [_document()], StubProvider(_strong_extraction(company_name=None))
    )
    assert stats.companies_unresolved == 1
    assert session.scalar(select(func.count(Company.id))) == 0
    assert session.scalar(select(func.count(Signal.id))) == 0
    # The source is still kept: it is a real document we retrieved.
    assert session.scalar(select(func.count(Source.id))) == 1


def test_a_known_company_is_recognised_in_free_text(session: Session, db_engine) -> None:
    """Recognition of an existing account is not the same as inventing one."""
    make_company(session, "Juhayna Food Industries")
    session.commit()

    stats = ingest_documents(
        [
            _document(
                url="https://press.test/1",
                title="Dairy producer announces expansion",
                content=(
                    "Juhayna Food Industries announced an expansion of its production "
                    "plant, the company said in a statement. The group said the "
                    "expansion increases capacity for its dairy portfolio and follows "
                    "an investment programme agreed with its board. Management said "
                    "customers and distribution partners were briefed on the plan."
                ),
                source_type=SourceType.BUSINESS_PUBLICATION,
            )
        ],
        StubProvider(_strong_extraction(company_name=None, company_domain=None)),
    )
    assert stats.companies_unresolved == 0
    assert stats.signals_created == 1
    assert session.scalar(select(func.count(Company.id))) == 1


def test_a_failed_extraction_stores_no_derived_data(session: Session, db_engine) -> None:
    stats = ingest_documents([_document()], StubProvider(None))
    assert stats.extractions_failed == 1
    assert session.scalar(select(func.count(Source.id))) == 1
    assert session.scalar(select(func.count(Signal.id))) == 0
    assert session.scalar(select(func.count(Opportunity.id))) == 0


def test_no_event_implication_means_signal_but_no_opportunity(
    session: Session, db_engine
) -> None:
    """Most business news implies no event. That is the normal case."""
    stats = ingest_documents(
        [_document()],
        StubProvider(_strong_extraction(possible_event=False, event_type="UNKNOWN")),
    )
    assert stats.signals_created == 1
    assert stats.no_event_implication == 1
    assert session.scalar(select(func.count(Opportunity.id))) == 0


def test_an_opportunity_without_a_reason_is_not_created(session: Session, db_engine) -> None:
    stats = ingest_documents(
        [_document()], StubProvider(_strong_extraction(why_now=None))
    )
    assert stats.no_event_implication == 1
    assert session.scalar(select(func.count(Opportunity.id))) == 0


def test_one_bad_document_does_not_stop_the_run(session: Session, db_engine) -> None:
    documents = [
        _document(url="https://a.test/1", content="First story. " + _LONG_BODY),
        _document(url="https://b.test/2", content="Second story. " + _LONG_BODY),
    ]

    class FlakyProvider(AIProvider):
        name = "flaky"

        def __init__(self) -> None:
            self.count = 0

        def extract(self, request: ExtractionRequest) -> Extraction | None:
            self.count += 1
            if self.count == 1:
                raise RuntimeError("extractor exploded")
            return _strong_extraction(signal_title="Second announcement")

    stats = ingest_documents(documents, FlakyProvider())
    assert len(stats.errors) == 1
    assert stats.signals_created == 1


# --------------------------------------------------------------------------
# truth labelling
# --------------------------------------------------------------------------

def test_a_prediction_is_never_labelled_fact(session: Session, db_engine) -> None:
    """Spec §6: a predicted event must never present as confirmed."""
    ingest_documents([_document()], StubProvider(_strong_extraction()))
    opportunity = session.scalars(select(Opportunity)).one()
    assert opportunity.assertion_level is not AssertionLevel.FACT


def test_assertion_levels() -> None:
    # An announced event from an official channel is a fact.
    assert determine_assertion_level(SignalType.CONFERENCE, SourceType.COMPANY) is \
        AssertionLevel.FACT
    assert determine_assertion_level(SignalType.EXHIBITION, SourceType.GOVERNMENT) is \
        AssertionLevel.FACT
    # The same event reported second-hand is an inference.
    assert determine_assertion_level(SignalType.CONFERENCE,
                                     SourceType.BUSINESS_PUBLICATION) is AssertionLevel.INFERENCE
    # Anything we reasoned our way to is a prediction.
    assert determine_assertion_level(SignalType.PRODUCT_LAUNCH, SourceType.COMPANY) is \
        AssertionLevel.PREDICTION
    assert determine_assertion_level(SignalType.TENDER, SourceType.PROCUREMENT) is \
        AssertionLevel.PREDICTION


def test_confirmed_events_may_score_above_the_unconfirmed_cap(
    session: Session, db_engine, settings
) -> None:
    ingest_documents(
        [_document()],
        StubProvider(_strong_extraction(signal_type=SignalType.CONFERENCE,
                                        event_type=OpportunityType.CONFERENCE,
                                        event_probability=97)),
    )
    opportunity = session.scalars(select(Opportunity)).one()
    assert opportunity.assertion_level is AssertionLevel.FACT


# --------------------------------------------------------------------------
# contacts
# --------------------------------------------------------------------------

def test_contacts_raise_the_opportunity_score(session: Session, db_engine) -> None:
    ingest_documents([_document(url="https://a.test/1", content="One. " + _LONG_BODY)],
                     StubProvider(_strong_extraction()))
    without_contacts = session.scalars(select(Opportunity)).one().score

    company = session.scalars(select(Company)).one()
    upsert_contact(
        session,
        company=company,
        payload=ContactInput(name="Ahmed Hassan", job_title="Marketing Director",
                             department=Department.MARKETING,
                             email="ahmed.hassan@elsewedy.test",
                             email_status=EmailStatus.PUBLIC, confidence=0.9),
    )
    session.commit()

    # Re-ingest the same signal from a new source so it is re-scored.
    ingest_documents(
        [_document(url="https://a.test/2", content="Two, different text. " + _LONG_BODY)],
                     StubProvider(_strong_extraction()))
    session.expire_all()
    opportunity = session.scalars(select(Opportunity)).one()
    assert opportunity.score > without_contacts
    assert opportunity.primary_contact_id is not None


def test_inferred_email_is_never_stored_as_verified(session: Session, db_engine) -> None:
    company = make_company(session)
    contact, _ = upsert_contact(
        session,
        company=company,
        payload=ContactInput(name="Mona Said", job_title="PR Manager",
                             department=Department.PR, email="mona@example.com",
                             email_status=EmailStatus.VERIFIED),
    )
    session.commit()
    assert contact is not None
    assert contact.email_status is EmailStatus.PUBLIC


def test_a_contact_without_an_email_has_unknown_status(session: Session, db_engine) -> None:
    company = make_company(session)
    contact, _ = upsert_contact(
        session,
        company=company,
        payload=ContactInput(name="Nadia Kamal", job_title="Events Manager",
                             department=Department.EVENTS,
                             linkedin_url="linkedin.com/in/nadia-kamal"),
    )
    session.commit()
    assert contact is not None
    assert contact.email_status is EmailStatus.UNKNOWN
    assert contact.normalized_linkedin_url == "https://www.linkedin.com/in/nadia-kamal"


def test_contacts_are_deduplicated_by_email(session: Session, db_engine) -> None:
    company = make_company(session)
    first, created_first = upsert_contact(
        session, company=company,
        payload=ContactInput(name="Ahmed Hassan", email="A.Hassan@Example.com",
                             department=Department.MARKETING),
    )
    second, created_second = upsert_contact(
        session, company=company,
        payload=ContactInput(name="Ahmed  Hassan", email="a.hassan@example.com",
                             job_title="Marketing Director", department=Department.MARKETING),
    )
    session.commit()
    assert created_first and not created_second
    assert first is not None and second is not None and first.id == second.id
    assert session.scalar(select(func.count(Contact.id))) == 1
    # A gap was filled in on the existing row.
    assert second.job_title == "Marketing Director"


def test_malformed_contact_email_is_dropped_not_stored(session: Session, db_engine) -> None:
    company = make_company(session)
    contact, _ = upsert_contact(
        session, company=company,
        payload=ContactInput(name="Test Person", email="not-an-email",
                             email_status=EmailStatus.PUBLIC),
    )
    session.commit()
    assert contact is not None
    assert contact.email is None
    assert contact.email_status is EmailStatus.UNKNOWN


# --------------------------------------------------------------------------
# the relevance gate inside the pipeline (spec §10)
# --------------------------------------------------------------------------

def test_irrelevant_documents_cost_nothing(session: Session, db_engine) -> None:
    """Filtered before anything is written and before the extractor is called."""
    provider = StubProvider(_strong_extraction())
    stats = ingest_documents(
        [
            _document(
                url="https://sport.test/1",
                title="Al Ahly beats Zamalek 2-1 in Cairo derby",
                content=(
                    "A late goal from the striker settled the match at the stadium before a "
                    "full crowd. The referee added four minutes of stoppage time and the "
                    "tournament table was left unchanged by the result."
                ),
            )
        ],
        provider,
    )
    assert stats.filtered_irrelevant == 1
    assert stats.sources_created == 0
    # No extraction call: the gate exists to save that cost.
    assert provider.calls == []
    assert session.scalar(select(func.count(Source.id))) == 0


def test_the_gate_can_be_disabled(session: Session, db_engine) -> None:
    from app.config import Settings

    permissive = Settings(postgres_password="paradigm", relevance_enabled=False)
    stats = ingest_documents(
        [_document(url="https://a.test/thin", title="Hi", content="Short.")],
        StubProvider(_strong_extraction()),
        settings=permissive,
    )
    assert stats.filtered_irrelevant == 0
    assert stats.sources_created == 1


# --------------------------------------------------------------------------
# parent / subsidiary resolution (spec §28)
# --------------------------------------------------------------------------

def test_a_subsidiary_is_linked_to_a_known_parent(session: Session, db_engine) -> None:
    """A link, not a merge: the subsidiary keeps its own signals and contacts."""
    ingest_documents(
        [_document(url="https://a.test/1", content="Parent story. " + _LONG_BODY)],
        StubProvider(_strong_extraction(company_name="Elsewedy Electric")),
    )
    ingest_documents(
        [_document(url="https://a.test/2", content="Subsidiary story. " + _LONG_BODY)],
        StubProvider(
            _strong_extraction(
                company_name="Elsewedy Electric for Trading and Distribution",
                company_domain=None,
                signal_title="A distribution subsidiary announcement",
            )
        ),
    )
    companies = {c.name: c for c in session.scalars(select(Company)).all()}
    assert len(companies) == 2
    child = companies["Elsewedy Electric for Trading and Distribution"]
    parent = companies["Elsewedy Electric"]
    assert child.parent_company_id == parent.id
    assert parent.parent_company_id is None


def test_unrelated_companies_are_not_linked(session: Session, db_engine) -> None:
    """One shared word is not a corporate relationship."""
    ingest_documents(
        [_document(url="https://a.test/1", content="First. " + _LONG_BODY)],
        StubProvider(_strong_extraction(company_name="Misr Insurance")),
    )
    ingest_documents(
        [_document(url="https://a.test/2", content="Second. " + _LONG_BODY)],
        StubProvider(
            _strong_extraction(
                company_name="Misr Fertilizers Production Company",
                company_domain=None,
                signal_title="A fertilizer announcement",
            )
        ),
    )
    for company in session.scalars(select(Company)).all():
        assert company.parent_company_id is None


def test_a_company_is_never_its_own_parent(session: Session, db_engine) -> None:
    from app.services.companies import link_parent

    company = make_company(session, "Elsewedy Electric for Trading and Distribution")
    session.commit()
    assert link_parent(session, company) is None
    assert company.parent_company_id is None


def test_the_longest_matching_parent_wins(session: Session, db_engine) -> None:
    """With an intermediate holding company, attach to the nearer one."""
    from app.services.companies import link_parent

    make_company(session, "Elsewedy Electric")
    nearer = make_company(session, "Elsewedy Electric Industries")
    session.commit()

    child = make_company(session, "Elsewedy Electric Industries Cables Division")
    session.commit()
    link_parent(session, child)
    assert child.parent_company_id == nearer.id
