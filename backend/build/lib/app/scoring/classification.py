"""Score bands (spec §11) and Top 50 eligibility."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.domain.enums import Classification

#: Inclusive lower bound for each band, highest first.
_BANDS: tuple[tuple[int, Classification], ...] = (
    (95, Classification.EXCEPTIONAL),
    (90, Classification.HOT),
    (85, Classification.VERY_HIGH),
    (80, Classification.HIGH),
)


def classify(score: int, settings: Settings | None = None) -> Classification:
    """Map a 0-100 score onto its band.

    The ``QUALIFIED`` floor is ``MIN_QUALIFYING_SCORE`` rather than a literal 70,
    so raising the bar moves the bands and the Top 50 filter together instead of
    leaving them to disagree. Anything below the threshold is ``NOT_ELIGIBLE``,
    whichever fixed band its raw score would otherwise fall into.
    """
    settings = settings or get_settings()

    # Eligibility is checked first, so classification and the Top 50 filter can
    # never disagree. With MIN_QUALIFYING_SCORE raised to 85, a score of 80 is
    # NOT_ELIGIBLE - calling it HIGH while excluding it from the list would be a
    # label the ranking does not honour.
    if score < settings.min_qualifying_score:
        return Classification.NOT_ELIGIBLE

    for threshold, classification in _BANDS:
        if score >= threshold:
            return classification
    return Classification.QUALIFIED


def is_qualified(score: int, settings: Settings | None = None) -> bool:
    """Whether a score is eligible for the Top 50 at all."""
    settings = settings or get_settings()
    return score >= settings.min_qualifying_score
