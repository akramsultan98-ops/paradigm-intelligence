"""Deterministic keyword extractor.

**This is not AI and is not a stand-in for it.** It is a dependency-free,
network-free extractor used for tests, local development and CI, so the pipeline
can be exercised end to end without an API key.

It is deliberately limited in one important way: it performs no named-entity
recognition. Without a ``company_hint`` from the adapter it reports no company at
all, rather than guessing one from capitalisation. Guessing here would mean
inventing accounts, which the spec forbids outright.

Its ``confidence`` is capped at ``MAX_CONFIDENCE`` so a rule-based run can never
look as well-evidenced as a real extraction, and ``extractor`` records
``rule_based`` on every row it produces.
"""

from __future__ import annotations

from app.ai.base import AIProvider, Extraction, ExtractionFactors, ExtractionRequest
from app.domain.enums import (
    Department,
    Level,
    OpportunityType,
    OpportunityWindow,
    RecommendedAction,
    Scale,
    Service,
    SignalType,
)

#: Rule-based output is never treated as strong evidence.
MAX_CONFIDENCE = 0.45

#: Keyword → signal type, most specific first. The first match wins, so
#: "groundbreaking ceremony" must be tested before the bare "ceremony".
_SIGNAL_RULES: tuple[tuple[SignalType, tuple[str, ...]], ...] = (
    (SignalType.EXHIBITION, ("exhibition", "expo", "trade fair", "trade show")),
    (SignalType.CONFERENCE, ("conference", "summit", "forum", "congress")),
    (SignalType.WORKSHOP, ("workshop", "hackathon")),
    (SignalType.SEMINAR, ("seminar", "webinar", "symposium")),
    (SignalType.TRAINING_PROGRAM, ("training program", "training programme", "academy",
                                   "upskilling", "capacity building")),
    (SignalType.SPONSORSHIP, ("sponsor", "sponsorship", "title partner")),
    (SignalType.PRODUCT_LAUNCH, ("launches new", "launch of", "unveil", "new product",
                                 "product launch", "introduces new", "debuts")),
    (SignalType.NEW_FACILITY, ("new factory", "new plant", "new facility", "new office",
                               "new branch", "opens its", "inaugurat", "groundbreaking",
                               "breaks ground")),
    (SignalType.JOINT_VENTURE, ("joint venture", "jv with")),
    (SignalType.MOU, ("memorandum of understanding", "mou")),
    (SignalType.PARTNERSHIP, ("partnership", "partners with", "strategic alliance",
                              "teams up with", "collaborat")),
    (SignalType.MARKET_ENTRY, ("enters the", "market entry", "expands into",
                               "first in egypt")),
    (SignalType.EXPANSION, ("expansion", "expands", "scaling up")),
    (SignalType.PROJECT_COMPLETION, ("completes", "completion of", "delivered the project",
                                     "handover")),
    (SignalType.PROJECT_LAUNCH, ("project launch", "launches project", "kicks off",
                                 "kick-off", "begins construction")),
    (SignalType.NEW_CONTRACT, ("awarded", "wins contract", "signs contract",
                               "secures contract", "contract worth")),
    (SignalType.TENDER, ("tender", "request for proposal", "rfp", "invitation to bid")),
    (SignalType.PROCUREMENT, ("procurement", "prequalification")),
    (SignalType.INVESTMENT, ("invest", "funding round", "raises", "capital increase")),
    (SignalType.DIGITAL_TRANSFORMATION, ("digital transformation", "digitalization",
                                         "digitisation", "cloud migration")),
    (SignalType.NEW_TECHNOLOGY, ("new technology", "ai-powered", "deploys",
                                 "implements system")),
    (SignalType.CUSTOMER_WIN, ("customer win", "new client", "selected by")),
    (SignalType.DELEGATION, ("delegation", "trade mission")),
    (SignalType.EXECUTIVE_VISIT, ("visit of", "official visit", "ceo visit")),
    (SignalType.ANNIVERSARY, ("anniversary", "years in egypt", "celebrates")),
    (SignalType.MILESTONE, ("milestone", "record", "first time")),
    (SignalType.NEW_PROJECT, ("new project", "develops")),
)

