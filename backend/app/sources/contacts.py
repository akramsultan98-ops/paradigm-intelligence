"""Contact discovery from public company pages (spec §14, §15).

What this does: reads a company's own leadership, management or press-contact
page and records the professional contacts published there.

What it will not do, ever:

- invent an email, a name, a title or a profile URL;
- guess an address from a name-and-domain pattern (that is an *inferred* address
  and this adapter only reports what a page actually publishes);
- collect people with no plausible relationship to event spending;
- touch anything behind a login or a paywall.

Every contact it yields carries the URL of the page it was read from.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.config import get_settings
from app.domain.enums import Department, EmailStatus, IngestMode, SourceType
from app.sources.base import SourceConfig
from app.sources.http import FetchClient

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LINKEDIN_RE = re.compile(r"https?://[a-z]{0,3}\.?linkedin\.com/(?:in|pub)/[^\s\"'<>)]+", re.I)
_WHITESPACE = re.compile(r"\s+")

#: Role keywords that matter to event spend, mapped to a department. Order
#: matters: the most specific phrasing is tested first.
_TITLE_DEPARTMENTS: tuple[tuple[tuple[str, ...], Department], ...] = (
    (("head of events", "events manager", "event manager", "events director",
      "event marketing"), Department.EVENTS),
    (("corporate communications", "corporate comms"), Department.CORPORATE_COMMUNICATIONS),
    (("public relations", "pr manager", "pr director", "press office", "press contact",
      "media relations", "media enquiries", "media inquiries"), Department.PR),
    (("communications",), Department.COMMUNICATIONS),
    (("marketing", "brand"), Department.MARKETING),
    (("procurement", "purchasing", "sourcing", "tender", "supply chain"),
     Department.PROCUREMENT),
    (("business development", "commercial director", "commercial manager"),
     Department.BUSINESS_DEVELOPMENT),
    (("human resources", "hr manager", "hr director", "people and culture", "talent"),
     Department.HR),
)

#: Mailbox names that are departmental rather than personal. These are real,
#: publishable business addresses and worth keeping — but as a department contact
#: with no person attached, never as an invented individual.
_ROLE_MAILBOXES: dict[str, Department] = {
    "marketing": Department.MARKETING,
    "brand": Department.MARKETING,
    "communications": Department.COMMUNICATIONS,
    "comms": Department.COMMUNICATIONS,
    "corporatecommunications": Department.CORPORATE_COMMUNICATIONS,
    "pr": Department.PR,
    "press": Department.PR,
    "media": Department.PR,
    "events": Department.EVENTS,
    "event": Department.EVENTS,
    "procurement": Department.PROCUREMENT,
    "purchasing": Department.PROCUREMENT,
    "tenders": Department.PROCUREMENT,
    "sourcing": Department.PROCUREMENT,
    "bd": Department.BUSINESS_DEVELOPMENT,
    "businessdevelopment": Department.BUSINESS_DEVELOPMENT,
    "hr": Department.HR,
    "careers": Department.HR,
    "recruitment": Department.HR,
}

#: Mailboxes that are never a route to event spend.
_IGNORED_MAILBOXES = frozenset({
    "webmaster", "postmaster", "abuse", "noreply", "no-reply", "donotreply",
    "privacy", "legal", "dpo", "security", "unsubscribe", "support", "helpdesk",
    "billing", "accounts", "invoice", "investor", "ir",
})

#: A person's name: two to four capitalised words, no digits.
_NAME_RE = re.compile(r"^(?:[A-Z][A-Za-z'’\-]{1,20}\.?\s+){1,3}[A-Z][A-Za-z'’\-]{1,20}$")

#: Words that make a capitalised phrase a job title rather than a name.
#: "Marketing Director" matches the name pattern perfectly well, so the pattern
#: alone is not enough to tell a person from a role.
_ROLE_WORDS = frozenset({
    "director", "manager", "head", "chief", "officer", "president", "vice",
    "lead", "coordinator", "executive", "specialist", "assistant", "associate",
    "supervisor", "consultant", "analyst", "marketing", "communications",
    "events", "event", "procurement", "purchasing", "relations", "affairs",
    "media", "press", "brand", "sales", "commercial", "development", "human",
    "resources", "department", "team", "office", "contact", "enquiries",
    "inquiries", "general", "senior", "junior", "group", "corporate", "public",
})

#: Container tags that plausibly wrap one person's details.
_CARD_TAGS = frozenset({
    "li", "tr", "td", "div", "article", "section", "dd", "p", "figure", "aside",
})

#: Never climb past these: the whole page is not one person's block.
_STOP_TAGS = frozenset({"body", "html", "[document]", "main", "table", "ul", "ol"})


@dataclass(slots=True)
class DiscoveredContact:
    """A professional contact read off a public page."""

    company_name: str
    name: str
    source_url: str
    job_title: str | None = None
    department: Department = Department.UNKNOWN
    email: str | None = None
    linkedin_url: str | None = None
    #: Published on a public page, so PUBLIC. Never VERIFIED: that would require
    #: an actual verification step, which V1 does not have.
    email_status: EmailStatus = EmailStatus.PUBLIC
    confidence: float = 0.6
    source_title: str | None = None
    source_type: SourceType = SourceType.COMPANY
    ingest_mode: IngestMode = IngestMode.AUTOMATED
    adapter_key: str | None = None


class ContactSourceAdapter(ABC):
    """Discovers contacts. A different contract from ``SourceAdapter`` because
    the output is a person, not a document."""

    def __init__(self, config: SourceConfig):
        self.config = config

    @property
    def key(self) -> str:
        return self.config.key

    @abstractmethod
    def discover(self) -> Iterator[DiscoveredContact]:
        """Yield contacts. Must not raise for one bad page."""

    def close(self) -> None:  # noqa: B027 - optional hook, not an abstract method
        """Release held resources. Empty by default; most adapters hold nothing."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.key!r}>"


