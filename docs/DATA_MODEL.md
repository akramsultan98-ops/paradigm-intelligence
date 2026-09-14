# DATA MODEL

Five tables. That is the whole V1 schema, as required by the product spec.

```
sources ──┬──▶ signals ──▶ opportunities ──┐
          │       │              │         │
          └──▶ contacts ◀────────┘         │
                  │                        │
                  ▼                        ▼
              companies ◀──────────────────┘
```

A sixth table was not added. Score history for the daily brief is carried on the
opportunity row itself (`previous_score`, `previous_classification`,
`score_changed_at`), which is enough to report NEW / UPGRADED / DOWNGRADED /
EXPIRED without an events table.

---

## companies

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | text, not null | as published |
| `normalized_name` | text, **unique**, not null | dedupe key |
| `domain` | text, **unique**, nullable | registrable domain, lowercased |
| `website` | text, nullable | |
| `sector` | text, nullable | validated against configured `SECTORS` |
| `city` | text, nullable | |
| `description` | text, nullable | |
| `size_band` | enum, nullable | `SMALL` … `ENTERPRISE`; feeds scoring |
| `event_potential_score` | int 0–100, nullable | standing company-level potential |
| `created_at` / `updated_at` | timestamptz | |

Indexes: `sector`, `normalized_name` (unique), `domain` (unique).

`size_band` is beyond the spec minimum and is justified: both event probability and
commercial value depend on company scale, and re-deriving it per signal would be
both slower and less stable.

---

## contacts

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `company_id` | UUID FK → companies, not null, `ON DELETE CASCADE` | |
| `name` | text, not null | |
| `normalized_name` | text, not null | dedupe key |
| `job_title` | text, nullable | |
| `department` | enum, not null | `MARKETING` … `UNKNOWN` |
| `email` | text, nullable | |
| `normalized_email` | text, nullable | dedupe key |
| `linkedin_url` | text, nullable | |
| `normalized_linkedin_url` | text, nullable | dedupe key |
| `email_status` | enum, not null | `VERIFIED` / `PUBLIC` / `INFERRED` / `UNKNOWN` |
| `contact_score` | int 0–100, not null | see `SCORING.md` |
| `confidence` | numeric(3,2) 0–1, not null | evidence confidence |
| `source_id` | UUID FK → sources, nullable | provenance |
| `created_at` / `updated_at` | timestamptz | |

Constraints:
- unique `(company_id, normalized_name, department)`
- unique `normalized_email`
- unique `normalized_linkedin_url`
- check `email_status <> 'VERIFIED'` unless the row was set verified by an actual
  verification step — enforced in `services/contacts.py`; an inferred address is
  never stored as `VERIFIED`.

Only publicly available professional information is stored. Emails, phone numbers,
LinkedIn URLs, titles, companies and relationships are never synthesised.

---

## signals

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `company_id` | UUID FK → companies, not null | |
| `type` | enum, not null | `PRODUCT_LAUNCH`, `TENDER`, … , `UNKNOWN` |
| `title` | text, not null | |
| `summary` | text, nullable | |
| `business_impact` | text, nullable | |
| `published_at` | timestamptz, nullable | from the source |
| `source_id` | UUID FK → sources, not null | |
| `confidence` | numeric(3,2) 0–1, not null | |
| `evidence_level` | enum, not null | `FACT` / `INFERENCE` |
| `dedupe_key` | text, **unique**, not null | `sha256(company_id \| type \| normalized title)` |
| `created_at` | timestamptz | |

Indexes: `(company_id, published_at DESC)`, `type`.

---

