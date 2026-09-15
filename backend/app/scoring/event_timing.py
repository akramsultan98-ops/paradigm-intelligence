"""Commercial timing of an opportunity (Priority 4).

The judgement an Account Manager actually needs is not "how strong is this" but
"can I still win this one, or is this a relationship for the next one". Lead time
answers that, and the answer is counter-intuitive: **an event two weeks away is
usually already contracted.** Its value is the account, not the job.

Three outcomes:

- ``IMMEDIATE`` — far enough out that procurement is plausibly still open. Bid.
- ``FUTURE_ACCOUNT`` — upcoming but too close to win, or undated. Build the
  relationship for what comes next.
- ``HISTORICAL`` — already happened. Useful for account research, and must never
  be ranked as a live opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.config import Settings, get_settings
from app.domain.enums import OpportunityTiming, OpportunityWindow

#: Representative lead time for each fuzzy window, used only when no real event
#: date is known.
_WINDOW_LEAD_DAYS: dict[OpportunityWindow, int | None] = {
    OpportunityWindow.DAYS_0_14: 7,
    OpportunityWindow.DAYS_15_30: 22,
    OpportunityWindow.DAYS_30_60: 45,
    OpportunityWindow.DAYS_60_90: 75,
    OpportunityWindow.MONTHS_3_6: 135,
    OpportunityWindow.MONTHS_6_12: 270,
    OpportunityWindow.UNKNOWN: None,
}


@dataclass(frozen=True, slots=True)
class TimingVerdict:
    """The classification, plus the sentence explaining it."""

    timing: OpportunityTiming
    rationale: str
    #: Days until the event, when a real date is known. Negative means past.
    lead_days: int | None = None

    @property
    def is_live(self) -> bool:
        return self.timing is not OpportunityTiming.HISTORICAL


def classify_timing(
    *,
    event_date: date | None = None,
    event_already_occurred: bool | None = None,
    window: OpportunityWindow = OpportunityWindow.UNKNOWN,
    window_ends_on: date | None = None,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> TimingVerdict:
    """Decide how an opportunity should be played.

    Evidence is used strongest-first: an explicit statement that the event has
    happened, then a real event date, then the window's closing date, then the
    fuzzy window. Anything undated is ``FUTURE_ACCOUNT`` — immediacy has to be
    evidenced, not assumed.
    """
    settings = settings or get_settings()
    as_of = as_of or datetime.now(UTC).date()
    threshold = settings.timing_contracted_lead_days

    if event_already_occurred:
        return TimingVerdict(
            OpportunityTiming.HISTORICAL,
            "The source reports this event has already taken place. Useful for "
            "account research; not a live opportunity.",
        )

    if event_date is not None:
        lead = (event_date - as_of).days
        if lead < 0:
            return TimingVerdict(
                OpportunityTiming.HISTORICAL,
                f"The event was {abs(lead)} day(s) ago ({event_date:%d %b %Y}). "
                "Account research only.",
                lead,
            )
        if lead <= threshold:
            return TimingVerdict(
                OpportunityTiming.FUTURE_ACCOUNT,
                f"The event is in {lead} day(s) ({event_date:%d %b %Y}), so production "
                "is very likely already contracted. Approach it as an account "
                "relationship for the next one — and ask about late-stage gaps.",
                lead,
            )
        return TimingVerdict(
            OpportunityTiming.IMMEDIATE,
            f"The event is in {lead} day(s) ({event_date:%d %b %Y}), far enough out "
            "that procurement is plausibly still open. Bid for it.",
            lead,
        )

    if window_ends_on is not None:
        lead = (window_ends_on - as_of).days
        if lead < 0:
            return TimingVerdict(
                OpportunityTiming.FUTURE_ACCOUNT,
                f"The opportunity window closed {abs(lead)} day(s) ago and no event "
                "date was reported. Treat the company as an account to build rather "
                "than a job to win.",
                None,
            )
        if lead <= threshold:
            return TimingVerdict(
                OpportunityTiming.FUTURE_ACCOUNT,
                f"The window closes in {lead} day(s) and no exact event date was "
                "reported, so anything concrete is likely already committed. Play it "
                "as an account relationship.",
                None,
            )
        return TimingVerdict(
            OpportunityTiming.IMMEDIATE,
            f"The window runs for another {lead} day(s), so there is plausibly still "
            "time to be considered.",
            None,
        )

    lead = _WINDOW_LEAD_DAYS[window]
    if lead is None:
        return TimingVerdict(
            OpportunityTiming.FUTURE_ACCOUNT,
            "No event date and no usable window were reported, so immediacy cannot "
            "be claimed. Worth building the account.",
        )
    if lead <= threshold:
        return TimingVerdict(
            OpportunityTiming.FUTURE_ACCOUNT,
            f"The reported window implies roughly {lead} day(s) of lead time, which "
            "is usually too short to win the work. Build the relationship.",
        )
    return TimingVerdict(
        OpportunityTiming.IMMEDIATE,
        f"The reported window implies roughly {lead} day(s) of lead time, enough to "
        "be considered.",
    )
