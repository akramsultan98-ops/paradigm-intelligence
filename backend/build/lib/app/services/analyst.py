"""Analyst-supplied signal intake.

A person reads something real and enters it with its evidence. The structure they
supply is validated by exactly the same schema an AI extraction is, and processed
by exactly the same pipeline — the only differences are that ``ingest_mode`` is
``ANALYST`` and ``extractor`` says so.
"""

from __future__ import annotations

import logging

from app.ai.base import Extraction
from app.ai.static import StaticExtractionProvider
from app.config import Settings, get_settings
from app.domain.enums import IngestMode, SourceType
from app.services.pipeline import IngestionStats, ingest_documents
from app.sources.base import RawDocument

logger = logging.getLogger(__name__)


def ingest_analyst_signal(
    *,
    url: str,
    title: str | None,
    content: str,
    extraction: Extraction,
    source_type: SourceType = SourceType.OTHER,
    publisher: str | None = None,
    published_at: object = None,
    confidence: float = 0.8,
    settings: Settings | None = None,
) -> IngestionStats:
    """Ingest one analyst-verified signal through the normal pipeline."""
    settings = settings or get_settings()
    document = RawDocument(
        url=url,
        title=title,
        content=content,
        source_type=source_type,
        publisher=publisher,
        published_at=published_at,  # type: ignore[arg-type]
        company_hint=extraction.company_name,
        confidence=confidence,
        adapter_key="analyst",
        ingest_mode=IngestMode.ANALYST,
    )
    return ingest_documents(
        [document], StaticExtractionProvider(extraction, extractor="analyst"), settings=settings
    )
