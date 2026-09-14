"""Persisting signals, with deduplication."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import Extraction
from app.domain.enums import EvidenceLevel, SignalType
from app.models import Company, Signal, Source
from app.services.normalize import content_hash

logger = logging.getLogger(__name__)


def compute_dedupe_key(company_id: object, signal_type: SignalType, title: str) -> str:
    """``sha256(company_id | type | normalized title)``.

    Company and type are included so that two genuinely different events at the
    same company stay separate, while the same announcement picked up from two
    feeds collapses into one signal.
    """
    return content_hash(str(company_id), signal_type.value, title)


def count_corroborating_sources(
    session: Session, company_id: object, signal_type: SignalType
) -> int:
    """Distinct sources reporting this company and signal type.

    Feeds the corroboration component of the evidence score: several independent
    outlets reporting the same thing is real evidence.
    """
    return int(
        session.scalar(
            select(func.count(func.distinct(Signal.source_id))).where(
                Signal.company_id == company_id, Signal.type == signal_type
            )
        )
        or 0
    )


def get_or_create_signal(
    session: Session, *, company: Company, source: Source, extraction: Extraction
) -> tuple[Signal | None, bool]:
    """Return ``(signal, created)``, or ``(None, False)`` if unusable.

    A signal needs a title. Where the extractor gave none, the source title is
    used; with neither there is nothing to deduplicate on and the document is
    skipped.
    """
    title = (extraction.signal_title or source.title or "").strip()
    if not title:
        logger.warning("signal has no usable title; skipping", extra={"url": source.url})
        return None, False

    signal_type = extraction.signal_type
    dedupe_key = compute_dedupe_key(company.id, signal_type, title)

    existing = session.scalars(select(Signal).where(Signal.dedupe_key == dedupe_key)).first()
    if existing is not None:
        return existing, False

    signal = Signal(
        company_id=company.id,
        source_id=source.id,
        type=signal_type,
        title=title,
        summary=extraction.signal_summary,
        business_impact=extraction.business_impact,
        published_at=source.publication_date,
        confidence=Decimal(str(round(extraction.confidence, 2))),
        # A signal records what the source reported. The inference lives on the
        # opportunity, not here.
        evidence_level=(
            EvidenceLevel.FACT if signal_type is not SignalType.UNKNOWN else EvidenceLevel.INFERENCE
        ),
        dedupe_key=dedupe_key,
    )
    session.add(signal)
    session.flush()
    logger.info(
        "signal recorded",
        extra={
            "signal_id": str(signal.id),
            "company": company.name,
            "type": signal_type.value,
        },
    )
    return signal, True
