/**
 * The Top 50 view.
 *
 * A server component: fetches on the server, ships no API client to the browser.
 * Filters, sorting and search are plain GET query parameters, so every view is a
 * shareable URL and there is no client-side state to keep in sync.
 */

import Link from "next/link";
import {
  Filters,
  OPPORTUNITY_STATUSES,
  OPPORTUNITY_TYPES,
  Opportunity,
  SORT_FIELDS,
  TIMING_CLASSES,
  fetchSectors,
  fetchTop50,
  humanize,
} from "@/lib/api";
import {
  AssertionTag,
  ContactCard,
  ErrorPanel,
  Masthead,
  Nav,
  ScoreBadge,
  ScorePanel,
  SourceLine,
  TimingBadge,
} from "@/components/ui";

export const dynamic = "force-dynamic";

function Card({ opportunity }: { opportunity: Opportunity }) {
  const o = opportunity;

  return (
    <article className="card">
      <ScoreBadge score={o.score} classification={o.classification} rank={o.rank} />

      <div>
        <h2 className="title">
          <Link href={`/opportunities/${o.id}`}>{o.company.name}</Link>
        </h2>
        <p className="sub">
          {[o.company.sector, o.company.city].filter(Boolean).join(" · ") || "Sector unknown"}
        </p>

        <div className="tags">
          <span className="tag strong">{humanize(o.type)}</span>
          <TimingBadge timing={o.timing_class} eventDate={o.event_date} />
          <AssertionTag level={o.assertion_level} />
          <span className="tag">{humanize(o.status)}</span>
          <span className="tag">{o.opportunity_window.replace(/_/g, " ")}</span>
          <span className="tag">{humanize(o.recommended_contact_timing)}</span>
          <span className="tag">{o.commercial_value_band.replace("_", " ")} value</span>
        </div>

        <div className="block">
          <div className="k">Signal</div>
          <div className="v">
            {humanize(o.signal.type)} — {o.signal.title}
          </div>
        </div>

        <div className="block">
          <div className="k">Why now</div>
          <div className="v">{o.why_now}</div>
        </div>

        {o.timing_rationale && (
          <div className="block">
            <div className="k">Timing</div>
            <div className="v">{o.timing_rationale}</div>
          </div>
        )}

        <div className="block">
          <div className="k">Sales angle</div>
          <div className="v">{o.sales_angle}</div>
        </div>

        <div className="block">
          <div className="k">Next action</div>
          <div className="v action">{humanize(o.recommended_action)}</div>
        </div>

        {o.recommended_services.length > 0 && (
          <div className="block">
            <div className="k">Services</div>
            <div className="services">
              {o.recommended_services.map((service) => (
                <span className="service" key={service}>
                  {humanize(service)}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="block">
          <div className="k">Source</div>
          <div className="v">
            <SourceLine source={o.signal.source} />
          </div>
        </div>
      </div>

      <div className="side">
        <ScorePanel o={o} />
        <div className="block">
          <div className="k">Contact</div>
          <ContactCard contact={o.primary_contact} />
        </div>
        <Link className="detail-link" href={`/opportunities/${o.id}`}>
          Full detail →
        </Link>
      </div>
    </article>
  );
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const pick = (key: string): string | undefined => {
    const value = params[key];
    return Array.isArray(value) ? value[0] : value;
  };

  const filters: Filters = {
    sector: pick("sector"),
    min_score: pick("min_score"),
    status: pick("status"),
    type: pick("type"),
    date_from: pick("date_from"),
    timing: pick("timing"),
    include_historical: pick("include_historical"),
    search: pick("search"),
    sort: pick("sort"),
    order: pick("order"),
  };

  let data;
  let error: string | null = null;
  let sectors: string[] = [];

  try {
    [data, sectors] = await Promise.all([fetchTop50(filters), fetchSectors()]);
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "Unknown error";
  }

  return (
    <div className="wrap">
      <Masthead subtitle="The corporate sales opportunities most likely to generate event business in Egypt, ranked by opportunity score." />
      <Nav active="top50" />

      {error ? (
        <ErrorPanel message={error} />
      ) : (
        data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Showing</div>
                <div className="value">{data.returned}</div>
              </div>
              <div className="stat">
                <div className="label">Target</div>
                <div className="value">{data.top_n}</div>
              </div>
              <div className="stat">
                <div className="label">Qualifying</div>
                <div className="value">{data.eligible_total}</div>
              </div>
              <div className="stat">
                <div className="label">Threshold</div>
                <div className="value">{data.qualifying_threshold}+</div>
              </div>
              <div className="stat">
                <div className="label">Generated</div>
                <div className="value small">
                  {new Date(data.generated_at).toLocaleString()}
                </div>
              </div>
            </div>

            {/* Plain GET form: every filtered view is a shareable URL. */}
            <form className="filters" method="get">
              <label className="grow">
                Search company or contact
                <input
                  type="search"
                  name="search"
                  placeholder="e.g. Elsewedy, or a contact name or email"
                  defaultValue={filters.search ?? ""}
                />
              </label>

              <label>
                Sector
                <select name="sector" defaultValue={filters.sector ?? ""}>
                  <option value="">All sectors</option>
                  {sectors.map((sector) => (
                    <option key={sector} value={sector}>
                      {sector}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Min score
                <input
                  type="number"
                  name="min_score"
                  min={0}
                  max={100}
                  placeholder={String(data.qualifying_threshold)}
                  defaultValue={filters.min_score ?? ""}
                />
              </label>

              <label>
                Status
                <select name="status" defaultValue={filters.status ?? ""}>
                  <option value="">Any status</option>
                  {OPPORTUNITY_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {humanize(status)}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Opportunity type
                <select name="type" defaultValue={filters.type ?? ""}>
                  <option value="">Any type</option>
                  {OPPORTUNITY_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {humanize(type)}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Found since
                <input type="date" name="date_from" defaultValue={filters.date_from ?? ""} />
              </label>

              <label>
                Timing
                <select name="timing" defaultValue={filters.timing ?? ""}>
                  <option value="">Live only (excludes past events)</option>
                  {TIMING_CLASSES.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Sort by
                <select name="sort" defaultValue={filters.sort ?? "score"}>
                  {SORT_FIELDS.map((field) => (
                    <option key={field.value} value={field.value}>
                      {field.label}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Direction
                <select name="order" defaultValue={filters.order ?? "desc"}>
                  <option value="desc">Highest first</option>
                  <option value="asc">Lowest first</option>
                </select>
              </label>

              <button type="submit">Apply</button>
              <a className="reset" href="/">
                Reset
              </a>
            </form>

            {data.items.length === 0 ? (
              <div className="empty">
                <h2>No opportunities qualify yet</h2>
                <p>
                  Only opportunities scoring {data.qualifying_threshold} or above are eligible, and
                  the remaining slots are deliberately left empty rather than filled with weak
                  leads. Run an ingestion cycle, or relax the filters.
                </p>
              </div>
            ) : (
              <>
                {data.items.map((opportunity) => (
                  <Card key={opportunity.id} opportunity={opportunity} />
                ))}
                {data.returned < data.top_n && (
                  <footer className="note">
                    {data.returned} of a possible {data.top_n} shown. Only opportunities scoring{" "}
                    {data.qualifying_threshold}+ qualify; empty slots are never padded with weak
                    leads.
                  </footer>
                )}
              </>
            )}

            <footer className="note">
              Every opportunity is labelled <strong>FACT</strong>, <strong>INFERENCE</strong> or{" "}
              <strong>PREDICTION</strong>. A predicted event is not a confirmed one. Contact
              details are public professional information and carry an email status; an inferred
              address is never shown as verified.
            </footer>
          </>
        )
      )}
    </div>
  );
}
