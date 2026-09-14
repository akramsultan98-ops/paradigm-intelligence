"""The ingestion pipeline.

    SOURCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE → TOP 50

One linear pass per document. Each document is committed on its own so that one
bad document cannot roll back a whole run's work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.base import AIProvider, Extraction, ExtractionRequest
from app.config import Settings, get_settings
from app.db import session_scope
from app.services.companies import find_company_mentioned, resolve_or_create
from app.services.opportunities import create_or_update_opportunity
from app.services.signals import get_or_create_signal
from app.services.sources import get_or_create_source
from app.sources.base import RawDocument, SourceAdapter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionStats:
    """What a run actually did. Returned by the API and printed by the CLI."""

    documents_seen: int = 0
    sources_created: int = 0
    duplicates_skipped: int = 0
    extractions_failed: int = 0
    companies_unresolved: int = 0
    signals_created: int = 0
    opportunities_created: int = 0
    opportunities_updated: int = 0
    no_event_implication: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "documents_seen": self.documents_seen,
            "sources_created": self.sources_created,
            "duplicates_skipped": self.duplicates_skipped,
            "extractions_failed": self.extractions_failed,
            "companies_unresolved": self.companies_unresolved,
            "signals_created": self.signals_created,
            "opportunities_created": self.opportunities_created,
            "opportunities_updated": self.opportunities_updated,
            "no_event_implication": self.no_event_implication,
            "errors": self.errors,
        }


def _resolve_company(session: Session, extraction: Extraction, document: RawDocument):
    """Resolve the company, falling back to recognising a known one.

    The fallback only ever matches a company already in the database whose name
    appears verbatim in the text. It never creates one from a guess, so an
    unattributable article stays unattributed.
    """
    company = resolve_or_create(session, extraction)
    if company is not None:
        return company
    return find_company_mentioned(session, document.title, document.content)


def process_document(
    session: Session,
    document: RawDocument,
    provider: AIProvider,
    stats: IngestionStats,
    *,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> None:
    """Run one document through the whole pipeline."""
    settings = settings or get_settings()
    stats.documents_seen += 1

    source, created = get_or_create_source(session, document)
    if not created:
        stats.duplicates_skipped += 1
        return
    stats.sources_created += 1

    extraction = provider.extract(
        ExtractionRequest(
            url=document.url,
            title=document.title,
            publisher=document.publisher,
            published_at=document.published_at,
            source_type=document.source_type,
            content=document.content,
            company_hint=document.company_hint,
        )
    )
    if extraction is None:
        # The source row stays: it is a real document we retrieved, and keeping it
        # stops us re-extracting the same failure on every run.
        stats.extractions_failed += 1
        return

    company = _resolve_company(session, extraction, document)
    if company is None:
        stats.companies_unresolved += 1
        logger.info("no company resolved; source kept, no signal", extra={"url": document.url})
        return

    signal, signal_created = get_or_create_signal(
        session, company=company, source=source, extraction=extraction
    )
    if signal is None:
        return
    if signal_created:
        stats.signals_created += 1

    opportunity, opportunity_created = create_or_update_opportunity(
        session,
        company=company,
        signal=signal,
        source=source,
        extraction=extraction,
        as_of=as_of,
        settings=settings,
    )
    if opportunity is None:
        stats.no_event_implication += 1
    elif opportunity_created:
        stats.opportunities_created += 1
    else:
        stats.opportunities_updated += 1


def ingest_documents(
    documents: list[RawDocument],
    provider: AIProvider | None = None,
    *,
    as_of: date | None = None,
    settings: Settings | None = None,
) -> IngestionStats:
    """Process a list of documents, one transaction each."""
    from app.ai import get_provider

    settings = settings or get_settings()
    owns_provider = provider is None
    provider = provider or get_provider(settings)
    stats = IngestionStats()

    try:
        for document in documents:
            try:
                with session_scope() as session:
                    process_document(
                        session, document, provider, stats, as_of=as_of, settings=settings
                    )
            except SQLAlchemyError as exc:
                # A per-document transaction means a constraint violation costs
                # one document, not the run.
                message = f"{document.url}: {type(exc).__name__}"
                stats.errors.append(message)
                logger.exception("database error processing document", extra={"url": document.url})
            except Exception as exc:  # noqa: BLE001 - one document must not kill a run
                stats.errors.append(f"{document.url}: {exc}")
                logger.exception("failed processing document", extra={"url": document.url})
    finally:
        if owns_provider:
            provider.close()

    logger.info("ingestion finished", extra=stats.as_dict())
    return stats


def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    *,
    only: list[str] | None = None,
    since: datetime | None = None,
    settings: Settings | None = None,
) -> IngestionStats:
    """Fetch from configured adapters and ingest everything they yield."""
    from app.sources import load_sources

    settings = settings or get_settings()
    adapters = adapters if adapters is not None else load_sources(only=only)
    if not adapters:
        logger.warning("no sources configured or enabled; nothing to ingest")
        return IngestionStats()

    if since is None:
        since = datetime.now(UTC) - timedelta(days=settings.ingest_lookback_days)

    documents: list[RawDocument] = []
    for adapter in adapters:
        try:
            fetched = list(adapter.fetch(since))
        except Exception:  # noqa: BLE001 - one broken feed must not kill the run
            logger.exception("source fetch failed", extra={"source": adapter.key})
            continue
        logger.info("source fetched", extra={"source": adapter.key, "documents": len(fetched)})
        documents.extend(fetched)

    return ingest_documents(documents, settings=settings)
