"""Controlled vocabularies.

Every enum here is stored in PostgreSQL as ``VARCHAR`` with a ``CHECK``
constraint (see ``models/base.py``), so adding a member is an ordinary migration
rather than an ``ALTER TYPE``.
"""

from __future__ import annotations

from enum import StrEnum


class SignalType(StrEnum):
    """Recent business activity worth paying attention to (spec §5).

    The spec's list is consolidated where two phrasings mean the same thing to
    the scoring engine: "new offices"/"new factories"/"new plants" are all
    ``NEW_FACILITY``; "new products"/"product launches" are ``PRODUCT_LAUNCH``.
    """

    NEW_CONTRACT = "NEW_CONTRACT"
    NEW_PROJECT = "NEW_PROJECT"
    PROJECT_LAUNCH = "PROJECT_LAUNCH"
    PROJECT_COMPLETION = "PROJECT_COMPLETION"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    PARTNERSHIP = "PARTNERSHIP"
    MOU = "MOU"
    JOINT_VENTURE = "JOINT_VENTURE"
    INVESTMENT = "INVESTMENT"
    EXPANSION = "EXPANSION"
    NEW_FACILITY = "NEW_FACILITY"
    MARKET_ENTRY = "MARKET_ENTRY"
    NEW_TECHNOLOGY = "NEW_TECHNOLOGY"
    DIGITAL_TRANSFORMATION = "DIGITAL_TRANSFORMATION"
    CUSTOMER_WIN = "CUSTOMER_WIN"
    EXECUTIVE_VISIT = "EXECUTIVE_VISIT"
    DELEGATION = "DELEGATION"
    CONFERENCE = "CONFERENCE"
    EXHIBITION = "EXHIBITION"
    SPONSORSHIP = "SPONSORSHIP"
    WORKSHOP = "WORKSHOP"
    SEMINAR = "SEMINAR"
    TRAINING_PROGRAM = "TRAINING_PROGRAM"
    ANNIVERSARY = "ANNIVERSARY"
    MILESTONE = "MILESTONE"
    TENDER = "TENDER"
    PROCUREMENT = "PROCUREMENT"
    UNKNOWN = "UNKNOWN"


#: Signal types that are themselves announcements of a confirmed event. Only
#: these may ever produce an opportunity asserted as ``FACT``, and only when the
#: source is official.
CONFIRMED_EVENT_SIGNALS: frozenset[SignalType] = frozenset(
    {
        SignalType.CONFERENCE,
        SignalType.EXHIBITION,
        SignalType.WORKSHOP,
        SignalType.SEMINAR,
        SignalType.TRAINING_PROGRAM,
    }
)


class OpportunityType(StrEnum):
    """The corporate activity PARADIGM could be engaged for (spec §6)."""

    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    CUSTOMER_EVENT = "CUSTOMER_EVENT"
    CLIENT_APPRECIATION = "CLIENT_APPRECIATION"
    PARTNER_EVENT = "PARTNER_EVENT"
    DEALER_EVENT = "DEALER_EVENT"
    DISTRIBUTOR_EVENT = "DISTRIBUTOR_EVENT"
    CONFERENCE = "CONFERENCE"
    WORKSHOP = "WORKSHOP"
    TECHNICAL_DAY = "TECHNICAL_DAY"
    SEMINAR = "SEMINAR"
    TRAINING_EVENT = "TRAINING_EVENT"
    EXECUTIVE_MEETING = "EXECUTIVE_MEETING"
    ROUNDTABLE = "ROUNDTABLE"
    BUSINESS_LUNCH = "BUSINESS_LUNCH"
    BUSINESS_DINNER = "BUSINESS_DINNER"
    VIP_DINNER = "VIP_DINNER"
    PRESS_EVENT = "PRESS_EVENT"
    MEDIA_EVENT = "MEDIA_EVENT"
    EXHIBITION = "EXHIBITION"
    ROADSHOW = "ROADSHOW"
    TOWN_HALL = "TOWN_HALL"
    ANNUAL_MEETING = "ANNUAL_MEETING"
    AWARDS = "AWARDS"
    TEAM_BUILDING = "TEAM_BUILDING"
    CORPORATE_CELEBRATION = "CORPORATE_CELEBRATION"
    ANNIVERSARY = "ANNIVERSARY"
    PROJECT_LAUNCH = "PROJECT_LAUNCH"
    PROJECT_KICKOFF = "PROJECT_KICKOFF"
    PROJECT_COMPLETION_EVENT = "PROJECT_COMPLETION_EVENT"
    GROUNDBREAKING = "GROUNDBREAKING"
    DELEGATION_EVENT = "DELEGATION_EVENT"
    HOSPITALITY = "HOSPITALITY"
    UNKNOWN = "UNKNOWN"


