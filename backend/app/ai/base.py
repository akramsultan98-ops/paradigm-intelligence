"""The extraction contract.

Every provider returns an ``Extraction`` or ``None``. Anything that does not
validate against this schema is discarded before it can reach the database —
spec §26 requires schema validation, and an unvalidated model response is
exactly the sort of thing that writes a hallucinated company into a table.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import (
    AttendeeBand,
    Department,
    Level,
    OpportunityType,
    OpportunityWindow,
    RecommendedAction,
    Scale,
    Service,
    SignalType,
    SizeBand,
    SourceType,
)

Score100 = Annotated[int, Field(ge=0, le=100)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ExtractionRequest(BaseModel):
    """One source document, ready for extraction."""

    model_config = ConfigDict(frozen=True)

    url: str
    title: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    source_type: SourceType = SourceType.OTHER
    content: str
    #: The company this document is about, when the adapter already knows.
    #: For a company newsroom feed the publisher *is* the company, and passing
    #: that through is recognition, not inference.
    company_hint: str | None = None


class ExtractionFactors(BaseModel):
    """Scoring factors read off the document.

    Every field defaults to unknown. A provider that cannot find evidence for a
    factor must leave it unknown rather than guess, and unknown always scores
    below medium (see ``app.scoring.scales``).
    """

    model_config = ConfigDict(extra="ignore")

    announcement_scale: Scale = Scale.UNKNOWN
    company_size: SizeBand = SizeBand.UNKNOWN
    has_event_history: bool | None = None
    marketing_activity: Level = Level.UNKNOWN
    comms_activity: Level = Level.UNKNOWN
    ecosystem_breadth: Level = Level.UNKNOWN
    stakeholder_count: int | None = Field(default=None, ge=0, le=500)
    executive_involvement: bool | None = None
    expected_attendees: AttendeeBand = AttendeeBand.UNKNOWN
    production_complexity: Level = Level.UNKNOWN
    repeat_potential: Level = Level.UNKNOWN
    brand_value: Level = Level.UNKNOWN


class Extraction(BaseModel):
    """Structured output for one source document (spec §26)."""

    model_config = ConfigDict(extra="ignore")

    # --- company ---------------------------------------------------------
    #: ``None`` when the document names no company. The pipeline drops the
    #: document rather than inventing an account.
    company_name: str | None = None
    company_domain: str | None = None
    company_sector: str | None = None
    company_city: str | None = None

    # --- signal ----------------------------------------------------------
    signal_type: SignalType = SignalType.UNKNOWN
    signal_title: str | None = None
    signal_summary: str | None = None
    business_impact: str | None = None

    # --- event opportunity ----------------------------------------------
    possible_event: bool = False
    event_type: OpportunityType = OpportunityType.UNKNOWN
    event_probability: Score100 | None = None
    commercial_value: Score100 | None = None
    opportunity_window: OpportunityWindow = OpportunityWindow.UNKNOWN
    #: The actual event date, only when the source states one. This is what turns
    #: timing from a guess into a fact, so never infer it.
    event_date: date | None = None
    #: True only when the source reports the event has already taken place.
    event_already_occurred: bool | None = None

    # --- contact routing (a role, never a fabricated person) -------------
    likely_department: Department = Department.UNKNOWN
    potential_contact_role: str | None = None

    # --- the three epistemic statements (spec §6, §23, §36) --------------
    #: What the source states, in its own terms. No reasoning.
    fact: str | None = None
    #: What follows from the fact. Reasoned, not stated.
    inference: str | None = None
    #: What may happen next. Never confirmed.
    prediction: str | None = None

    # --- sales payload ---------------------------------------------------
    why_now: str | None = None
    sales_angle: str | None = None
    recommended_services: list[Service] = Field(default_factory=list)
    recommended_action: RecommendedAction = RecommendedAction.NURTURE_ACCOUNT

    # --- scoring inputs --------------------------------------------------
    factors: ExtractionFactors = Field(default_factory=ExtractionFactors)
    confidence: Confidence = 0.0
    #: Which extractor produced this, recorded so a rule-based run is never
    #: mistaken for an AI run.
    extractor: str = "unknown"

    @field_validator("company_name", "signal_title", "signal_summary", "business_impact",
                     "why_now", "sales_angle", "potential_contact_role",
                     "company_domain", "company_sector", "company_city",
                     "fact", "inference", "prediction", mode="before")
    @classmethod
    def _blank_and_unknown_to_none(cls, value: object) -> object:
        """Treat blanks and the literal string "UNKNOWN" as absent.

        Models are asked to answer ``UNKNOWN`` where there is no evidence
        (spec §26). Carrying that through as text would put the word "UNKNOWN"
        into a company name field, so it is normalized to ``None`` here.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.casefold() in {"unknown", "n/a", "none", "null"}:
                return None
            return stripped
        return value

    @field_validator("recommended_services")
    @classmethod
    def _dedupe_services(cls, value: list[Service]) -> list[Service]:
        seen: list[Service] = []
        for service in value:
            if service not in seen:
                seen.append(service)
        return seen

    @property
    def has_company(self) -> bool:
        return bool(self.company_name)

    @property
    def is_actionable_opportunity(self) -> bool:
        """Whether this warrants an opportunity row at all.

        An event implication needs a company, an affirmative judgement, a known
        event type, and an actual reason to act. Missing any of those, the signal
        is still recorded — it just does not become an opportunity.
        """
        return (
            self.has_company
            and self.possible_event
            and self.event_type is not OpportunityType.UNKNOWN
            and bool(self.why_now)
            and bool(self.sales_angle)
        )


class AIProvider(ABC):
    """Extraction provider."""

    #: Stable identifier, recorded on every extraction.
    name: str = "base"

    @abstractmethod
    def extract(self, request: ExtractionRequest) -> Extraction | None:
        """Structure one document, or return ``None`` if it cannot be trusted."""

    def close(self) -> None:  # noqa: B027 - optional hook, not an abstract method
        """Release any held resources (HTTP clients, sockets).

        Deliberately concrete and empty: most providers hold nothing, and forcing
        every one to implement a no-op would be noise.
        """
