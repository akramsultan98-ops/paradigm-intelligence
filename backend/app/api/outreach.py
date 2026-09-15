"""Outreach endpoints that are not scoped to one company.

Logging an interaction lives under ``/companies/{id}/outreach``, where it belongs.
What remains here is the cross-account working list: who is owed a call.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.opportunity import ContactRef
from app.schemas.outreach import FollowUpDue
from app.services.outreach import due_follow_ups

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get(
    "/follow-ups", response_model=list[FollowUpDue], summary="Contacts due a follow-up"
)
def follow_ups(session: SessionDep) -> list[FollowUpDue]:
    """Contacts whose follow-up date has arrived or passed, oldest first.

    The Account Manager's day: relationships that were promised a next step and
    have not had one. Nothing here is a prediction — every date was typed by
    whoever logged the last interaction.
    """
    today = datetime.now(UTC).date()
    return [
        FollowUpDue(
            contact=ContactRef.model_validate(contact),
            company_id=contact.company_id,
            company_name=contact.company.name,
            next_follow_up_on=contact.next_follow_up_on,
            days_overdue=max(0, (today - contact.next_follow_up_on).days),
        )
        for contact in due_follow_ups(session, on=today)
    ]
