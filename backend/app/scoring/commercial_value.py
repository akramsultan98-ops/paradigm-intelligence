"""COMMERCIAL_VALUE: how much the work is worth to PARADIGM.

No monetary figure is produced. Where a value cannot be verified the answer is a
band — ``LOW`` / ``MEDIUM`` / ``HIGH`` / ``VERY_HIGH`` — never an invented budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import AttendeeBand, CommercialValueBand, Level, SizeBand
from app.scoring.scales import (
    ATTENDEE_SCORES,
    LEVEL_SCORES,
    SIZE_SCORES,
    count_score,
    weighted,
)

WEIGHTS = {
    "company_size": 0.20,
    "attendee_band": 0.18,
    "production_complexity": 0.18,
    "service_scope": 0.14,
    "repeat_potential": 0.10,
    "brand_value": 0.10,
    "ai_estimate": 0.10,
}

#: Inclusive lower bound of each band, highest first.
_BANDS: tuple[tuple[int, CommercialValueBand], ...] = (
    (80, CommercialValueBand.VERY_HIGH),
    (60, CommercialValueBand.HIGH),
    (35, CommercialValueBand.MEDIUM),
)


@dataclass(frozen=True, slots=True)
class CommercialValueFactors:
    """Named inputs to commercial value."""

    company_size: SizeBand = SizeBand.UNKNOWN
    attendee_band: AttendeeBand = AttendeeBand.UNKNOWN
    production_complexity: Level = Level.UNKNOWN
    #: How many of PARADIGM's services the opportunity plausibly needs.
    service_count: int | None = None
    repeat_potential: Level = Level.UNKNOWN
    brand_value: Level = Level.UNKNOWN
    ai_estimate: int | None = None
    breakdown: dict[str, float] = field(default_factory=dict, compare=False)


def band_for(value: int) -> CommercialValueBand:
    """Map a 0-100 commercial value onto its band."""
    for threshold, band in _BANDS:
        if value >= threshold:
            return band
    return CommercialValueBand.LOW


def score_commercial_value(factors: CommercialValueFactors) -> tuple[int, CommercialValueBand]:
    """COMMERCIAL_VALUE (0-100) and its band."""
    components = {
        "company_size": (SIZE_SCORES[factors.company_size], WEIGHTS["company_size"]),
        "attendee_band": (ATTENDEE_SCORES[factors.attendee_band], WEIGHTS["attendee_band"]),
        "production_complexity": (
            LEVEL_SCORES[factors.production_complexity],
            WEIGHTS["production_complexity"],
        ),
        # Scope breadth: a single-service job is a small job, a full production
        # is a large one.
        "service_scope": (
            count_score(factors.service_count, base=25.0, step=9.0),
            WEIGHTS["service_scope"],
        ),
        "repeat_potential": (
            LEVEL_SCORES[factors.repeat_potential],
            WEIGHTS["repeat_potential"],
        ),
        "brand_value": (LEVEL_SCORES[factors.brand_value], WEIGHTS["brand_value"]),
        "ai_estimate": (
            float(factors.ai_estimate) if factors.ai_estimate is not None else 30.0,
            WEIGHTS["ai_estimate"],
        ),
    }
    factors.breakdown.update({name: round(score, 2) for name, (score, _) in components.items()})
    value = round(weighted(components))
    return value, band_for(value)
