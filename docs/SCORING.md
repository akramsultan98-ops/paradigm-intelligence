# SCORING

Every number in this document is a default in `backend/app/config.py` and can be
changed with an environment variable. No scoring constant is hard-coded at a call
site.

The engine is **deterministic**. Given the same facts it always produces the same
score, which is what makes the Top 50 defensible to an Account Manager.

---

## 1. OPPORTUNITY_SCORE

```
base_score = 0.35 × EVENT_PROBABILITY
           + 0.25 × COMMERCIAL_VALUE
           + 0.20 × CONTACT_QUALITY
           + 0.10 × TIMING
           + 0.10 × EVIDENCE_QUALITY

score      = round(base_score × decay_factor)
```

Weights are `WEIGHT_EVENT_PROBABILITY`, `WEIGHT_COMMERCIAL_VALUE`,
`WEIGHT_CONTACT_QUALITY`, `WEIGHT_TIMING`, `WEIGHT_EVIDENCE`. They are validated
at startup to sum to 1.0 (±0.001); a bad configuration fails fast rather than
silently skewing the ranking.

### Classification

| Score | Classification |
|---|---|
| 95–100 | `EXCEPTIONAL` |
| 90–94 | `HOT` |
| 85–89 | `VERY_HIGH` |
| 80–84 | `HIGH` |
| 70–79 | `QUALIFIED` |
| < 70 | `NOT_ELIGIBLE` |

---

## 2. EVENT_PROBABILITY (0–100)

A weighted sum of named factors, then deliberately pushed downward.

| Factor | Weight | Source |
|---|---|---|
| signal strength | 0.24 | signal type base table |
| announcement scale | 0.12 | extraction |
| company size | 0.11 | company record / extraction |
| event history | 0.08 | does this company run events? |
| marketing activity | 0.07 | extraction |
| corporate comms activity | 0.05 | extraction |
| customer/partner ecosystem | 0.07 | extraction |
| stakeholder count | 0.05 | extraction |
| executive involvement | 0.06 | extraction |
| timing proximity | 0.05 | derived from the opportunity window |
| AI's own estimate | 0.10 | extraction |

The AI's own estimate is one factor at weight 0.10. It cannot drive the score on
its own — that is the point.

### Signal strength table

| Signal type | Strength |
|---|---|
| `CONFERENCE` | 95 |
| `EXHIBITION` | 92 |
| `PRODUCT_LAUNCH`, `WORKSHOP`, `SEMINAR` | 85 |
| `NEW_FACILITY`, `PROJECT_LAUNCH`, `SPONSORSHIP` | 80 |
| `MARKET_ENTRY`, `TRAINING_PROGRAM` | 78 |
| `JOINT_VENTURE`, `ANNIVERSARY` | 75 |
| `PARTNERSHIP`, `EXPANSION`, `PROJECT_COMPLETION`, `DELEGATION` | 72 |
| `MOU`, `MILESTONE`, `NEW_PROJECT`, `EXECUTIVE_VISIT` | 70 |
| `NEW_CONTRACT` | 68 |
| `INVESTMENT` | 65 |
| `NEW_TECHNOLOGY` | 62 |
| `DIGITAL_TRANSFORMATION` | 60 |
| `CUSTOMER_WIN` | 58 |
| `TENDER` | 55 |
| `PROCUREMENT` | 50 |
| `UNKNOWN` | 20 |

### Ordinal factor scales

| Level | Score |
|---|---|
| `LOW` / `SMALL` | 25 |
| `MEDIUM` | 50–55 |
| `HIGH` / `LARGE` | 75–85 |
| `MAJOR` / `ENTERPRISE` | 100 |
| `UNKNOWN` | 30–35 |

`UNKNOWN` is scored *below* `MEDIUM`, never at the midpoint. Missing evidence must
never help an opportunity.

Booleans: `true` → 85–90, `false` → 25, unknown → 35.
Stakeholder count *n* → `min(100, 20 + 8n)`.

### Conservatism

Three mechanisms make high scores hard to reach:

1. **Power transform** — `p = 100 × (raw / 100) ^ 1.25`
   (`EVENT_PROBABILITY_EXPONENT`). A raw 70 becomes 64; a raw 50 becomes 42. Only a
   near-perfect factor profile stays near 100.
2. **Evidence cap** — `p ≤ 55 + 0.45 × EVIDENCE_QUALITY`. A thinly sourced signal
   cannot exceed 55 no matter how suggestive it reads.
3. **Unconfirmed cap** — `p ≤ 95` (`EVENT_PROBABILITY_CAP_UNCONFIRMED`) unless
   `assertion_level = FACT`, i.e. the source actually announces the event. A
   prediction is never allowed to look like a certainty.

---

## 3. COMMERCIAL_VALUE (0–100)

| Factor | Weight |
|---|---|
| company size | 0.20 |
| expected attendee band | 0.18 |
| production complexity | 0.18 |
| service scope breadth | 0.14 |
| repeat-business potential | 0.10 |
| corporate brand value | 0.10 |
| AI's own estimate | 0.10 |

Attendee bands: `UNDER_50` 25, `FROM_50_TO_200` 50, `FROM_200_TO_500` 75,
`OVER_500` 100, `UNKNOWN` 35.
Service scope breadth from the count *n* of recommended services:
`min(100, 25 + 9n)`.

### Band

| Score | Band |
|---|---|
| ≥ 80 | `VERY_HIGH` |
| 60–79 | `HIGH` |
| 35–59 | `MEDIUM` |
| < 35 | `LOW` |

**Budgets are never invented.** No monetary figure is stored or displayed unless a
source states one. The band is the answer to "how big is this", not a price.

---

## 4. CONTACT_QUALITY