#: Signal type → the corporate activity it most plausibly implies, the department
#: that would own it, and the action to take.
_OPPORTUNITY_MAP: dict[SignalType, tuple[OpportunityType, Department, RecommendedAction]] = {
    SignalType.EXHIBITION: (OpportunityType.EXHIBITION, Department.MARKETING,
                            RecommendedAction.PREPARE_EVENT_CONCEPT),
    SignalType.CONFERENCE: (OpportunityType.CONFERENCE, Department.MARKETING,
                            RecommendedAction.PREPARE_EVENT_CONCEPT),
    SignalType.WORKSHOP: (OpportunityType.WORKSHOP, Department.MARKETING,
                          RecommendedAction.CONTACT_MARKETING),
    SignalType.SEMINAR: (OpportunityType.SEMINAR, Department.MARKETING,
                         RecommendedAction.CONTACT_MARKETING),
    SignalType.TRAINING_PROGRAM: (OpportunityType.TRAINING_EVENT, Department.HR,
                                  RecommendedAction.CONTACT_MARKETING),
    SignalType.SPONSORSHIP: (OpportunityType.PARTNER_EVENT, Department.MARKETING,
                             RecommendedAction.CONTACT_MARKETING),
    SignalType.PRODUCT_LAUNCH: (OpportunityType.PRODUCT_LAUNCH, Department.MARKETING,
                                RecommendedAction.CONTACT_MARKETING),
    SignalType.NEW_FACILITY: (OpportunityType.GROUNDBREAKING, Department.CORPORATE_COMMUNICATIONS,
                              RecommendedAction.CONTACT_COMMUNICATIONS),
    SignalType.JOINT_VENTURE: (OpportunityType.PARTNER_EVENT, Department.CORPORATE_COMMUNICATIONS,
                               RecommendedAction.CONTACT_COMMUNICATIONS),
    SignalType.MOU: (OpportunityType.PRESS_EVENT, Department.CORPORATE_COMMUNICATIONS,
                     RecommendedAction.CONTACT_COMMUNICATIONS),
    SignalType.PARTNERSHIP: (OpportunityType.PARTNER_EVENT, Department.CORPORATE_COMMUNICATIONS,
                             RecommendedAction.CONTACT_COMMUNICATIONS),
    SignalType.MARKET_ENTRY: (OpportunityType.ROADSHOW, Department.MARKETING,
                              RecommendedAction.PREPARE_EVENT_CONCEPT),
    SignalType.EXPANSION: (OpportunityType.CORPORATE_CELEBRATION, Department.MARKETING,
                           RecommendedAction.CONTACT_MARKETING),
    SignalType.PROJECT_COMPLETION: (OpportunityType.PROJECT_COMPLETION_EVENT,
                                    Department.CORPORATE_COMMUNICATIONS,
                                    RecommendedAction.CONTACT_PROJECT_DIRECTOR),
    SignalType.PROJECT_LAUNCH: (OpportunityType.PROJECT_KICKOFF,
                                Department.CORPORATE_COMMUNICATIONS,
                                RecommendedAction.CONTACT_PROJECT_DIRECTOR),
    SignalType.NEW_CONTRACT: (OpportunityType.PROJECT_KICKOFF, Department.BUSINESS_DEVELOPMENT,
                              RecommendedAction.CONTACT_PROJECT_DIRECTOR),
    SignalType.TENDER: (OpportunityType.UNKNOWN, Department.PROCUREMENT,
                        RecommendedAction.MONITOR_FOR_RFP),
    SignalType.PROCUREMENT: (OpportunityType.UNKNOWN, Department.PROCUREMENT,
                             RecommendedAction.MONITOR_FOR_RFP),
    SignalType.INVESTMENT: (OpportunityType.PRESS_EVENT, Department.CORPORATE_COMMUNICATIONS,
                            RecommendedAction.NURTURE_ACCOUNT),
    SignalType.DIGITAL_TRANSFORMATION: (OpportunityType.TECHNICAL_DAY, Department.MARKETING,
                                        RecommendedAction.NURTURE_ACCOUNT),
    SignalType.NEW_TECHNOLOGY: (OpportunityType.TECHNICAL_DAY, Department.MARKETING,
                                RecommendedAction.NURTURE_ACCOUNT),
    SignalType.CUSTOMER_WIN: (OpportunityType.CLIENT_APPRECIATION, Department.MARKETING,
                              RecommendedAction.NURTURE_ACCOUNT),
    SignalType.DELEGATION: (OpportunityType.DELEGATION_EVENT, Department.CORPORATE_COMMUNICATIONS,
                            RecommendedAction.CONTACT_COMMUNICATIONS),
    SignalType.EXECUTIVE_VISIT: (OpportunityType.EXECUTIVE_MEETING,
                                 Department.CORPORATE_COMMUNICATIONS,
                                 RecommendedAction.REQUEST_INTRODUCTION),
    SignalType.ANNIVERSARY: (OpportunityType.ANNIVERSARY, Department.MARKETING,
                             RecommendedAction.PREPARE_EVENT_CONCEPT),
    SignalType.MILESTONE: (OpportunityType.CORPORATE_CELEBRATION, Department.MARKETING,
                           RecommendedAction.NURTURE_ACCOUNT),
    SignalType.NEW_PROJECT: (OpportunityType.PROJECT_KICKOFF, Department.BUSINESS_DEVELOPMENT,
                             RecommendedAction.MONITOR_FOR_RFP),
    SignalType.UNKNOWN: (OpportunityType.UNKNOWN, Department.UNKNOWN,
                         RecommendedAction.NURTURE_ACCOUNT),
}