def department_for_title(job_title: str | None) -> Department:
    """Map a job title onto a department, or UNKNOWN."""
    if not job_title:
        return Department.UNKNOWN
    lowered = job_title.casefold()
    for keywords, department in _TITLE_DEPARTMENTS:
        if any(keyword in lowered for keyword in keywords):
            return department
    return Department.UNKNOWN


def department_for_mailbox(email: str) -> Department:
    """Department implied by a role mailbox such as ``press@``."""
    local = email.split("@", 1)[0].casefold()
    compact = re.sub(r"[^a-z]", "", local)
    return _ROLE_MAILBOXES.get(compact, Department.UNKNOWN)


def is_ignored_mailbox(email: str) -> bool:
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].casefold())
    return local in _IGNORED_MAILBOXES


def looks_like_person_name(text: str) -> bool:
    """Whether a line reads as a person's name rather than a role.

    The shape test alone is not sufficient — "Marketing Director" satisfies it —
    so any line containing a role word is rejected.
    """
    candidate = text.strip()
    if not _NAME_RE.match(candidate):
        return False
    return not any(word.casefold() in _ROLE_WORDS for word in candidate.split())


def _person_block(anchor):
    """Smallest sensible ancestor of ``anchor`` describing one person.

    Climbs to the nearest card-like container that actually contains a name, and
    stops at page-level tags. Without that stop the walk escapes to the whole
    document and every contact on the page inherits the first name on it.
    """
    candidates = []
    node = anchor
    for _ in range(6):
        parent = node.parent
        if parent is None or parent.name in _STOP_TAGS:
            break
        node = parent
        if node.name in _CARD_TAGS:
            candidates.append(node)
            lines = [
                line.strip()
                for line in node.get_text("\n", strip=True).split("\n")
                if line.strip()
            ]
            if any(looks_like_person_name(line) for line in lines):
                return node
    return candidates[0] if candidates else (anchor.parent or anchor)


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _WHITESPACE.sub(" ", text).strip(" \t\n\r-–—|·•,")
    return cleaned or None