### Per contact (`contacts.contact_score`, 0–100)

| Factor | Weight |
|---|---|
| seniority | 0.35 |
| department relevance | 0.30 |
| evidence quality | 0.20 |
| event / procurement ownership | 0.15 |

Seniority from title keywords: chief / C-level 100, director / head of 90,
manager 78, senior / lead 65, specialist 50, coordinator / officer / executive 40,
otherwise 20.

Department relevance: `EVENTS` and `MARKETING` 100,
`CORPORATE_COMMUNICATIONS` 95, `COMMUNICATIONS` 90, `PR` 85, `PROCUREMENT` 80,
`BUSINESS_DEVELOPMENT` 70, `HR` 60, `OTHER` 25, `UNKNOWN` 20.

Evidence quality from `email_status` (`VERIFIED` 100, `PUBLIC` 80, `INFERRED` 35,
`UNKNOWN` 20), lifted to at least 60 and bonused +10 when a LinkedIn URL is
present, then scaled by `0.6 + 0.4 × source_confidence`.

Ownership from title keywords: event / sponsorship / exhibition 100,
procurement / purchasing / tender 85, marketing / brand / communications / PR /
media 70, otherwise 30.

### Per opportunity (damped)

```
no contacts                  → 0
best = max(contact_score)
best <  CONTACT_QUALITY_FLOOR → best × 0.5
best >= CONTACT_QUALITY_FLOOR → best + min(9, 3 × (number of other contacts above the floor))
```

`CONTACT_QUALITY_FLOOR` defaults to 40. This is the spec's requirement that weak
contacts must not significantly inflate the opportunity score: a roster of junior
coordinators is *halved*, while genuine corroboration earns at most 9 points.

---

## 5. TIMING

| `OPPORTUNITY_WINDOW` | Timing score | `RECOMMENDED_CONTACT_TIMING` |
|---|---|---|
| `DAYS_0_14` | 100 | `IMMEDIATE` |
| `DAYS_15_30` | 90 | `WITHIN_1_WEEK` |
| `DAYS_30_60` | 75 | `WITHIN_2_WEEKS` |
| `DAYS_60_90` | 60 | `WITHIN_1_MONTH` |
| `MONTHS_3_6` | 45 | `MONITOR_MONTHLY` |
| `MONTHS_6_12` | 25 | `MONITOR_QUARTERLY` |
| `UNKNOWN` | 20 | `RESEARCH_FIRST` |

`window_ends_on` = signal publication date + the window's upper bound (14, 30, 60,
90, 183, 365 days; `NULL` for `UNKNOWN`). It drives missed-window decay.

---

## 6. EVIDENCE_QUALITY

| Factor | Weight |
|---|---|
| source type tier | 0.45 |
| source confidence | 0.25 |
| publication date present | 0.10 |
| extraction confidence | 0.10 |
| corroboration | 0.10 |

Source tiers follow spec §17: `COMPANY` 100, `GOVERNMENT` 95, `PROCUREMENT` 92,
`BUSINESS_PUBLICATION` 80, `INDUSTRY_PUBLICATION` 70, `EVENT` 60,
`PUBLIC_PROFILE` 55, `OTHER` 35.

Publication date present → 100, absent → 30.
Corroboration from *n* distinct sources for the same company and signal type:
`min(100, 40 + 30(n − 1))`.

---

## 7. Score decay

Opportunities lose relevance with time. `services/rescore.py` recomputes this; the
recommended cadence is once per day, after ingestion.

```
age_days   = today − signal.published_at

age_factor = 1.0                                     if age_days ≤ 14
           = max(DECAY_FLOOR, exp(−(age_days − 14) / DECAY_TAU_DAYS))   otherwise

missed     = MISSED_WINDOW_PENALTY (0.60)  if window_ends_on < today  else 1.0
thin       = 0.90                          if EVIDENCE_QUALITY < 40   else 1.0

decay_factor = clamp(age_factor × missed × thin, DECAY_FLOOR, 1.0)
```

With `DECAY_TAU_DAYS = 120` and a 14-day grace period:

| Signal age | `age_factor` |
|---|---|
| ≤ 14 days | 1.00 |
| 30 days | 0.88 |
| 60 days | 0.68 |
| 90 days | 0.53 |
| 180 days | 0.25 |

A signal that was worth 84 fresh falls to about 57 at 90 days and leaves the Top 50
on its own. A missed window drops it immediately — 84 × 0.60 = 50.

---

## 8. TOP 50 selection

```sql
WHERE score >= MIN_QUALIFYING_SCORE   -- 70
  AND status NOT IN ('WON', 'LOST')
ORDER BY score DESC, event_probability DESC, created_at ASC
LIMIT TOP_N                           -- 50
```

`WON` and `LOST` opportunities are closed and leave the list; the other statuses
are live work and stay.

Two rules matter more than the arithmetic:

- **A new opportunity replaces an existing one only if it is stronger.** That falls
  out of ranking by score rather than by recency — nothing gets in for being new.
- **If fewer than 50 opportunities reach 70, the list is shorter.** Empty slots are
  never filled with weak leads. A 23-row Top 50 is a correct Top 50.

---

## 9. Tuning

`config.py` is the single place to change behaviour. In rough order of leverage:

1. `MIN_QUALIFYING_SCORE` — how exclusive the list is.
2. `EVENT_PROBABILITY_EXPONENT` — global conservatism. Raise it to compress scores.
3. The five `WEIGHT_*` values — what the business actually cares about.
4. `DECAY_TAU_DAYS` — how fast the list turns over.
5. `CONTACT_QUALITY_FLOOR` — how much a contactless opportunity is punished.

Change one at a time and compare Top 50 membership before and after.
