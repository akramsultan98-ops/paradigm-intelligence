"""The ``sources`` table — provenance for everything else."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import IngestMode, SourceType
from app.models.base import Base, created_at_col, enum_col, uuid_pk


class Source(Base):
    """A single retrieved document.

    Two independent dedupe keys, because they catch different things:
    ``normalized_url`` catches the same page fetched twice, ``content_hash``
    catches the same story republished at a different URL.
    """

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(
        enum_col(SourceType, "source_type"), nullable=False, index=True
    )
    publisher: Mapped[str | None] = mapped_column(String(300))
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: Which adapter produced this, for debugging a misbehaving feed.
    adapter_key: Mapped[str | None] = mapped_column(String(120), index=True)
    #: Provenance. Keeps fixtures out of the operational Top 50 (spec §37).
    ingest_mode: Mapped[IngestMode] = mapped_column(
        enum_col(IngestMode, "source_ingest_mode"),
        nullable=False,
        default=IngestMode.AUTOMATED,
        index=True,
    )

    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_is_sha256"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Source {self.source_type} {self.url[:60]!r}>"
