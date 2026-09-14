"""Pre-extraction relevance filter (spec §10).

AI extraction is the expensive step, so a document earns it. This filter is a
cheap, deterministic gate that answers one question: does this text plausibly
describe a *corporate business change at scale that could produce an event*?

It is tuned to be generous on the way in and firm on obvious noise. A false
negative here silently loses a real opportunity, so the bar to reject is
deliberately higher than the bar to pass: only content with no business signal at
all, or with a clear noise marker and nothing to offset it, is dropped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Business-change vocabulary. Presence of these is what makes a document worth
#: reading — they are the textual footprint of the signals in spec §9.
BUSINESS_TERMS: tuple[str, ...] = (
    "contract", "award", "awarded", "tender", "bid", "procurement", "rfp",
    "project", "launch", "launches", "launched", "unveil", "inaugurat",
    "partnership", "partner", "agreement", "memorandum", "mou", "joint venture",
    "investment", "invest", "funding", "expansion", "expand", "acquisition",
    "acquire", "merger", "factory", "plant", "facility", "office", "branch",
    "capacity", "production", "manufacturing", "export", "deal", "sign",
    "signed", "stake", "milestone", "anniversary", "conference", "summit",
    "forum", "exhibition", "expo", "workshop", "seminar", "sponsorship",
    "delegation", "ceremony", "groundbreaking", "opening", "operations",
    "platform", "digital transformation", "technology", "rollout", "deploy",
    "customer", "client", "distributor", "dealer", "supplier", "strategy",
    "strategic", "revenue", "growth", "billion", "million", "egp", "usd",
    # Added after a live run: an SCZONE story about nine factories opening scored
    # too low to pass, because none of its actual vocabulary was covered.
    "open", "zone", "economic", "industrial", "localization", "localisation",
    "worth", "facilities", "develop", "developer", "construction", "infrastructure",
    "allocation", "spectrum", "licence", "license", "permit", "venture", "fund",
)

#: Corporate-actor vocabulary. A business word with no organisation behind it is
#: usually commentary rather than an event.
CORPORATE_TERMS: tuple[str, ...] = (
    "company", "group", "corporation", "holding", "bank", "ltd", "s.a.e", "sae",
    "llc", "plc", "inc", "firm", "enterprise", "subsidiary", "ceo",
    "chairman", "managing director", "chief executive", "board", "management",
    "ministry", "minister", "authority", "agency", "association", "chamber",
    "sector", "industry", "market",
    "zone", "organisation", "organization", "entity", "developer", "operator",
    "manufacturer", "conglomerate", "venture", "partner", "headquarters",
)

#: Event-possibility vocabulary. Not required, but a strong positive.
EVENT_TERMS: tuple[str, ...] = (
    "event", "ceremony", "conference", "summit", "forum", "exhibition", "expo",
    "workshop", "seminar", "launch", "celebration", "anniversary", "gala",
    "roadshow", "briefing", "press conference", "inauguration", "groundbreaking",
    "opening", "awards", "hosted", "host", "attend", "delegation", "visit",
)

#: Clear noise markers (spec §10). These only reject when the document has no
#: real business footprint to offset them.
NOISE_TERMS: tuple[str, ...] = (
    "football", "soccer", "match", "goal", "striker", "midfielder", "premier league",
    "al ahly club", "zamalek", "tournament", "fixture", "referee",
    "movie", "film", "cinema", "actress", "actor", "singer", "song", "album",
    "celebrity", "fashion week", "recipe", "horoscope", "zodiac", "obituary",
    "weather forecast", "prayer times", "lottery", "gossip",
    "opinion piece", "editorial", "op-ed", "letter to the editor",
)

#: Low-value corporate chatter: real companies, nothing to sell against.
WEAK_TERMS: tuple[str, ...] = (
    "employee of the month", "internship", "job vacancy", "we are hiring",
    "recruitment drive", "staff promotion", "obituary", "condolence",
)

_WORD = re.compile(r"[a-z][a-z'&.-]*")


def _stem(word: str) -> str:
    """Reduce a word to a crude stem so inflections match.

    Real reporting is full of plurals and past tenses — "nine factories opened",
    "contracts awarded", "partnerships signed" — and matching raw tokens against a
    singular term list silently loses those documents. That is the worst kind of
    failure here: a real opportunity dropped before it is ever extracted.

    Deliberately not a full stemmer. Five suffix rules cover the inflections that
    actually appear in business copy, and anything more aggressive would start
    conflating unrelated words.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"          # factories -> factory
    if len(word) > 4 and word.endswith("ing"):
        return word[:-3]                # opening -> open
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]                # awarded -> award
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]                # launches -> launch
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]                # plants -> plant
    return word


