"""Creating, scoring and re-scoring opportunities.

This is where the pipeline's judgement is made explicit: whether a signal implies
an event, how sure we are, and how that is labelled.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import Extraction
from app.config import Settings, get_settings
from app.domain.enums import (
    CONFIRMED_EVENT_SIGNALS,
    OFFICIAL_SOURCE_TYPES,
    AssertionLevel,
    OpportunityStatus,
    SourceType,
)
from app.models import Company, Contact, Opportunity, Signal, Source
from app.scoring import (
    CommercialValueFactors,
    EventProbabilityFactors,
    EvidenceFactors,
    ScoreInputs,
    ScoreResult,
    is_qualified,
    score_opportunity,
)
from app.services.companies import note_event_potential
from app.services.contacts import contacts_for_company
from app.services.signals import count_corroborating_sources

logger = logging.getLogger(__name__)


def determine_assertion_level(
    signal_type: object, source_type: SourceType
) -> AssertionLevel:
    """Label the claim honestly (spec §6).

    - ``FACT`` only when the source *announces* an event and speaks officially.
    - ``INFERENCE`` when an event is announced but reported second-hand.
    - ``PREDICTION`` for everything else: we are reasoning about what the company
      will probably do, and that must never read as confirmed.
    """
    if signal_type in CONFIRMED_EVENT_SIGNALS:
        if source_type in OFFICIAL_SOURCE_TYPES:
            return AssertionLevel.FACT
        return AssertionLevel.INFERENCE
    return AssertionLevel.PREDICTION


def build_score_inputs(
    session: Session,
    *,
    company: Company,
    signal: Signal,
    source: Source,
    extraction: Extraction,
    contact_scores: tuple[int, ...],
    as_of: date | None = None,
) -> ScoreInputs:
    """Assemble every scoring input from the persisted record."""
    factors = extraction.factors
    corroboration = count_corroborating_sources(session, company.id, signal.type)

    return ScoreInputs(
        evidence=EvidenceFactors(
            source_type=source.source_type,
            source_confidence=float(source.confidence),
            has_publication_date=source.publication_date is not None,
            extraction_confidence=float(signal.confidence),
            corroborating_sources=max(corroboration, 1),
        ),
        commercial=CommercialValueFactors(
            # The company's stored size wins over a single article's impression
            # of it.
            company_size=(
                company.size_band
                if company.size_band.value != "UNKNOWN"
                else factors.company_size
            ),
            attendee_band=factors.expected_attendees,
            production_complexity=factors.production_complexity,
            service_count=len(extraction.recommended_services) or None,
            repeat_potential=factors.repeat_potential,
            brand_value=factors.brand_value,
            ai_estimate=extraction.commercial_value,
        ),
        contact_scores=contact_scores,
        window=extraction.opportunity_window,
        assertion_level=determine_assertion_level(signal.type, source.source_type),
        event=EventProbabilityFactors(
            signal_type=signal.type,
            announcement_scale=factors.announcement_scale,
            company_size=(
                company.size_band
                if company.size_band.value != "UNKNOWN"
                else factors.company_size
            ),
            has_event_history=factors.has_event_history,
            marketing_activity=factors.marketing_activity,
            comms_activity=factors.comms_activity,
            ecosystem_breadth=factors.ecosystem_breadth,
            stakeholder_count=factors.stakeholder_count,
            executive_involvement=factors.executive_involvement,
            ai_estimate=extraction.event_probability,
        ),
        signal_date=signal.effective_date,
        as_of=as_of,
    )


def _apply_score(
    opportunity: Opportunity, result: ScoreResult, *, track_change: bool
) -> None:
    """Write a score onto an opportunity, recording movement for the brief."""
    if track_change and opportunity.score != result.score:
        opportunity.previous_score = opportunity.score
        opportunity.previous_classification = opportunity.classification
        opportunity.score_changed_at = datetime.now(UTC)

    opportunity.event_probability = result.event_probability
    opportunity.commercial_value = result.commercial_value
    opportunity.commercial_value_band = result.commercial_value_band
    opportunity.contact_quality = result.contact_quality
    opportunity.timing_score = result.timing_score
    opportunity.evidence_score = result.evidence_score
    opportunity.base_score = result.base_score
    opportunity.decay_factor = Decimal(str(result.decay.factor))
    opportunity.score = result.score
    opportunity.classification = result.classification
    opportunity.window_ends_on = result.window_ends_on
    opportunity.recommended_contact_timing = result.recommended_contact_timing
    opportunity.scored_at = datetime.now(UTC)


def _best_contact(contacts: list[Contact]) -> Contact | None:
    return contacts[0] if contacts else None


def create_or_update_opportunity(
    session: Session,
    *,
    company: Company,
    signal: Signal,
    source: Source,
    extraction: Extraction,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> tuple[Opportunity | None, bool]:
    """Create or re-score the opportunity implied by a signal.

    Returns ``(None, False)`` when the extraction carries no realistic event
    implication. That is the common case and it is correct: most business news
    does not imply an event, and recording one anyway is how a Top 50 fills up
    with noise.
    """
    settings = settings or get_settings()

    if not extraction.is_actionable_opportunity:
        return None, False
    # Guarded by is_actionable_opportunity; asserted for the type checker and to
    # keep the NOT NULL columns honest.
    assert extraction.why_now and extraction.sales_angle

    contacts = contacts_for_company(session, company.id)
    contact_scores = tuple(contact.contact_score for contact in contacts)
    inputs = build_score_inputs(
        session,
        company=company,
        signal=signal,
        source=source,
        extraction=extraction,
        contact_scores=contact_scores,
        as_of=as_of,
    )
    result = score_opportunity(inputs, settings)
    best_contact = _best_contact(contacts)

    existing = session.scalars(
        select(Opportunity).where(
            Opportunity.signal_id == signal.id, Opportunity.type == extraction.event_type
        )
    ).first()

    if existing is not None:
        _apply_score(existing, result, track_change=True)
        existing.primary_contact_id = best_contact.id if best_contact else None
        # Promote a NEW opportunity that now qualifies. Statuses a human has
        # moved on are never touched.
        if existing.status is OpportunityStatus.NEW and is_qualified(result.score, settings):
            existing.status = OpportunityStatus.QUALIFIED
        session.flush()
        note_event_potential(session, company, result.event_probability)
        return existing, False

    opportunity = Opportunity(
        company_id=company.id,
        signal_id=signal.id,
        primary_contact_id=best_contact.id if best_contact else None,
        type=extraction.event_type,
        assertion_level=inputs.assertion_level,
        why_now=extraction.why_now,
        sales_angle=extraction.sales_angle,
        recommended_action=extraction.recommended_action,
        recommended_services=[service.value for service in extraction.recommended_services],
        opportunity_window=extraction.opportunity_window,
        status=(
            OpportunityStatus.QUALIFIED
            if is_qualified(result.score, settings)
            else OpportunityStatus.NEW
        ),
        event_probability=result.event_probability,
        commercial_value=result.commercial_value,
        commercial_value_band=result.commercial_value_band,
        contact_quality=result.contact_quality,
        timing_score=result.timing_score,
        evidence_score=result.evidence_score,
        base_score=result.base_score,
        decay_factor=Decimal(str(result.decay.factor)),
        score=result.score,
        classification=result.classification,
        window_ends_on=result.window_ends_on,
        recommended_contact_timing=result.recommended_contact_timing,
    )
    session.add(opportunity)
    session.flush()
    note_event_potential(session, company, result.event_probability)
    logger.info(
        "opportunity created",
        extra={
            "opportunity_id": str(opportunity.id),
            "company": company.name,
            "type": opportunity.type.value,
            "score": opportunity.score,
            "classification": opportunity.classification.value,
            "assertion": opportunity.assertion_level.value,
        },
    )
    return opportunity, True
