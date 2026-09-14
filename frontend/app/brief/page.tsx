/**
 * Daily intelligence brief (spec §25).
 */

import Link from "next/link";
import { ChangedOpportunity, Opportunity, fetchBrief, humanize } from "@/lib/api";
import { AssertionTag, ErrorPanel, Masthead, Nav, ScoreBadge } from "@/components/ui";

export const dynamic = "force-dynamic";

function Row({ o, delta }: { o: Opportunity; delta?: number }) {
  return (
    <div className="mini-row">
      <ScoreBadge score={o.score} classification={o.classification} rank={o.rank} />
      <div>
        <div className="v">
          <Link href={`/opportunities/${o.id}`}>{o.company.name}</Link>{" "}
          <AssertionTag level={o.assertion_level} />
          {delta !== undefined && (
            <span className={`delta ${delta >= 0 ? "up" : "down"}`}>
              {delta >= 0 ? `+${delta}` : delta}
            </span>
          )}
        </div>
        <div className="sub">
          {humanize(o.type)} · {humanize(o.signal.type)} — {o.signal.title}
        </div>
        <div className="sub small">{humanize(o.recommended_action)}</div>
      </div>
    </div>
  );
}

function Section({
  title,
  hint,
  items,
}: {
  title: string;
  hint: string;
  items: Opportunity[];
}) {
  return (
    <section className="panel">
      <h3>
        {title} <span className="count">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="sub">{hint}</p>
      ) : (
        items.map((o) => <Row key={o.id} o={o} />)
      )}
    </section>
  );
}

function ChangeSection({
  title,
  hint,
  items,
}: {
  title: string;
  hint: string;
  items: ChangedOpportunity[];
}) {
  return (
    <section className="panel">
      <h3>
        {title} <span className="count">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="sub">{hint}</p>
      ) : (
        items.map((entry) => (
          <Row key={entry.opportunity.id} o={entry.opportunity} delta={entry.delta} />
        ))
      )}
    </section>
  );
}

export default async function Page() {
  let brief;
  let error: string | null = null;
  try {
    brief = await fetchBrief();
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "Unknown error";
  }

  return (
    <div className="wrap">
      <Masthead subtitle="Daily intelligence brief" />
      <Nav active="brief" />

      {error ? (
        <ErrorPanel message={error} />
      ) : (
        brief && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Window</div>
                <div className="value">{brief.window_hours}h</div>
              </div>
              <div className="stat">
                <div className="label">New qualified</div>
                <div className="value">{brief.new_total}</div>
              </div>
              <div className="stat">
                <div className="label">In Top 50</div>
                <div className="value">{brief.current_top_50.length}</div>
              </div>
              <div className="stat">
                <div className="label">Qualifying</div>
                <div className="value">{brief.eligible_total}</div>
              </div>
              <div className="stat">
                <div className="label">Generated</div>
                <div className="value small">
                  {new Date(brief.generated_at).toLocaleString()}
                </div>
              </div>
            </div>

            <Section
              title="New hot leads"
              hint="No new opportunities reached HOT or EXCEPTIONAL in this window."
              items={brief.new_hot}
            />
            <Section
              title={`Top new opportunities`}
              hint="No new qualified opportunities in this window."
              items={brief.top_new_opportunities}
            />
            <ChangeSection
              title="Upgraded"
              hint="Nothing moved up in this window."
              items={brief.upgraded}
            />
            <ChangeSection
              title="Downgraded"
              hint="Nothing moved down in this window."
              items={brief.downgraded}
            />
            <ChangeSection
              title="Expired"
              hint="Nothing dropped out of the Top 50 in this window."
              items={brief.expired}
            />
            <Section
              title="Current Top 50"
              hint="Nothing qualifies yet."
              items={brief.current_top_50}
            />

            <footer className="note">
              Counts by band:{" "}
              {Object.entries(brief.classification_counts)
                .filter(([, count]) => count > 0)
                .map(([band, count]) => `${band.replace(/_/g, " ")} ${count}`)
                .join(" · ") || "none"}
              .
            </footer>
          </>
        )
      )}
    </div>
  );
}
