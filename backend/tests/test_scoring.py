"""Scoring tests.

These encode the spec's judgement calls, not just arithmetic: high scores must be
hard to reach, UNKNOWN must never help, weak contacts must not inflate a score,
and stale opportunities must fall out of the Top 50 on their own.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.domain.enums import (
    AssertionLevel,
    AttendeeBand,
    Classification,
    CommercialValueBand,
    ContactTiming,
    Department,
    EmailStatus,
    Level,
    OpportunityWindow,
    Scale,
    SignalType,
    SizeBand,
    SourceType,
)
from app.scoring import (
    CommercialValueFactors,
    ContactFactors,
    DecayInputs,
    EventProbabilityFactors,
    EvidenceFactors,
    ScoreInputs,
    classify,
    compute_decay,
    contact_timing_for,
    is_qualified,
    score_commercial_value,
    score_contact,
    score_event_probability,
    score_evidence,
    score_opportunity,
    score_opportunity_contacts,
    timing_score_for,
    window_end_date,
)
from app.scoring.scales import LEVEL_SCORES, SIGNAL_STRENGTH, SIZE_SCORES


@pytest.fixture
def settings() -> Settings:
    return Settings(postgres_password="test")


# --------------------------------------------------------------------------
# configuration guards
# --------------------------------------------------------------------------

def test_weights_must_sum_to_one() -> None:
    """A mis-weighted config silently skews every score, so it must fail at startup."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        Settings(postgres_password="t", weight_timing=0.9)


def test_default_weights_match_the_spec() -> None:
    s = Settings(postgres_password="t")
    assert (s.weight_event_probability, s.weight_commercial_value, s.weight_contact_quality,
            s.weight_timing, s.weight_evidence) == (0.35, 0.25, 0.20, 0.10, 0.10)


@pytest.mark.parametrize("bad", [{"decay_floor": 0.0}, {"decay_tau_days": 0}, {"top_n": 0},
                                {"min_qualifying_score": 101}])
def test_invalid_tunables_are_rejected(bad: dict) -> None:
    with pytest.raises(ValueError):
        Settings(postgres_password="t", **bad)


# --------------------------------------------------------------------------
# the UNKNOWN rule
# --------------------------------------------------------------------------

def test_unknown_always_scores_below_medium() -> None:
    """Spec-critical: missing evidence must never help an opportunity."""
    assert LEVEL_SCORES[Level.UNKNOWN] < LEVEL_SCORES[Level.MEDIUM]
    assert SIZE_SCORES[SizeBand.UNKNOWN] < SIZE_SCORES[SizeBand.MEDIUM]


def test_every_signal_type_has_a_strength() -> None:
    """A missing entry would raise a KeyError mid-pipeline."""
    assert set(SIGNAL_STRENGTH) == set(SignalType)


def test_unknown_signal_is_the_weakest() -> None:
    assert SIGNAL_STRENGTH[SignalType.UNKNOWN] == min(SIGNAL_STRENGTH.values())


# --------------------------------------------------------------------------
# event probability conservatism
# --------------------------------------------------------------------------

def _perfect_event_factors(**overrides) -> EventProbabilityFactors:
    defaults = dict(
        signal_type=SignalType.CONFERENCE,
        announcement_scale=Scale.MAJOR,
        company_size=SizeBand.ENTERPRISE,
        has_event_history=True,
        marketing_activity=Level.HIGH,
        comms_activity=Level.HIGH,
        ecosystem_breadth=Level.HIGH,
        stakeholder_count=12,
        executive_involvement=True,
        timing_score=100,
        ai_estimate=95,
        evidence_score=100,
        assertion_level=AssertionLevel.INFERENCE,
    )
    defaults.update(overrides)
    return EventProbabilityFactors(**defaults)