def extract_contacts_from_html(
    html: str,
    *,
    company_name: str,
    source_url: str,
    source_title: str | None = None,
    adapter_key: str | None = None,
    confidence: float = 0.6,
    source_type: SourceType = SourceType.COMPANY,
) -> list[DiscoveredContact]:
    """Parse a public page into contacts.

    Two passes, because real pages come in two shapes:

    1. **Person blocks** — a card or row containing a name, a title and often an
       email. These give the best contacts, so they are taken first and their
       addresses are claimed.
    2. **Loose addresses** — a departmental mailbox in a footer or contact table
       with no person attached. Kept as a department contact, named for the
       department rather than for an invented person.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    page_title = source_title or _clean(soup.title.get_text() if soup.title else None)
    found: list[DiscoveredContact] = []
    claimed_emails: set[str] = set()

    linkedin_by_block: dict[int, str] = {}

    # --- pass 1: person blocks -------------------------------------------
    # Anchored on mailto links, which are the reliable marker of a published
    # contact; the surrounding block supplies the name and title.
    for anchor in soup.select('a[href^="mailto:"]'):
        href = anchor.get("href") or ""
        match = _EMAIL_RE.search(href)
        if not match:
            continue
        email = match.group(0).casefold()
        if email in claimed_emails or is_ignored_mailbox(email):
            continue

        block = _person_block(anchor)
        block_text = block.get_text("\n", strip=True)
        lines = [line for line in (_clean(raw) for raw in block_text.split("\n")) if line]
        lines = [line for line in lines if email not in line.casefold()]

        name = next((line for line in lines if looks_like_person_name(line)), None)
        job_title = None
        if name is not None:
            index = lines.index(name)
            # The title is conventionally the line after the name.
            for candidate in lines[index + 1 : index + 3]:
                if not looks_like_person_name(candidate) and 2 < len(candidate) <= 120:
                    job_title = candidate
                    break
        else:
            job_title = next((line for line in lines if 2 < len(line) <= 120), None)

        department = department_for_title(job_title)
        if department is Department.UNKNOWN:
            department = department_for_mailbox(email)
        if department is Department.UNKNOWN:
            # No evidence of relevance to event spend: skip rather than hoard.
            continue

        linkedin = None
        if link := block.find("a", href=_LINKEDIN_RE):
            linkedin = link.get("href")
        if linkedin:
            linkedin_by_block[id(block)] = linkedin

        claimed_emails.add(email)
        found.append(
            DiscoveredContact(
                company_name=company_name,
                name=name or _department_label(department, company_name),
                job_title=job_title,
                department=department,
                email=email,
                linkedin_url=linkedin,
                source_url=source_url,
                source_title=page_title,
                adapter_key=adapter_key,
                # A named person on a company page is better evidence than a
                # bare departmental mailbox.
                confidence=min(1.0, confidence + (0.15 if name else 0.0)),
                source_type=source_type,
            )
        )

    # --- pass 2: loose departmental addresses ----------------------------
    text = soup.get_text(" ", strip=True)
    for match in _EMAIL_RE.finditer(text):
        email = match.group(0).casefold()
        if email in claimed_emails or is_ignored_mailbox(email):
            continue
        department = department_for_mailbox(email)
        if department is Department.UNKNOWN:
            continue
        claimed_emails.add(email)
        found.append(
            DiscoveredContact(
                company_name=company_name,
                name=_department_label(department, company_name),
                job_title=None,
                department=department,
                email=email,
                source_url=source_url,
                source_title=page_title,
                adapter_key=adapter_key,
                confidence=confidence,
                source_type=source_type,
            )
        )

    return found


def _department_label(department: Department, company_name: str) -> str:
    """Name for a departmental mailbox.

    Explicitly a department, not a person, so nobody mistakes it for a named
    individual we do not have.
    """
    return f"{company_name} {department.value.replace('_', ' ').title()} (department contact)"


class ContactPageAdapter(ContactSourceAdapter):
    """Reads contacts from one public company page.

    Options:
        ``url`` (required) — the leadership, management or press-contact page.
        ``company`` (required) — the company the page belongs to.
    """

    def __init__(self, config: SourceConfig, client: FetchClient | None = None):
        super().__init__(config)
        self.url = config.options.get("url")
        self.company_name = config.options.get("company") or config.company_hint
        if not self.url:
            raise ValueError(f"contact source {config.key!r}: requires options.url")
        if not self.company_name:
            raise ValueError(
                f"contact source {config.key!r}: requires options.company "
                "(a contact must belong to a known company)"
            )
        self._settings = get_settings()
        self._owns_client = client is None
        self._client = client or FetchClient(self._settings)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def discover(self) -> Iterator[DiscoveredContact]:
        result = self._client.fetch(
            self.url, requests_per_minute=self.config.rate_limit_per_minute
        )
        if not result.ok:
            logger.error(
                "contact page unavailable",
                extra={"source": self.key, "status": result.status, "error": result.error},
            )
            return

        try:
            html = (result.content or b"").decode("utf-8", "replace")
            contacts = extract_contacts_from_html(
                html,
                company_name=self.company_name,
                source_url=self.url,
                adapter_key=self.key,
                confidence=self.config.confidence,
                source_type=self.config.source_type,
            )
        except Exception:  # noqa: BLE001 - one unparseable page must not kill a run
            logger.exception("contact page parse failed", extra={"source": self.key})
            return

        logger.info(
            "contacts discovered",
            extra={"source": self.key, "count": len(contacts), "company": self.company_name},
        )
        yield from contacts
