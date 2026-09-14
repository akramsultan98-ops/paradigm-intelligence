"""The ``companies`` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import SizeBand
from app.models.base import Base, created_at_col, enum_col, updated_at_col, uuid_pk

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.opportunity import Opportunity
    from app.models.signal import Signal


class Company(Base):
    """A corporate account.

    ``normalized_name`` is the deduplication key: ``domain`` is more reliable but
    is often simply unavailable from a news article, so it cannot be required.
    """

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(253), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    sector: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    #: Beyond the spec minimum, and load-bearing: both event probability and
    #: commercial value depend on company scale.
    size_band: Mapped[SizeBand] = mapped_column(
        enum_col(SizeBand, "company_size_band"), nullable=False, default=SizeBand.UNKNOWN
    )
    event_potential_score: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    signals: Mapped[list[Signal]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    opportunities: Mapped[list[Opportunity]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_potential_score IS NULL "
            "OR (event_potential_score >= 0 AND event_potential_score <= 100)",
            name="event_potential_score_range",
        ),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # Leads with sector, so it also serves sector-only filtering.
        Index("ix_companies_sector_size", "sector", "size_band"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Company {self.name!r} sector={self.sector!r}>"
