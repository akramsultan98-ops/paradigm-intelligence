"""Score decay (spec §28).

An opportunity that was strong three months ago is not strong today. Decay is
what lets a stale opportunity leave the Top 50 on its own, without anyone having
to prune the list by hand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class DecayInputs:
    """What ages an opportunity."""

    #: When the underlying signal was published (or first seen).
    signal_date: datetime | date | None
    #: When the opportunity window closes, if known.
    window_ends_on: date | None
    evidence_score: int
    #: Defaults to today; injected so decay is testable.
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class DecayResult:
    factor: float
    age_days: int
    age_factor: float
    missed_window: bool
    thin_evidence: bool

    @property
    def reasons(self) -> list[str]:
        """Human-readable explanation, surfaced through the API."""
        reasons: list[str] = []
        if self.age_factor < 1.0:
            reasons.append(f"signal is {self.age_days} days old")
        if self.missed_window:
            reasons.append("opportunity window has closed")
        if self.thin_evidence:
            reasons.append("evidence is thin")
        return reasons


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # Naive timestamps are treated as UTC rather than rejected; feeds are
        # inconsistent about offsets and an unusable date is worse than an
        # assumed one here.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).date()
    return value


def compute_decay(inputs: DecayInputs, settings: Settings | None = None) -> DecayResult:
    """Combine age, missed-window and thin-evidence penalties.

    An undated signal gets no age credit and no age penalty — it is neither aged
    nor treated as permanently fresh, because we genuinely do not know.
    """
    settings = settings or get_settings()
    as_of = inputs.as_of or datetime.now(UTC).date()
    signal_date = _as_date(inputs.signal_date)

    if signal_date is None:
        age_days = 0
        age_factor = 1.0
    else:
        age_days = max((as_of - signal_date).days, 0)
        if age_days <= settings.decay_grace_days:
            age_factor = 1.0
        else:
            age_factor = max(
                settings.decay_floor,
                math.exp(-(age_days - settings.decay_grace_days) / settings.decay_tau_days),
            )

    missed_window = inputs.window_ends_on is not None and inputs.window_ends_on < as_of
    thin_evidence = inputs.evidence_score < settings.thin_evidence_threshold

    factor = age_factor
    if missed_window:
        factor *= settings.missed_window_penalty
    if thin_evidence:
        factor *= settings.thin_evidence_penalty

    factor = max(settings.decay_floor, min(1.0, factor))
    return DecayResult(
        factor=round(factor, 3),
        age_days=age_days,
        age_factor=round(age_factor, 3),
        missed_window=missed_window,
        thin_evidence=thin_evidence,
    )
