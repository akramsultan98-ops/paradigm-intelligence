# ARCHITECTURE

## Mission boundary

PARADIGM INTELLIGENCE has exactly one job: **maintain a ranked list of the 50
corporate sales opportunities most likely to generate event business for PARADIGM
in Egypt.**

It is not a scraper, not a contact database, not a CRM. Everything below exists
only to serve the Top 50.

One deliberate extension of that boundary: the list is worked by an Account Manager,
so the system also has to say **who to approach at each company and what was last
said to them**. A ranked company nobody can reach is not an opportunity. That is the
whole of `scoring/contact_routing.py`, `scoring/event_timing.py`,
`services/outreach.py` and the `outreach_log` table — enough to run an account
relationship, and firmly short of a CRM (no sending, no pipeline management, no
forecasting).

## Shape

A **modular monolith**. One FastAPI process, one PostgreSQL database, one Next.js
read-only UI. No queues, no workers, no microservices, no Kubernetes. Recurring
work is either a background thread inside the API process or a cron entry calling
the CLI — the same code either way.

```
                      ┌────────────────────────────────────────────┐
  external world      │              backend (FastAPI)             │
  ──────────────      │                                            │
  RSS / newsroom  ───▶│  sources/    adapters + FetchClient        │
  company pages   ───▶│      │       (timeout, retry, rate limit)  │
  local JSONL     ───▶│      ▼                                     │
  analyst intake  ───▶│  services/relevance.py   ◀── cheap gate    │
                      │      │                                     │
                      │      ▼                                     │
                      │  ai/         extraction (provider-agnostic)│
                      │      │       schema-validated              │
                      │      ▼                                     │
                      │  services/   pipeline · dedupe · normalize │
                      │      │                                     │
                      │      ▼                                     │
                      │  scoring/    deterministic score engine    │
                      │      │                                     │
                      │      ▼                                     │
                      │  models/     SQLAlchemy ──▶ PostgreSQL     │
                      │      │                                     │
                      │      ▼                                     │
                      │  api/        top50 · detail · company ·    │
                      │              brief · ingest · outreach ·   │
                      │              maintenance                   │
                      └────────────────────────────────────────────┘
                                          │
                                          ▼
       frontend (Next.js): Top 50 · detail · company profile · brief · follow-ups
```

`scoring/` holds two modules that are not score arithmetic: `event_timing.py` decides
whether an opportunity can still be won, and `contact_routing.py` decides who to
approach for it. Both are pure functions of stored evidence, which is why they live
beside the scorer rather than in the API — and both are recomputed rather than
cached, because the calendar moves on its own.

## The pipeline

One linear pass, in `backend/app/services/pipeline.py`:

```
SOURCE → RELEVANCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE → TOP 50
```

| Stage | Module | What happens |
|---|---|---|
| SOURCE | `sources/`, `services/sources.py` | An adapter yields a `RawDocument` through `FetchClient` (timeout, bounded retry, per-host rate limit). Persisted as a `Source`, deduplicated on normalized URL **and** content hash. |
| RELEVANCE | `services/relevance.py` | A cheap deterministic gate. Noise is dropped **before** any row is written and before the extractor is called, so a football report costs one keyword pass and nothing else. |
| extraction | `ai/` | The document becomes a validated `Extraction`. Anything unevidenced comes back `UNKNOWN`. A response that fails validation is discarded, never partially salvaged. |
| COMPANY | `services/companies.py` | Resolved against existing companies by domain, then normalized name. A known company mentioned verbatim in free text is *recognised*; nothing is ever invented. Subsidiaries are linked to parents, never merged. |
| SIGNAL | `services/signals.py` | A `Signal` records the business fact, deduplicated per company on `sha256(company | type | normalized title)`. |
| EVENT OPPORTUNITY | `services/opportunities.py` | Created only where a realistic event implication exists — labelled `INFERENCE` or `PREDICTION`, `FACT` only when an official source announces a confirmed event. |
| CONTACT | `sources/contacts.py`, `services/contact_discovery.py` | Contacts are read from public company pages, or submitted with a mandatory `source_url`. Never synthesised. |
| SCORE | `scoring/` | Deterministic, configurable, conservative. See `SCORING.md`. |
| TOP 50 | `services/top50.py` | Score ≥ 70 qualifies; the highest 50 are the Top 50. Fewer qualifiers means a shorter list, never padding. |

Each document is processed in **its own transaction**, so one bad document costs
one document rather than the run. One unreachable source, one unparseable feed
entry and one failed extraction are all isolated the same way.

## Division of responsibility: AI vs. deterministic code

Deliberate and load-bearing.

**AI extracts and reasons.** It reads unstructured text and returns structured
evidence: which company, what kind of signal, whether an event is plausible, which
department owns it, why it matters now, what PARADIGM could sell. It is also asked
for its own `event_probability` and `commercial_value` estimates.

**Deterministic code scores and ranks.** The final `OPPORTUNITY_SCORE` is computed
in `scoring/` from named factors with configurable weights. The AI's own estimates
enter as *one weighted factor among eleven* (weight 0.10), not as the answer. A
test asserts the AI estimate alone cannot drive a score.

Every AI response is schema-validated against a Pydantic model. Invalid responses
are logged and dropped.

## Truth labelling

