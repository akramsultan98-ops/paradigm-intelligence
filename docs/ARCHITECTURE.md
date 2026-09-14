# ARCHITECTURE

## Mission boundary

PARADIGM INTELLIGENCE has exactly one V1 job: **maintain a ranked list of the 50
corporate sales opportunities most likely to generate event business for PARADIGM
in Egypt.**

It is not a scraper, not a contact database, not a CRM. Everything below exists
only to serve the Top 50.

## Shape

A **modular monolith**. One FastAPI process, one PostgreSQL database, one Next.js
read-only UI. No queues, no workers, no microservices, no Kubernetes. Scheduling
is a cron entry that calls a CLI command.

```
                    ┌──────────────────────────────────────────┐
  external world    │              backend (FastAPI)           │
  ──────────────    │                                          │
  RSS / newsroom ──▶│  sources/   adapter framework            │
  local JSONL    ──▶│      │                                   │
                    │      ▼                                   │
                    │  ai/        extraction (provider-agnostic)│
                    │      │                                   │
                    │      ▼                                   │
                    │  services/  pipeline · dedupe · normalize │
                    │      │                                   │
                    │      ▼                                   │
                    │  scoring/   deterministic score engine    │
                    │      │                                   │
                    │      ▼                                   │
                    │  models/    SQLAlchemy  ──▶ PostgreSQL    │
                    │      │                                   │
                    │      ▼                                   │
                    │  api/       /opportunities/top50, /brief  │
                    └──────────────────────────────────────────┘
                                        │
                                        ▼
                            frontend (Next.js) — Top 50 view
```

## The pipeline

The core logic is a single linear pass, implemented in
`backend/app/services/pipeline.py`:

```
SOURCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE → TOP 50
```

| Stage | Module | What happens |
|---|---|---|
| SOURCE | `sources/`, `services/sources.py` | An adapter yields a `RawDocument`. It is persisted as a `Source` row, deduplicated on normalized URL and content hash. |
| extraction | `ai/` | The document is turned into a validated `Extraction`. Anything unevidenced comes back `UNKNOWN`. |
| COMPANY | `services/companies.py` | The extracted company is resolved against existing companies by normalized name, then domain. Created only if new. |
| SIGNAL | `services/signals.py` | A `Signal` row records the business fact, deduplicated per company. |
| EVENT OPPORTUNITY | `services/opportunities.py` | If, and only if, the signal carries a realistic event implication, an `Opportunity` is created — always labelled `INFERENCE` or `PREDICTION`, never `FACT` unless the source announces a confirmed event. |
| CONTACT | `services/contacts.py` | Contacts are attached from contact sources that carry a `source_url`. Contacts are never invented. |
| SCORE | `scoring/` | Deterministic, configurable, conservative. See `SCORING.md`. |
| TOP 50 | `services/top50.py` | Score ≥ 70 qualifies; the highest 50 are the Top 50. Fewer than 50 qualifiers means a shorter list — never padding. |

## Division of responsibility: AI vs. deterministic code

This split is deliberate and load-bearing.

**AI extracts and reasons.** It reads unstructured source text and returns
structured evidence: what company, what kind of signal, whether an event is
plausible, which department would own it, why it matters now, what PARADIGM could
sell. It is also asked for its own `event_probability` and `commercial_value`
estimates.

**Deterministic code scores and ranks.** The final `OPPORTUNITY_SCORE` is computed
in `scoring/`, from named factors, using configurable weights. The AI's own
estimates enter as *one weighted factor among many*, not as the answer. This keeps
the ranking reproducible, auditable, and tunable without prompt archaeology.

Every AI response is schema-validated against a Pydantic model. A response that
does not validate is discarded and logged — it never reaches the database.

## Truth labelling

Section 6 of the product spec forbids presenting a predicted event as confirmed,
so the distinction is carried in the data model, not just in prose:

- `Signal.evidence_level` — `FACT` for what a source actually reports, `INFERENCE`
  where the system read between the lines.
- `Opportunity.assertion_level` — `PREDICTION` by default. Promoted to `INFERENCE`
  when the signal strongly implies corporate activity. Only ever `FACT` when the
  source itself announces a confirmed event (a conference, exhibition, seminar or
  workshop) *and* the source is official.

The API returns these fields and the UI renders them, so an Account Manager can
never mistake a prediction for a booking.

## Source adapters

`sources/base.py` defines one small contract:

```python
class SourceAdapter(ABC):
    key: str
    source_type: SourceType
    def fetch(self, since: datetime | None) -> Iterable[RawDocument]: ...
```

Two adapters ship in V1, both real:

- `RssSourceAdapter` — any RSS/Atom feed: company newsrooms, business press,
  industry press, event listings. Which feeds exist is *configuration*
  (`config/sources.json`), not code.
- `JsonlFileSourceAdapter` — reads newline-delimited JSON documents from disk, for
  manual and analyst-supplied material.

The spec's source *categories* (CompanySource, GovernmentSource, NewsSource,
ProcurementSource, EventSource) are modelled as the `SourceType` enum rather than
as five near-identical classes, because they differ in trust tier and provenance,
not in fetch mechanics. Adding a genuinely different mechanism (an HTML scraper, a
tender portal API) means one new class and one registry entry; the pipeline does
not change.

Government and procurement portals are deliberately **not** faked in V1. They are
high-value and are listed in `ROADMAP.md`; each needs its access terms, rate
limits and redistribution rights verified before it is wired in.

## Deduplication

Every entity has an explicit dedupe strategy backed by a database constraint, not
just application logic — see `DATA_MODEL.md`.

## Configuration

All tunable behaviour lives in `backend/app/config.py`, loaded from environment
variables with documented defaults: sectors, scoring weights, the qualifying
threshold, `TOP_N`, conservatism exponent, decay constants, ingestion limits. No
magic numbers in the scoring code.

## What is intentionally absent

Outreach sending, CRM pipeline management, multi-country support, a queue, a
warehouse, and per-source bespoke scrapers. Each would cost V1 focus and can be
added behind the existing seams.
