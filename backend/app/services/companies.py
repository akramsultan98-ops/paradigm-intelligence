"""Company resolution.

Resolution, not creation-by-default: the same company arrives spelled a dozen
ways, and every duplicate row splits its signals and weakens its score.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import Extraction
from app.config import get_settings
from app.domain.enums import SizeBand
from app.models import Company
from app.services.normalize import (
    normalize_company_name,
    normalize_domain,
    normalize_text,
)

logger = logging.getLogger(__name__)

#: Below this length a normalized name is too generic to match on safely
#: ("nbe" would match inside far too much text).
MIN_MENTION_LENGTH = 6


def find_by_name(session: Session, name: str) -> Company | None:
    try:
        normalized = normalize_company_name(name)
    except ValueError:
        return None
    return session.scalars(
        select(Company).where(Company.normalized_name == normalized)
    ).first()


def find_by_domain(session: Session, domain: str | None) -> Company | None:
    normalized = normalize_domain(domain)
    if not normalized:
        return None
    return session.scalars(select(Company).where(Company.domain == normalized)).first()


def find_company_mentioned(session: Session, *parts: str | None) -> Company | None:
    """Match text against companies we already know.

    This is *recognition*, not inference: it only ever returns a company that is
    already in the database and whose normalized name appears verbatim in the
    text. It exists so that a news article that the extractor could not attribute
    can still be attached to a known account, without anything being invented.

    The longest match wins, so "Banque Misr Leasing" is preferred over
    "Banque Misr" when both are known.
    """
    haystack = normalize_text(" ".join(part for part in parts if part))
    if not haystack:
        return None

    candidates = session.scalars(select(Company)).all()
    best: Company | None = None
    for company in candidates:
        name = company.normalized_name
        if len(name) < MIN_MENTION_LENGTH:
            continue
        if name in haystack and (best is None or len(name) > len(best.normalized_name)):
            best = company
    return best


def resolve_or_create(session: Session, extraction: Extraction) -> Company | None:
    """Find or create the company an extraction refers to.

    Returns ``None`` when the extraction names no usable company. The caller then
    keeps the source but creates no signal — an unattributable document is not a
    reason to invent an account.

    Domain is checked before name because it is the stronger identity, and a
    rename is more common than a domain change.
    """
    if not extraction.company_name:
        return None

    company = find_by_domain(session, extraction.company_domain)
    if company is None:
        company = find_by_name(session, extraction.company_name)

    if company is not None:
        _enrich(session, company, extraction)
        return company

    try:
        normalized = normalize_company_name(extraction.company_name)
    except ValueError:
        logger.warning(
            "company name normalized to empty; skipping",
            extra={"company_name": extraction.company_name},
        )
        return None

    settings = get_settings()
    company = Company(
        name=extraction.company_name.strip(),
        normalized_name=normalized,
        domain=normalize_domain(extraction.company_domain),
        website=extraction.company_domain,
        sector=settings.canonical_sector(extraction.company_sector),
        city=extraction.company_city,
        size_band=extraction.factors.company_size,
    )
    session.add(company)
    session.flush()
    logger.info(
        "company created",
        extra={
            "company_id": str(company.id),
            "company_name": company.name,
            "sector": company.sector,
        },
    )
    return company


def _enrich(session: Session, company: Company, extraction: Extraction) -> None:
    """Fill in blanks on a known company.

    Only ever fills gaps — an existing value is never overwritten from a single
    article. One loose mention should not be able to reclassify an account we
    already know something about.
    """
    settings = get_settings()
    changed = False

    if company.domain is None and (domain := normalize_domain(extraction.company_domain)):
        company.domain = domain
        changed = True
    if company.sector is None and (
        sector := settings.canonical_sector(extraction.company_sector)
    ):
        company.sector = sector
        changed = True
    if company.city is None and extraction.company_city:
        company.city = extraction.company_city
        changed = True
    if (
        company.size_band is SizeBand.UNKNOWN
        and extraction.factors.company_size is not SizeBand.UNKNOWN
    ):
        company.size_band = extraction.factors.company_size
        changed = True

    if changed:
        session.flush()


def note_event_potential(session: Session, company: Company, event_probability: int) -> None:
    """Track the best event probability ever seen for a company.

    A standing company-level indicator, useful for account planning and for
    scoring a future signal from the same company.
    """
    if company.event_potential_score is None or event_probability > company.event_potential_score:
        company.event_potential_score = event_probability
        session.flush()
