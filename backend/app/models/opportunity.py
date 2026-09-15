"""The ``opportunities`` table — the product's actual output."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    AssertionLevel,
    Classification,
    CommercialValueBand,
    ContactTiming,
    OpportunityStatus,
    OpportunityTiming,
    OpportunityType,
    OpportunityWindow,
    RecommendedAction,
)
from app.models.base import Base, created_at_col, enum_col, updated_at_col, uuid_pk

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.signal import Signal


class Opportunity(Base):
    """A scored, ranked, actionable event opportunity.

    Score components are stored alongside the total on purpose. A ranking an
    Account Manager cannot interrogate is a ranking they will not trust, and
    keeping the parts means a weight change can be explained after the fact.
    """

    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    primary_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )

    type: Mapped[OpportunityType] = mapped_column(
        enum_col(OpportunityType, "opportunity_type"), nullable=False, index=True
    )
    #: Never ``FACT`` unless the source announced a confirmed event (spec §6).
    assertion_level: Mapped[AssertionLevel] = mapped_column(
        enum_col(AssertionLevel, "opportunity_assertion_level"),
        nullable=False,
        default=AssertionLevel.PREDICTION,
    )

    # --- score components -------------------------------------------------
    event_probability: Mapped[int] = mapped_column(Integer, nullable=False)
    commercial_value: Mapped[int] = mapped_column(Integer, nullable=False)
    commercial_value_band: Mapped[CommercialValueBand] = mapped_column(
        enum_col(CommercialValueBand, "opportunity_commercial_value_band"), nullable=False
    )
    contact_quality: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timing_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    base_score: Mapped[int] = mapped_column(Integer, nullable=False)
    decay_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=1)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[Classification] = mapped_column(
        enum_col(Classification, "opportunity_classification"), nullable=False, index=True
    )

    # --- the three epistemic statements (spec §23, §36) -------------------
    # Held apart as separate columns rather than blended into prose, so the UI
    # cannot accidentally present a prediction as a fact.
    #: What the source actually states.
    fact: Mapped[str | None] = mapped_column(Text)
    #: What follows from that, reasoned but not stated.
    inference: Mapped[str | None] = mapped_column(Text)
    #: What may happen. Never confirmed.
    prediction: Mapped[str | None] = mapped_column(Text)

    # --- sales payload ----------------------------------------------------
    why_now: Mapped[str] = mapped_column(Text, nullable=False)
    sales_angle: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[RecommendedAction] = mapped_column(
        enum_col(RecommendedAction, "opportunity_recommended_action"), nullable=False
    )
    #: Only services the opportunity actually supports (spec §14).
    recommended_services: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )

    # --- timing -----------------------------------------------------------
    opportunity_window: Mapped[OpportunityWindow] = mapped_column(
        enum_col(OpportunityWindow, "opportunity_window"), nullable=False
    )
    window_ends_on: Mapped[date | None] = mapped_column(Date)
    #: The actual date of the event, when a source states one. This is what makes
    #: timing classification real rather than inferred from a fuzzy window.
    event_date: Mapped[date | None] = mapped_column(Date, index=True)
    #: IMMEDIATE / FUTURE_ACCOUNT / HISTORICAL — how to play it commercially.
    timing_class: Mapped[OpportunityTiming] = mapped_column(
        enum_col(OpportunityTiming, "opportunity_timing_class"),
        nullable=False,
        default=OpportunityTiming.FUTURE_ACCOUNT,
        index=True,
    )
    #: One line explaining the timing verdict, shown to the Account Manager.
    timing_rationale: Mapped[str | None] = mapped_column(Text)
    recommended_contact_timing: Mapped[ContactTiming] = mapped_column(
        enum_col(ContactTiming, "opportunity_contact_timing"), nullable=False
    )

    # --- pipeline ---------------------------------------------------------
    status: Mapped[OpportunityStatus] = mapped_column(
        enum_col(OpportunityStatus, "opportunity_status"),
        nullable=False,
        default=OpportunityStatus.NEW,
        index=True,
    )

    # --- brief bookkeeping ------------------------------------------------
    # Enough history for NEW / UPGRADED / DOWNGRADED / EXPIRED without adding a
    # sixth table.
    previous_score: Mapped[int | None] = mapped_column(Integer)
    previous_classification: Mapped[Classification | None] = mapped_column(
        enum_col(Classification, "opportunity_previous_classification")
    )
    score_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    company: Mapped[Company] = relationship(back_populates="opportunities")
    signal: Mapped[Signal] = relationship(back_populates="opportunities")
    primary_contact: Mapped[Contact | None] = relationship()

    __table_args__ = (
        UniqueConstraint("signal_id", "type", name="uq_opportunities_signal_type"),
        CheckConstraint(
            "event_probability BETWEEN 0 AND 100", name="event_probability_range"
        ),
        CheckConstraint("commercial_value BETWEEN 0 AND 100", name="commercial_value_range"),
        CheckConstraint("contact_quality BETWEEN 0 AND 100", name="contact_quality_range"),
        CheckConstraint("timing_score BETWEEN 0 AND 100", name="timing_score_range"),
        CheckConstraint("evidence_score BETWEEN 0 AND 100", name="evidence_score_range"),
        CheckConstraint("base_score BETWEEN 0 AND 100", name="base_score_range"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("decay_factor > 0 AND decay_factor <= 1", name="decay_factor_range"),
        CheckConstraint("length(trim(why_now)) > 0", name="why_now_not_blank"),
        CheckConstraint("length(trim(sales_angle)) > 0", name="sales_angle_not_blank"),
        # The Top 50 read path: score DESC with a covering status filter. This
        # leads with score, so a standalone score index would be redundant.
        Index("ix_opportunities_rank", score.desc(), "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Opportunity {self.type} score={self.score} {self.classification}>"
