"""Helpers for building database fixtures in integration tests.

These construct rows through the real service layer wherever possible, so the
tests exercise the same normalization and dedupe paths production uses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import (
    AssertionLevel,
    CommercialValueBand,
    ContactTiming,
    Department,
    EmailStatus,
    EvidenceLevel,
    OpportunityStatus,
    OpportunityType,
    OpportunityWindow,
    RecommendedAction,
    SignalType,
    SizeBand,
    SourceType,
)
from app.models import Company, Contact, Opportunity, Signal, Source
from app.scoring.classification import classify
from app.services.normalize import content_hash, normalize_company_name, normalize_person_name


def make_company(
    session: Session,
    name: str = "Example Corporation",
    *,
    sector: str | None = "Technology",
    size_band: SizeBand = SizeBand.LARGE,
) -> Company:
    company = Company(
        name=name,
        normalized_name=normalize_company_name(name),
        sector=sector,
        city="Cairo",
        size_band=size_band,
    )
    session.add(company)
    session.flush()
    return company


def make_source(
    session: Session,
    *,
    url: str | None = None,
    source_type: SourceType = SourceType.COMPANY,
    published_at: datetime | None = None,
    confidence: float = 0.9,
) -> Source:
    url = url or f"https://example.test/{uuid.uuid4().hex}"
    source = Source(
        url=url,
        normalized_url=url,
        title="Announcement",
        source_type=source_type,
        publisher="Example Corporation",
        publication_date=published_at or datetime.now(UTC),
        confidence=Decimal(str(confidence)),
        content_hash=content_hash(uuid.uuid4().hex),
        adapter_key="test",
    )
    session.add(source)
    session.flush()
    return source


def make_signal(
    session: Session,
    company: Company,
    source: Source,
    *,
    signal_type: SignalType = SignalType.PRODUCT_LAUNCH,
    title: str = "Example launches a new product line",
    published_at: datetime | None = None,
) -> Signal:
    signal = Signal(
        company_id=company.id,
        source_id=source.id,
        type=signal_type,
        title=title,
        summary="A summary of the announcement.",
        published_at=published_at or source.publication_date,
        confidence=Decimal("0.85"),
        evidence_level=EvidenceLevel.FACT,
        dedupe_key=content_hash(str(company.id), signal_type.value, title),
    )
    session.add(signal)
    session.flush()
    return signal


def make_contact(
    session: Session,
    company: Company,
    *,
    name: str = "Ahmed Hassan",
    job_title: str = "Marketing Director",
    department: Department = Department.MARKETING,
    email: str | None = "ahmed.hassan@example.com",
    contact_score: int = 88,
    email_status: EmailStatus = EmailStatus.PUBLIC,
) -> Contact:
    contact = Contact(
        company_id=company.id,
        name=name,
        normalized_name=normalize_person_name(name),
        job_title=job_title,
        department=department,
        email=email,
        normalized_email=email,
        email_status=email_status if email else EmailStatus.UNKNOWN,
        contact_score=contact_score,
        confidence=Decimal("0.8"),
    )
    session.add(contact)
    session.flush()
    return contact


def make_opportunity(
    session: Session,
    *,
    company: Company | None = None,
    score: int = 85,
    opportunity_type: OpportunityType = OpportunityType.PRODUCT_LAUNCH,
    status: OpportunityStatus = OpportunityStatus.QUALIFIED,
    signal_age_days: int = 2,
    window: OpportunityWindow = OpportunityWindow.DAYS_15_30,
    company_name: str | None = None,
    sector: str | None = "Technology",
    previous_score: int | None = None,
    created_at: datetime | None = None,
    score_changed_at: datetime | None = None,
    base_score: int | None = None,
) -> Opportunity:
    """Create a fully-formed opportunity at an exact score.

    Scores are set directly rather than derived, so a test can pin the precise
    boundary condition it is about (69 versus 70, say).
    """
    published = datetime.now(UTC) - timedelta(days=signal_age_days)
    if company is None:
        company = make_company(
            session, company_name or f"Company {uuid.uuid4().hex[:8]}", sector=sector
        )
    source = make_source(session, published_at=published)
    signal = make_signal(
        session,
        company,
        source,
        published_at=published,
        title=f"Announcement {uuid.uuid4().hex[:8]}",
    )

    opportunity = Opportunity(
        company_id=company.id,
        signal_id=signal.id,
        type=opportunity_type,
        assertion_level=AssertionLevel.INFERENCE,
        event_probability=min(100, score),
        commercial_value=min(100, score),
        commercial_value_band=CommercialValueBand.HIGH,
        contact_quality=60,
        timing_score=90,
        evidence_score=90,
        base_score=base_score if base_score is not None else score,
        decay_factor=Decimal("1.000"),
        score=score,
        classification=classify(score),
        why_now="A launch was announced; a launch event is likely to follow.",
        sales_angle="Full launch production: staging, AV, branding.",
        recommended_action=RecommendedAction.CONTACT_MARKETING,
        recommended_services=["EVENT_MANAGEMENT", "AV"],
        opportunity_window=window,
        window_ends_on=date.today() + timedelta(days=20),
        recommended_contact_timing=ContactTiming.WITHIN_1_WEEK,
        status=status,
        previous_score=previous_score,
        previous_classification=classify(previous_score) if previous_score is not None else None,
        score_changed_at=score_changed_at,
        scored_at=datetime.now(UTC),
    )
    session.add(opportunity)
    session.flush()
    if created_at is not None:
        # created_at has a server default, so an explicit value is applied after
        # the insert.
        opportunity.created_at = created_at
        session.flush()
    session.commit()
    return opportunity