def test_high_event_probability_is_hard_to_reach(settings: Settings) -> None:
    """Even a near-perfect factor profile must not sail past the unconfirmed cap."""
    score = score_event_probability(_perfect_event_factors(), settings)
    assert score <= settings.event_probability_cap_unconfirmed


def test_power_transform_pulls_middling_scores_down(settings: Settings) -> None:
    """A mediocre profile must not look like a good one."""
    middling = EventProbabilityFactors(
        signal_type=SignalType.PARTNERSHIP,
        announcement_scale=Scale.MEDIUM,
        company_size=SizeBand.MEDIUM,
        timing_score=50,
        evidence_score=100,
    )
    assert score_event_probability(middling, settings) < 55


def test_thin_evidence_caps_event_probability(settings: Settings) -> None:
    """A suggestive story from a weak source cannot score high."""
    capped = score_event_probability(_perfect_event_factors(evidence_score=0), settings)
    assert capped <= settings.evidence_cap_base


def test_only_a_confirmed_event_may_exceed_the_unconfirmed_cap(settings: Settings) -> None:
    unconfirmed = score_event_probability(
        _perfect_event_factors(assertion_level=AssertionLevel.PREDICTION), settings
    )
    confirmed = score_event_probability(
        _perfect_event_factors(assertion_level=AssertionLevel.FACT), settings
    )
    assert unconfirmed <= settings.event_probability_cap_unconfirmed
    assert confirmed >= unconfirmed


def test_missing_ai_estimate_does_not_help(settings: Settings) -> None:
    """An absent estimate must behave like an unknown, not like a midpoint."""
    with_estimate = score_event_probability(_perfect_event_factors(ai_estimate=90), settings)
    without = score_event_probability(_perfect_event_factors(ai_estimate=None), settings)
    assert without < with_estimate


def test_ai_estimate_alone_cannot_drive_the_score(settings: Settings) -> None:
    """The AI is one factor at weight 0.10; it must not be able to dictate a 100."""
    ai_only = EventProbabilityFactors(
        signal_type=SignalType.PROCUREMENT, ai_estimate=100, evidence_score=100
    )
    assert score_event_probability(ai_only, settings) < 50


def test_more_conservative_exponent_lowers_scores() -> None:
    factors = _perfect_event_factors(signal_type=SignalType.PARTNERSHIP, ai_estimate=60)
    lenient = score_event_probability(factors, Settings(postgres_password="t",
                                                       event_probability_exponent=1.0))
    strict = score_event_probability(factors, Settings(postgres_password="t",
                                                      event_probability_exponent=1.6))
    assert strict < lenient


# --------------------------------------------------------------------------
# commercial value
# --------------------------------------------------------------------------

def test_commercial_value_bands() -> None:
    big, band = score_commercial_value(
        CommercialValueFactors(SizeBand.ENTERPRISE, AttendeeBand.OVER_500, Level.HIGH, 10,
                               Level.HIGH, Level.HIGH, 95)
    )
    small, small_band = score_commercial_value(
        CommercialValueFactors(SizeBand.SMALL, AttendeeBand.UNDER_50, Level.LOW, 1,
                               Level.LOW, Level.LOW, 10)
    )
    assert band is CommercialValueBand.VERY_HIGH and big >= 80
    assert small_band is CommercialValueBand.LOW and small < 35


def test_unknown_commercial_factors_land_in_the_lower_bands() -> None:
    value, band = score_commercial_value(CommercialValueFactors())
    assert value < 40
    assert band in {CommercialValueBand.LOW, CommercialValueBand.MEDIUM}


def test_broader_service_scope_raises_value() -> None:
    narrow, _ = score_commercial_value(CommercialValueFactors(service_count=1))
    wide, _ = score_commercial_value(CommercialValueFactors(service_count=9))
    assert wide > narrow


# --------------------------------------------------------------------------
# contact quality
# --------------------------------------------------------------------------

def _contact(title: str | None, department: Department, status=EmailStatus.PUBLIC,
             linkedin=True, confidence=0.9) -> int:
    return score_contact(ContactFactors(title, department, status, linkedin, confidence))


