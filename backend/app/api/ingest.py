"""Ingestion and maintenance endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep, SettingsDep
from app.domain.enums import IngestMode, SourceType
from app.schemas.ingest import (
    AnalystSignalRequest,
    ContactDiscoveryRequest,
    ContactDiscoveryStatsOut,
    ContactIngestResult,
    IngestContactsRequest,
    IngestDocumentsRequest,
    IngestionStatsOut,
    IngestRunRequest,
    RescoreStatsOut,
)
from app.services.analyst import ingest_analyst_signal
from app.services.companies import find_by_name
from app.services.contact_discovery import run_contact_discovery
from app.services.contacts import ContactInput, upsert_contact
from app.services.pipeline import ingest_documents, run_ingestion
from app.services.rescore import refresh_contact_quality, rescore_all
from app.services.sources import get_or_create_source
from app.sources.base import RawDocument

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])


@router.post(
    "/ingest/run",
    response_model=IngestionStatsOut,
    summary="Run the configured source adapters",
)
def ingest_run(payload: IngestRunRequest, settings: SettingsDep) -> IngestionStatsOut:
    """Fetch from configured sources and run the full pipeline.

    Synchronous on purpose: V1 volumes are small, and a queue would be
    infrastructure without a problem to solve. For a long run, call the CLI from
    cron instead.
    """
    stats = run_ingestion(only=payload.sources, since=payload.since, settings=settings)
    return IngestionStatsOut(**stats.as_dict())


@router.post(
    "/ingest/documents",
    response_model=IngestionStatsOut,
    summary="Submit source documents directly",
)
def ingest_docs(payload: IngestDocumentsRequest, settings: SettingsDep) -> IngestionStatsOut:
    """Ingest documents supplied in the request, bypassing the adapters."""
    documents = [
        RawDocument(
            url=str(document.url),
            title=document.title,
            content=document.content,
            source_type=document.source_type,
            publisher=document.publisher,
            published_at=document.published_at,
            company_hint=document.company_hint,
            confidence=document.confidence,
            adapter_key="api",
        )
        for document in payload.documents
    ]
    stats = ingest_documents(documents, settings=settings)
    return IngestionStatsOut(**stats.as_dict())


@router.post(
    "/ingest/signals",
    response_model=IngestionStatsOut,
    summary="Submit an analyst-verified signal",
)
def ingest_signal(payload: AnalystSignalRequest, settings: SettingsDep) -> IngestionStatsOut:
    """Record a signal a person verified, with its source.

    Runs the ordinary pipeline — relevance gate, deduplication, company
    resolution, deterministic scoring — so an analyst-entered signal is scored by
    exactly the same rules as an automated one. It is marked ANALYST provenance
    and is never presented as automated extraction.
    """
    stats = ingest_analyst_signal(
        url=str(payload.source_url),
        title=payload.source_title,
        content=payload.content,
        extraction=payload.extraction,
        source_type=payload.source_type,
        publisher=payload.publisher,
        published_at=payload.published_at,
        confidence=payload.confidence,
        settings=settings,
    )
    return IngestionStatsOut(**stats.as_dict())


@router.post(
    "/ingest/contacts/discover",
    response_model=ContactDiscoveryStatsOut,
    summary="Run configured contact sources",
)
def discover_contacts(
    payload: ContactDiscoveryRequest, settings: SettingsDep
) -> ContactDiscoveryStatsOut:
    """Read contacts from configured public company pages.

    Attaches them to companies we already know and re-scores those companies'
    opportunities, because contact quality is 20% of the score.
    """
    stats = run_contact_discovery(only=payload.sources, settings=settings)
    return ContactDiscoveryStatsOut(**stats.as_dict())


@router.post(
    "/ingest/contacts",
    response_model=ContactIngestResult,
    summary="Submit publicly-sourced contacts",
)
def ingest_contacts(payload: IngestContactsRequest, session: SessionDep) -> ContactIngestResult:
    """Attach contacts to companies we already know.

    Two deliberate constraints:

    - ``source_url`` is required, so every contact carries provenance.
    - The company must already exist. A contact does not justify creating an
      account, and creating one from a contact payload would put unverified
      company records into the system.

    Contacts for an unknown company are reported back in
    ``unresolved_companies`` rather than silently dropped.
    """
    created = updated = skipped = 0
    unresolved: list[str] = []
    # Companies whose contacts changed. Re-scored once each after every contact is
    # attached, so contact quality actually reaches the opportunity score and the
    # brief reports one real movement rather than several intermediate ones.
    affected: set[object] = set()

    for entry in payload.contacts:
        company = find_by_name(session, entry.company_name)
        if company is None:
            unresolved.append(entry.company_name)
            skipped += 1
            continue

        source, _ = get_or_create_source(
            session,
            RawDocument(
                url=str(entry.source_url),
                title=entry.source_title or f"Contact page: {entry.company_name}",
                # The page's identity is its URL and title; contact pages have no
                # body we retrieved, and hashing the contact itself would make the
                # same page a new source for every person on it.
                content=entry.source_title or str(entry.source_url),
                source_type=entry.source_type or SourceType.PUBLIC_PROFILE,
                published_at=entry.source_published_at,
                confidence=entry.confidence,
                adapter_key="api:contacts",
                # A person submitted this, so it is ANALYST provenance. Only a
                # source an adapter actually fetched is AUTOMATED, and mislabelling
                # hand-entered data as automated is exactly what provenance exists
                # to prevent.
                ingest_mode=IngestMode.ANALYST,
            ),
        )

        contact, was_created = upsert_contact(
            session,
            company=company,
            payload=ContactInput(
                name=entry.name,
                job_title=entry.job_title,
                department=entry.department,
                email=entry.email,
                linkedin_url=entry.linkedin_url,
                email_status=entry.email_status,
                confidence=entry.confidence,
            ),
            source=source,
        )
        if contact is None:
            skipped += 1
        else:
            affected.add(company.id)
            if was_created:
                created += 1
            else:
                updated += 1

    rescored = 0
    for company_id in affected:
        rescored += refresh_contact_quality(session, company_id)

    session.commit()
    logger.info(
        "contacts ingested",
        extra={
            # Not "created"/"updated": both collide with built-in LogRecord
            # attributes and logging raises KeyError at the call site.
            "contacts_created": created,
            "contacts_updated": updated,
            "opportunities_rescored": rescored,
        },
    )
    return ContactIngestResult(
        created=created,
        updated=updated,
        skipped=skipped,
        unresolved_companies=sorted(set(unresolved)),
        opportunities_rescored=rescored,
    )


@router.get(
    "/sources/health",
    summary="Probe configured sources",
)
def sources_health(settings: SettingsDep) -> dict:
    """Which configured sources are reachable and usable from this host.

    Distinguishes an egress-policy block from a source that is genuinely down —
    the two need completely different fixes.
    """
    from app.services.source_health import check_all, summarize

    results = check_all(settings=settings)
    return {**summarize(results), "sources": [health.as_dict() for health in results]}


@router.get(
    "/maintenance/scheduler",
    summary="Background scheduler status",
)
def scheduler_status() -> dict:
    """Whether recurring ingestion is on, and what the last cycle did."""
    from app.services.scheduler import scheduler

    return scheduler.status()


@router.post(
    "/maintenance/cycle",
    summary="Run one full refresh cycle now",
)
def run_refresh_cycle(settings: SettingsDep) -> dict:
    """Ingest, discover contacts, then apply decay — the scheduled cycle, on demand."""
    from app.services.scheduler import run_cycle

    return run_cycle(settings).as_dict()


@router.post(
    "/maintenance/rescore",
    response_model=RescoreStatsOut,
    summary="Re-apply score decay",
)
def rescore(session: SessionDep, settings: SettingsDep) -> RescoreStatsOut:
    """Re-apply decay to every open opportunity.

    Intended to run daily after ingestion. Without it, a stale opportunity would
    keep its original score and never leave the Top 50.
    """
    try:
        stats = rescore_all(session, settings=settings)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a 500
        logger.exception("rescore failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"rescore failed: {exc}"
        ) from exc
    return RescoreStatsOut(**stats.as_dict())
