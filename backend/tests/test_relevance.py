"""Relevance filter tests (spec §10).

The asymmetry matters: a false negative silently loses a real opportunity before
it is ever extracted, so recall is tested harder than precision. The stemming
tests exist because a live run found exactly that bug — an SCZONE story about
"nine factories opened" scored 15 and was dropped, because the term list had
"factory" and "open" while the text had "factories" and "opened".
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.relevance import _stem, assess, is_relevant

ARTICLE = (
    "Elsewedy Electric announced the signing of a new EPC contract with the Egyptian "
    "Electricity Transmission Company to build an electrical network, the group said in a "
    "statement. The chairman said the project is worth EGP 475 million and supports the "
    "company's industrial strategy across the governorates."
)


@pytest.fixture
def settings() -> Settings:
    return Settings(postgres_password="t")


# --------------------------------------------------------------------------
# stemming — the recall bug a live run exposed
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("factories", "factory"), ("factory", "factory"),
        ("companies", "company"),
        ("plants", "plant"), ("plant", "plant"),
        ("opened", "open"), ("opens", "open"), ("opening", "open"), ("open", "open"),
        ("awarded", "award"), ("launches", "launch"), ("launched", "launch"),
        ("partnerships", "partnership"), ("signed", "sign"),
        # The "ss" guard stops "business" becoming "busines".
        ("business", "business"),
    ],
)
def test_stemming(word: str, stem: str) -> None:
    assert _stem(word) == stem


def test_plural_and_past_tense_forms_are_matched(settings: Settings) -> None:
    """The live-run regression, pinned.

    This exact document scored 15 and was dropped before stemming was added.
    """
    text = (
        "Egypt opened nine factories in the Suez Canal Economic Zone worth a combined "
        "USD 84.5 million as industrial localization accelerates. The Sokhna manufacturing "
        "base reached 212 plants, with new entrants producing calcium carbonate and "
        "synthetic turf."
    )
    verdict = assess("Egypt opens nine SCZONE factories worth $84.5 million", text, settings)
    assert verdict.relevant, verdict.reason
    assert verdict.score >= settings.relevance_min_score


# --------------------------------------------------------------------------
# accepting real business signals
# --------------------------------------------------------------------------

def test_a_real_corporate_signal_passes(settings: Settings) -> None:
    verdict = assess("Elsewedy Electric signs EGP 475m EPC contract", ARTICLE, settings)
    assert verdict.relevant
    assert verdict.business_hits
    assert verdict.corporate_hits


@pytest.mark.parametrize(
    "title",
    [
        "Company signs strategic partnership with global technology group",
        "Minister inaugurates new pharmaceutical plant in Sadat City",
        "Bank launches digital transformation programme for corporate clients",
        "Developer announces new project worth EGP 3 billion",
        "Group awarded contract for infrastructure works",
        "Firm to host annual customer conference in Cairo",
    ],
)
def test_varied_real_signals_pass(title: str, settings: Settings) -> None:
    body = (
        " The company said in a statement that the agreement was signed by its chairman "
        "and management board, and that customers and distribution partners across the "
        "Egyptian market were briefed on the investment and its expected capacity."
    )
    assert is_relevant(title, title + body, settings), title


# --------------------------------------------------------------------------
# rejecting noise
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("title", "body"),
    [
        (
            "Al Ahly beats Zamalek 2-1 in Cairo derby",
            "A late goal from the striker settled the match at the stadium before a full "
            "crowd. The referee added four minutes and the tournament table was unchanged.",
        ),
        (
            "Actress announces new film role",
            "The celebrity told an interviewer about the cinema project and her album, "
            "ahead of fashion week, in a wide-ranging conversation about her career.",
        ),
        (
            "Opinion: what Egypt's economy needs next",
            "An editorial reflecting on public debate among commentators about the general "
            "direction of policy, offering no announcement or corporate development at all.",
        ),
    ],
)
def test_noise_is_rejected(title: str, body: str, settings: Settings) -> None:
    verdict = assess(title, body, settings)
    assert not verdict.relevant, verdict.reason


def test_short_documents_are_rejected(settings: Settings) -> None:
    assert not assess("Tiny", "Too short to judge.", settings).relevant


def test_no_business_signal_is_rejected(settings: Settings) -> None:
    body = (
        "A general reflection on the weather and the passing of the seasons in the city, "
        "with observations about daily life and the habits of its residents over time."
    )
    assert not assess("A quiet morning", body, settings).relevant


def test_sponsorship_of_a_sports_event_is_not_treated_as_sports_noise(
    settings: Settings,
) -> None:
    """A football sponsorship is a real sponsorship opportunity.

    The noise-override rule exists for exactly this: enough business substance
    outweighs a noise keyword.
    """
    body = (
        "The bank announced a three-year sponsorship agreement with the football league, "
        "signed by its chairman. The company said the partnership includes branding, "
        "hospitality and a customer activation programme, and represents an investment of "
        "EGP 250 million over the contract term."
    )
    verdict = assess("Bank signs league sponsorship deal", body, settings)
    assert verdict.relevant, verdict.reason


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def test_the_filter_can_be_turned_off_by_configuration() -> None:
    strict = Settings(postgres_password="t", relevance_min_score=99)
    assert not is_relevant("Elsewedy signs contract", ARTICLE, strict)


def test_verdict_explains_itself(settings: Settings) -> None:
    """The reason is logged and surfaced, so it has to be meaningful."""
    verdict = assess("Tiny", "Short.", settings)
    assert "too short" in verdict.reason
    assert assess("Elsewedy signs contract", ARTICLE, settings).reason.startswith(
        "relevance score"
    )
