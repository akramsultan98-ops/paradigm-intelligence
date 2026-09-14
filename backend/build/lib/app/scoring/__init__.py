"""The deterministic scoring engine.

Given the same facts this package always produces the same score. Every constant
it uses comes from ``app.config``. See ``docs/SCORING.md``.
"""

from app.scoring.classification import classify, is_qualified
from app.scoring.commercial_value import CommercialValueFactors, score_commercial_value
from app.scoring.contact_quality import (
    ContactFactors,
    score_contact,
    score_opportunity_contacts,
)
from app.scoring.decay import DecayInputs, compute_decay
from app.scoring.engine import ScoreInputs, ScoreResult, score_opportunity
from app.scoring.event_probability import EventProbabilityFactors, score_event_probability
from app.scoring.evidence import EvidenceFactors, score_evidence
from app.scoring.timing import contact_timing_for, timing_score_for, window_end_date

__all__ = [
    "CommercialValueFactors",
    "ContactFactors",
    "DecayInputs",
    "EvidenceFactors",
    "EventProbabilityFactors",
    "ScoreInputs",
    "ScoreResult",
    "classify",
    "compute_decay",
    "contact_timing_for",
    "is_qualified",
    "score_commercial_value",
    "score_contact",
    "score_evidence",
    "score_event_probability",
    "score_opportunity",
    "score_opportunity_contacts",
    "timing_score_for",
    "window_end_date",
]
