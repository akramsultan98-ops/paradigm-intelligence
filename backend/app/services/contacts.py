"""Contact ingestion and scoring.

Two rules govern this module, both from the spec:

- Only publicly available professional information is stored, always with a
  source.
- An address we worked out is never recorded as verified. V1 has no verification
  step, so an incoming ``VERIFIED`` is downgraded to ``PUBLIC`` rather than
  trusted (see ``docs/ROADMAP.md``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import ContactKind, Department, EmailStatus
from app.models import Company, Contact, Source
from app.scoring.contact_quality import ContactFactors, score_contact
from app.services.normalize import (
    normalize_email,
    normalize_linkedin_url,
    normalize_person_name,
    normalize_phone,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ContactInput:
    """A contact as supplied by an operator or a contact source."""

    name: str
    job_title: str | None = None
    department: Department = Department.UNKNOWN
    email: str | None = None
    linkedin_url: str | None = None
    #: Public business number only, and only if a source publishes one.
    phone: str | None = None
    email_status: EmailStatus = EmailStatus.UNKNOWN
    #: A person, an official department route, or neither.
    contact_kind: ContactKind = ContactKind.UNKNOWN
    confidence: float = 0.5


def _safe_email_status(requested: EmailStatus, email: str | None) -> EmailStatus:
    """Apply the verification rule.

    ``VERIFIED`` is a claim this system cannot currently substantiate, so it is
    stored as ``PUBLIC``. No email at all means ``UNKNOWN``, which the database
    also enforces with a check constraint.
    """
    if email is None:
        return EmailStatus.UNKNOWN
    if requested is EmailStatus.VERIFIED:
        logger.warning(
            "downgrading VERIFIED email status to PUBLIC: no verification step exists in V1"
        )
        return EmailStatus.PUBLIC
    return requested


def compute_contact_score(
    *,
    job_title: str | None,
    department: Department,
    email_status: EmailStatus,
    has_linkedin: bool,
    source_confidence: float,
) -> int:
    return score_contact(
        ContactFactors(
            job_title=job_title,
            department=department,
            email_status=email_status,
            has_linkedin=has_linkedin,
            source_confidence=source_confidence,
        )
    )


def upsert_contact(
    session: Session,
    *,
    company: Company,
    payload: ContactInput,
    source: Source | None = None,
) -> tuple[Contact | None, bool]:
    """Create or update one contact. Returns ``(contact, created)``.

    Matching is attempted on email, then LinkedIn, then normalized name within the
    company and department — in that order, strongest identity first.
    """
    try:
        normalized_name = normalize_person_name(payload.name)
    except ValueError:
        logger.warning(
            "contact name normalized to empty; skipping",
            extra={"contact_name": payload.name},
        )
        return None, False

    email = normalize_email(payload.email)
    linkedin = normalize_linkedin_url(payload.linkedin_url)
    phone = normalize_phone(payload.phone)
    email_status = _safe_email_status(payload.email_status, email)
    source_confidence = float(source.confidence) if source is not None else payload.confidence

    existing: Contact | None = None
    if email:
        existing = session.scalars(
            select(Contact).where(Contact.normalized_email == email)
        ).first()
    if existing is None and linkedin:
        existing = session.scalars(
            select(Contact).where(Contact.normalized_linkedin_url == linkedin)
        ).first()
    if existing is None:
        existing = session.scalars(
            select(Contact).where(
                Contact.company_id == company.id,
                Contact.normalized_name == normalized_name,
                Contact.department == payload.department,
            )
        ).first()

    score = compute_contact_score(
        job_title=payload.job_title,
        department=payload.department,
        email_status=email_status,
        has_linkedin=linkedin is not None,
        source_confidence=source_confidence,
    )

    if existing is not None:
        # Gaps get filled; known values are left alone.
        if existing.job_title is None and payload.job_title:
            existing.job_title = payload.job_title
        if (
            existing.department is Department.UNKNOWN
            and payload.department is not Department.UNKNOWN
        ):
            existing.department = payload.department
        if existing.normalized_email is None and email:
            existing.email = payload.email
            existing.normalized_email = email
            existing.email_status = email_status
        if existing.normalized_linkedin_url is None and linkedin:
            existing.linkedin_url = payload.linkedin_url
            existing.normalized_linkedin_url = linkedin
        if existing.normalized_phone is None and phone:
            existing.phone = payload.phone
            existing.normalized_phone = phone
        if existing.contact_kind is ContactKind.UNKNOWN and (
            payload.contact_kind is not ContactKind.UNKNOWN
        ):
            existing.contact_kind = payload.contact_kind
        if source is not None and existing.source_id is None:
            existing.source_id = source.id
        # Seen again in its source, so the freshness clock resets.
        existing.last_verified_at = datetime.now(UTC)
        existing.contact_score = compute_contact_score(
            job_title=existing.job_title,
            department=existing.department,
            email_status=existing.email_status,
            has_linkedin=existing.normalized_linkedin_url is not None,
            source_confidence=source_confidence,
        )
        session.flush()
        return existing, False

    contact = Contact(
        company_id=company.id,
        source_id=source.id if source is not None else None,
        name=payload.name.strip(),
        normalized_name=normalized_name,
        job_title=payload.job_title,
        department=payload.department,
        email=payload.email.strip() if (payload.email and email) else None,
        normalized_email=email,
        linkedin_url=payload.linkedin_url.strip() if (payload.linkedin_url and linkedin) else None,
        normalized_linkedin_url=linkedin,
        phone=payload.phone.strip() if (payload.phone and phone) else None,
        normalized_phone=phone,
        email_status=email_status,
        contact_kind=payload.contact_kind,
        last_verified_at=datetime.now(UTC),
        contact_score=score,
        confidence=Decimal(str(round(max(0.0, min(1.0, payload.confidence)), 2))),
    )
    session.add(contact)
    session.flush()
    logger.info(
        "contact recorded",
        extra={"contact_id": str(contact.id), "company": company.name, "score": score},
    )
    return contact, True


def contacts_for_company(session: Session, company_id: object) -> list[Contact]:
    """All contacts for a company, best first.

    The source is eager-loaded: every contact is displayed with the page it was
    read from, so fetching it lazily would be one query per contact.
    """
    return list(
        session.scalars(
            select(Contact)
            .options(joinedload(Contact.source))
            .where(Contact.company_id == company_id)
            .order_by(Contact.contact_score.desc())
        ).unique().all()
    )
