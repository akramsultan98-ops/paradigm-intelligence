"""Normalization for deduplication.

These functions decide whether two records are the same thing. They are pure,
cheap and unit-tested, and their output is what the unique constraints in the
database actually guard.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Legal and structural suffixes that carry no identity. Egyptian filings use
#: S.A.E. heavily, and the same company appears with and without it constantly.
_LEGAL_SUFFIXES = (
    "s.a.e.", "s.a.e", "sae", "l.l.c.", "llc", "ltd.", "ltd", "limited",
    "inc.", "inc", "plc", "co.", "co", "company", "corporation", "corp.",
    "corp", "group", "holding", "holdings", "gmbh", "s.a.", "sa", "egypt",
    "for trading", "for investment", "for development", "and partners",
)


_TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z_]+|gclid|fbclid|mc_cid|mc_eid|igshid|ref|ref_src|spm)$", re.I
)

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9\s&]+")
_LINKEDIN_SLUG = re.compile(r"/(?:in|pub)/([^/?#]+)")
_LINKEDIN_COMPANY = re.compile(r"/company/([^/?#]+)")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def _normalize_token(value: str) -> str:
    """Put a suffix through the same mangling company names get.

    This has to match ``normalize_company_name`` exactly. "S.A.E." becomes
    "s a e" there once punctuation is replaced by spaces, so a suffix token of
    "sae" would never match and the suffix would survive.
    """
    text = strip_accents(value).casefold().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def strip_accents(value: str) -> str:
    """Drop combining marks so "Telecom Égypte" matches "Telecom Egypte"."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_SUFFIX_TOKENS = tuple(
    sorted(
        {token for token in (_normalize_token(s) for s in _LEGAL_SUFFIXES) if token},
        key=len,
        reverse=True,
    )
)


def normalize_company_name(name: str) -> str:
    """Canonical company identity key.

    Casefolds, strips accents and punctuation, then removes legal and structural
    suffixes repeatedly — "Orascom Construction Ltd Group" needs two passes.

    Raises ``ValueError`` if nothing identifying survives, because an empty
    dedupe key would silently collapse unrelated companies into one row.
    """
    text = strip_accents(name).casefold()
    text = text.replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()

    changed = True
    while changed and text:
        changed = False
        for token in _SUFFIX_TOKENS:
            if text == token:
                # The name is nothing but a legal suffix ("S.A.E."). There is no
                # identity here, and keeping it would mint a garbage dedupe key
                # that unrelated companies could collide on.
                text = ""
                changed = True
                break
            if text.endswith(" " + token):
                text = text[: -(len(token) + 1)].strip()
                changed = True
                break
    if not text:
        raise ValueError(f"company name {name!r} normalizes to empty")
    return text


def normalize_domain(value: str | None) -> str | None:
    """Bare hostname: no scheme, no ``www.``, no port, no path."""
    if not value:
        return None
    candidate = value.strip().casefold()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = "//" + candidate
    host = urlsplit(candidate).netloc or urlsplit(candidate).path
    host = host.split("@")[-1].split(":")[0].strip("/")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_url(url: str) -> str:
    """Stable URL identity: tracking parameters and fragments removed.

    Query parameters are sorted so that two orderings of the same query do not
    become two sources.
    """
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").casefold()
    netloc = parts.netloc.casefold()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAMS.match(key)
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_email(value: str | None) -> str | None:
    """Lowercase and trim. Nothing more.

    Gmail-style dot and ``+tag`` folding is deliberately *not* applied:
    ``a.hassan@`` and ``ahassan@`` are routinely different people on a corporate
    mail server, and collapsing them would merge two real contacts.

    Returns ``None`` for anything that is not plausibly an address, so malformed
    input is dropped rather than stored.
    """
    if not value:
        return None
    candidate = value.strip().casefold()
    if not _EMAIL.match(candidate):
        return None
    return candidate


def normalize_linkedin_url(value: str | None) -> str | None:
    """Canonical LinkedIn profile or company URL.

    Returns ``None`` for a LinkedIn URL that is neither, rather than guessing.
    """
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = "https://" + candidate
    parts = urlsplit(candidate)
    if "linkedin.com" not in parts.netloc.casefold():
        return None

    if match := _LINKEDIN_SLUG.search(parts.path):
        return f"https://www.linkedin.com/in/{match.group(1).casefold()}"
    if match := _LINKEDIN_COMPANY.search(parts.path):
        return f"https://www.linkedin.com/company/{match.group(1).casefold()}"
    return None


def normalize_person_name(name: str) -> str:
    """Canonical person key: accents stripped, punctuation dropped, collapsed."""
    text = strip_accents(name).casefold()
    text = _NON_ALNUM.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        raise ValueError(f"person name {name!r} normalizes to empty")
    return text


def normalize_text(value: str) -> str:
    """Collapse whitespace, for hashing and title comparison."""
    return _WHITESPACE.sub(" ", strip_accents(value).casefold()).strip()


def content_hash(*parts: str | None) -> str:
    """SHA-256 over normalized parts.

    Whitespace is collapsed first, so a republished article that differs only in
    formatting hashes to the same value and is deduplicated.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(normalize_text(part or "").encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()