def test_seniority_and_department_both_matter() -> None:
    director = _contact("Marketing Director", Department.MARKETING)
    coordinator = _contact("Marketing Coordinator", Department.MARKETING)
    hr_director = _contact("HR Director", Department.HR)
    assert director > coordinator
    assert director > hr_director


def test_head_of_events_is_a_top_contact() -> None:
    assert _contact("Head of Events", Department.EVENTS) >= 85


def test_untitled_unknown_contact_scores_low() -> None:
    assert _contact(None, Department.UNKNOWN, EmailStatus.UNKNOWN, linkedin=False,
                    confidence=0.2) < 30


def test_inferred_email_scores_below_public() -> None:
    inferred = _contact("Marketing Manager", Department.MARKETING, EmailStatus.INFERRED)
    public = _contact("Marketing Manager", Department.MARKETING, EmailStatus.PUBLIC)
    assert inferred < public


def test_no_contacts_scores_zero(settings: Settings) -> None:
    assert score_opportunity_contacts((), settings) == 0


def test_weak_contacts_are_halved(settings: Settings) -> None:
    """Spec §27: poor contacts must not significantly inflate the score."""
    weak = score_opportunity_contacts((30, 25, 20), settings)
    assert weak == round(30 * settings.contact_quality_weak_multiplier)


def test_best_contact_sets_the_level_not_the_sum(settings: Settings) -> None:
    assert score_opportunity_contacts((88,), settings) <= 88 + \
        settings.contact_corroboration_max_bonus
    assert score_opportunity_contacts((45, 45, 45, 45), settings) < 88


def test_corroboration_bonus_is_capped(settings: Settings) -> None:
    many = score_opportunity_contacts((80,) * 20, settings)
    assert many <= 80 + settings.contact_corroboration_max_bonus


def test_contact_quality_never_exceeds_100(settings: Settings) -> None:
    assert score_opportunity_contacts((100, 100, 100, 100), settings) == 100


# --------------------------------------------------------------------------
# timing
# --------------------------------------------------------------------------

def test_timing_scores_decrease_with_distance() -> None:
    order = [OpportunityWindow.DAYS_0_14, OpportunityWindow.DAYS_15_30,
             OpportunityWindow.DAYS_30_60, OpportunityWindow.DAYS_60_90,
             OpportunityWindow.MONTHS_3_6, OpportunityWindow.MONTHS_6_12]
    scores = [timing_score_for(w) for w in order]
    assert scores == sorted(scores, reverse=True)
    assert timing_score_for(OpportunityWindow.UNKNOWN) < scores[-1]


def test_every_window_has_a_timing_score_and_contact_timing() -> None:
    for window in OpportunityWindow:
        assert 0 <= timing_score_for(window) <= 100
        assert contact_timing_for(window) in set(ContactTiming)


def test_without_a_contact_the_recommendation_is_research() -> None:
    """An urgent window is not actionable if there is nobody to call."""
    assert contact_timing_for(OpportunityWindow.DAYS_0_14, has_contact=False) is \
        ContactTiming.RESEARCH_FIRST
    assert contact_timing_for(OpportunityWindow.DAYS_0_14, has_contact=True) is \
        ContactTiming.IMMEDIATE


def test_window_end_date() -> None:
    assert window_end_date(OpportunityWindow.DAYS_0_14, date(2026, 9, 1)) == date(2026, 9, 15)
    # An unknown window must not get a guessed expiry, which would trigger the
    # missed-window penalty on evidence we do not have.
    assert window_end_date(OpportunityWindow.UNKNOWN, date(2026, 9, 1)) is None
    assert window_end_date(OpportunityWindow.DAYS_0_14, None) is None


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

