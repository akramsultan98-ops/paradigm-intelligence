"""Persisting sources, with deduplication."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Source
from app.services.normalize import content_hash, normalize_url
from app.sources.base import RawDocument

logger = logging.getLogger(__name__)


def compute_document_hash(document: RawDocument) -> str:
    """Content identity for a document.

    Title and body are hashed, not the URL: the point is to catch the same story
    republished at a different address, which a URL hash would miss.
    """
    return content_hash(document.title, document.content)


def get_or_create_source(session: Session, document: RawDocument) -> tuple[Source, bool]:
    """Return ``(source, created)`` for a document.

    Two dedupe keys are checked together in one query, because either is enough
    to mean "we already have this": the same URL fetched twice, or the same text
    published at two addresses.
    """
    normalized_url = normalize_url(document.url)
    hash_value = compute_document_hash(document)

    existing = session.scalars(
        select(Source).where(
            or_(Source.normalized_url == normalized_url, Source.content_hash == hash_value)
        )
    ).first()
    if existing is not None:
        return existing, False

    source = Source(
        url=document.url,
        normalized_url=normalized_url,
        title=document.title,
        source_type=document.source_type,
        publisher=document.publisher,
        publication_date=document.published_at,
        confidence=Decimal(str(round(document.confidence, 2))),
        content_hash=hash_value,
        adapter_key=document.adapter_key,
    )
    session.add(source)
    session.flush()
    logger.info(
        "source recorded",
        extra={"source_id": str(source.id), "url": document.url, "adapter": document.adapter_key},
    )
    return source, True
