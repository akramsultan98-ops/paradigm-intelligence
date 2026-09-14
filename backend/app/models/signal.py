"""The ``signals`` table — a business fact about a company."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import EvidenceLevel, SignalType
from app.models.base import Base, created_at_col, enum_col, uuid_pk

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.opportunity import Opportunity
    from app.models.source import Source


class Signal(Base):
    """Recent business activity detected for a company.

    A signal records what a source *reported*. Whether it implies an event is a
    separate judgement, carried by ``Opportunity``.
    """

    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    type: Mapped[SignalType] = mapped_column(
        enum_col(SignalType, "signal_type"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    business_impact: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    evidence_level: Mapped[EvidenceLevel] = mapped_column(
        enum_col(EvidenceLevel, "signal_evidence_level"),
        nullable=False,
        default=EvidenceLevel.FACT,
    )
    #: ``sha256(company_id | type | normalized title)`` — stops the same story
    #: from two feeds becoming two signals.
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    created_at: Mapped[datetime] = created_at_col()

    company: Mapped[Company] = relationship(back_populates="signals")
    source: Mapped[Source] = relationship()
    opportunities: Mapped[list[Opportunity]] = relationship(
        back_populates="signal", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        # Leads with company_id, covering FK lookups and cascade deletes.
        Index("ix_signals_company_published", "company_id", "published_at"),
    )

    @property
    def effective_date(self) -> datetime:
        """Publication date where known, else when we first saw it.

        Decay needs a date for every signal, and a feed without dates must not
        be treated as permanently fresh.
        """
        return self.published_at or self.created_at

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Signal {self.type} {self.title[:50]!r}>"