## opportunities

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `company_id` | UUID FK → companies, not null | |
| `signal_id` | UUID FK → signals, not null | |
| `primary_contact_id` | UUID FK → contacts, nullable | best contact at scoring time |
| `type` | enum, not null | `PRODUCT_LAUNCH`, `VIP_DINNER`, … |
| `assertion_level` | enum, not null | `FACT` / `INFERENCE` / `PREDICTION` |
| `event_probability` | int 0–100, not null | |
| `commercial_value` | int 0–100, not null | |
| `commercial_value_band` | enum, not null | `LOW` / `MEDIUM` / `HIGH` / `VERY_HIGH` |
| `contact_quality` | int 0–100, not null | damped, see scoring |
| `timing_score` | int 0–100, not null | |
| `evidence_score` | int 0–100, not null | |
| `base_score` | int 0–100, not null | weighted score before decay |
| `score` | int 0–100, not null | `base_score × decay_factor` |
| `decay_factor` | numeric(4,3), not null | |
| `classification` | enum, not null | `EXCEPTIONAL` … `NOT_ELIGIBLE` |
| `why_now` | text, not null | required on every qualified opportunity |
| `sales_angle` | text, not null | required on every qualified opportunity |
| `recommended_action` | enum, not null | |
| `recommended_services` | jsonb, not null default `[]` | subset of PARADIGM's catalogue |
| `opportunity_window` | enum, not null | `DAYS_0_14` … `UNKNOWN` |
| `window_ends_on` | date, nullable | used for missed-window decay |
| `recommended_contact_timing` | enum, not null | |
| `status` | enum, not null | `NEW` / `QUALIFIED` / `CONTACTED` / `MEETING` / `WON` / `LOST` / `NURTURE` |
| `previous_score` | int, nullable | for the daily brief |
| `previous_classification` | enum, nullable | for the daily brief |
| `score_changed_at` | timestamptz, nullable | |
| `scored_at` | timestamptz, not null | |
| `created_at` / `updated_at` | timestamptz | |

Constraints and indexes:
- unique `(signal_id, type)` — one opportunity per signal per event type
- index `score DESC` (the Top 50 read path)
- index `status`, `company_id`, `type`, `created_at`

---

## sources

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `url` | text, not null | as fetched |
| `normalized_url` | text, **unique**, not null | tracking params stripped |
| `title` | text, nullable | |
| `source_type` | enum, not null | see trust tiers below |
| `publisher` | text, nullable | |
| `publication_date` | timestamptz, nullable | |
| `confidence` | numeric(3,2) 0–1, not null | |
| `content_hash` | text, **unique**, not null | `sha256` of normalized content |
| `adapter_key` | text, nullable | which adapter produced it |
| `created_at` | timestamptz | |

`source_type` trust tiers, highest first (spec §17):

1. `COMPANY` — official company channels
2. `GOVERNMENT`
3. `PROCUREMENT` — official tender/procurement portals
4. `BUSINESS_PUBLICATION` — reputable business press
5. `INDUSTRY_PUBLICATION`
6. `PUBLIC_PROFILE` — public professional/company pages
7. `EVENT`, `OTHER`

Every important record carries `source_url`, `source_title`, `publication_date` and
`confidence`, reachable from signals, opportunities and contacts via `source_id`.

---

## Normalization rules

Implemented in `backend/app/services/normalize.py` and unit-tested.

| Value | Rule |
|---|---|
| company name | casefold, strip diacritics, drop legal suffixes (`s.a.e.`, `sae`, `llc`, `ltd`, `inc`, `co`, `company`, `group`, `holding`, `for trading` …), collapse whitespace and punctuation |
| domain | lowercase, strip scheme / `www.` / path / port |
| email | lowercase, trim; Gmail-style dot and `+tag` stripping is **not** applied — corporate mailboxes are dot-significant |
| LinkedIn URL | force `https://www.linkedin.com/in/<slug>`, lowercase slug, strip query and trailing slash |
| URL | lowercase host, strip fragment and `utm_*` / `gclid` / `fbclid` params, strip trailing slash |
| content | collapse all whitespace before hashing, so reformatting does not defeat the hash |

## Enum storage

All enums are stored as `VARCHAR` with a `CHECK` constraint (SQLAlchemy
`native_enum=False`) rather than as PostgreSQL `ENUM` types. Adding a value is then
an ordinary constraint change instead of a `ALTER TYPE` migration that cannot run
inside a transaction.
