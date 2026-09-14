"""EVENT_PROBABILITY: how likely a real event actually follows from a signal.

Conservative by construction. High scores are meant to be hard to reach, because
an Account Manager acting on a 90 needs that 90 to mean something.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.domain.enums import AssertionLevel, Level, Scale, SignalType, SizeBand
from app.scoring.scales import (
    LEVEL_SCORES,
    SCALE_SCORES,
    SIGNAL_STRENGTH,
    SIZE_SCORES,
    clamp,
    count_score,
    tri_state,
    weighted,
)

WEIGHTS = {
    "signal_strength": 0.24,
    "announcement_scale": 0.12,
    "company_size": 0.11,
    "event_history": 0.08,
    "marketing_activity": 0.07,
    "comms_activity": 0.05,
    "ecosystem_breadth": 0.07,
    "stakeholder_count": 0.05,
    "executive_involvement": 0.06,
    "timing_proximity": 0.05,
    # The AI's own estimate is one factor among eleven. It informs the score; it
    # does not decide it.
    "ai_estimate": 0.10,
}


@dataclass(frozen=True, slots=True)
class EventProbabilityFactors:
    """Named inputs, all optional so that missing evidence is explicit."""

    signal_type: SignalType
    announcement_scale: Scale = Scale.UNKNOWN
    company_size: SizeBand = SizeBand.UNKNOWN
    has_event_history: bool | None = None
    marketing_activity: Level = Level.UNKNOWN
    comms_activity: Level = Level.UNKNOWN
    ecosystem_breadth: Level = Level.UNKNOWN
    stakeholder_count: int | None = None
    executive_involvement: bool | None = None
    #: The TIMING component, reused here as timing proximity.
    timing_score: int = 20
    #: The extractor's own 0-100 estimate, if it offered one.
    ai_estimate: int | None = None
    #: EVIDENCE_QUALITY, used to cap the result.
    evidence_score: int = 0
    assertion_level: AssertionLevel = AssertionLevel.PREDICTION
    breakdown: dict[str, float] = field(default_factory=dict, compare=False)


def raw_event_probability(factors: EventProbabilityFactors) -> float:
    """The weighted factor sum, before any conservatism is applied."""
    components = {
        "signal_strength": (
            SIGNAL_STRENGTH[factors.signal_type],
            WEIGHTS["signal_strength"],
        ),
        "announcement_scale": (
            SCALE_SCORES[factors.announcement_scale],
            WEIGHTS["announcement_scale"],
        ),
        "company_size": (SIZE_SCORES[factors.company_size], WEIGHTS["company_size"]),
        "event_history": (tri_state(factors.has_event_history), WEIGHTS["event_history"]),
        "marketing_activity": (
            LEVEL_SCORES[factors.marketing_activity],
            WEIGHTS["marketing_activity"],
        ),
        "comms_activity": (LEVEL_SCORES[factors.comms_activity], WEIGHTS["comms_activity"]),
        "ecosystem_breadth": (
            LEVEL_SCORES[factors.ecosystem_breadth],
            WEIGHTS["ecosystem_breadth"],
        ),
        "stakeholder_count": (
            count_score(factors.stakeholder_count, base=20.0, step=8.0),
            WEIGHTS["stakeholder_count"],
        ),
        "executive_involvement": (
            tri_state(factors.executive_involvement),
            WEIGHTS["executive_involvement"],
        ),
        "timing_proximity": (float(factors.timing_score), WEIGHTS["timing_proximity"]),
        "ai_estimate": (
            # An absent estimate is treated as an unknown at 30, not as a zero
            # and not as a midpoint.
            float(factors.ai_estimate) if factors.ai_estimate is not None else 30.0,
            WEIGHTS["ai_estimate"],
        ),
    }
    factors.breakdown.update({name: round(score, 2) for name, (score, _) in components.items()})
    return weighted(components)


def score_event_probability(
    factors: EventProbabilityFactors, settings: Settings | None = None
) -> int:
    """EVENT_PROBABILITY, 0-100.

    Three separate brakes are applied to the raw factor sum:

    1. A power transform, which compresses everything below 100 downward.
    2. An evidence cap, so a thinly sourced signal cannot score high however
       suggestive it reads.
    3. An unconfirmed cap, so a prediction never presents as a certainty.
    """
    settings = settings or get_settings()
    raw = raw_event_probability(factors)

    # 1. Conservatism: (raw/100)^exponent keeps 0 and 100 fixed and pulls
    #    everything in between down.
    adjusted = 100.0 * (raw / 100.0) ** settings.event_probability_exponent

    # 2. Weak evidence is a ceiling, not a deduction.
    evidence_cap = (
        settings.evidence_cap_base + settings.evidence_cap_slope * factors.evidence_score
    )
    adjusted = min(adjusted, evidence_cap)

    # 3. Only a source-confirmed event may exceed the unconfirmed cap.
    if factors.assertion_level is not AssertionLevel.FACT:
        adjusted = min(adjusted, float(settings.event_probability_cap_unconfirmed))

    return round(clamp(adjusted))
