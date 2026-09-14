# PARADIGM INTELLIGENCE

AI-powered B2B sales intelligence for **PARADIGM**, an event management company
operating in Egypt.

## What it does

One job:

> **Find the 50 corporate sales opportunities most likely to generate event
> business for PARADIGM.**

It reads public sources, drops the noise, detects recent business signals, infers
whether each implies a realistic corporate event, identifies the people who own
that spend, scores the opportunity deterministically, and maintains a live ranked
Top 50.

```
SOURCE → RELEVANCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE → TOP 50
```

An Account Manager opens it and sees, for each opportunity: who to contact, why
now, what happened, what event could result, what PARADIGM could sell, when to
approach, and how strong it is.

It is **not** a CRM, **not** a scraper, and **not** a contact database.

## Principles

- **Quality over volume.** Only opportunities scoring 70+ qualify. If 17 qualify,
  the Top 50 shows 17 — empty slots are never padded.
- **Facts are labelled.** Every opportunity carries an `assertion_level` of `FACT`,
  `INFERENCE` or `PREDICTION`, plus three separate `fact` / `inference` /
  `prediction` fields. A predicted event is never presented as confirmed.
- **Nothing is invented.** No emails, phone numbers, LinkedIn profiles, job titles,
  companies, relationships or budgets are ever synthesised. Missing evidence is
  `UNKNOWN`, and `UNKNOWN` always scores below `MEDIUM`.
- **AI reasons, code scores.** AI turns prose into structured evidence. The ranking
  is deterministic, weighted and configurable — reproducible and auditable. The
  model's own estimate is one factor at weight 0.10.
- **Real and test data never mix.** Every source carries `AUTOMATED`, `ANALYST` or
  `TEST` provenance, and the API excludes `TEST` by default.
- **Public information only.** Contacts are professional business contacts from
  public pages, each with a `source_url` and an explicit `email_status`.

## Quick start

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, and API_KEY if not local
docker compose up -d --build  # postgres + api + web
```

- Web: <http://localhost:3000>
- API: <http://localhost:8000> — interactive docs at `/docs`
- Health: `/health/live`, `/health/ready`

Migrations run automatically on API start.

### Local development without Docker

```bash
make venv                     # virtualenv + editable install
export DATABASE_URL=postgresql+psycopg://paradigm:paradigm@127.0.0.1:5432/paradigm
make migrate
uvicorn app.main:app --app-dir backend --reload
```

```bash
cd frontend && npm install && npm run dev
```

## Running the pipeline

```bash
python -m app.cli ingest                      # fetch sources, filter, extract, score
python -m app.cli ingest --source sis-egypt    # one source
python -m app.cli discover-contacts            # read public contact pages
python -m app.cli cycle                        # ingest + contacts + decay
python -m app.cli rescore                      # re-apply decay only
python -m app.cli brief                        # today's brief as JSON
python -m app.cli sources                      # list configured sources
python -m app.cli status                       # config, counts, provenance split
```

Recurring refresh is either a cron entry calling `cycle`:

```cron
0 5 * * *  cd /srv/paradigm && python -m app.cli cycle >> /var/log/paradigm/cycle.log 2>&1
```

…or the in-process scheduler (`SCHEDULER_ENABLED=true`,
`SCHEDULER_INTERVAL_HOURS=6`). Both run the same function; pick one.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/opportunities/top50` | the Top 50, filtered, sorted, searchable |
| `GET` | `/api/v1/opportunities` | all opportunities, paginated |
| `GET` | `/api/v1/opportunities/{id}` | full detail with company, signal, source, all contacts |
| `PATCH` | `/api/v1/opportunities/{id}` | update status (the only mutable field) |
| `GET` | `/api/v1/companies` · `/{id}` | company list and profile |
| `GET` | `/api/v1/companies/sectors` | configured sectors |
| `GET` | `/api/v1/brief/daily` | new / upgraded / downgraded / expired / current Top 50 |
| `POST` | `/api/v1/ingest/run` | run configured source adapters |
| `POST` | `/api/v1/ingest/documents` | submit raw documents |
| `POST` | `/api/v1/ingest/signals` | submit an analyst-verified signal (`source_url` required) |
| `POST` | `/api/v1/ingest/contacts` | submit public contacts (`source_url` required) |
| `POST` | `/api/v1/ingest/contacts/discover` | run configured contact sources |
| `POST` | `/api/v1/maintenance/cycle` | run one full refresh now |
| `POST` | `/api/v1/maintenance/rescore` | re-apply decay |
| `GET` | `/api/v1/maintenance/scheduler` | scheduler status and last cycle |

