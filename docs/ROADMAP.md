# ROADMAP

## Implemented and verified

Everything here is in the repository, exercised by the test suite, and — where the
build environment allowed it — run against real data.

**Foundation.** FastAPI, PostgreSQL, two Alembic revisions (both verified to run
forward and backward with zero model drift), Docker Compose (config validated; see
the gap below), configuration with startup validation, structured logging, health
and readiness probes, 435 tests.

**Data model.** Five tables, real constraints and indexes, explicit deduplication
for companies, contacts, signals, opportunities and sources. Provenance
(`AUTOMATED` / `ANALYST` / `TEST`) and parent/subsidiary links.

**Ingestion.** Source adapter framework over a shared `FetchClient` with timeouts,
bounded retries, per-host rate limiting, `Retry-After`, a response byte cap and a
real User-Agent. Three working adapters: RSS/Atom, local JSONL, and public
contact-page parsing. A JSON source registry with priority and per-source limits.

**Relevance gate.** A deterministic pre-extraction filter, so noise never reaches
the expensive step. Includes light stemming, added after a live run showed that
matching singular terms against real copy ("nine factories opened") silently
dropped genuine signals.

**AI extraction.** Provider abstraction, live Claude Messages API implementation
with a tool schema generated from the Pydantic model, bounded retries, and hard
discard of anything that fails validation. A deterministic non-AI extractor for
offline development, labelled as such and capped at 0.45 confidence.

**Scoring.** Deterministic and fully configurable: event probability, commercial
value, contact quality, timing, evidence quality, decay. Three separate brakes on
event probability. Top 50 selection with a hard floor and no padding.

**Contact intelligence.** Discovery from public company pages, department and
seniority classification, damped roll-up into the opportunity score, and
re-scoring of affected companies after discovery.

**Interface.** Four pages — Top 50, opportunity detail, company profile, daily
brief — with filtering by sector, score, status, type and date, sorting on eight
fields, and search across company name, contact name and contact email.

**Source preflight.** `python -m app.cli check-sources` (and
`GET /api/v1/sources/health`) probes every configured source and reports a verdict
and advice for each. It distinguishes an egress-policy block from a source that is
genuinely down — the two need completely different fixes, and conflating them
wastes an afternoon. One attempt per source, no retries (a policy denial must not
be retried), so it answers in seconds. Exits non-zero when nothing is usable.

**Operations.** A background scheduler (off by default) and a CLI covering
`check-sources`, `ingest`, `discover-contacts`, `cycle`, `rescore`, `brief`,
`sources`, `status`. All CLI diagnostics go to stderr so every command is pipeable.
API-key access control on `/api/v1`, refused open outside development.

## Known gaps, and why

### 1. No automated source can run from the build environment — measured, not assumed

The egress proxy in the environment this was built in answers **403 to CONNECT**
for every news, government and business-publication host. The boundary was mapped
directly:

| Reachable | Blocked (403 CONNECT) |
|---|---|
| `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `jsr.io`, `index.crates.io`, `proxy.golang.org` | `sis.gov.eg`, `mcit.gov.eg`, `dailynewsegypt.com`, `english.ahram.org.eg`, `egyptoil-gas.com`, `zawya.com` |
| `api.anthropic.com` | `feeds.bbci.co.uk`, `news.google.com`, `reuters.com` |
| `github.com`, `raw.githubusercontent.com`, `api.github.com` | every other public host tested |
| `localhost` and private ranges | |

Only developer infrastructure is permitted. `check-sources` reports all seven
network sources as `BLOCKED_BY_EGRESS`, which is an *unverified* state, not a
failed one — the sources may be perfectly healthy.

**Exact change required to unblock it:** run the ingestion where outbound HTTPS to
those domains is permitted. Either
(a) run the backend on a normal host or server — nothing in the code needs to
change, just `python -m app.cli check-sources` then `ingest`; or
(b) if it must stay in a sandboxed environment, have the source domains added to
that environment's egress allowlist. For Claude Code on the web the network policy
is chosen when the environment is created; see
<https://code.claude.com/docs/en/claude-code-on-the-web>.

Routing around the proxy was not attempted: the proxy's own documentation states
that a 403 is an organisation policy denial and must be reported rather than
worked around.

**No source has therefore been enabled**, because enabling one on the strength of
an unverified probe is exactly what the rule forbids.

### 2. No named contacts, and no email addresses

Four real **department contact routes** exist, each evidenced by an official page
on the company's own website (Elsewedy Electric's media and contact pages, Egypt
Energy's exhibitor page, MOC's site). All carry `email_status: UNKNOWN`, which the
UI displays explicitly.

No named individuals and no addresses, for two separate reasons:

- **Addresses:** the official contact pages exist but cannot be fetched (same
  egress block), and search results do not expose the addresses printed on them.
  Deriving an address from a name pattern is forbidden, so the answer is `UNKNOWN`.
- **Names:** searching did surface named marketing and communications executives —
  but only via contact-data brokers whose product *is* aggregated personal contact
  data. Citing those as provenance would breach the rule that only publicly
  available professional information from legitimate sources is used, so they were
  discarded rather than recorded. An Investor Relations contact found on a genuinely
  official page was also discarded: IR has no relationship to event spending, and
  collecting contacts with no logical link to the opportunity is forbidden.

This is why most real opportunities sit below the 70-point threshold: a department
route scores about 45, so `contact_quality` contributes roughly 9 of the 20 points
available. That is the scoring working as designed, and it is a fair measure of how
much a real named decision-maker is worth.

**What unblocks it:** egress. `ContactPageAdapter` is implemented and tested, and
the real leadership-page URLs are already in the registry as templates — once those
pages are reachable, `python -m app.cli discover-contacts` reads them.

### 3. The Docker build is unverified

The development environment has a `docker` CLI and **no daemon** — no
`/var/run/docker.sock`, no podman, no nerdctl. So the images have never been built
and the claim "Docker Compose works" is not made.

What *was* verified without a daemon: `docker compose config` validates and
interpolates correctly, `pip install ./backend` succeeds from `pyproject.toml`
alone in a clean virtualenv (18 routes, console script working), and the Next.js
`standalone/server.js` output that the runtime stage copies exists. The non-Docker
path in `README.md` is fully verified end to end.

### 4. Government and procurement adapters are not written

These are the highest-value sources for Egyptian corporate signals and the first
thing to build next. They are deliberately absent rather than stubbed: most publish
HTML rather than feeds and need purpose-built parsers, and writing those against
endpoints nobody has been able to read would produce exactly the fake integration
the brief forbids.

## Next increments

1. **Verify and enable the shipped sources.** From a host with egress, run
   `python -m app.cli check-sources`, then enable everything it reports
   `READY_TO_ENABLE` once its terms of use are confirmed. This is the single
   highest-value task and needs no new code.
2. **Government and procurement adapters.** One class each, registered in
   `ADAPTERS`. The `SourceType` trust tiers and the adapter contract are already in
   place; the pipeline does not change.
3. **Contact sources at scale.** The `ContactPageAdapter` works; what it needs is a
   curated list of real leadership and press-contact pages per target company.
4. **Email verification.** `email_status` already separates `VERIFIED` from
   `PUBLIC` and `INFERRED`, and the API refuses a `VERIFIED` claim outright. An
   actual MX/SMTP verification step is what would earn that label.
5. **Delivery.** The daily brief is exposed as data and as a page. Telegram or
   email is a thin adapter over `services/brief.py` plus a cron entry.
6. **Company enrichment.** `size_band` and `event_potential_score` come from
   extraction today. A dedicated enrichment pass would improve both scoring inputs
   materially.

## V2 — once V1 is earning its keep

- **Calibrate the weights against outcomes.** Once `WON` / `LOST` has accumulated,
  fit the weights to real conversions instead of choosing them. The engine is
  deterministic and configurable for exactly this.
- **Arabic-language sources.** Much Egyptian business and government publishing is
  Arabic. Affects normalization (diacritics are already stripped), extraction
  prompts and company-name matching.
- **Signal clustering.** Several outlets reporting one event should become one
  signal with corroboration rather than N near-duplicates. The `dedupe_key` and
  corroboration scoring are the groundwork; today deduplication is per company and
  title, so differently-headlined coverage of one event still produces two signals.
- **Account-level view.** Company rollups for account planning rather than
  opportunity chasing.
- **Light CRM write-back.** Push a qualified opportunity into whatever PARADIGM
  actually uses. Still not a CRM replacement.

## Explicitly out of scope

| Not building | Why |
|---|---|
| Automated outreach | Spec §21. The system prepares a recommendation; a human acts. |
| Multi-country architecture | Spec §6. Egypt only; no premature abstraction. |
| Kubernetes, microservices, queues, warehouse | Spec §42. A monolith and a cron entry suffice at this volume. |
| Hundreds of bespoke scrapers | Spec §7. A few reliable sources beat broad, brittle coverage. |
| Generic contact database | Spec §3. Contacts serve an opportunity; they are not the asset. |
| CRM / marketing automation integrations | Spec §42. |