#: A conservative service shortlist per opportunity type. Only services the
#: activity genuinely implies (spec §14) — no catalogue dumping.
_SERVICE_MAP: dict[OpportunityType, tuple[Service, ...]] = {
    OpportunityType.PRODUCT_LAUNCH: (Service.EVENT_MANAGEMENT, Service.AV, Service.LED_SCREENS,
                                     Service.STAGING, Service.BRANDING, Service.PHOTOGRAPHY),
    OpportunityType.CONFERENCE: (Service.CONFERENCE_MANAGEMENT, Service.VENUE_SOURCING,
                                 Service.AV, Service.REGISTRATION, Service.INTERPRETATION),
    OpportunityType.EXHIBITION: (Service.EXHIBITION_BOOTHS, Service.BRANDING, Service.AV,
                                 Service.USHERS),
    OpportunityType.WORKSHOP: (Service.VENUE_SOURCING, Service.AV, Service.CATERING),
    OpportunityType.SEMINAR: (Service.VENUE_SOURCING, Service.AV, Service.REGISTRATION),
    OpportunityType.TRAINING_EVENT: (Service.VENUE_SOURCING, Service.AV, Service.PRINTING,
                                     Service.CATERING),
    OpportunityType.GROUNDBREAKING: (Service.EVENT_MANAGEMENT, Service.STAGING,
                                     Service.BRANDING, Service.VIP_MANAGEMENT,
                                     Service.HOSPITALITY, Service.PHOTOGRAPHY),
    OpportunityType.PARTNER_EVENT: (Service.EVENT_MANAGEMENT, Service.VENUE_SOURCING,
                                    Service.BRANDING, Service.PHOTOGRAPHY),
    OpportunityType.PRESS_EVENT: (Service.EVENT_MANAGEMENT, Service.AV, Service.BRANDING,
                                  Service.PHOTOGRAPHY, Service.VIDEO_PRODUCTION),
    OpportunityType.ROADSHOW: (Service.ROADSHOWS, Service.AV, Service.BRANDING,
                               Service.TRANSPORTATION),
    OpportunityType.CORPORATE_CELEBRATION: (Service.EVENT_MANAGEMENT, Service.VENUE_SOURCING,
                                            Service.CATERING, Service.AV),
    OpportunityType.PROJECT_COMPLETION_EVENT: (Service.EVENT_MANAGEMENT, Service.STAGING,
                                               Service.VIP_MANAGEMENT, Service.PHOTOGRAPHY),
    OpportunityType.PROJECT_KICKOFF: (Service.EVENT_MANAGEMENT, Service.VENUE_SOURCING,
                                      Service.AV),
    OpportunityType.TECHNICAL_DAY: (Service.VENUE_SOURCING, Service.AV, Service.LED_SCREENS,
                                    Service.REGISTRATION),
    OpportunityType.CLIENT_APPRECIATION: (Service.EVENT_MANAGEMENT, Service.HOSPITALITY,
                                          Service.CATERING, Service.CORPORATE_GIFTS),
    OpportunityType.DELEGATION_EVENT: (Service.VIP_MANAGEMENT, Service.HOSPITALITY,
                                       Service.TRANSPORTATION, Service.INTERPRETATION),
    OpportunityType.EXECUTIVE_MEETING: (Service.VENUE_SOURCING, Service.VIP_MANAGEMENT,
                                        Service.HOSPITALITY),
    OpportunityType.ANNIVERSARY: (Service.EVENT_MANAGEMENT, Service.VENUE_SOURCING,
                                  Service.CATERING, Service.CORPORATE_GIFTS, Service.AV),
}

#: Words that suggest something is imminent rather than vague.
_IMMINENT_WORDS = ("next week", "this month", "upcoming", "scheduled for", "will open",
                   "set to open", "later this month")
_EXECUTIVE_WORDS = ("ceo", "chairman", "chief executive", "managing director", "minister",
                    "vice president", "board")
_MAJOR_WORDS = ("billion", "largest", "biggest", "flagship", "landmark", "nationwide",
                "first in egypt", "mega")
_LARGE_WORDS = ("million", "major", "strategic", "significant", "expansion")


