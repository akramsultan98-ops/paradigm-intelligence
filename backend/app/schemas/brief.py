"""Daily brief responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import BriefChange
from app.schemas.opportunity import OpportunityOut


class ChangedOpportunityOut(BaseModel):
    change: BriefChange
    delta: int = Field(description="Score movement since the previous score.")
    opportunity: OpportunityOut


class DailyBriefResponse(BaseModel):
    """Spec §30: new, changed, current Top 50, and the four movement buckets."""

    generated_at: datetime
    window_hours: int
    qualifying_threshold: int
    top_n: int
    eligible_total: int
    classification_counts: dict[str, int]

    top_new_opportunities: list[OpportunityOut] = Field(default_factory=list)
    top_changed_opportunities: list[ChangedOpportunityOut] = Field(default_factory=list)
    current_top_50: list[OpportunityOut] = Field(default_factory=list)

    new_hot: list[OpportunityOut] = Field(default_factory=list)
    upgraded: list[ChangedOpportunityOut] = Field(default_factory=list)
    downgraded: list[ChangedOpportunityOut] = Field(default_factory=list)
    expired: list[ChangedOpportunityOut] = Field(default_factory=list)
