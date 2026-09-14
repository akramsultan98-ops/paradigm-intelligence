/**
 * The Top 50 view — the whole V1 interface.
 *
 * A server component: it fetches on the server, renders once, and ships no API
 * client to the browser. Filters are plain GET query parameters, so every view
 * is a shareable URL and there is no client-side state to keep in sync.
 */

import {
  Filters,
  OPPORTUNITY_STATUSES,
  OPPORTUNITY_TYPES,
  Opportunity,
  fetchSectors,
  fetchTop50,
  humanize,
} from "@/lib/api";

export const dynamic = "force-dynamic";

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <span>
        {value}
        <div className="bar">
          <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
        </div>
      </span>
    </div>
  );
}

function Card({ opportunity }: { opportunity: Opportunity }) {
  const o = opportunity;
  const source = o.signal.source;
  const contact = o.primary_contact;

  return (
    <article className="card">
      <div className="rankbox">
        <div className="rank">#{o.rank}</div>
        <div className="score">{o.score}</div>
        <div className={`band ${o.classification}`}>{o.classification.replace("_", " ")}</div>
      </div>

      <div>
        <h2 className="title">{o.company.name}</h2>
        <p className="sub">
          {[o.company.sector, o.company.city].filter(Boolean).join(" · ") || "Sector unknown"}
        </p>

        <div className="tags">
          <span className="tag">{humanize(o.type)}</span>
          {/* The epistemic label. A prediction must never read as a booking. */}
          <span className={`tag assert-${o.assertion_level}`} title="Fact, inference or prediction">
            {o.assertion_level}
          </span>
          <span className="tag">{humanize(o.status)}</span>
          <span className="tag">{o.opportunity_window.replace(/_/g, " ")}</span>
          <span className="tag">{humanize(o.recommended_contact_timing)}</span>
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

        <div className="block">
          <div className="k">Sales angle</div>
          <div className="v">{o.sales_angle}</div>
        </div>

        <div className="block">
          <div className="k">Recommended action</div>
          <div className="v">{humanize(o.recommended_action)}</div>
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

        {source && (
          <div className="block">
            <div className="k">Source</div>
            <div className="v">
              <a href={source.source_url} target="_blank" rel="noreferrer noopener">
                {source.source_title ?? source.source_url}
              </a>
              <span className="sub">
                {" "}
                — {source.publisher ?? humanize(source.source_type)}
                {source.publication_date
                  ? ` · ${new Date(source.publication_date).toLocaleDateString()}`
                  : " · date unknown"}
              </span>
            </div>
          </div>
        )}
      </div>

      <div className="side">
        <div className="metrics">
          <Metric label="Event prob." value={o.event_probability} />
          <Metric label="Comm. value" value={o.commercial_value} />
          <Metric label="Contact" value={o.contact_quality} />
          <Metric label="Timing" value={o.timing_score} />
          <Metric label="Evidence" value={o.evidence_score} />
          <div className="metric">
            <span>Decay</span>
            <span>{o.decay_factor.toFixed(2)}×</span>
          </div>
        </div>

        <div className="block">
          <div className="k">Commercial value</div>
          <div className="v">{o.commercial_value_band.replace("_", " ")}</div>
        </div>

        <div className="block contact">
          <div className="k">Contact</div>
          {contact ? (
            <>
              <div className="name">{contact.name}</div>
              <div className="role">
                {contact.job_title ?? "Title unknown"} · {humanize(contact.department)}
              </div>
              {contact.email ? (
                <div className="email">
                  {contact.email} <span className={`pill ${contact.email_status}`}>{contact.email_status}</span>
                </div>
              ) : (
                <div className="role">No public email on record</div>
              )}
              {contact.linkedin_url && (
                <a href={contact.linkedin_url} target="_blank" rel="noreferrer noopener">
                  LinkedIn
                </a>
              )}
            </>
          ) : (
            <div className="role">
              No contact identified yet — research the account before approaching.
            </div>
          )}
        </div>
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
      <header className="masthead">
        <h1>PARADIGM INTELLIGENCE</h1>
        <p>
          The corporate sales opportunities most likely to generate event business in Egypt,
          ranked by opportunity score.
        </p>
      </header>

      {error ? (
        <div className="error">
          <h2>Could not reach the API</h2>
          <p>{error}</p>
          <p>
            Check that the backend is running and that <code>API_BASE_URL</code> points at it.
          </p>
        </div>
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
                <div className="value" style={{ fontSize: 13 }}>
                  {new Date(data.generated_at).toLocaleString()}
                </div>
              </div>
            </div>

            {/* Plain GET form: every filtered view is a shareable URL. */}
            <form className="filters" method="get">
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
                Created since
                <input type="date" name="date_from" defaultValue={filters.date_from ?? ""} />
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
                  leads. Run an ingestion pass, or relax the filters.
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