class OpportunityStatus(StrEnum):
    """Where an opportunity stands with the sales team (spec §22)."""

    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    CONTACTED = "CONTACTED"
    MEETING = "MEETING"
    WON = "WON"
    LOST = "LOST"
    NURTURE = "NURTURE"


#: Closed statuses. These leave the Top 50 regardless of score.
CLOSED_STATUSES: frozenset[OpportunityStatus] = frozenset(
    {OpportunityStatus.WON, OpportunityStatus.LOST}
)


class OpportunityWindow(StrEnum):
    """How soon the opportunity is live (spec §16)."""

    DAYS_0_14 = "DAYS_0_14"
    DAYS_15_30 = "DAYS_15_30"
    DAYS_30_60 = "DAYS_30_60"
    DAYS_60_90 = "DAYS_60_90"
    MONTHS_3_6 = "MONTHS_3_6"
    MONTHS_6_12 = "MONTHS_6_12"
    UNKNOWN = "UNKNOWN"


class ContactTiming(StrEnum):
    """When an Account Manager should make contact."""

    IMMEDIATE = "IMMEDIATE"
    WITHIN_1_WEEK = "WITHIN_1_WEEK"
    WITHIN_2_WEEKS = "WITHIN_2_WEEKS"
    WITHIN_1_MONTH = "WITHIN_1_MONTH"
    MONITOR_MONTHLY = "MONITOR_MONTHLY"
    MONITOR_QUARTERLY = "MONITOR_QUARTERLY"
    RESEARCH_FIRST = "RESEARCH_FIRST"


class RecommendedAction(StrEnum):
    """What to do next (spec §15). Never automated outreach."""

    CONTACT_MARKETING = "CONTACT_MARKETING"
    CONTACT_COMMUNICATIONS = "CONTACT_COMMUNICATIONS"
    CONTACT_PROCUREMENT = "CONTACT_PROCUREMENT"
    CONTACT_PROJECT_DIRECTOR = "CONTACT_PROJECT_DIRECTOR"
    REQUEST_INTRODUCTION = "REQUEST_INTRODUCTION"
    MONITOR_FOR_RFP = "MONITOR_FOR_RFP"
    PREPARE_EVENT_CONCEPT = "PREPARE_EVENT_CONCEPT"
    NURTURE_ACCOUNT = "NURTURE_ACCOUNT"


class Department(StrEnum):
    """Departments that influence event spending (spec §9), in priority order."""

    MARKETING = "MARKETING"
    CORPORATE_COMMUNICATIONS = "CORPORATE_COMMUNICATIONS"
    COMMUNICATIONS = "COMMUNICATIONS"
    PR = "PR"
    EVENTS = "EVENTS"
    PROCUREMENT = "PROCUREMENT"
    BUSINESS_DEVELOPMENT = "BUSINESS_DEVELOPMENT"
    HR = "HR"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class EmailStatus(StrEnum):
    """How an email address is known (spec §10).

    ``INFERRED`` must never be presented or stored as ``VERIFIED``.
    """

    VERIFIED = "VERIFIED"
    PUBLIC = "PUBLIC"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class SourceType(StrEnum):
    """Source categories, ordered by trust (spec §17)."""

    COMPANY = "COMPANY"
    GOVERNMENT = "GOVERNMENT"
    PROCUREMENT = "PROCUREMENT"
    BUSINESS_PUBLICATION = "BUSINESS_PUBLICATION"
    INDUSTRY_PUBLICATION = "INDUSTRY_PUBLICATION"
    EVENT = "EVENT"
    PUBLIC_PROFILE = "PUBLIC_PROFILE"
    OTHER = "OTHER"


