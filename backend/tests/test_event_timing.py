"""Event timing (Priority 4).

The rule the whole feature exists for: **a past event is never ranked as if it
were still upcoming**, and an event two weeks away is an account relationship
rather than a job to bid for.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domain.enums import LIVE_TIMINGS, OpportunityTiming, OpportunityWindow
from app.scoring.event_timing import classify_timing

AS_OF = date(2026, 9, 15)


def _timing(**kwargs) -> OpportunityTiming:
    return classify_timing(as_of=AS_OF, **kwargs).timing


# --- the non-negotiable: the past is the past ------------------------------


def test_a_past_event_is_historical() -> None:
    verdict = classify_timing(event_date=date(2026, 7, 20), as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.HISTORICAL
    assert verdict.lead_days == -57
    assert "57" in verdict.rationale


def test_an_event_reported_as_already_held_is_historical_even_without_a_date() -> None:
    """A source saying "opened its new plant" needs no date to be in the past."""
    verdict = classify_timing(event_already_occurred=True, as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.HISTORICAL


def test_already_occurred_beats_an_optimistic_window() -> None:
    """Explicit evidence outranks a fuzzy window, which is only ever a guess."""
    assert (
        _timing(event_already_occurred=True, window=OpportunityWindow.MONTHS_3_6)
        is OpportunityTiming.HISTORICAL
    )


def test_historical_is_not_a_live_timing() -> None:
    assert OpportunityTiming.HISTORICAL not in LIVE_TIMINGS
    assert OpportunityTiming.IMMEDIATE in LIVE_TIMINGS
    assert OpportunityTiming.FUTURE_ACCOUNT in LIVE_TIMINGS


# --- the counter-intuitive part: soon means already contracted -------------


@pytest.mark.parametrize("lead", [0, 1, 7, 14, 21])
def test_an_event_inside_the_contracted_window_is_a_future_account(lead: int) -> None:
    verdict = classify_timing(event_date=AS_OF + timedelta(days=lead), as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.FUTURE_ACCOUNT
    assert verdict.lead_days == lead
    assert "already contracted" in verdict.rationale


@pytest.mark.parametrize("lead", [22, 30, 90, 400])
def test_an_event_far_enough_out_is_immediate(lead: int) -> None:
    verdict = classify_timing(event_date=AS_OF + timedelta(days=lead), as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.IMMEDIATE
    assert "still open" in verdict.rationale


def test_today_is_not_biddable() -> None:
    """Nothing about an event happening today is a procurement opportunity."""
    assert _timing(event_date=AS_OF) is OpportunityTiming.FUTURE_ACCOUNT


# --- degrading gracefully when no date was published ----------------------


def test_nothing_known_is_a_future_account_not_an_immediate_one() -> None:
    """Immediacy has to be evidenced. Silence is not evidence."""
    verdict = classify_timing(as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.FUTURE_ACCOUNT
    assert verdict.lead_days is None


def test_a_closed_window_without_an_event_date_is_not_historical() -> None:
    """A stale window means we lost track, not that the event happened.

    Calling it HISTORICAL would assert something no source said.
    """
    verdict = classify_timing(window_ends_on=AS_OF - timedelta(days=10), as_of=AS_OF)
    assert verdict.timing is OpportunityTiming.FUTURE_ACCOUNT


def test_an_open_window_is_biddable() -> None:
    assert (
        _timing(window_ends_on=AS_OF + timedelta(days=60)) is OpportunityTiming.IMMEDIATE
    )


def test_a_window_closing_within_the_threshold_is_a_future_account() -> None:
    assert (
        _timing(window_ends_on=AS_OF + timedelta(days=10))
        is OpportunityTiming.FUTURE_ACCOUNT
    )


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (OpportunityWindow.DAYS_0_14, OpportunityTiming.FUTURE_ACCOUNT),
        (OpportunityWindow.DAYS_15_30, OpportunityTiming.IMMEDIATE),
        (OpportunityWindow.DAYS_30_60, OpportunityTiming.IMMEDIATE),
        (OpportunityWindow.MONTHS_6_12, OpportunityTiming.IMMEDIATE),
        (OpportunityWindow.UNKNOWN, OpportunityTiming.FUTURE_ACCOUNT),
    ],
)
def test_fuzzy_windows_are_the_last_resort(
    window: OpportunityWindow, expected: OpportunityTiming
) -> None:
    assert _timing(window=window) is expected


def test_an_exact_date_beats_the_window_it_disagrees_with() -> None:
    """A stated date is evidence; a window is an inference from one."""
    assert (
        _timing(event_date=AS_OF - timedelta(days=3), window=OpportunityWindow.MONTHS_3_6)
        is OpportunityTiming.HISTORICAL
    )


# --- the rationale is for a person to read -------------------------------


def test_every_verdict_explains_itself_in_a_sentence() -> None:
    cases = [
        {},
        {"event_already_occurred": True},
        {"event_date": AS_OF + timedelta(days=40)},
        {"event_date": AS_OF + timedelta(days=5)},
        {"event_date": AS_OF - timedelta(days=5)},
        {"window": OpportunityWindow.DAYS_30_60},
        {"window_ends_on": AS_OF + timedelta(days=40)},
    ]
    for case in cases:
        verdict = classify_timing(as_of=AS_OF, **case)
        assert verdict.rationale.endswith("."), case
        assert len(verdict.rationale) > 40, case
