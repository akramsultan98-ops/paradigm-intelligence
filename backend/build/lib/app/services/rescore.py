"""Re-scoring: re-apply decay so the Top 50 stays current.

Run this once a day, after ingestion. Without it, decay would only ever be
applied when a signal happened to be re-ingested, and a stale opportunity would
sit in the Top 50 indefinitely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.domain.enums import CLOSED_STATUSES, Classification
from app.models import Opportunity
from app.scoring.classification import classify
from app.scoring.decay import DecayInputs, compute_decay

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RescoreStats:
    examined: int = 0
    changed: int = 0
    dropped_below_threshold: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "examined": self.examined,
            "changed": self.changed,
            "dropped_below_threshold": self.dropped_below_threshold,
        }


def rescore_all(
    session: Session, *, as_of: date | None = None, settings: Settings | None = None
) -> RescoreStats:
    """Re-apply decay to every open opportunity.

    Only decay is recalculated, not the component scores: those depend on the
    source document, which has not changed. Re-running extraction here would cost
    an API call per opportunity per day and change nothing.
    """
    settings = settings or get_settings()
    as_of = as_of or datetime.now(UTC).date()
    stats = RescoreStats()

    opportunities = session.scalars(
        select(Opportunity)
        .options(joinedload(Opportunity.signal))
        .where(Opportunity.status.notin_([status.value for status in CLOSED_STATUSES]))
    ).unique().all()

    for opportunity in opportunities:
        stats.examined += 1
        decay = compute_decay(
            DecayInputs(
                signal_date=opportunity.signal.effective_date,
                window_ends_on=opportunity.window_ends_on,
                evidence_score=opportunity.evidence_score,
                as_of=as_of,
            ),
            settings,
        )
        new_score = round(max(0.0, min(100.0, opportunity.base_score * decay.factor)))
        unchanged = (
            new_score == opportunity.score
            and Decimal(str(decay.factor)) == opportunity.decay_factor
        )
        if unchanged:
            continue

        was_qualified = opportunity.score >= settings.min_qualifying_score
        opportunity.previous_score = opportunity.score
        opportunity.previous_classification = opportunity.classification
        opportunity.score_changed_at = datetime.now(UTC)
        opportunity.decay_factor = Decimal(str(decay.factor))
        opportunity.score = new_score
        opportunity.classification = classify(new_score, settings)
        opportunity.scored_at = datetime.now(UTC)
        stats.changed += 1

        if was_qualified and new_score < settings.min_qualifying_score:
            stats.dropped_below_threshold += 1
            logger.info(
                "opportunity decayed out of the Top 50",
                extra={
                    "opportunity_id": str(opportunity.id),
                    "score": new_score,
                    "reasons": decay.reasons,
                },
            )

    session.commit()
    logger.info("rescore finished", extra=stats.as_dict())
    return stats


def refresh_contact_quality(
    session: Session, company_id: object, settings: Settings | None = None
) -> int:
    """Re-score a company's open opportunities after its contacts changed.

    Only the contact-quality component is recomputed; the others depend on the
    source document, which has not changed. Re-running extraction here would cost
    an API call per opportunity and produce the same answer.

    Returns the number of opportunities whose score moved.
    """
    settings = settings or get_settings()
    from app.models import Contact
    from app.scoring.contact_quality import score_opportunity_contacts

    contacts = list(
        session.scalars(
            select(Contact)
            .where(Contact.company_id == company_id)
            .order_by(Contact.contact_score.desc())
        ).all()
    )
    contact_quality = score_opportunity_contacts(
        tuple(contact.contact_score for contact in contacts), settings
    )
    best = contacts[0] if contacts else None

    opportunities = session.scalars(
        select(Opportunity).where(
            Opportunity.company_id == company_id,
            Opportunity.status.notin_([status.value for status in CLOSED_STATUSES]),
        )
    ).all()

    changed = 0
    for opportunity in opportunities:
        base = round(
            max(0.0, min(100.0,
                settings.weight_event_probability * opportunity.event_probability
                + settings.weight_commercial_value * opportunity.commercial_value
                + settings.weight_contact_quality * contact_quality
                + settings.weight_timing * opportunity.timing_score
                + settings.weight_evidence * opportunity.evidence_score))
        )
        new_score = round(max(0.0, min(100.0, base * float(opportunity.decay_factor))))
        opportunity.primary_contact_id = best.id if best else None

        if (
            opportunity.contact_quality == contact_quality
            and opportunity.base_score == base
            and opportunity.score == new_score
        ):
            continue

        if opportunity.score != new_score:
            opportunity.previous_score = opportunity.score
            opportunity.previous_classification = opportunity.classification
            opportunity.score_changed_at = datetime.now(UTC)
        opportunity.contact_quality = contact_quality
        opportunity.base_score = base
        opportunity.score = new_score
        opportunity.classification = classify(new_score, settings)
        opportunity.scored_at = datetime.now(UTC)
        changed += 1

    if changed:
        session.flush()
        logger.info(
            "opportunities re-scored after contact change",
            extra={"company_id": str(company_id), "changed": changed,
                   "contact_quality": contact_quality},
        )
    return changed


def eligible_count(session: Session, settings: Settings | None = None) -> int:
    """How many opportunities currently qualify.

    Reported by the brief, because "23 of a possible 50" is the honest headline
    when only 23 opportunities clear the bar.
    """
    settings = settings or get_settings()
    from sqlalchemy import func

    return int(
        session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.score >= settings.min_qualifying_score,
                Opportunity.status.notin_([status.value for status in CLOSED_STATUSES]),
            )
        )
        or 0
    )


def classification_counts(session: Session) -> dict[str, int]:
    """Opportunity counts per classification band."""
    from sqlalchemy import func

    rows = session.execute(
        select(Opportunity.classification, func.count(Opportunity.id)).group_by(
            Opportunity.classification
        )
    ).all()
    counts = {band.value: 0 for band in Classification}
    for classification, count in rows:
        counts[classification.value] = int(count)
    return counts