def _token_stems(text: str) -> set[str]:
    """Every token in ``text``, plus its stem, so either form can match."""
    stems: set[str] = set()
    for word in _WORD.findall(text):
        stems.add(word)
        stems.add(_stem(word))
    return stems


@dataclass(slots=True)
class RelevanceVerdict:
    """Why a document was kept or dropped. Logged, and surfaced in run stats."""

    relevant: bool
    score: int
    reason: str
    business_hits: list[str] = field(default_factory=list)
    corporate_hits: list[str] = field(default_factory=list)
    event_hits: list[str] = field(default_factory=list)
    noise_hits: list[str] = field(default_factory=list)


def _hits(tokens: set[str], text: str, terms: tuple[str, ...]) -> list[str]:
    """Terms present in the text.

    Single words are matched against the tokenised set, so "plant" does not fire
    inside "implantation"; both sides are stemmed so inflections match. Multi-word
    terms fall back to a substring test.
    """
    found: list[str] = []
    for term in terms:
        if " " in term or "." in term:
            if term in text:
                found.append(term)
        elif term in tokens or _stem(term) in tokens:
            found.append(term)
    return found


def assess(
    title: str | None, content: str, settings: Settings | None = None
) -> RelevanceVerdict:
    """Decide whether a document is worth extracting."""
    settings = settings or get_settings()
    raw = f"{title or ''}\n{content or ''}"
    text = raw.casefold()
    tokens = _token_stems(text)

    if len(text.strip()) < settings.relevance_min_chars:
        return RelevanceVerdict(
            False, 0, f"too short (<{settings.relevance_min_chars} chars)"
        )

    business = _hits(tokens, text, BUSINESS_TERMS)
    corporate = _hits(tokens, text, CORPORATE_TERMS)
    events = _hits(tokens, text, EVENT_TERMS)
    noise = _hits(tokens, text, NOISE_TERMS)
    weak = _hits(tokens, text, WEAK_TERMS)

    # The title carries most of the editorial intent, so noise there counts more.
    title_text = (title or "").casefold()
    title_tokens = _token_stems(title_text)
    title_noise = _hits(title_tokens, title_text, NOISE_TERMS)

    # Score is a transparent count, capped per category so one repeated word
    # cannot carry a document on its own.
    score = min(len(business), 8) * 5 + min(len(corporate), 5) * 4 + min(len(events), 5) * 3
    score = min(score, 100)

    verdict = lambda ok, reason: RelevanceVerdict(  # noqa: E731 - local shorthand
        ok, score, reason, business, corporate, events, noise
    )

    if title_noise and len(business) < settings.relevance_noise_override_hits:
        return verdict(False, f"noise in title ({', '.join(title_noise[:3])})")
    if weak and len(business) < settings.relevance_noise_override_hits:
        return verdict(False, f"low-value content ({', '.join(weak[:3])})")
    if len(noise) >= settings.relevance_noise_hits and len(business) < len(noise):
        return verdict(False, f"predominantly noise ({', '.join(noise[:3])})")
    if not business:
        return verdict(False, "no business-change signal")
    if not corporate and len(business) < settings.relevance_min_business_hits:
        return verdict(False, "no identifiable corporate actor")
    if score < settings.relevance_min_score:
        return verdict(False, f"relevance score {score} below {settings.relevance_min_score}")

    return verdict(True, f"relevance score {score}")


def is_relevant(title: str | None, content: str, settings: Settings | None = None) -> bool:
    return assess(title, content, settings).relevant
