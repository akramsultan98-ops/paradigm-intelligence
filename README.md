# PARADIGM INTELLIGENCE

AI-powered B2B sales intelligence for **PARADIGM**, an event management company
operating in Egypt.

## What it does

One job:

> **Find the 50 corporate sales opportunities most likely to generate event
> business for PARADIGM.**

It reads public sources, detects recent business signals, infers whether each
signal implies a realistic corporate event, identifies the people who would own
that spend, scores the opportunity, and maintains a live ranked Top 50.

```
SOURCE → SIGNAL → COMPANY → EVENT OPPORTUNITY → CONTACT → SCORE → TOP 50
```

It is **not** a generic scraper, **not** a contact database, and **not** a CRM
replacement. It is a corporate event opportunity intelligence engine.

## Principles

- **Quality over volume.** Only opportunities scoring 70+ qualify. If 23 qualify,
  the Top 50 has 23 rows — empty slots are never padded with weak leads.
- **Facts are labelled.** Every opportunity carries an `assertion_level` of `FACT`,
  `INFERENCE` or `PREDICTION`. A predicted event is never presented as confirmed.
- **Nothing is invented.** No emails, phone numbers, LinkedIn profiles, job titles,
  companies, relationships or budgets are ever synthesised. Missing evidence is
  recorded as `UNKNOWN`, and `UNKNOWN` always scores below `MEDIUM`.
- **AI reasons, code scores.** AI turns prose into structured evidence. The ranking
  itself is deterministic, weighted and configurable, so it is reproducible and
  auditable.
- **Public information only.** Contacts are professional business contacts drawn
  from public sources, each with a `source_url`.

## Quick start

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD
docker compose up -d --build  # postgres + api + web
```

- API: <http://localhost:8000> — docs at `/docs`
- Web: <http://localhost:3000>
- Health: `/health/live`, `/health/ready`

Migrations run automatically on API start. To run them by hand:

```bash
docker compose exec api alembic upgrade head
```

### Local development without Docker

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e 'backend[dev]'

export DATABASE_URL=postgresql+psycopg://paradigm:paradigm@127.0.0.1:5432/paradigm
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --app-dir backend --reload
```

```bash
cd frontend && npm install && npm run dev
```

## Running the pipeline

The CLI is the scheduling surface — point cron at it.

```bash
python -m app.cli ingest              # fetch configured sources, extract, score
python -m app.cli ingest --source egypt-business-news
python -m app.cli rescore             # re-apply decay, refresh the Top 50
python -m app.cli brief               # print today's daily brief as JSON
python -m app.cli sources             # list configured sources
```

A sensible crontab:

```cron
0 5 * * *  cd /srv/paradigm && python -m app.cli ingest  >> /var/log/paradigm/ingest.log 2>&1
30 5 * * * cd /srv/paradigm && python -m app.cli rescore >> /var/log/paradigm/rescore.log 2>&1
```

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/opportunities/top50` | the Top 50, filterable |
| `GET` | `/api/v1/opportunities` | all opportunities, paginated |
| `GET` | `/api/v1/opportunities/{id}` | full detail with company, signal, source, contacts |
| `PATCH` | `/api/v1/opportunities/{id}` | update status only |
| `GET` | `/api/v1/companies` · `/{id}` | companies |
| `GET` | `/api/v1/brief/daily` | new / upgraded / downgraded / expired / current Top 50 |
| `POST` | `/api/v1/ingest/run` | run configured source adapters |
| `POST` | `/api/v1/ingest/documents` | submit raw documents directly |
| `POST` | `/api/v1/ingest/contacts` | submit publicly-sourced contacts (`source_url` required) |
| `POST` | `/api/v1/maintenance/rescore` | re-apply decay |

Filters on the opportunity endpoints: `sector`, `min_score`, `max_score`, `status`,
`type`, `classification`, `date_from`, `date_to`.

## Configuring sources

`config/sources.json` — data, not code:

```json
{
  "sources": [
    {
      "key": "example-newsroom",
      "adapter": "rss",
      "source_type": "COMPANY",
      "publisher": "Example Corp",
      "enabled": true,
      "confidence": 0.9,
      "options": { "feed_url": "https://example.com/news/rss" }
    }
  ]
}
```

Adapters shipped: `rss` (any RSS/Atom feed) and `jsonl` (local newline-delimited
JSON, for analyst-supplied material). No feeds are enabled by default — the file
ships with commented examples so the repository makes no claim about sources whose
terms have not been checked.

## AI provider

`AI_PROVIDER=anthropic` uses the Claude Messages API and requires
`ANTHROPIC_API_KEY`. Responses are validated against a Pydantic schema; anything
that fails validation is discarded and logged, never stored.

`AI_PROVIDER=rule_based` is a deterministic keyword extractor with no network
calls, used for tests and offline development. It is **not** an AI stand-in and is
labelled as such in its output confidence — do not run production ranking on it.

## Tests

```bash
pytest backend/tests -q                  # unit tests, no database needed
TEST_DATABASE_URL=postgresql+psycopg://paradigm:paradigm@127.0.0.1:5432/paradigm_test \
  pytest backend/tests -q                # adds integration tests
```

Integration tests skip themselves cleanly when `TEST_DATABASE_URL` is unset.

## Repository layout

```
backend/
  app/
    api/        HTTP routes
    domain/     enums and value objects
    models/     SQLAlchemy tables
    schemas/    Pydantic request/response models
    services/   pipeline, normalization, dedupe, brief, rescore
    sources/    source adapter framework
    ai/         extraction provider abstraction
    scoring/    the deterministic score engine
  alembic/      migrations
  tests/
frontend/       Next.js Top 50 view
config/         source registry
docs/           ARCHITECTURE · DATA_MODEL · SCORING · ROADMAP
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — shape, pipeline, AI/code split
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — the five tables, constraints, normalization
- [`docs/SCORING.md`](docs/SCORING.md) — every weight and constant, and how to tune
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — what comes next and what is out of scope

## Data handling

Only publicly available professional and business information is collected.
Contacts are stored with provenance and an explicit `email_status`; an inferred
address is never recorded as verified. The system does not send outreach — it
recommends an action for a human to take.
