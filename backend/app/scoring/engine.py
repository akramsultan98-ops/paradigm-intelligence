"""OPPORTUNITY_SCORE: the weighted combination of every component."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.config import Settings, get_settings
from app.domain.enums import (
    AssertionLevel,
    Classification,
    CommercialValueBand,
    ContactTiming,
    OpportunityWindow,
)
from app.scoring.classification import classify
from app.scoring.commercial_value import CommercialValueFactors, score_commercial_value
from app.scoring.contact_quality import score_opportunity_contacts
from app.scoring.decay import DecayInputs, DecayResult, compute_decay
from app.scoring.event_probability import EventProbabilityFactors, score_event_probability
from app.scoring.evidence import EvidenceFactors, score_evidence
from app.scoring.scales import clamp
from app.scoring.timing import contact_timing_for, timing_score_for, window_end_date


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    """Everything needed to score one opportunity."""

    evidence: EvidenceFactors
    commercial: CommercialValueFactors
    #: Per-contact quality scores for the company, in any order.
    contact_scores: tuple[int, ...]
    window: OpportunityWindow
    assertion_level: AssertionLevel
    #: Event probability factors *except* the ones this engine derives
    #: (timing, evidence, assertion level), which are filled in here.
    event: EventProbabilityFactors
    signal_date: datetime | date | None = None
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """A fully-explained score."""

    event_probability: int
    commercial_value: int
    commercial_value_band: CommercialValueBand
    contact_quality: int
    timing_score: int
    evidence_score: int
    base_score: int
    decay: DecayResult
    score: int
    classification: Classification
    window_ends_on: date | None
    recommended_contact_timing: ContactTiming
    components: dict[str, float] = field(default_factory=dict)

    @property
    def decay_factor(self) -> float:
        return self.decay.factor


def score_opportunity(inputs: ScoreInputs, settings: Settings | None = None) -> ScoreResult:
    """Compute every component, the weighted base score, and the decayed total.

    Order matters. Evidence and timing feed event probability (as a cap and as a
    factor respectively), so they are computed first; decay is applied last, to
    the finished base score.
    """
    settings = settings or get_settings()

    evidence = score_evidence(inputs.evidence)
    timing = timing_score_for(inputs.window)

    # Event probability needs the evidence cap, the timing factor and the
    # assertion level, so they are injected rather than duplicated by callers.
    event_factors = EventProbabilityFactors(
        signal_type=inputs.event.signal_type,
        announcement_scale=inputs.event.announcement_scale,
        company_size=inputs.event.company_size,
        has_event_history=inputs.event.has_event_history,
        marketing_activity=inputs.event.marketing_activity,
        comms_activity=inputs.event.comms_activity,
        ecosystem_breadth=inputs.event.ecosystem_breadth,
        stakeholder_count=inputs.event.stakeholder_count,
        executive_involvement=inputs.event.executive_involvement,
        timing_score=timing,
        ai_estimate=inputs.event.ai_estimate,
        evidence_score=evidence,
        assertion_level=inputs.assertion_level,
    )
    event_probability = score_event_probability(event_factors, settings)
    commercial_value, commercial_band = score_commercial_value(inputs.commercial)
    contact_quality = score_opportunity_contacts(inputs.contact_scores, settings)

    base = (
        settings.weight_event_probability * event_probability
        + settings.weight_commercial_value * commercial_value
        + settings.weight_contact_quality * contact_quality
        + settings.weight_timing * timing
        + settings.weight_evidence * evidence
    )
    base_score = round(clamp(base))

    window_ends_on = window_end_date(inputs.window, inputs.signal_date)
    decay = compute_decay(
        DecayInputs(
            signal_date=inputs.signal_date,
            window_ends_on=window_ends_on,
            evidence_score=evidence,
            as_of=inputs.as_of,
        ),
        settings,
    )
    score = round(clamp(base_score * decay.factor))

    return ScoreResult(
        event_probability=event_probability,
        commercial_value=commercial_value,
        commercial_value_band=commercial_band,
        contact_quality=contact_quality,
        timing_score=timing,
        evidence_score=evidence,
        base_score=base_score,
        decay=decay,
        score=score,
        classification=classify(score, settings),
        window_ends_on=window_ends_on,
        recommended_contact_timing=contact_timing_for(
            inputs.window, has_contact=bool(inputs.contact_scores)
        ),
        components={
            "event_probability": float(event_probability),
            "commercial_value": float(commercial_value),
            "contact_quality": float(contact_quality),
            "timing": float(timing),
            "evidence": float(evidence),
            "event_probability_factors": event_factors.breakdown,  # type: ignore[dict-item]
            "commercial_value_factors": inputs.commercial.breakdown,  # type: ignore[dict-item]
        },
    )
