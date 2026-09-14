"""EVIDENCE_QUALITY: how well-sourced an opportunity is."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import SourceType
from app.scoring.scales import SOURCE_TIER_SCORES, clamp, count_score, weighted

WEIGHTS = {
    "source_tier": 0.45,
    "source_confidence": 0.25,
    "publication_date": 0.10,
    "extraction_confidence": 0.10,
    "corroboration": 0.10,
}

#: A record with no publication date is not worthless, but it cannot be aged,
#: so it is scored well below one that can be.
DATE_PRESENT_SCORE = 100.0
DATE_MISSING_SCORE = 30.0


@dataclass(frozen=True, slots=True)
class EvidenceFactors:
    """Inputs to the evidence score."""

    source_type: SourceType
    source_confidence: float
    has_publication_date: bool
    extraction_confidence: float
    #: Distinct sources reporting the same company + signal type.
    corroborating_sources: int = 1


def score_evidence(factors: EvidenceFactors) -> int:
    """EVIDENCE_QUALITY, 0-100."""
    components = {
        "source_tier": (SOURCE_TIER_SCORES[factors.source_type], WEIGHTS["source_tier"]),
        "source_confidence": (
            clamp(factors.source_confidence * 100.0),
            WEIGHTS["source_confidence"],
        ),
        "publication_date": (
            DATE_PRESENT_SCORE if factors.has_publication_date else DATE_MISSING_SCORE,
            WEIGHTS["publication_date"],
        ),
        "extraction_confidence": (
            clamp(factors.extraction_confidence * 100.0),
            WEIGHTS["extraction_confidence"],
        ),
        # One source is the baseline at 40; each additional independent source
        # adds 30 up to the cap.
        "corroboration": (
            count_score(max(factors.corroborating_sources - 1, 0), base=40.0, step=30.0),
            WEIGHTS["corroboration"],
        ),
    }
    return round(weighted(components))
