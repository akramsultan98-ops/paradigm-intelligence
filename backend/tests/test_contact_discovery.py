"""Contact discovery tests (spec §14, §15).

Two things are being protected. First, that the parser finds the people who
actually matter to event spend. Second, and more important, that it never invents
anything and never collects anyone irrelevant.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.enums import ContactKind, Department, EmailStatus, IngestMode, SourceType
from app.models import Contact, Opportunity
from app.services.contact_discovery import ContactDiscoveryStats, run_contact_discovery
from app.sources.base import SourceConfig
from app.sources.contacts import (
    ContactPageAdapter,
    department_for_mailbox,
    department_for_title,
    extract_contacts_from_html,
    is_ignored_mailbox,
    looks_like_person_name,
)
from app.sources.http import FetchClient
from tests.conftest import requires_db
from tests.factories import make_company, make_opportunity

FIXTURE = Path(__file__).parent / "fixtures_leadership.html"


def _parse(html: str | None = None):
    return extract_contacts_from_html(
        html if html is not None else FIXTURE.read_text(encoding="utf-8"),
        company_name="Example Corp",
        source_url="https://example.com/leadership",
    )


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def test_named_people_are_found_with_titles_and_departments() -> None:
    by_email = {c.email: c for c in _parse()}
    ahmed = by_email["a.hassan@example.com"]
    assert ahmed.name == "Ahmed Hassan"
    assert ahmed.job_title == "Marketing Director"
    assert ahmed.department is Department.MARKETING
    assert ahmed.linkedin_url == "https://www.linkedin.com/in/ahmed-hassan"

    mona = by_email["mona.said@example.com"]
    assert mona.name == "Mona Said"
    assert mona.department is Department.EVENTS


def test_each_contact_gets_its_own_name() -> None:
    """The block walk must not escape to the page and give everyone one name."""
    contacts = _parse()
    named = [c for c in contacts if "department contact" not in c.name]
    assert len(named) == len({c.name for c in named})
    assert len(named) >= 3


def test_irrelevant_seniority_is_skipped() -> None:
    """A CFO is senior and has no relationship to event spend."""
    assert not any("k.fouad" in (c.email or "") for c in _parse())


@pytest.mark.parametrize("mailbox", ["webmaster", "support", "ir", "noreply", "legal", "billing"])
def test_never_a_route_to_event_spend(mailbox: str) -> None:
    assert is_ignored_mailbox(f"{mailbox}@example.com")
    assert not any(f"{mailbox}@" in (c.email or "") for c in _parse())


def test_departmental_mailboxes_are_kept_but_marked_as_routes() -> None:
    """A real published mailbox is worth having; inventing a person for it is not.

    The guarantee is the ``contact_kind`` field, not the wording of the name: a
    structured flag cannot be misread the way a naming convention can.
    """
    press = next(c for c in _parse() if c.email == "press@example.com")
    assert press.department is Department.PR
    assert press.job_title is None
    assert press.contact_kind is ContactKind.DEPARTMENT_ROUTE
    assert "route" in press.name.casefold()


def test_named_people_are_marked_as_individuals() -> None:
    """The two kinds must never be conflated (Priority 3)."""
    named = [c for c in _parse() if c.contact_kind is ContactKind.NAMED_INDIVIDUAL]
    assert named, "the fixture page lists real people"
    assert all(c.job_title or c.name for c in named)
    # Nothing is left unclassified: every contact is a person or a route.
    assert all(c.contact_kind is not ContactKind.UNKNOWN for c in _parse())


def test_every_contact_carries_its_source() -> None:
    for contact in _parse():
        assert contact.source_url == "https://example.com/leadership"
        assert contact.source_title


def test_published_addresses_are_public_never_verified() -> None:
    """Published on a page is PUBLIC. VERIFIED needs a verification step V1 lacks."""
    assert all(c.email_status is EmailStatus.PUBLIC for c in _parse())


def test_named_contacts_are_more_confident_than_bare_mailboxes() -> None:
    contacts = _parse()
    named = next(c for c in contacts if c.name == "Ahmed Hassan")
    mailbox = next(c for c in contacts if c.email == "press@example.com")
    assert named.confidence > mailbox.confidence


def test_no_email_addresses_are_synthesised() -> None:
    """Every address returned must literally appear in the source HTML."""
    html = FIXTURE.read_text(encoding="utf-8")
    for contact in _parse(html):
        assert contact.email is not None
        assert contact.email in html.casefold()


def test_an_empty_or_junk_page_yields_nothing() -> None:
    assert _parse("") == []
    assert _parse("<html><body><p>Nothing here at all.</p></body></html>") == []


def test_malformed_html_does_not_raise() -> None:
    assert isinstance(_parse("<div><a href='mailto:marketing@x.com'>x</div></p></span>"), list)


# --------------------------------------------------------------------------
# classification helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("title", "department"),
    [
        ("Head of Events", Department.EVENTS),
        ("Events Manager", Department.EVENTS),
        ("Corporate Communications Manager", Department.CORPORATE_COMMUNICATIONS),
        ("PR Manager", Department.PR),
        ("Press Office", Department.PR),
        ("Communications Director", Department.COMMUNICATIONS),
        ("Marketing Director", Department.MARKETING),
        ("Brand Manager", Department.MARKETING),
        ("Procurement Manager", Department.PROCUREMENT),
        ("Business Development Manager", Department.BUSINESS_DEVELOPMENT),
        ("HR Manager", Department.HR),
        ("Chief Financial Officer", Department.UNKNOWN),
        ("Software Engineer", Department.UNKNOWN),
        (None, Department.UNKNOWN),
    ],
)
def test_department_for_title(title: str | None, department: Department) -> None:
    assert department_for_title(title) is department


@pytest.mark.parametrize(
    ("email", "department"),
    [
        ("press@x.com", Department.PR),
        ("marketing@x.com", Department.MARKETING),
        ("events@x.com", Department.EVENTS),
        ("tenders@x.com", Department.PROCUREMENT),
        ("corporate.communications@x.com", Department.CORPORATE_COMMUNICATIONS),
        ("someone.random@x.com", Department.UNKNOWN),
    ],
)
def test_department_for_mailbox(email: str, department: Department) -> None:
    assert department_for_mailbox(email) is department


@pytest.mark.parametrize(
    ("text", "is_name"),
    [
        ("Ahmed Hassan", True),
        ("Mona Said", True),
        ("Nadia El-Sayed", True),
        # A title matches the name *shape*, which is why the shape test alone is
        # not enough.
        ("Marketing Director", False),
        ("Head Of Events", False),
        ("Corporate Communications", False),
        ("ahmed hassan", False),
        ("A", False),
        ("Team 4", False),
    ],
)
def test_person_name_detection(text: str, is_name: bool) -> None:
    assert looks_like_person_name(text) is is_name


# --------------------------------------------------------------------------
# the adapter over HTTP
# --------------------------------------------------------------------------

def _adapter(handler, **options) -> ContactPageAdapter:
    config = SourceConfig(
        key="example-leadership",
        adapter="contact_page",
        source_type=SourceType.COMPANY,
        confidence=0.7,
        # 20/minute is the right politeness budget against a real page and pure
        # dead time against a mock transport.
        rate_limit_per_minute=100_000,
        options={"url": "https://example.com/leadership", "company": "Example Corp", **options},
    )
    return ContactPageAdapter(
        config,
        client=FetchClient(
            Settings(postgres_password="t", ingest_default_rate_limit_per_minute=100_000),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )


def test_adapter_fetches_and_parses() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    contacts = list(_adapter(handler).discover())
    assert len(contacts) >= 4
    assert all(c.adapter_key == "example-leadership" for c in contacts)


def test_adapter_survives_an_unreachable_page() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert list(_adapter(handler).discover()) == []


def test_adapter_requires_a_company() -> None:
    """A contact has to belong to a company we can name."""
    with pytest.raises(ValueError, match="options.company"):
        ContactPageAdapter(
            SourceConfig(key="x", adapter="contact_page", source_type=SourceType.COMPANY,
                         options={"url": "https://x.test/team"})
        )


def test_adapter_requires_a_url() -> None:
    with pytest.raises(ValueError, match="options.url"):
        ContactPageAdapter(
            SourceConfig(key="x", adapter="contact_page", source_type=SourceType.COMPANY,
                         options={"company": "X"})
        )


# --------------------------------------------------------------------------
# attaching to the database
# --------------------------------------------------------------------------

pytest_plugins: tuple[str, ...] = ()


@requires_db
def test_discovery_attaches_contacts_and_rescores(session: Session, db_engine) -> None:
    """Contact quality is 20% of the score, so discovery has to move it."""
    company = make_company(session, "Example Corp")
    opportunity = make_opportunity(session, company=company, score=60, base_score=60)
    before = opportunity.score

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    stats = run_contact_discovery([_adapter(handler)])
    assert stats.contacts_created >= 3
    assert stats.opportunities_rescored >= 1
    assert stats.errors == []

    session.expire_all()
    refreshed = session.get(Opportunity, opportunity.id)
    assert refreshed is not None
    assert refreshed.contact_quality > 0
    assert refreshed.score > before
    assert refreshed.primary_contact_id is not None
    # Movement is recorded so the daily brief can report it.
    assert refreshed.previous_score == before


@requires_db
def test_discovery_never_creates_a_company(session: Session, db_engine) -> None:
    """A contact page is not evidence a company belongs in the pipeline."""
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    stats = run_contact_discovery([_adapter(handler)])
    assert stats.contacts_created == 0
    assert stats.companies_unresolved == ["Example Corp"]
    assert session.scalar(select(func.count(Contact.id))) == 0


@requires_db
def test_discovery_is_idempotent(session: Session, db_engine) -> None:
    make_company(session, "Example Corp")
    session.commit()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    first = run_contact_discovery([_adapter(handler)])
    count_after_first = session.scalar(select(func.count(Contact.id)))
    second = run_contact_discovery([_adapter(handler)])

    assert first.contacts_created > 0
    assert second.contacts_created == 0
    assert session.scalar(select(func.count(Contact.id))) == count_after_first


@requires_db
def test_discovery_records_provenance(session: Session, db_engine) -> None:
    make_company(session, "Example Corp")
    session.commit()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    run_contact_discovery([_adapter(handler)])
    contact = session.scalars(select(Contact).where(Contact.email.is_not(None))).first()
    assert contact is not None
    assert contact.source is not None
    assert contact.source.ingest_mode is IngestMode.AUTOMATED
    assert contact.source.url == "https://example.com/leadership"


@requires_db
def test_one_failing_source_does_not_stop_the_others(session: Session, db_engine) -> None:
    make_company(session, "Example Corp")
    session.commit()

    class Exploding:
        key = "broken"
        config = SourceConfig(key="broken", adapter="contact_page", source_type=SourceType.COMPANY)

        def discover(self):
            raise RuntimeError("page exploded")

        def close(self) -> None:
            pass

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    stats = run_contact_discovery([Exploding(), _adapter(handler)])  # type: ignore[list-item]
    assert len(stats.errors) == 1
    assert stats.contacts_created > 0


def test_no_sources_configured_is_not_an_error() -> None:
    stats = run_contact_discovery([])
    assert isinstance(stats, ContactDiscoveryStats)
    assert stats.contacts_found == 0
    assert stats.errors == []