def test_official_sources_outrank_unknown_ones() -> None:
    official = score_evidence(EvidenceFactors(SourceType.COMPANY, 0.95, True, 0.9, 3))
    other = score_evidence(EvidenceFactors(SourceType.OTHER, 0.3, False, 0.3, 1))
    assert official > other
    assert other < 40


def test_corroboration_raises_evidence() -> None:
    single = score_evidence(EvidenceFactors(SourceType.BUSINESS_PUBLICATION, 0.8, True, 0.8, 1))
    triple = score_evidence(EvidenceFactors(SourceType.BUSINESS_PUBLICATION, 0.8, True, 0.8, 3))
    assert triple > single


def test_missing_publication_date_lowers_evidence() -> None:
    dated = score_evidence(EvidenceFactors(SourceType.COMPANY, 0.9, True, 0.9, 1))
    undated = score_evidence(EvidenceFactors(SourceType.COMPANY, 0.9, False, 0.9, 1))
    assert undated < dated


# --------------------------------------------------------------------------
# decay
# --------------------------------------------------------------------------

def test_fresh_signals_do_not_decay(settings: Settings) -> None:
    result = compute_decay(
        DecayInputs(date(2026, 9, 10), None, 90, as_of=date(2026, 9, 14)), settings
    )
    assert result.factor == 1.0
    assert result.reasons == []


def test_decay_increases_with_age(settings: Settings) -> None:
    factors = [
        compute_decay(DecayInputs(date(2026, 9, 14) - __import__("datetime").timedelta(days=d),
                                  None, 90, as_of=date(2026, 9, 14)), settings).factor
        for d in (0, 30, 60, 90, 180, 365)
    ]
    assert factors == sorted(factors, reverse=True)
    assert factors[0] == 1.0


def test_decay_respects_the_floor(settings: Settings) -> None:
    ancient = compute_decay(
        DecayInputs(date(2010, 1, 1), None, 90, as_of=date(2026, 9, 14)), settings
    )
    assert ancient.factor == pytest.approx(settings.decay_floor)


def test_missed_window_is_penalised(settings: Settings) -> None:
    missed = compute_decay(
        DecayInputs(date(2026, 9, 10), date(2026, 9, 12), 90, as_of=date(2026, 9, 14)), settings
    )
    assert missed.missed_window
    assert missed.factor == pytest.approx(settings.missed_window_penalty)
    assert "opportunity window has closed" in missed.reasons


def test_thin_evidence_is_penalised(settings: Settings) -> None:
    thin = compute_decay(DecayInputs(date(2026, 9, 14), None, 10, as_of=date(2026, 9, 14)),
                         settings)
    assert thin.thin_evidence
    assert thin.factor < 1.0


def test_undated_signal_is_neither_aged_nor_treated_as_fresh(settings: Settings) -> None:
    result = compute_decay(DecayInputs(None, None, 90, as_of=date(2026, 9, 14)), settings)
    assert result.age_days == 0
    assert result.factor == 1.0


# --------------------------------------------------------------------------
# classification and eligibility
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, Classification.EXCEPTIONAL), (95, Classification.EXCEPTIONAL),
        (94, Classification.HOT), (90, Classification.HOT),
        (89, Classification.VERY_HIGH), (85, Classification.VERY_HIGH),
        (84, Classification.HIGH), (80, Classification.HIGH),
        (79, Classification.QUALIFIED), (70, Classification.QUALIFIED),
        (69, Classification.NOT_ELIGIBLE), (0, Classification.NOT_ELIGIBLE),
    ],
)
def test_classification_bands(score: int, expected: Classification) -> None:
    assert classify(score, Settings(postgres_password="t")) is expected


def test_qualifying_threshold_is_configurable() -> None:
    strict = Settings(postgres_password="t", min_qualifying_score=85)
    assert not is_qualified(80, strict)
    assert is_qualified(85, strict)
    # The band moves with the threshold rather than disagreeing with it.
    assert classify(80, strict) is Classification.NOT_ELIGIBLE


