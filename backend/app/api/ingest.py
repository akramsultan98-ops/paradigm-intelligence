"""Ingestion and maintenance endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep, SettingsDep
from app.domain.enums import SourceType
from app.schemas.ingest import (
    ContactIngestResult,
    IngestContactsRequest,
    IngestDocumentsRequest,
    IngestionStatsOut,
    IngestRunRequest,
    RescoreStatsOut,
)
from app.services.companies import find_by_name
from app.services.contacts import ContactInput, upsert_contact
from app.services.pipeline import ingest_documents, run_ingestion
from app.services.rescore import rescore_all
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
        elif was_created:
            created += 1
        else:
            updated += 1

    session.commit()
    return ContactIngestResult(
        created=created,
        updated=updated,
        skipped=skipped,
        unresolved_companies=sorted(set(unresolved)),
    )


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
