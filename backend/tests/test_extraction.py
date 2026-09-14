"""Extraction tests.

The guarantees under test are integrity guarantees: nothing is invented, missing
evidence surfaces as UNKNOWN, and an unvalidated response never becomes data.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.anthropic_provider import TOOL_NAME, AnthropicProvider, build_tool_schema
from app.ai.base import Extraction, ExtractionRequest
from app.ai.rule_based import MAX_CONFIDENCE, RuleBasedProvider
from app.config import Settings
from app.domain.enums import (
    Department,
    OpportunityType,
    OpportunityWindow,
    Service,
    SignalType,
    SourceType,
)


def _request(**overrides) -> ExtractionRequest:
    defaults = dict(
        url="https://example.test/news/1",
        title="Elsewedy Electric unveils new smart metering product line",
        publisher="Elsewedy Electric",
        source_type=SourceType.COMPANY,
        content=(
            "Elsewedy Electric announced the launch of a new smart metering product line "
            "worth 2 billion EGP. The CEO said the rollout is scheduled for next month."
        ),
        company_hint="Elsewedy Electric",
    )
    defaults.update(overrides)
    return ExtractionRequest(**defaults)


# --------------------------------------------------------------------------
# schema integrity
# --------------------------------------------------------------------------

def test_literal_unknown_strings_become_none() -> None:
    """Models are told to answer UNKNOWN; that must not land in a name column."""
    extraction = Extraction.model_validate(
        {"company_name": "UNKNOWN", "why_now": "  ", "sales_angle": "N/A",
         "company_sector": "none"}
    )
    assert extraction.company_name is None
    assert extraction.why_now is None
    assert extraction.sales_angle is None
    assert extraction.company_sector is None
    assert not extraction.has_company


def test_out_of_range_scores_are_rejected() -> None:
    with pytest.raises(ValueError):
        Extraction.model_validate({"event_probability": 140})
    with pytest.raises(ValueError):
        Extraction.model_validate({"confidence": 2.0})


def test_unknown_enum_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        Extraction.model_validate({"signal_type": "SOMETHING_MADE_UP"})


def test_duplicate_services_are_collapsed() -> None:
    extraction = Extraction.model_validate(
        {"recommended_services": ["AV", "AV", "STAGING", "AV"]}
    )
    assert extraction.recommended_services == [Service.AV, Service.STAGING]


def test_defaults_are_all_unknown() -> None:
    """An empty extraction must claim nothing."""
    extraction = Extraction()
    assert extraction.signal_type is SignalType.UNKNOWN
    assert extraction.event_type is OpportunityType.UNKNOWN
    assert extraction.opportunity_window is OpportunityWindow.UNKNOWN
    assert extraction.likely_department is Department.UNKNOWN
    assert extraction.event_probability is None
    assert extraction.confidence == 0.0
    assert not extraction.possible_event
    assert not extraction.is_actionable_opportunity


def test_actionability_requires_company_reason_and_angle() -> None:
    base = dict(company_name="X", possible_event=True, event_type="PRODUCT_LAUNCH",
                why_now="because", sales_angle="sell this")
    assert Extraction.model_validate(base).is_actionable_opportunity
    for missing in ("company_name", "why_now", "sales_angle"):
        payload = dict(base)
        payload[missing] = None
        assert not Extraction.model_validate(payload).is_actionable_opportunity
    no_event = Extraction.model_validate({**base, "possible_event": False})
    assert not no_event.is_actionable_opportunity
    unknown_type = Extraction.model_validate({**base, "event_type": "UNKNOWN"})
    assert not unknown_type.is_actionable_opportunity


# --------------------------------------------------------------------------
# the rule-based extractor
# --------------------------------------------------------------------------

def test_rule_based_detects_a_product_launch() -> None:
    extraction = RuleBasedProvider().extract(_request())
    assert extraction is not None
    assert extraction.signal_type is SignalType.PRODUCT_LAUNCH
    assert extraction.event_type is OpportunityType.PRODUCT_LAUNCH
    assert extraction.possible_event
    assert extraction.likely_department is Department.MARKETING
    assert Service.EVENT_MANAGEMENT in extraction.recommended_services


def test_rule_based_invents_no_company_without_a_hint() -> None:
    """It performs no NER, so an unattributed document yields no company."""
    extraction = RuleBasedProvider().extract(
        _request(company_hint=None, publisher=None, title="A firm partners with another",
                 content="A partnership was announced today.")
    )
    assert extraction is not None
    assert extraction.company_name is None
    assert not extraction.possible_event


def test_rule_based_offers_no_probability_estimate() -> None:
    """Guessing one would feed a made-up number into a weighted factor."""
    extraction = RuleBasedProvider().extract(_request())
    assert extraction is not None
    assert extraction.event_probability is None
    assert extraction.commercial_value is None


def test_rule_based_confidence_is_capped() -> None:
    extraction = RuleBasedProvider().extract(_request())
    assert extraction is not None
    assert extraction.confidence <= MAX_CONFIDENCE
    assert extraction.extractor == "rule_based"


def test_rule_based_labels_its_output_as_inference() -> None:
    """It has no grounds to claim an event is confirmed."""
    extraction = RuleBasedProvider().extract(_request())
    assert extraction is not None and extraction.why_now
    lowered = extraction.why_now.lower()
    assert "not a confirmed event" in lowered
    assert "typically" in lowered or "likely" in lowered


def test_rule_based_leaves_unevidenced_factors_unknown() -> None:
    extraction = RuleBasedProvider().extract(_request())
    assert extraction is not None
    factors = extraction.factors
    assert factors.company_size.value == "UNKNOWN"
    assert factors.marketing_activity.value == "UNKNOWN"
    assert factors.has_event_history is None
    assert factors.expected_attendees.value == "UNKNOWN"


def test_rule_based_is_deterministic() -> None:
    provider = RuleBasedProvider()
    first = provider.extract(_request())
    second = provider.extract(_request())
    assert first is not None and second is not None
    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The annual conference will be held in Cairo", SignalType.CONFERENCE),
        ("The company signed a memorandum of understanding", SignalType.MOU),
        ("A tender was issued for the supply of equipment", SignalType.TENDER),
        ("The group inaugurated a new factory", SignalType.NEW_FACILITY),
        ("Nothing much happened at all here", SignalType.UNKNOWN),
    ],
)
def test_rule_based_signal_detection(text: str, expected: SignalType) -> None:
    extraction = RuleBasedProvider().extract(_request(title=None, content=text))
    assert extraction is not None
    assert extraction.signal_type is expected


# --------------------------------------------------------------------------
# the Anthropic provider
# --------------------------------------------------------------------------

def test_tool_schema_is_derived_from_the_model() -> None:
    """The output contract and the validation contract must not drift apart."""
    schema = build_tool_schema()
    assert "extractor" not in schema["properties"]
    assert schema["additionalProperties"] is False
    for field in ("company_name", "signal_type", "possible_event", "event_probability",
                  "why_now", "sales_angle", "recommended_action", "factors", "confidence"):
        assert field in schema["properties"], field


def test_provider_requires_an_api_key() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(Settings(postgres_password="t", ai_provider="anthropic",
                                   anthropic_api_key=None))


def _provider(handler) -> AnthropicProvider:
    settings = Settings(postgres_password="t", ai_provider="anthropic",
                        anthropic_api_key="test-key")
    client = httpx.Client(base_url="https://api.anthropic.test",
                          transport=httpx.MockTransport(handler))
    return AnthropicProvider(settings, client=client)


def test_provider_parses_a_valid_tool_call() -> None:
    payload = {
        "company_name": "Elsewedy Electric",
        "signal_type": "PRODUCT_LAUNCH",
        "possible_event": True,
        "event_type": "PRODUCT_LAUNCH",
        "event_probability": 72,
        "why_now": "Launch announced; a launch event is likely.",
        "sales_angle": "Full launch production.",
        "recommended_action": "CONTACT_MARKETING",
        "confidence": 0.8,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
        return httpx.Response(
            200, json={"content": [{"type": "tool_use", "name": TOOL_NAME, "input": payload}]}
        )

    extraction = _provider(handler).extract(_request())
    assert extraction is not None
    assert extraction.company_name == "Elsewedy Electric"
    assert extraction.event_probability == 72
    assert extraction.extractor.startswith("anthropic:")


def test_provider_discards_a_response_that_fails_validation() -> None:
    """An unvalidated extraction must never reach the database."""
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": TOOL_NAME,
                               "input": {"event_probability": 500,
                                         "signal_type": "NOT_A_REAL_TYPE"}}]},
        )

    assert _provider(handler).extract(_request()) is None


def test_provider_discards_a_prose_only_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "Sure, here is the data..."}],
                       "stop_reason": "end_turn"}
        )

    assert _provider(handler).extract(_request()) is None


def test_provider_returns_none_on_a_hard_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    assert _provider(handler).extract(_request()) is None


def test_provider_retries_anthropic_overload() -> None:
    """529 is Anthropic's overloaded signal and is worth one more attempt."""
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(529, json={"error": "overloaded"})
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": TOOL_NAME,
                               "input": {"company_name": "X", "confidence": 0.5}}]},
        )

    extraction = _provider(handler).extract(_request())
    assert extraction is not None
    assert calls["n"] == 2


def test_provider_fails_closed_on_a_client_error() -> None:
    """A 400 is our bug, not a transient: retrying it just wastes calls."""
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    assert _provider(handler).extract(_request()) is None
    assert calls["n"] == 1


def test_provider_retries_on_429() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": TOOL_NAME,
                               "input": {"company_name": "X", "confidence": 0.5}}]},
        )

    extraction = _provider(handler).extract(_request())
    assert extraction is not None
    assert calls["n"] == 2