Query parameters on the opportunity endpoints: `sector`, `min_score`, `max_score`,
`status`, `type`, `classification`, `date_from`, `date_to`, `search`, `sort`,
`order`, `include_test`.

## Access control

`/api/v1` requires `API_KEY`, sent as `X-API-Key` or `Authorization: Bearer`.
Health probes are always open. If `API_KEY` is unset the API is open — allowed
under `APP_ENV=development`, and **refused** otherwise, so it cannot become the
silent production default. The frontend calls the API server-side, so the key is
never sent to a browser.

## Configuring sources

`config/sources.json` — data, not code. Each entry sets its adapter, trust tier,
priority, rate limit, document cap and adapter options.

**No source is enabled by default, on purpose.** The file ships eight real,
curated Egyptian and regional candidates, all disabled, because the spec permits
marking a source active only once it demonstrably works — and this repository was
built in an environment with no outbound access to public sites, so none of those
URLs has been confirmed. The file documents the four-step check to enable one.

## AI provider

`AI_PROVIDER=anthropic` uses the Claude Messages API and requires
`ANTHROPIC_API_KEY`; the tool schema is generated from the Pydantic model so the
output contract and the validation contract cannot drift. Responses that fail
validation are discarded and logged, never partially salvaged. A missing key is
logged as an error at startup rather than silently producing nothing.

`AI_PROVIDER=rule_based` is a deterministic keyword extractor with no network
calls, for tests and offline development. It is **not** an AI stand-in: it performs
no entity recognition, reports no company without an explicit hint, offers no
probability estimate, caps its confidence at 0.45, and stamps `extractor:
rule_based` on everything it produces. Do not rank production opportunities on it.

## Tests

```bash
make test-unit    # 274 tests, no database required
make test         # 408 tests, adds integration tests against real PostgreSQL
make lint
```

Integration tests skip cleanly when `TEST_DATABASE_URL` is unset, so `pytest` is
always runnable.

## Repository layout

```
backend/
  app/
    api/        HTTP routes + access control
    domain/     enums and controlled vocabularies
    models/     SQLAlchemy tables (five)
    schemas/    Pydantic request/response models
    services/   pipeline, relevance, normalize, dedupe, brief, rescore, scheduler
    sources/    adapter framework, FetchClient, RSS / JSONL / contact pages
    ai/         extraction provider abstraction
    scoring/    the deterministic score engine
  alembic/      migrations
  tests/
frontend/       Next.js: Top 50, opportunity detail, company profile, daily brief
config/         source registry
data/real/      real analyst-submitted signals, with their citations
docs/           ARCHITECTURE · DATA_MODEL · SCORING · ROADMAP
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — shape, pipeline, AI/code split, provenance
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — the five tables, constraints, normalization, migrations
- [`docs/SCORING.md`](docs/SCORING.md) — every weight and constant, when scores recompute, how to tune
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — what is implemented, the known gaps and why, what comes next

`ROADMAP.md` is the honest inventory: it states plainly which parts have been run
against real data and which have not.

## Data handling

Only publicly available professional and business information is collected.
Authentication, paywalls and access controls are never bypassed; rate limits and
`Retry-After` are respected. Contacts are stored with provenance and an explicit
`email_status`, and a `VERIFIED` claim is rejected at the API boundary because V1
has no verification step. The system does not send outreach — it recommends an
action for a human to take.
