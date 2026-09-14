"""Ingestion request bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.domain.enums import Department, EmailStatus, SourceType


class DocumentIn(BaseModel):
    """A source document submitted directly, bypassing the adapters."""

    url: HttpUrl
    title: str | None = None
    content: str = Field(min_length=1)
    source_type: SourceType = SourceType.OTHER
    publisher: str | None = None
    published_at: datetime | None = None
    company_hint: str | None = Field(
        default=None,
        description="The company this document is about, if already known.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class IngestDocumentsRequest(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1, max_length=200)


class IngestRunRequest(BaseModel):
    """Run configured source adapters."""

    sources: list[str] | None = Field(
        default=None, description="Source keys to run. Omit to run every enabled source."
    )
    since: datetime | None = Field(
        default=None, description="Only documents published at or after this time."
    )


class ContactIn(BaseModel):
    """A publicly-sourced professional contact.

    ``source_url`` is required. A contact without provenance is exactly the kind
    of record this system must not hold.
    """

    company_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    job_title: str | None = None
    department: Department = Department.UNKNOWN
    email: str | None = None
    linkedin_url: str | None = None
    email_status: EmailStatus = EmailStatus.UNKNOWN
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_url: HttpUrl = Field(description="Public page this contact was found on.")
    source_title: str | None = None
    source_type: SourceType = SourceType.PUBLIC_PROFILE
    source_published_at: datetime | None = None

    @field_validator("email_status")
    @classmethod
    def _reject_verified(cls, value: EmailStatus) -> EmailStatus:
        """``VERIFIED`` cannot be asserted through the API.

        V1 has no verification step, so accepting the claim would let an inferred
        address be stored as verified — which the spec forbids outright. Submit
        ``PUBLIC`` for an address published on a real page.
        """
        if value is EmailStatus.VERIFIED:
            raise ValueError(
                "email_status VERIFIED cannot be set through the API: no verification "
                "step exists in V1. Use PUBLIC for a publicly published address, or "
                "INFERRED for a derived one."
            )
        return value


class IngestContactsRequest(BaseModel):
    contacts: list[ContactIn] = Field(min_length=1, max_length=200)


class IngestionStatsOut(BaseModel):
    documents_seen: int
    sources_created: int
    duplicates_skipped: int
    extractions_failed: int
    companies_unresolved: int
    signals_created: int
    opportunities_created: int
    opportunities_updated: int
    no_event_implication: int
    errors: list[str] = Field(default_factory=list)


class ContactIngestResult(BaseModel):
    created: int
    updated: int
    skipped: int
    unresolved_companies: list[str] = Field(default_factory=list)


class RescoreStatsOut(BaseModel):
    examined: int
    changed: int
    dropped_below_threshold: int
