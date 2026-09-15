"""Opportunity responses — the product's actual output surface."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.domain.enums import (
    AssertionLevel,
    Classification,
    CommercialValueBand,
    ContactKind,
    ContactTiming,
    Department,
    EmailStatus,
    OpportunityStatus,
    OpportunityTiming,
    OpportunityType,
    OpportunityWindow,
    OutreachStatus,
    SignalType,
    SourceType,
)
from app.schemas.common import ORMModel


class SourceRef(ORMModel):
    """Provenance, attached to every important record (spec §17)."""

    id: uuid.UUID
    source_url: str = Field(validation_alias="url")
    source_title: str | None = Field(default=None, validation_alias="title")
    source_type: SourceType
    publisher: str | None = None
    publication_date: datetime | None = None
    confidence: Decimal
    #: AUTOMATED / ANALYST / TEST, so the UI can show where this came from.
    ingest_mode: str = "AUTOMATED"

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer("confidence")
    def _confidence(self, value: Decimal) -> float:
        return float(value)


class CompanyRef(ORMModel):
    id: uuid.UUID
    name: str
    sector: str | None = None
    city: str | None = None
    domain: str | None = None
    size_band: str
    event_potential_score: int | None = None


class ContactRef(ORMModel):
    """A contact, always with its provenance and freshness visible.

    ``contact_kind`` is the important field: it says whether this is a person, an
    official department route, or neither. A named individual and an info@ inbox
    are not the same thing and must never read as if they were.
    """

    id: uuid.UUID
    name: str
    job_title: str | None = None
    department: Department
    #: NAMED_INDIVIDUAL / DEPARTMENT_ROUTE / UNKNOWN.
    contact_kind: ContactKind
    email: str | None = None
    linkedin_url: str | None = None
    #: Published business number only. Never derived.
    phone: str | None = None
    #: Never ``VERIFIED`` unless an actual verification step set it.
    email_status: EmailStatus
    contact_score: int
    confidence: Decimal
    #: When this contact was last confirmed against its source. Contact data rots.
    last_verified_at: datetime | None = None

    # --- outreach state ------------------------------------------------
    outreach_status: OutreachStatus = OutreachStatus.NOT_CONTACTED
    last_contacted_at: datetime | None = None
    next_follow_up_on: date | None = None

    #: Where this contact was read from. Every contact has one or it should not
    #: be here.
    source: SourceRef | None = None

    @field_serializer("confidence")
    def _confidence(self, value: Decimal) -> float:
        return float(value)


class SignalRef(ORMModel):
    id: uuid.UUID
    type: SignalType
    title: str
    summary: str | None = None
    business_impact: str | None = None
    published_at: datetime | None = None
    evidence_level: str
    confidence: Decimal
    source: SourceRef | None = None

    @field_serializer("confidence")
    def _confidence(self, value: Decimal) -> float:
        return float(value)


class ScoreBreakdown(BaseModel):
    """The score, taken apart.

    Returned so the ranking can be interrogated rather than taken on faith.
    """

    event_probability: int
    commercial_value: int
    commercial_value_band: CommercialValueBand
    contact_quality: int
    timing_score: int
    evidence_score: int
    base_score: int
    decay_factor: float
    score: int
    classification: Classification


class OpportunityOut(ORMModel):
    """One opportunity, as the Top 50 view renders it (spec §29)."""

    id: uuid.UUID
    #: 1-based position in the current result set. Set by the API, not stored.
    rank: int | None = None

    score: int
    classification: Classification
    type: OpportunityType
    #: ``FACT`` / ``INFERENCE`` / ``PREDICTION`` — a prediction is never presented
    #: as a confirmed event (spec §6).
    assertion_level: AssertionLevel
    status: OpportunityStatus

    event_probability: int
    commercial_value: int
    commercial_value_band: CommercialValueBand
    contact_quality: int
    timing_score: int
    evidence_score: int
    base_score: int
    decay_factor: Decimal

    #: The three epistemic statements, kept apart (spec §23).
    fact: str | None = None
    inference: str | None = None
    prediction: str | None = None

    why_now: str
    sales_angle: str
    recommended_action: str
    recommended_services: list[str]

    opportunity_window: OpportunityWindow
    window_ends_on: date | None = None
    recommended_contact_timing: ContactTiming

    #: The event's own date, only when a source states one (spec: never inferred).
    event_date: date | None = None
    #: IMMEDIATE (bid for it) / FUTURE_ACCOUNT (build the relationship) /
    #: HISTORICAL (already happened; research only). A past event is never
    #: presented as if it were still upcoming.
    timing_class: OpportunityTiming
    #: Plain-language reason for the timing class, in the Account Manager's terms.
    timing_rationale: str | None = None

    previous_score: int | None = None
    previous_classification: Classification | None = None
    score_changed_at: datetime | None = None
    scored_at: datetime
    created_at: datetime
    updated_at: datetime

    company: CompanyRef
    signal: SignalRef
    primary_contact: ContactRef | None = None

    @field_serializer("decay_factor")
    def _decay(self, value: Decimal) -> float:
        return float(value)

    @property
    def breakdown(self) -> ScoreBreakdown:
        return ScoreBreakdown(
            event_probability=self.event_probability,
            commercial_value=self.commercial_value,
            commercial_value_band=self.commercial_value_band,
            contact_quality=self.contact_quality,
            timing_score=self.timing_score,
            evidence_score=self.evidence_score,
            base_score=self.base_score,
            decay_factor=float(self.decay_factor),
            score=self.score,
            classification=self.classification,
        )


class OpportunityDetail(OpportunityOut):
    """Detail view: every contact at the company, not just the best one."""

    contacts: list[ContactRef] = Field(default_factory=list)


class Top50Response(BaseModel):
    """The Top 50.

    ``returned`` may be fewer than ``top_n``: if only 23 opportunities clear the
    threshold, the list has 23 rows. Empty slots are never padded (spec §12).
    """

    generated_at: datetime
    qualifying_threshold: int
    top_n: int
    returned: int
    eligible_total: int
    items: list[OpportunityOut]


class OpportunityStatusUpdate(BaseModel):
    """The only mutation the API allows on an opportunity."""

    status: OpportunityStatus
