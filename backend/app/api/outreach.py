"""Outreach endpoints that are not scoped to one company.

Logging an interaction lives under ``/companies/{id}/outreach``, where it belongs.
What remains here is the cross-account working list: who is owed a call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.schemas.opportunity import ContactRef
from app.schemas.outreach import FollowUpDue
from app.services.outreach import due_follow_ups

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get(
    "/follow-ups", response_model=list[FollowUpDue], summary="Contacts due a follow-up"
)
def follow_ups(
    session: SessionDep,
    as_of: Annotated[
        date | None,
        Query(
            description=(
                "Treat this date as today. Lets an Account Manager look ahead — "
                "\"what is owed by Friday\" — without changing anything."
            )
        ),
    ] = None,
) -> list[FollowUpDue]:
    """Follow-ups whose date has arrived or passed, oldest first.

    The Account Manager's day: relationships that were promised a next step and
    have not had one. Nothing here is a prediction — every date was typed by
    whoever logged the last interaction. Accounts being worked without a named
    contact appear too, because that is most of them at the start.
    """
    today = as_of or datetime.now(UTC).date()
    return [
        FollowUpDue(
            company_id=item.company.id,
            company_name=item.company.name,
            next_follow_up_on=item.due_on,
            days_overdue=max(0, (today - item.due_on).days),
            contact=(
                ContactRef.model_validate(item.contact) if item.contact is not None else None
            ),
        )
        for item in due_follow_ups(session, on=today)
    ]
