"""The ``outreach_log`` table — what was actually done, and when.

The sixth table, and the only one added beyond the original five. It earns its
place: "store outreach history" means many records per company over time, which no
amount of columns on ``contacts`` can represent.

Current state (status, last contacted, next follow-up) is denormalised onto
``contacts`` so a profile renders in one query; this table is the history.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import OutreachAction, OutreachStatus
from app.models.base import Base, created_at_col, enum_col, uuid_pk

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.opportunity import Opportunity


class OutreachLog(Base):
    """One recorded outreach action."""

    __tablename__ = "outreach_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Always company-scoped: you can work an account without a named person yet.
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    #: Which opportunity prompted this, when it was prompted by one.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), index=True
    )

    action: Mapped[OutreachAction] = mapped_column(
        enum_col(OutreachAction, "outreach_action"), nullable=False
    )
    #: The status this action moved the relationship to.
    status_after: Mapped[OutreachStatus] = mapped_column(
        enum_col(OutreachStatus, "outreach_status_after"), nullable=False
    )
    #: The business time of the action, which may differ from ``created_at`` when
    #: something is logged after the fact. Indexed only through the per-company
    #: composite below: there is no global "all outreach by time" read path.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    next_follow_up_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    #: Who logged it. Free text: V1 has one shared API key, not user accounts.
    logged_by: Mapped[str | None] = mapped_column(String(120))

    created_at: Mapped[datetime] = created_at_col()

    company: Mapped[Company] = relationship()
    contact: Mapped[Contact | None] = relationship()
    opportunity: Mapped[Opportunity | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0", name="note_not_blank"
        ),
        # The company timeline read path: newest first.
        Index("ix_outreach_log_company_time", "company_id", occurred_at.desc()),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OutreachLog {self.action} {self.occurred_at:%Y-%m-%d}>"
