"""Running contact sources and attaching what they find.

Contacts exist to serve an opportunity, so discovering one is only half the job:
the opportunities at that company have to be re-scored, because contact quality is
20% of the opportunity score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import session_scope
from app.services.companies import find_by_name
from app.services.contacts import ContactInput, upsert_contact
from app.services.rescore import refresh_contact_quality
from app.services.sources import get_or_create_source
from app.sources.base import RawDocument
from app.sources.contacts import ContactSourceAdapter, DiscoveredContact

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ContactDiscoveryStats:
    contacts_found: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    contacts_skipped: int = 0
    companies_unresolved: list[str] = field(default_factory=list)
    opportunities_rescored: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "contacts_found": self.contacts_found,
            "contacts_created": self.contacts_created,
            "contacts_updated": self.contacts_updated,
            "contacts_skipped": self.contacts_skipped,
            "companies_unresolved": sorted(set(self.companies_unresolved)),
            "opportunities_rescored": self.opportunities_rescored,
            "errors": self.errors,
        }


def attach_contact(
    session: Session, discovered: DiscoveredContact, stats: ContactDiscoveryStats
) -> object | None:
    """Persist one discovered contact. Returns the company id when one changed.

    The company must already exist. A contact page is not evidence that a company
    belongs in our pipeline — signals are — so discovering a contact never creates
    an account.

    Deliberately does *not* re-score. Re-scoring once per contact would run N
    passes for one page and leave ``previous_score`` holding an intermediate value,
    so the daily brief would report several meaningless movements instead of one
    real one. The caller re-scores each affected company once, after attaching.
    """
    company = find_by_name(session, discovered.company_name)
    if company is None:
        if discovered.company_name not in stats.companies_unresolved:
            stats.companies_unresolved.append(discovered.company_name)
        stats.contacts_skipped += 1
        return None

    source, _ = get_or_create_source(
        session,
        RawDocument(
            url=discovered.source_url,
            title=discovered.source_title or f"Contact page: {discovered.company_name}",
            # The page's identity is its URL and title. Hashing the contact itself
            # would make one page a new source for every person listed on it.
            content=discovered.source_title or discovered.source_url,
            source_type=discovered.source_type,
            confidence=discovered.confidence,
            adapter_key=discovered.adapter_key,
            ingest_mode=discovered.ingest_mode,
        ),
    )

    contact, created = upsert_contact(
        session,
        company=company,
        payload=ContactInput(
            name=discovered.name,
            job_title=discovered.job_title,
            department=discovered.department,
            email=discovered.email,
            linkedin_url=discovered.linkedin_url,
            phone=discovered.phone,
            email_status=discovered.email_status,
            contact_kind=discovered.contact_kind,
            confidence=discovered.confidence,
        ),
        source=source,
    )
    if contact is None:
        stats.contacts_skipped += 1
        return None

    if created:
        stats.contacts_created += 1
    else:
        stats.contacts_updated += 1
    return company.id


def run_contact_discovery(
    adapters: list[ContactSourceAdapter] | None = None,
    *,
    only: list[str] | None = None,
    settings: Settings | None = None,
) -> ContactDiscoveryStats:
    """Run configured contact sources and attach what they find."""
    from app.sources import load_contact_sources

    settings = settings or get_settings()
    adapters = adapters if adapters is not None else load_contact_sources(only=only)
    stats = ContactDiscoveryStats()
    #: Companies whose contacts changed, re-scored once each after attaching.
    affected: set[object] = set()

    if not adapters:
        logger.warning("no contact sources configured or enabled")
        return stats

    for adapter in adapters:
        try:
            discovered = list(adapter.discover())
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill the run
            stats.errors.append(f"{adapter.key}: {exc}")
            logger.exception("contact source failed", extra={"source": adapter.key})
            continue
        finally:
            adapter.close()

        stats.contacts_found += len(discovered)
        for contact in discovered:
            try:
                with session_scope() as session:
                    if (company_id := attach_contact(session, contact, stats)) is not None:
                        affected.add(company_id)
            except SQLAlchemyError as exc:
                stats.errors.append(f"{contact.source_url}: {type(exc).__name__}")
                logger.exception(
                    "database error attaching contact", extra={"source": adapter.key}
                )
            except Exception as exc:  # noqa: BLE001 - isolate one bad contact
                stats.errors.append(f"{contact.source_url}: {exc}")
                logger.exception("failed attaching contact", extra={"source": adapter.key})

    # One re-score per affected company, after every contact is in place, so the
    # score moves once and previous_score means "before this run".
    for company_id in affected:
        try:
            with session_scope() as session:
                stats.opportunities_rescored += refresh_contact_quality(
                    session, company_id, settings
                )
        except Exception as exc:  # noqa: BLE001 - isolate one bad company
            stats.errors.append(f"rescore {company_id}: {exc}")
            logger.exception("failed re-scoring after contact discovery")

    logger.info("contact discovery finished", extra=stats.as_dict())
    return stats
