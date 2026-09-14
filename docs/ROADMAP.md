# ROADMAP

## V1 — shipped in this repository

- Modular-monolith foundation: FastAPI, PostgreSQL, Alembic, Docker Compose,
  configuration, structured logging, health checks, pytest.
- Five-table schema with real constraints, indexes and deduplication.
- Source adapter framework with two working adapters (RSS/Atom, local JSONL) and a
  JSON source registry.
- AI extraction behind a provider abstraction, schema-validated, with a
  deterministic non-AI extractor for offline development and tests.
- Deterministic, fully configurable scoring engine: event probability, commercial
  value, contact quality, timing, evidence quality, decay.
- Top 50 selection with a hard 70-point floor and no padding.
- Daily brief API: new, upgraded, downgraded, expired, current Top 50.
- Read-only Next.js Top 50 UI with sector / score / status / type / date filters.

## V1.1 — the obvious next increments

1. **Government and procurement sources.** The highest-value signals in Egypt are
   public tenders and state project announcements. Deliberately not faked in V1.
   Each candidate portal needs its access method, rate limits, terms of use and
   redistribution rights confirmed before a `GOVERNMENT` or `PROCUREMENT` adapter
   is written. The `SourceType` tiers and the adapter contract are already in place.
2. **Contact discovery sources.** V1 accepts contacts through an explicit ingestion
   endpoint that requires a `source_url`; it does not go looking for people. A
   compliant contact source (public company leadership pages, official press
   contacts) is the next adapter. Nothing that would require synthesising an
   address belongs here.
3. **Email verification.** `email_status` already distinguishes `VERIFIED` from
   `PUBLIC` and `INFERRED`. An actual SMTP/MX verification step is what earns a row
   the `VERIFIED` label; until that exists, nothing is written as verified.
4. **Delivery.** The daily brief is exposed as data. Telegram and email delivery are
   a thin adapter over `services/brief.py` plus a cron entry.
5. **Company enrichment.** `size_band` and `event_potential_score` are populated
   from extraction today. A dedicated enrichment pass (official registry data,
   headcount, past event footprint) would improve both scoring inputs materially.

## V2 — once V1 is earning its keep

- **Scoring calibration from outcomes.** Once `WON` / `LOST` statuses have
  accumulated, fit the weights against real conversions instead of choosing them.
  The engine is already deterministic and configurable for exactly this.
- **Arabic-language sources.** Egyptian business press and government publishing
  are substantially Arabic. This affects normalization (diacritics are already
  stripped), extraction prompts and company-name matching.
- **Signal clustering.** Several sources reporting one event should become one
  signal with corroboration, rather than N near-duplicate signals. The
  `dedupe_key` and corroboration scoring are the groundwork.
- **Account-level view.** Company-level rollups across signals, for account
  planning rather than opportunity chasing.
- **Light CRM write-back.** Push a qualified opportunity into whatever PARADIGM
  actually uses. Still not a CRM replacement.

## Explicitly out of scope

| Not building | Why |
|---|---|
| Automated outreach | Spec §15. The system recommends an action; a human takes it. |
| Multi-country architecture | Spec §4. Egypt only in V1; no premature abstraction. |
| Kubernetes, microservices, queues, warehouse | Spec §31. A monolith and a cron entry are sufficient at this volume. |
| Hundreds of bespoke scrapers | Spec §25. A small number of reliable sources beats broad, brittle coverage. |
| Generic contact database | Spec §1. Contacts exist to serve an opportunity, not as an asset in themselves. |