#: Sources that speak for the organisation itself or for the state.
OFFICIAL_SOURCE_TYPES: frozenset[SourceType] = frozenset(
    {SourceType.COMPANY, SourceType.GOVERNMENT, SourceType.PROCUREMENT}
)


class IngestMode(StrEnum):
    """How a source entered the system (spec §37).

    Real and test data must never be indistinguishable, so provenance is a column
    rather than a convention. The API defaults to excluding ``TEST``.
    """

    #: Fetched by a source adapter from a public source.
    AUTOMATED = "AUTOMATED"
    #: Submitted by a person, with a mandatory source URL as evidence.
    ANALYST = "ANALYST"
    #: Fixtures. Never mixed into the operational Top 50.
    TEST = "TEST"


class AssertionLevel(StrEnum):
    """Epistemic status of a claim (spec §6).

    A predicted event is never stated as confirmed, so this travels with the
    data rather than living only in prose.
    """

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    PREDICTION = "PREDICTION"


class Classification(StrEnum):
    """Score bands (spec §11)."""

    EXCEPTIONAL = "EXCEPTIONAL"
    HOT = "HOT"
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    QUALIFIED = "QUALIFIED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class CommercialValueBand(StrEnum):
    """Used wherever a monetary value cannot be verified (spec §8).

    Budgets are never invented; this answers "how big", not "how much".
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class Level(StrEnum):
    """Generic ordinal for evidence-light qualitative factors."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class Scale(StrEnum):
    """How big an announcement is."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    MAJOR = "MAJOR"
    UNKNOWN = "UNKNOWN"


class SizeBand(StrEnum):
    """Company size."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    ENTERPRISE = "ENTERPRISE"
    UNKNOWN = "UNKNOWN"


class AttendeeBand(StrEnum):
    """Expected attendee scale, for commercial value."""

    UNDER_50 = "UNDER_50"
    FROM_50_TO_200 = "FROM_50_TO_200"
    FROM_200_TO_500 = "FROM_200_TO_500"
    OVER_500 = "OVER_500"
    UNKNOWN = "UNKNOWN"


class EvidenceLevel(StrEnum):
    """Whether a signal is reported or read between the lines."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"


class Service(StrEnum):
    """PARADIGM's service catalogue (spec §14).

    Only services the opportunity actually supports are recommended.
    """

    EVENT_MANAGEMENT = "EVENT_MANAGEMENT"
    CONFERENCE_MANAGEMENT = "CONFERENCE_MANAGEMENT"
    VENUE_SOURCING = "VENUE_SOURCING"
    AV = "AV"
    LED_SCREENS = "LED_SCREENS"
    LIGHTING = "LIGHTING"
    STAGING = "STAGING"
    SET_DESIGN = "SET_DESIGN"
    SCENOGRAPHY = "SCENOGRAPHY"
    BRANDING = "BRANDING"
    PRINTING = "PRINTING"
    REGISTRATION = "REGISTRATION"
    USHERS = "USHERS"
    VIP_MANAGEMENT = "VIP_MANAGEMENT"
    HOSPITALITY = "HOSPITALITY"
    CATERING = "CATERING"
    TRANSPORTATION = "TRANSPORTATION"
    INTERPRETATION = "INTERPRETATION"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    VIDEOGRAPHY = "VIDEOGRAPHY"
    VIDEO_PRODUCTION = "VIDEO_PRODUCTION"
    LIVE_STREAMING = "LIVE_STREAMING"
    HYBRID_EVENT_PRODUCTION = "HYBRID_EVENT_PRODUCTION"
    EXHIBITION_BOOTHS = "EXHIBITION_BOOTHS"
    ROADSHOWS = "ROADSHOWS"
    TEAM_BUILDING = "TEAM_BUILDING"
    CORPORATE_GIFTS = "CORPORATE_GIFTS"
    GIVEAWAYS = "GIVEAWAYS"


class BriefChange(StrEnum):
    """How an opportunity moved since the last brief (spec §30)."""

    NEW_HOT = "NEW_HOT"
    UPGRADED = "UPGRADED"
    DOWNGRADED = "DOWNGRADED"
    EXPIRED = "EXPIRED"