# --------------------------------------------------------------------------
# the whole engine
# --------------------------------------------------------------------------

def _inputs(**overrides) -> ScoreInputs:
    defaults = dict(
        evidence=EvidenceFactors(SourceType.COMPANY, 0.95, True, 0.9, 2),
        commercial=CommercialValueFactors(SizeBand.ENTERPRISE, AttendeeBand.OVER_500,
                                          Level.HIGH, 8, Level.HIGH, Level.HIGH, 80),
        contact_scores=(88,),
        window=OpportunityWindow.DAYS_15_30,
        assertion_level=AssertionLevel.INFERENCE,
        event=EventProbabilityFactors(SignalType.PRODUCT_LAUNCH, Scale.MAJOR,
                                      SizeBand.ENTERPRISE, True, Level.HIGH, Level.HIGH,
                                      Level.HIGH, 6, True, ai_estimate=80),
        signal_date=date(2026, 9, 10),
        as_of=date(2026, 9, 14),
    )
    defaults.update(overrides)
    return ScoreInputs(**defaults)


def test_strong_opportunity_qualifies(settings: Settings) -> None:
    result = score_opportunity(_inputs(), settings)
    assert result.score >= settings.min_qualifying_score
    assert result.classification is not Classification.NOT_ELIGIBLE
    assert result.decay_factor == 1.0


def test_weak_opportunity_is_not_eligible(settings: Settings) -> None:
    result = score_opportunity(
        _inputs(
            evidence=EvidenceFactors(SourceType.OTHER, 0.3, False, 0.3, 1),
            commercial=CommercialValueFactors(),
            contact_scores=(),
            window=OpportunityWindow.UNKNOWN,
            assertion_level=AssertionLevel.PREDICTION,
            event=EventProbabilityFactors(SignalType.PROCUREMENT),
            signal_date=date(2026, 3, 1),
        ),
        settings,
    )
    assert result.score < settings.min_qualifying_score
    assert result.classification is Classification.NOT_ELIGIBLE


def test_score_is_the_weighted_sum_times_decay(settings: Settings) -> None:
    """The documented formula, verified rather than assumed."""
    result = score_opportunity(_inputs(), settings)
    expected_base = round(
        settings.weight_event_probability * result.event_probability
        + settings.weight_commercial_value * result.commercial_value
        + settings.weight_contact_quality * result.contact_quality
        + settings.weight_timing * result.timing_score
        + settings.weight_evidence * result.evidence_score
    )
    assert result.base_score == expected_base
    assert result.score == round(result.base_score * result.decay_factor)


def test_losing_contacts_lowers_the_score(settings: Settings) -> None:
    with_contact = score_opportunity(_inputs(contact_scores=(88,)), settings)
    without = score_opportunity(_inputs(contact_scores=()), settings)
    assert without.score < with_contact.score


def test_a_stale_opportunity_leaves_the_top_50(settings: Settings) -> None:
    """Spec §28: decay alone must be enough to drop a once-strong opportunity."""
    fresh = score_opportunity(_inputs(signal_date=date(2026, 9, 10)), settings)
    stale = score_opportunity(_inputs(signal_date=date(2025, 9, 10)), settings)
    assert fresh.score >= settings.min_qualifying_score
    assert stale.score < fresh.score
    assert stale.score < settings.min_qualifying_score


def test_engine_is_deterministic(settings: Settings) -> None:
    first = score_opportunity(_inputs(), settings)
    second = score_opportunity(_inputs(), settings)
    assert first.score == second.score
    assert first.classification is second.classification


def test_all_components_are_in_range(settings: Settings) -> None:
    result = score_opportunity(_inputs(), settings)
    for value in (result.event_probability, result.commercial_value, result.contact_quality,
                  result.timing_score, result.evidence_score, result.base_score, result.score):
        assert 0 <= value <= 100
    assert 0 < result.decay_factor <= 1.0
