"""The ``contacts`` table — publicly available professional contacts only."""

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
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ContactKind, Department, EmailStatus, OutreachStatus
from app.models.base import Base, created_at_col, enum_col, updated_at_col, uuid_pk

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.source import Source


class Contact(Base):
    """A person who plausibly influences event spending at a company.

    Nothing in this table is ever synthesised. An address we worked out rather
    than read is stored as ``INFERRED`` and stays that way until an actual
    verification step says otherwise.
    """

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(300))
    department: Mapped[Department] = mapped_column(
        enum_col(Department, "contact_department"),
        nullable=False,
        default=Department.UNKNOWN,
        index=True,
    )

    email: Mapped[str | None] = mapped_column(String(320))
    normalized_email: Mapped[str | None] = mapped_column(String(320), unique=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    normalized_linkedin_url: Mapped[str | None] = mapped_column(String(500), unique=True)
    #: Public business number only, and only when a source publishes one. Never
    #: derived, never a personal mobile inferred from anything.
    phone: Mapped[str | None] = mapped_column(String(50))
    normalized_phone: Mapped[str | None] = mapped_column(String(32), index=True)

    #: Whether this is a person, an official department route, or neither. A field
    #: rather than a guess from the name, so the two can never be confused.
    contact_kind: Mapped[ContactKind] = mapped_column(
        enum_col(ContactKind, "contact_kind"),
        nullable=False,
        default=ContactKind.UNKNOWN,
        index=True,
    )
    #: When this contact was last confirmed against its source. Contact data rots;
    #: an Account Manager needs to know how old it is.
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- outreach state (Priority 5) -----------------------------------
    # Denormalised from outreach_log so a profile renders in one query. The log
    # remains the record of what happened.
    outreach_status: Mapped[OutreachStatus] = mapped_column(
        enum_col(OutreachStatus, "contact_outreach_status"),
        nullable=False,
        default=OutreachStatus.NOT_CONTACTED,
        index=True,
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_follow_up_on: Mapped[date | None] = mapped_column(Date, index=True)

    email_status: Mapped[EmailStatus] = mapped_column(
        enum_col(EmailStatus, "contact_email_status"),
        nullable=False,
        default=EmailStatus.UNKNOWN,
    )
    contact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    company: Mapped[Company] = relationship(back_populates="contacts")
    source: Mapped[Source | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "company_id", "normalized_name", "department", name="uq_contacts_company_person"
        ),
        CheckConstraint(
            "contact_score >= 0 AND contact_score <= 100", name="contact_score_range"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # An address is either absent or actually present; a blank string is a
        # bug we would rather not store.
        CheckConstraint(
            "email IS NULL OR length(trim(email)) > 0", name="email_not_blank"
        ),
        # No email means no email status other than UNKNOWN.
        CheckConstraint(
            "email IS NOT NULL OR email_status = 'UNKNOWN'",
            name="email_status_requires_email",
        ),
        # Leads with company_id, covering FK lookups and cascade deletes.
        Index("ix_contacts_company_score", "company_id", "contact_score"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Contact {self.name!r} {self.job_title!r} score={self.contact_score}>"