Spec §6 forbids presenting a predicted event as confirmed, so the distinction
lives in the schema rather than in prose:

- `Signal.evidence_level` — `FACT` / `INFERENCE`.
- `Opportunity.assertion_level` — `PREDICTION` by default; `INFERENCE` when the
  signal strongly implies activity; `FACT` only when the source itself announces a
  confirmed event **and** the source is official (company, government,
  procurement). The same event reported second-hand is `INFERENCE`.
- `Opportunity.fact` / `.inference` / `.prediction` — three separate columns, so
  the UI renders them as visually distinct rows and cannot blur them.

## Provenance: real vs. test data

`Source.ingest_mode` is one of:

| Mode | Meaning |
|---|---|
| `AUTOMATED` | fetched by a source adapter from a public source |
| `ANALYST` | submitted by a person, with a mandatory public `source_url` |
| `TEST` | fixtures |

The API **excludes `TEST` by default**; `?include_test=true` reveals it. Fixtures
can therefore exist in a database without ever reaching the operational Top 50
(spec §37).

## Source adapters

Two contracts, because the outputs differ:

```python
class SourceAdapter(ABC):        # yields documents
    def fetch(self, since) -> Iterator[RawDocument]: ...

class ContactSourceAdapter(ABC): # yields people
    def discover(self) -> Iterator[DiscoveredContact]: ...
```

Shipped and tested:

- `RssSourceAdapter` — any RSS/Atom feed: company newsrooms, business press,
  industry press, event listings. Which feeds exist is *configuration*.
- `JsonlFileSourceAdapter` — newline-delimited JSON from disk, for
  analyst-supplied material.
- `ContactPageAdapter` — a company's own public leadership or press-contact page.
  Reads only what the page publishes: it never derives an address from a
  name-and-domain pattern, skips mailboxes with no route to event spend
  (`webmaster@`, `ir@`, `support@`), and skips senior people whose role has no
  relationship to events (a CFO). A departmental mailbox is kept but labelled as a
  department, never as an invented person.

`FetchClient` owns what is easy to get wrong per-adapter: timeouts, bounded
retries (transient statuses only — a 403 is an answer, not a hiccup), per-**host**
rate limiting, `Retry-After`, a response byte cap, and a real User-Agent. It
returns a result rather than raising, so no adapter can abort a run.

The spec's source *categories* are the `SourceType` enum rather than five
near-identical classes, because they differ in trust tier, not in fetch mechanics.

## Analyst intake

`POST /api/v1/ingest/signals` takes a structured, verified signal plus its
mandatory source. It is implemented as `StaticExtractionProvider` — a provider that
returns the extraction it was handed — so it reuses the **entire** pipeline rather
than a parallel path that would drift. It records `ANALYST` provenance and
`extractor: "analyst"`, and it faces the same relevance gate and the same
deduplication.

## Enabling a source

The registry ships every entry disabled, and `config/` is mounted read-only in the
container, so a running deployment cannot edit it. Enablement is therefore a
setting: `SOURCES_ENABLED` names the keys that run, and when set it replaces the
file's `enabled` flags entirely — exactly those keys run and every other source is
off, applied once in `load_source_configs` so ingestion, contact discovery, the
preflight and the `sources` listing cannot disagree about what is live.

That direction matters as much as the other: a source left `enabled: true` after it
breaks cannot creep back in, because the allowlist is the whole answer rather than
one flag among many.

`python -m app.cli enable-sources` builds the line from the preflight's verdicts, so
a source can only be switched on by demonstrating that it is reachable and parses.
An unknown key is rejected with the keys that do exist: a typo would otherwise mean
"ingest nothing", reported as a successful run with no documents, which is the most
expensive way for this to fail. The API keeps serving either way — a bad ingestion
setting is not a reason to take the Top 50 offline — and `status` surfaces it as
`sources_error`.

## Recurring refresh

`services/scheduler.py` runs one cycle on an interval in a daemon thread, off by
default:

1. ingest configured sources
2. discover contacts, then re-score each affected company **once**
3. apply decay

Order matters: each stage feeds the next. Contact re-scoring happens after all of
a page's contacts are attached, not per contact — otherwise one page produces
several meaningless score movements in the daily brief.

`python -m app.cli cycle` runs the same function, for anyone who prefers cron.

## Access control

A single shared API key (`X-API-Key` or a bearer token), applied as a dependency on
the whole `/api/v1` router so a new route cannot be added unprotected by omission.
Health probes stay open. No key configured means open access — fine locally, and
**refused outright** when `APP_ENV` is not a development value, so it can never be
the silent production default.

## Configuration

Everything tunable is in `backend/app/config.py`, loaded from the environment with
documented defaults: sectors, scoring weights, the qualifying threshold, `TOP_N`,
conservatism exponent, decay constants, relevance thresholds, rate limits,
scheduler interval. Scoring weights are validated at startup to sum to 1.0; a bad
vector fails fast rather than silently skewing every score.

## What is intentionally absent

Outreach **sending** (the log records what a person did; it does not email anybody),
CRM pipeline management and forecasting, user accounts, multi-country support, a
queue, a warehouse, per-source bespoke scrapers, and any government or procurement
adapter whose access terms have not been verified. Each would cost focus and can be
added behind the existing seams.
