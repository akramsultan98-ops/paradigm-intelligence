"""The daily brief (spec §30).

Exposed as data. Telegram or email delivery is a thin adapter over this — see
``docs/ROADMAP.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.domain.enums import CLOSED_STATUSES, BriefChange, Classification
from app.models import Opportunity, Signal
from app.services.rescore import classification_counts, eligible_count
from app.services.top50 import get_top_opportunities

#: Bands that count as "hot" for NEW HOT.
HOT_BANDS = frozenset({Classification.HOT, Classification.EXCEPTIONAL})


@dataclass(slots=True)
class ChangedOpportunity:
    """An opportunity that moved, and how."""

    opportunity: Opportunity
    change: BriefChange
    delta: int


@dataclass(slots=True)
class DailyBrief:
    generated_at: datetime
    window_hours: int
    qualifying_threshold: int
    top_n: int
    eligible_total: int
    classification_counts: dict[str, int]
    #: Total new qualified opportunities in the window, before the top-N trim, so
    #: the UI can say "showing 10 of 23".
    new_total: int = 0
    new_opportunities: list[Opportunity] = field(default_factory=list)
    changed_opportunities: list[ChangedOpportunity] = field(default_factory=list)
    top_opportunities: list[Opportunity] = field(default_factory=list)
    new_hot: list[Opportunity] = field(default_factory=list)
    upgraded: list[ChangedOpportunity] = field(default_factory=list)
    downgraded: list[ChangedOpportunity] = field(default_factory=list)
    expired: list[ChangedOpportunity] = field(default_factory=list)


def _loaded() -> object:
    return (
        joinedload(Opportunity.company),
        joinedload(Opportunity.signal).joinedload(Signal.source),
        joinedload(Opportunity.primary_contact),
    )


def build_daily_brief(
    session: Session,
    *,
    window_hours: int | None = None,
    settings: Settings | None = None,
) -> DailyBrief:
    """Assemble today's brief.

    "Changed" is derived from ``previous_score`` on the opportunity row rather
    than from an events table: it is the one piece of history the brief actually
    needs, and carrying it inline keeps V1 at five tables.
    """
    settings = settings or get_settings()
    window_hours = window_hours or settings.brief_lookback_hours
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=window_hours)
    threshold = settings.min_qualifying_score

    new_opportunities = list(
        session.scalars(
            select(Opportunity)
            .options(*_loaded())
            .where(
                Opportunity.created_at >= cutoff,
                Opportunity.score >= threshold,
                Opportunity.status.notin_([status.value for status in CLOSED_STATUSES]),
            )
            .order_by(Opportunity.score.desc())
        ).unique().all()
    )

    moved = list(
        session.scalars(
            select(Opportunity)
            .options(*_loaded())
            .where(
                Opportunity.score_changed_at.is_not(None),
                Opportunity.score_changed_at >= cutoff,
                Opportunity.previous_score.is_not(None),
                # A brand-new opportunity is reported as new, not as changed.
                or_(Opportunity.created_at < cutoff, Opportunity.created_at.is_(None)),
            )
            .order_by(Opportunity.score.desc())
        ).unique().all()
    )

    changed: list[ChangedOpportunity] = []
    upgraded: list[ChangedOpportunity] = []
    downgraded: list[ChangedOpportunity] = []
    expired: list[ChangedOpportunity] = []

    for opportunity in moved:
        previous = opportunity.previous_score or 0
        delta = opportunity.score - previous

        # Expiry is the meaningful transition: it left the Top 50. Report it as
        # expired rather than merely downgraded.
        if previous >= threshold and opportunity.score < threshold:
            entry = ChangedOpportunity(opportunity, BriefChange.EXPIRED, delta)
            expired.append(entry)
        elif delta > 0:
            entry = ChangedOpportunity(opportunity, BriefChange.UPGRADED, delta)
            upgraded.append(entry)
        elif delta < 0:
            entry = ChangedOpportunity(opportunity, BriefChange.DOWNGRADED, delta)
            downgraded.append(entry)
        else:
            continue
        changed.append(entry)

    changed.sort(key=lambda item: abs(item.delta), reverse=True)
    changed = changed[: settings.brief_top_changed_limit]

    # Computed before the top-N trim so a hot lead is never hidden by the cut.
    new_hot = [
        opportunity
        for opportunity in new_opportunities
        if opportunity.classification in HOT_BANDS
    ]
    new_total = len(new_opportunities)

    return DailyBrief(
        generated_at=now,
        window_hours=window_hours,
        new_total=new_total,
        qualifying_threshold=threshold,
        top_n=settings.top_n,
        eligible_total=eligible_count(session, settings),
        classification_counts=classification_counts(session),
        new_opportunities=new_opportunities[: settings.brief_top_new_limit],
        changed_opportunities=changed,
        top_opportunities=get_top_opportunities(session, settings=settings),
        new_hot=new_hot,
        upgraded=upgraded,
        downgraded=downgraded,
        expired=expired,
    )