class RuleBasedProvider(AIProvider):
    """Keyword-driven extraction. Deterministic, offline, and clearly labelled."""

    name = "rule_based"

    def extract(self, request: ExtractionRequest) -> Extraction | None:
        haystack = f"{request.title or ''}\n{request.content}".casefold()

        signal_type = self._detect_signal(haystack)
        opportunity_type, department, action = _OPPORTUNITY_MAP[signal_type]
        services = list(_SERVICE_MAP.get(opportunity_type, ()))

        # No NER: without a hint from the adapter there is no company, full stop.
        company = (request.company_hint or "").strip() or None

        possible_event = (
            company is not None
            and opportunity_type is not OpportunityType.UNKNOWN
            and signal_type is not SignalType.UNKNOWN
        )

        confidence = 0.0
        if signal_type is not SignalType.UNKNOWN:
            confidence = 0.30
        if company and signal_type is not SignalType.UNKNOWN:
            confidence = MAX_CONFIDENCE

        why_now = sales_angle = None
        fact = inference = prediction = None
        if possible_event:
            when = "in the coming weeks" if self._is_imminent(haystack) else "in the near term"
            activity_label = opportunity_type.value.replace("_", " ").lower()
            # Phrased as inference throughout — this extractor never has grounds
            # to claim an event is confirmed.
            why_now = (
                f"{company} has a recent {signal_type.value.replace('_', ' ').lower()} signal. "
                f"Companies typically organise a {activity_label} around activity of "
                f"this kind, likely {when}. "
                "This is an inference from the source, not a confirmed event."
            )
            owner = department.value.replace("_", " ").title()
            activity = opportunity_type.value.replace("_", " ").lower()
            if services:
                shortlist = ", ".join(s.value.replace("_", " ").lower() for s in services[:4])
                sales_angle = (
                    f"Approach {owner} with a {activity} concept covering {shortlist}."
                )
            else:
                sales_angle = f"Approach {owner} to scope {activity} requirements."

            signal_label = signal_type.value.replace("_", " ").lower()
            fact = (
                f"{request.publisher or company} published content matching a "
                f"{signal_label} signal. Detected by keyword match, not by reading."
            )
            inference = (
                f"A {signal_label} of this kind would typically involve external "
                "stakeholders and some form of corporate gathering."
            )
            prediction = (
                f"A {activity_label} may follow. Not stated by the source and not confirmed."
            )

        return Extraction(
            company_name=company,
            signal_type=signal_type,
            signal_title=request.title,
            signal_summary=self._summarize(request.content),
            possible_event=possible_event,
            event_type=opportunity_type if possible_event else OpportunityType.UNKNOWN,
            # No probability estimate is offered. Guessing one would put a made-up
            # number into a weighted factor; the engine handles a missing estimate.
            event_probability=None,
            commercial_value=None,
            opportunity_window=self._window(haystack),
            likely_department=department,
            potential_contact_role=self._role_for(department),
            fact=fact,
            inference=inference,
            prediction=prediction,
            why_now=why_now,
            sales_angle=sales_angle,
            recommended_services=services,
            recommended_action=action,
            factors=self._factors(haystack),
            confidence=confidence,
            extractor=self.name,
        )

    @staticmethod
    def _detect_signal(haystack: str) -> SignalType:
        for signal_type, keywords in _SIGNAL_RULES:
            if any(keyword in haystack for keyword in keywords):
                return signal_type
        return SignalType.UNKNOWN

    @staticmethod
    def _is_imminent(haystack: str) -> bool:
        return any(word in haystack for word in _IMMINENT_WORDS)

    def _window(self, haystack: str) -> OpportunityWindow:
        # Only two outcomes, because keyword matching cannot justify more
        # precision than "there are date words" versus "there are none".
        return (
            OpportunityWindow.DAYS_15_30
            if self._is_imminent(haystack)
            else OpportunityWindow.UNKNOWN
        )

    @staticmethod
    def _factors(haystack: str) -> ExtractionFactors:
        if any(word in haystack for word in _MAJOR_WORDS):
            scale = Scale.MAJOR
        elif any(word in haystack for word in _LARGE_WORDS):
            scale = Scale.LARGE
        else:
            scale = Scale.UNKNOWN
        return ExtractionFactors(
            announcement_scale=scale,
            executive_involvement=(
                True if any(word in haystack for word in _EXECUTIVE_WORDS) else None
            ),
            # Everything else stays unknown: keyword matching is no evidence of
            # company size, marketing posture or event history.
            production_complexity=Level.UNKNOWN,
        )

    @staticmethod
    def _summarize(content: str, limit: int = 400) -> str | None:
        text = " ".join(content.split())
        if not text:
            return None
        return text[:limit] + ("…" if len(text) > limit else "")

    @staticmethod
    def _role_for(department: Department) -> str | None:
        roles = {
            Department.MARKETING: "Marketing Director",
            Department.CORPORATE_COMMUNICATIONS: "Corporate Communications Manager",
            Department.COMMUNICATIONS: "Communications Manager",
            Department.PR: "PR Manager",
            Department.EVENTS: "Head of Events",
            Department.PROCUREMENT: "Procurement Manager",
            Department.BUSINESS_DEVELOPMENT: "Business Development Manager",
            Department.HR: "HR Manager",
        }
        return roles.get(department)
