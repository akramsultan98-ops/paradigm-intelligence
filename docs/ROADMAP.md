# ROADMAP

## Implemented and verified

Everything here is in the repository, exercised by the test suite, and — where the
build environment allowed it — run against real data.

**Foundation.** FastAPI, PostgreSQL, two Alembic revisions (both verified to run
forward and backward with zero model drift), Docker Compose, configuration with
startup validation, structured logging, health and readiness probes, 408 tests.

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

**Operations.** A background scheduler (off by default) and a CLI covering
`ingest`, `discover-contacts`, `cycle`, `rescore`, `brief`, `sources`, `status`.
API-key access control on `/api/v1`, refused open outside development.

## Known gaps, and why

**No source is enabled by default.** `config/sources.json` ships eight real,
curated candidates — all disabled. The spec is explicit that a source may only be
marked active if it actually works, and the build environment has no outbound
network access to public sites, so no feed URL in that file has been confirmed to
resolve, to be a valid feed, or to permit automated access. Enabling one is a
four-step check documented in the file itself.

**No contact data in the live dataset.** Verified public contact information could
not be obtained for the real companies currently in the database, and inventing an
address, a name or a title is forbidden. Every real opportunity therefore scores
`contact_quality = 0`, which is what holds most of them below the 70-point
threshold. That is the honest result, not a bug — and it is a fair demonstration of
how much contact quality is worth. The discovery path itself is implemented and
tested end to end against fixture pages.

**Government and procurement adapters are not written.** These are the
highest-value sources for Egyptian corporate signals and the first thing to build
next. They are deliberately absent rather than stubbed: most publish HTML rather
than feeds and need purpose-built parsers, and writing those against unverified
endpoints would produce exactly the fake integration the brief forbids.

## Next increments

1. **Verify and enable the shipped sources.** In an environment with egress, work
   through `config/sources.json` one entry at a time: fetch, confirm it parses,
   read the terms, set the rate limit, enable. This is the single highest-value
   task and needs no new code.
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
