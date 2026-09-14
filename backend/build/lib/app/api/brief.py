"""Daily brief endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, SettingsDep
from app.schemas.brief import ChangedOpportunityOut, DailyBriefResponse
from app.schemas.opportunity import OpportunityOut
from app.services.brief import ChangedOpportunity, build_daily_brief

router = APIRouter(prefix="/brief", tags=["brief"])


def _changed(entries: list[ChangedOpportunity]) -> list[ChangedOpportunityOut]:
    return [
        ChangedOpportunityOut(
            change=entry.change,
            delta=entry.delta,
            opportunity=OpportunityOut.model_validate(entry.opportunity),
        )
        for entry in entries
    ]


def _ranked(opportunities: list) -> list[OpportunityOut]:
    items = []
    for index, opportunity in enumerate(opportunities, start=1):
        item = OpportunityOut.model_validate(opportunity)
        item.rank = index
        items.append(item)
    return items


@router.get("/daily", response_model=DailyBriefResponse, summary="Today's brief")
def daily(
    session: SessionDep,
    settings: SettingsDep,
    window_hours: int = Query(default=None, ge=1, le=720),
) -> DailyBriefResponse:
    """New, changed, and current Top 50, plus the four movement buckets.

    Exposed as data. Telegram and email delivery sit on top of this without any
    change here.
    """
    brief = build_daily_brief(session, window_hours=window_hours, settings=settings)
    return DailyBriefResponse(
        generated_at=brief.generated_at,
        window_hours=brief.window_hours,
        qualifying_threshold=brief.qualifying_threshold,
        top_n=brief.top_n,
        eligible_total=brief.eligible_total,
        classification_counts=brief.classification_counts,
        top_new_opportunities=_ranked(brief.new_opportunities),
        top_changed_opportunities=_changed(brief.changed_opportunities),
        current_top_50=_ranked(brief.top_opportunities),
        new_hot=_ranked(brief.new_hot),
        upgraded=_changed(brief.upgraded),
        downgraded=_changed(brief.downgraded),
        expired=_changed(brief.expired),
    )
