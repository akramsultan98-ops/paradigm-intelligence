"""Ordinal scales and the signal strength table.

One rule governs every scale here: **``UNKNOWN`` scores below ``MEDIUM``.**
Missing evidence must never help an opportunity, and scoring an unknown at the
midpoint is exactly how a thin lead climbs a ranking it has not earned.
"""

from __future__ import annotations

from app.domain.enums import AttendeeBand, Level, Scale, SignalType, SizeBand, SourceType

# --- generic ordinals -----------------------------------------------------

LEVEL_SCORES: dict[Level, float] = {
    Level.LOW: 25.0,
    Level.MEDIUM: 55.0,
    Level.HIGH: 85.0,
    Level.UNKNOWN: 30.0,
}

SCALE_SCORES: dict[Scale, float] = {
    Scale.SMALL: 25.0,
    Scale.MEDIUM: 50.0,
    Scale.LARGE: 75.0,
    Scale.MAJOR: 100.0,
    Scale.UNKNOWN: 30.0,
}

SIZE_SCORES: dict[SizeBand, float] = {
    SizeBand.SMALL: 25.0,
    SizeBand.MEDIUM: 50.0,
    SizeBand.LARGE: 75.0,
    SizeBand.ENTERPRISE: 100.0,
    SizeBand.UNKNOWN: 35.0,
}

ATTENDEE_SCORES: dict[AttendeeBand, float] = {
    AttendeeBand.UNDER_50: 25.0,
    AttendeeBand.FROM_50_TO_200: 50.0,
    AttendeeBand.FROM_200_TO_500: 75.0,
    AttendeeBand.OVER_500: 100.0,
    AttendeeBand.UNKNOWN: 35.0,
}

#: Tri-state boolean: True / False / unknown.
BOOL_TRUE_SCORE = 88.0
BOOL_FALSE_SCORE = 25.0
BOOL_UNKNOWN_SCORE = 35.0


# --- signal strength ------------------------------------------------------

#: How strongly each kind of business activity implies corporate event spend.
#: Event announcements sit at the top because they *are* the thing; tenders sit
#: low because procurement noise rarely converts on its own.
SIGNAL_STRENGTH: dict[SignalType, float] = {
    SignalType.CONFERENCE: 95.0,
    SignalType.EXHIBITION: 92.0,
    SignalType.PRODUCT_LAUNCH: 85.0,
    SignalType.WORKSHOP: 85.0,
    SignalType.SEMINAR: 85.0,
    SignalType.NEW_FACILITY: 80.0,
    SignalType.PROJECT_LAUNCH: 80.0,
    SignalType.SPONSORSHIP: 80.0,
    SignalType.MARKET_ENTRY: 78.0,
    SignalType.TRAINING_PROGRAM: 78.0,
    SignalType.JOINT_VENTURE: 75.0,
    SignalType.ANNIVERSARY: 75.0,
    SignalType.PARTNERSHIP: 72.0,
    SignalType.EXPANSION: 72.0,
    SignalType.PROJECT_COMPLETION: 72.0,
    SignalType.DELEGATION: 72.0,
    SignalType.MOU: 70.0,
    SignalType.MILESTONE: 70.0,
    SignalType.NEW_PROJECT: 70.0,
    SignalType.EXECUTIVE_VISIT: 70.0,
    SignalType.NEW_CONTRACT: 68.0,
    SignalType.INVESTMENT: 65.0,
    SignalType.NEW_TECHNOLOGY: 62.0,
    SignalType.DIGITAL_TRANSFORMATION: 60.0,
    SignalType.CUSTOMER_WIN: 58.0,
    SignalType.TENDER: 55.0,
    SignalType.PROCUREMENT: 50.0,
    SignalType.UNKNOWN: 20.0,
}


# --- source trust tiers (spec §17) ---------------------------------------

SOURCE_TIER_SCORES: dict[SourceType, float] = {
    SourceType.COMPANY: 100.0,
    SourceType.GOVERNMENT: 95.0,
    SourceType.PROCUREMENT: 92.0,
    SourceType.BUSINESS_PUBLICATION: 80.0,
    SourceType.INDUSTRY_PUBLICATION: 70.0,
    SourceType.EVENT: 60.0,
    SourceType.PUBLIC_PROFILE: 55.0,
    SourceType.OTHER: 35.0,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return max(low, min(high, value))


def tri_state(value: bool | None) -> float:
    """Score a boolean factor that may be unknown."""
    if value is None:
        return BOOL_UNKNOWN_SCORE
    return BOOL_TRUE_SCORE if value else BOOL_FALSE_SCORE


def count_score(count: int | None, base: float, step: float, unknown: float = 30.0) -> float:
    """Score a count: ``base + step × count``, capped at 100.

    Used for stakeholder counts and service-scope breadth, where more is better
    but the gain flattens out.
    """
    if count is None or count < 0:
        return unknown
    return clamp(base + step * count)


def weighted(components: dict[str, tuple[float, float]]) -> float:
    """Weighted mean of ``{name: (score, weight)}``.

    Weights are normalized by their own sum, so a factor set can be extended or
    trimmed without every weight needing to be rebalanced by hand.
    """
    total_weight = sum(weight for _, weight in components.values())
    if total_weight <= 0:
        return 0.0
    total = sum(score * weight for score, weight in components.values())
    return clamp(total / total_weight)
