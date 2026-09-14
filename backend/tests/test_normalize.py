"""Normalization is what the unique constraints actually guard, so it is tested
against the spellings Egyptian corporate names really arrive in."""

from __future__ import annotations

import pytest

from app.services.normalize import (
    content_hash,
    normalize_company_name,
    normalize_domain,
    normalize_email,
    normalize_linkedin_url,
    normalize_person_name,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Elsewedy Electric Co.", "elsewedy electric"),
        ("Orascom Construction Ltd Group", "orascom construction"),
        ("Telecom Égypte S.A.E.", "telecom egypte"),
        ("EFG Hermes Holding S.A.E", "efg hermes"),
        ("AMOC S.A.E", "amoc"),
        ("Al Ahly for Trading", "al ahly"),
        ("Commercial International Bank (CIB) Egypt", "commercial international bank cib"),
        ("  Juhayna   Food  Industries  ", "juhayna food industries"),
        ("Procter & Gamble", "procter and gamble"),
    ],
)
def test_company_name_normalization(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


def test_legal_suffix_variants_collapse_to_one_key() -> None:
    """The whole point: these must all be the same company."""
    keys = {
        normalize_company_name(name)
        for name in ("Elsewedy Electric", "Elsewedy Electric SAE", "Elsewedy Electric S.A.E.",
                     "Elsewedy Electric Co.", "Elsewedy Electric Company")
    }
    assert keys == {"elsewedy electric"}


def test_company_name_that_is_only_a_suffix_is_rejected() -> None:
    """An empty dedupe key would silently merge unrelated companies."""
    with pytest.raises(ValueError):
        normalize_company_name("S.A.E.")
    with pytest.raises(ValueError):
        normalize_company_name("   ")


def test_distinct_companies_stay_distinct() -> None:
    assert normalize_company_name("Banque Misr") != normalize_company_name("Banque du Caire")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://WWW.Example.com:8080/path", "example.com"),
        ("Example.COM", "example.com"),
        ("http://sub.example.com/a/b", "sub.example.com"),
        (None, None),
        ("", None),
    ],
)
def test_domain_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


def test_url_normalization_strips_tracking_and_sorts_query() -> None:
    assert normalize_url(
        "HTTPS://WWW.Example.com/News/Item/?utm_source=x&b=2&a=1&gclid=9#frag"
    ) == "https://example.com/News/Item?a=1&b=2"


def test_url_normalization_is_order_independent() -> None:
    assert normalize_url("https://a.test/x?b=2&a=1") == normalize_url("https://a.test/x?a=1&b=2")


def test_email_normalization_keeps_dots_significant() -> None:
    """Corporate mailboxes are dot-significant; folding them would merge two people."""
    assert normalize_email("A.Hassan@Example.COM ") == "a.hassan@example.com"
    assert normalize_email("a.hassan@example.com") != normalize_email("ahassan@example.com")


@pytest.mark.parametrize("bad", ["not-an-email", "@example.com", "a@b", "", None])
def test_malformed_emails_are_dropped(bad: str | None) -> None:
    assert normalize_email(bad) is None


def test_linkedin_normalization() -> None:
    assert (
        normalize_linkedin_url("linkedin.com/in/Ahmed-Hassan-123/?trk=x")
        == "https://www.linkedin.com/in/ahmed-hassan-123"
    )
    assert (
        normalize_linkedin_url("https://eg.linkedin.com/company/Example-Corp")
        == "https://www.linkedin.com/company/example-corp"
    )


@pytest.mark.parametrize("bad", ["https://example.com/in/x", "https://linkedin.com/feed", None, ""])
def test_non_profile_linkedin_urls_are_dropped(bad: str | None) -> None:
    assert normalize_linkedin_url(bad) is None


def test_person_name_normalization() -> None:
    assert normalize_person_name("Ahmed  El-Sayed") == "ahmed el sayed"
    with pytest.raises(ValueError):
        normalize_person_name("!!!")


def test_content_hash_ignores_formatting_but_not_content() -> None:
    assert content_hash("Hello   World") == content_hash("hello world")
    assert content_hash("Hello World") != content_hash("Hello Worlds")
    assert len(content_hash("x")) == 64


def test_content_hash_distinguishes_field_boundaries() -> None:
    """Concatenation must not let two fields blur into one."""
    assert content_hash("ab", "c") != content_hash("a", "bc")
