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

It also answers the question that decides what to actually say: **can this still be
won?** An event two weeks away is usually already contracted, and a past event is not
an opportunity at all. Every opportunity is classed `IMMEDIATE` (bid for it),
`FUTURE_ACCOUNT` (build the relationship for the next one) or `HISTORICAL` (account
research only) — and a past event never appears in the ranking as if it were still
upcoming. Each company profile then names the department to approach *for that kind
of event*, every public route on record, and what was last said to them.

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
  public pages, each with a `source_url` and an explicit `email_status`. A person and
  an official department inbox are stored as different things (`contact_kind`) and can
  never read as each other. Contact-data brokers are not a source of provenance, and
  no address is ever derived from a name pattern.

## Quick start

### With Docker

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, and API_KEY if not local
docker compose up -d --build  # postgres + api + web
docker compose logs -f api
```

- Web: <http://localhost:3000>
- API: <http://localhost:8000> — interactive docs at `/docs`
- Health: `/health/live`, `/health/ready`

Migrations run automatically on API start.

> **The Docker build has not been verified.** It was written carefully but never
> built: the development environment has a `docker` CLI and no daemon (no
> `/var/run/docker.sock`, no podman). `docker compose config` validates, and the
> two steps most likely to fail inside the images were checked directly —
> `pip install ./backend` from `pyproject.toml` alone, and the Next.js
> `standalone/server.js` output the runtime stage copies. Treat the first
> `docker compose up --build` as unproven. The path below **is** verified.

### Without Docker (this is the verified path)

```bash
# 1. PostgreSQL
createdb paradigm

# 2. Backend
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/paradigm
export APP_ENV=development
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Frontend, in a second shell
cd frontend && npm install && npm run build
API_BASE_URL=http://127.0.0.1:8000 npm run start -- --port 3000

# 4. Check what your network can actually reach
.venv/bin/python -m app.cli check-sources
```

Then open <http://localhost:3000>.

## Running the pipeline

```bash
python -m app.cli check-sources                # probe sources: which work from HERE
python -m app.cli ingest                       # fetch sources, filter, extract, score
python -m app.cli ingest --source sis-egypt    # one source
python -m app.cli discover-contacts            # read public contact pages
python -m app.cli cycle                        # ingest + contacts + decay
python -m app.cli rescore                      # re-apply decay only
python -m app.cli brief                        # today's brief as JSON
python -m app.cli sources                      # list configured sources
python -m app.cli status                       # config, counts, provenance split
```

**Start with `check-sources`.** It probes every configured source and prints a
verdict and advice for each, and it distinguishes the two failures that need
completely different fixes:

| Verdict | Meaning |
|---|---|
| `READY_TO_ENABLE` | fetched and parsed. Check its terms of use, then enable it. |
| `ACTIVE` | working and already enabled. |
| `BLOCKED_BY_EGRESS` | **your network refused the connection.** The source may be fine; you cannot reach it from here. |
| `UNREACHABLE` | the connection was allowed and the publisher did not serve it. |
| `NOT_USABLE` | it answered, but not with a usable feed. |
| `EMPTY` | a valid feed with no entries. |
| `MISCONFIGURED` | the registry entry itself is wrong. |

It exits non-zero when nothing is usable, so it can gate a deploy. `--json` makes
it pipeable (all CLI diagnostics go to stderr, data to stdout).

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
| `GET` | `/api/v1/companies` · `/{id}` | company list and contact-first profile |
| `GET` | `/api/v1/companies/sectors` | configured sectors |
| `GET` | `/api/v1/companies/{id}/outreach` | outreach history for a company |
| `POST` | `/api/v1/companies/{id}/outreach` | log an interaction |
| `GET` | `/api/v1/outreach/follow-ups` | who is owed a next step (`as_of` looks ahead) |
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
`order`, `include_test`, `timing`, `include_historical`.

`timing` takes `IMMEDIATE`, `FUTURE_ACCOUNT` or `HISTORICAL`. Past events are
excluded from the ranking by default — see `docs/SCORING.md` §5a.

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
curated Egyptian and regional candidates, all disabled, because a source may only
be marked active once it demonstrably works — and this repository was built in an
environment whose egress proxy answers 403 to CONNECT for every one of those
domains, so none has been verified either way.

Run `python -m app.cli check-sources` from a host with outbound HTTPS. Anything it
reports `READY_TO_ENABLE` has been fetched and parsed; confirm the publisher's
terms permit automated access, then set `enabled: true`.

## Current real data

`data/real/` holds **18 real, source-backed signals** covering 17 Egyptian companies
in Telecommunications, Industrial, Real Estate, Engineering, Manufacturing, Energy,
Oil & Gas, Pharma, Banking and Fintech. Load them with:

```bash
make load-real-data     # or: python scripts/load_real_data.py --base-url ...
```

That produces 18 opportunities, of which three qualify for the Top 50. The script is
idempotent and the dataset is the repository's, so the state is reproducible rather
than something that happened once in a container.

Every entry carries a real public `source_url`, a real publication date where the
source gave one, and `ANALYST` provenance — they were entered through
`POST /api/v1/ingest/signals` with their citations, because automated ingestion is
blocked by the egress policy described above. They are **not** labelled as automated
extraction, and the UI shows the provenance on every row.

Event dates are present only where the source publishes one (three of the eighteen:
Egypt Energy 12–14 Oct, Mediterranean Offshore Conference 20–22 Oct, Cityscape Egypt
30 Sep – 3 Oct). Nothing infers a date, so the timing classes on the rest are derived
from the reported window and say so.

Contacts: **four real department contact routes**, each evidenced by an official page
on the company's own website, all `contact_kind: DEPARTMENT_ROUTE` and all with
`email_status: UNKNOWN` because no address could be obtained from this environment.
No named individuals and no email addresses — see `docs/ROADMAP.md` for exactly why,
and what unblocks it. The profile displays that as UNKNOWN rather than filling the
space.

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
make test-unit    # 384 tests, no database required
make test         # 562 tests, adds integration tests against real PostgreSQL
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
    models/     SQLAlchemy tables (six)
    schemas/    Pydantic request/response models
    services/   pipeline, relevance, normalize, dedupe, brief, rescore,
                scheduler, outreach, company_profile
    sources/    adapter framework, FetchClient, RSS / JSONL / contact pages
    ai/         extraction provider abstraction
    scoring/    the deterministic score engine, event timing, contact routing
  alembic/      migrations
  tests/
frontend/       Next.js: Top 50, opportunity detail, company profile, brief,
                follow-ups
config/         source registry
data/real/      real analyst-submitted signals and contact routes, with citations
scripts/        load_real_data.py — loads data/real through the analyst intake API
docs/           ARCHITECTURE · DATA_MODEL · SCORING · ROADMAP
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — shape, pipeline, AI/code split, provenance
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — the six tables, constraints, normalization, migrations
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
