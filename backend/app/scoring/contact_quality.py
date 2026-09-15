"""CONTACT_QUALITY: how well-placed the people we know actually are.

Two levels: a score per contact, and a damped roll-up per opportunity. The
damping is the point — spec §27 requires that poor contacts must not
significantly inflate an opportunity's score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.domain.enums import Department, EmailStatus
from app.scoring.scales import clamp, weighted

WEIGHTS = {
    "seniority": 0.35,
    "department": 0.30,
    "evidence": 0.20,
    "ownership": 0.15,
}

DEPARTMENT_RELEVANCE: dict[Department, float] = {
    Department.EVENTS: 100.0,
    Department.MARKETING: 100.0,
    Department.CORPORATE_COMMUNICATIONS: 95.0,
    Department.COMMUNICATIONS: 90.0,
    Department.PR: 85.0,
    Department.PROCUREMENT: 80.0,
    Department.BUSINESS_DEVELOPMENT: 70.0,
    Department.EXECUTIVE_OFFICE: 65.0,
    Department.HR: 60.0,
    Department.OTHER: 25.0,
    Department.UNKNOWN: 20.0,
}

EMAIL_STATUS_SCORES: dict[EmailStatus, float] = {
    EmailStatus.VERIFIED: 100.0,
    EmailStatus.PUBLIC: 80.0,
    EmailStatus.INFERRED: 35.0,
    EmailStatus.UNKNOWN: 20.0,
}

#: Seniority keywords, most senior first — the first match wins, so ordering
#: matters ("head of marketing" must beat the bare "marketing" in ownership).
_SENIORITY_RULES: tuple[tuple[tuple[str, ...], float], ...] = (
    (("chief", "cmo", "cco", "ceo", "c-level", "vice president", "vp "), 100.0),
    (("director", "head of", "head,"), 90.0),
    (("manager", "general manager"), 78.0),
    (("senior", "lead ", "team lead", "supervisor"), 65.0),
    (("specialist", "consultant", "analyst"), 50.0),
    (("coordinator", "officer", "executive", "assistant", "associate"), 40.0),
)
_SENIORITY_DEFAULT = 20.0

_OWNERSHIP_RULES: tuple[tuple[tuple[str, ...], float], ...] = (
    (("event", "sponsorship", "sponsor", "exhibition", "conference"), 100.0),
    (("procurement", "purchasing", "tender", "sourcing", "supply chain"), 85.0),
    (("marketing", "brand", "communication", "public relations", "pr ", "media"), 70.0),
)
_OWNERSHIP_DEFAULT = 30.0


@dataclass(frozen=True, slots=True)
class ContactFactors:
    """Inputs to a single contact's score."""

    job_title: str | None
    department: Department
    email_status: EmailStatus
    has_linkedin: bool
    source_confidence: float
    breakdown: dict[str, float] = field(default_factory=dict, compare=False)


def _match(title: str, rules: tuple[tuple[tuple[str, ...], float], ...], default: float) -> float:
    for keywords, score in rules:
        if any(keyword in title for keyword in keywords):
            return score
    return default


def seniority_score(job_title: str | None) -> float:
    """Seniority from title keywords. An unreadable title scores low, not average."""
    if not job_title:
        return _SENIORITY_DEFAULT
    return _match(f" {job_title.casefold()} ", _SENIORITY_RULES, _SENIORITY_DEFAULT)


def ownership_score(job_title: str | None) -> float:
    """Whether this person plausibly owns event budget or its procurement."""
    if not job_title:
        return _OWNERSHIP_DEFAULT
    return _match(f" {job_title.casefold()} ", _OWNERSHIP_RULES, _OWNERSHIP_DEFAULT)


def evidence_score(
    email_status: EmailStatus, has_linkedin: bool, source_confidence: float
) -> float:
    """How solid the public evidence for this contact is.

    A LinkedIn profile is independent corroboration of a role, so it lifts a
    weakly-evidenced address; it never makes an inferred address verified.
    """
    score = EMAIL_STATUS_SCORES[email_status]
    if has_linkedin:
        score = min(100.0, max(score, 60.0) + 10.0)
    return clamp(score * (0.6 + 0.4 * clamp(source_confidence, 0.0, 1.0)))


def score_contact(factors: ContactFactors) -> int:
    """A single contact's quality, 0-100."""
    components = {
        "seniority": (seniority_score(factors.job_title), WEIGHTS["seniority"]),
        "department": (DEPARTMENT_RELEVANCE[factors.department], WEIGHTS["department"]),
        "evidence": (
            evidence_score(factors.email_status, factors.has_linkedin, factors.source_confidence),
            WEIGHTS["evidence"],
        ),
        "ownership": (ownership_score(factors.job_title), WEIGHTS["ownership"]),
    }
    factors.breakdown.update({name: round(score, 2) for name, (score, _) in components.items()})
    return round(weighted(components))


def score_opportunity_contacts(
    contact_scores: Sequence[int], settings: Settings | None = None
) -> int:
    """Roll contact scores up to the opportunity, with damping.

    - No contacts at all scores 0. There is nobody to call.
    - The best contact sets the level; a roster of juniors is not additive.
    - If even the best contact is below the floor, the result is **halved**. This
      is the anti-inflation rule: knowing three coordinators is not the same as
      knowing the Marketing Director.
    - Genuine corroboration (more than one contact above the floor) earns a small
      capped bonus.
    """
    settings = settings or get_settings()
    if not contact_scores:
        return 0

    best = max(contact_scores)
    if best < settings.contact_quality_floor:
        return round(best * settings.contact_quality_weak_multiplier)

    others_above_floor = sum(
        1 for score in contact_scores if score >= settings.contact_quality_floor
    ) - 1
    bonus = min(
        settings.contact_corroboration_max_bonus,
        settings.contact_corroboration_bonus * max(others_above_floor, 0),
    )
    return round(clamp(best + bonus))
