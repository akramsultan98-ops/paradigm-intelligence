"""Timing: how soon the opportunity is live, and when to make contact."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.enums import ContactTiming, OpportunityWindow

TIMING_SCORES: dict[OpportunityWindow, int] = {
    OpportunityWindow.DAYS_0_14: 100,
    OpportunityWindow.DAYS_15_30: 90,
    OpportunityWindow.DAYS_30_60: 75,
    OpportunityWindow.DAYS_60_90: 60,
    OpportunityWindow.MONTHS_3_6: 45,
    OpportunityWindow.MONTHS_6_12: 25,
    OpportunityWindow.UNKNOWN: 20,
}

#: Upper bound of each window in days, used to date the window's expiry.
WINDOW_DAYS: dict[OpportunityWindow, int | None] = {
    OpportunityWindow.DAYS_0_14: 14,
    OpportunityWindow.DAYS_15_30: 30,
    OpportunityWindow.DAYS_30_60: 60,
    OpportunityWindow.DAYS_60_90: 90,
    OpportunityWindow.MONTHS_3_6: 183,
    OpportunityWindow.MONTHS_6_12: 365,
    OpportunityWindow.UNKNOWN: None,
}

CONTACT_TIMINGS: dict[OpportunityWindow, ContactTiming] = {
    OpportunityWindow.DAYS_0_14: ContactTiming.IMMEDIATE,
    OpportunityWindow.DAYS_15_30: ContactTiming.WITHIN_1_WEEK,
    OpportunityWindow.DAYS_30_60: ContactTiming.WITHIN_2_WEEKS,
    OpportunityWindow.DAYS_60_90: ContactTiming.WITHIN_1_MONTH,
    OpportunityWindow.MONTHS_3_6: ContactTiming.MONITOR_MONTHLY,
    OpportunityWindow.MONTHS_6_12: ContactTiming.MONITOR_QUARTERLY,
    OpportunityWindow.UNKNOWN: ContactTiming.RESEARCH_FIRST,
}


def timing_score_for(window: OpportunityWindow) -> int:
    """TIMING component, 0-100."""
    return TIMING_SCORES[window]


def contact_timing_for(
    window: OpportunityWindow, *, has_contact: bool = True
) -> ContactTiming:
    """RECOMMENDED_CONTACT_TIMING.

    Without a known contact there is nobody to call today, however urgent the
    window is, so the recommendation becomes research rather than a deadline we
    cannot act on.
    """
    if not has_contact:
        return ContactTiming.RESEARCH_FIRST
    return CONTACT_TIMINGS[window]


def window_end_date(
    window: OpportunityWindow, reference: datetime | date | None
) -> date | None:
    """When the window closes, or ``None`` when it cannot be known.

    ``None`` for an unknown window is deliberate: a guessed expiry date would
    trigger the missed-window decay penalty on evidence we do not have.
    """
    days = WINDOW_DAYS[window]
    if days is None or reference is None:
        return None
    start = reference.date() if isinstance(reference, datetime) else reference
    return start + timedelta(days=days)
