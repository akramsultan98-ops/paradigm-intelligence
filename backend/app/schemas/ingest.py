"""Ingestion request bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.ai.base import Extraction
from app.domain.enums import ContactKind, Department, EmailStatus, SourceType


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
    phone: str | None = Field(
        default=None,
        description="Published business number only. Never a derived or personal one.",
    )
    email_status: EmailStatus = EmailStatus.UNKNOWN
    contact_kind: ContactKind = Field(
        default=ContactKind.UNKNOWN,
        description=(
            "NAMED_INDIVIDUAL for a person, DEPARTMENT_ROUTE for an official "
            "department address or line. The two must never be conflated."
        ),
    )
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


class AnalystSignalRequest(BaseModel):
    """An analyst-verified signal, with its evidence.

    ``source_url`` is mandatory: an analyst assertion without a public source is
    exactly the unverifiable input this system must not hold. The ``extraction``
    body is validated by the same schema an AI extraction is.
    """

    source_url: HttpUrl
    source_title: str | None = None
    source_type: SourceType = SourceType.OTHER
    publisher: str | None = None
    published_at: datetime | None = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    content: str = Field(
        min_length=1,
        description="The source text the extraction was made from, for the audit trail.",
    )
    extraction: Extraction


class ContactDiscoveryRequest(BaseModel):
    """Run configured contact sources."""

    sources: list[str] | None = Field(
        default=None, description="Contact source keys. Omit to run every enabled one."
    )


class ContactDiscoveryStatsOut(BaseModel):
    contacts_found: int
    contacts_created: int
    contacts_updated: int
    contacts_skipped: int
    companies_unresolved: list[str] = Field(default_factory=list)
    opportunities_rescored: int
    errors: list[str] = Field(default_factory=list)


class IngestionStatsOut(BaseModel):
    documents_seen: int
    sources_created: int
    duplicates_skipped: int
    filtered_irrelevant: int
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
    opportunities_rescored: int = Field(
        default=0,
        description="Opportunities whose score moved because contact quality changed.",
    )


class RescoreStatsOut(BaseModel):
    examined: int
    changed: int
    dropped_below_threshold: int
