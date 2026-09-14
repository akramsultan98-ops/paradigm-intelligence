/**
 * Opportunity detail (spec §23).
 *
 * Everything an Account Manager needs before picking up the phone, without
 * opening another tool.
 */

import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchOpportunity, formatDate, humanize } from "@/lib/api";
import {
  AssertionTag,
  ContactCard,
  EmailStatusLegend,
  ErrorPanel,
  Masthead,
  Nav,
  ScoreBadge,
  ScorePanel,
  SourceLine,
  TruthBlock,
} from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let o;
  let error: string | null = null;
  try {
    o = await fetchOpportunity(id);
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "Unknown error";
    if (message.includes("404")) notFound();
    error = message;
  }

  if (error || !o) {
    return (
      <div className="wrap">
        <Masthead subtitle="Opportunity detail" />
        <Nav active="top50" />
        <ErrorPanel message={error ?? "Not found"} />
      </div>
    );
  }

  const others = o.contacts.filter((c) => c.id !== o.primary_contact?.id);

  return (
    <div className="wrap">
      <Masthead subtitle="Opportunity detail" />
      <Nav active="top50" />

      <p className="crumbs">
        <Link href="/">← Back to Top 50</Link>
      </p>

      <article className="detail">
        <header className="detail-head">
          <ScoreBadge score={o.score} classification={o.classification} rank={o.rank} />
          <div>
            <h2 className="title big">
              <Link href={`/companies/${o.company.id}`}>{o.company.name}</Link>
            </h2>
            <p className="sub">
              {[o.company.sector, o.company.city, humanize(o.company.size_band)]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <div className="tags">
              <span className="tag strong">{humanize(o.type)}</span>
              <AssertionTag level={o.assertion_level} />
              <span className="tag">{humanize(o.status)}</span>
              <span className="tag">{o.commercial_value_band.replace("_", " ")} value</span>
            </div>
          </div>
        </header>

        <section className="panel">
          <h3>What we know</h3>
          {/* The three statements, visually distinct, so a prediction can never
              be mistaken for a fact. */}
          <TruthBlock o={o} />
          {!o.fact && !o.inference && !o.prediction && (
            <p className="sub">
              This opportunity predates the separated fact / inference / prediction fields. The
              reasoning below still distinguishes them in wording.
            </p>
          )}
        </section>

        <div className="cols">
          <section className="panel">
            <h3>Signal</h3>
            <div className="block">
              <div className="k">Type</div>
              <div className="v">{humanize(o.signal.type)}</div>
            </div>
            <div className="block">
              <div className="k">Headline</div>
              <div className="v">{o.signal.title}</div>
            </div>
            {o.signal.summary && (
              <div className="block">
                <div className="k">Summary</div>
                <div className="v">{o.signal.summary}</div>
              </div>
            )}
            {o.signal.business_impact && (
              <div className="block">
                <div className="k">Business impact</div>
                <div className="v">{o.signal.business_impact}</div>
              </div>
            )}
            <div className="block">
              <div className="k">Published</div>
              <div className="v">{formatDate(o.signal.published_at)}</div>
            </div>
            <div className="block">
              <div className="k">Evidence level</div>
              <div className="v">{o.signal.evidence_level}</div>
            </div>
            <div className="block">
              <div className="k">Source</div>
              <div className="v">
                <SourceLine source={o.signal.source} />
              </div>
            </div>
          </section>

          <section className="panel">
            <h3>Opportunity score</h3>
            <ScorePanel o={o} />
            <div className="block">
              <div className="k">Opportunity window</div>
              <div className="v">
                {o.opportunity_window.replace(/_/g, " ")}
                {o.window_ends_on ? ` · closes ${formatDate(o.window_ends_on)}` : ""}
              </div>
            </div>
            <div className="block">
              <div className="k">Contact timing</div>
              <div className="v">{humanize(o.recommended_contact_timing)}</div>
            </div>
            <div className="block">
              <div className="k">Last scored</div>
              <div className="v">{new Date(o.scored_at).toLocaleString()}</div>
            </div>
            {o.previous_score !== null && (
              <div className="block">
                <div className="k">Movement</div>
                <div className="v">
                  {o.previous_score} → {o.score}
                  {o.score_changed_at ? ` · ${formatDate(o.score_changed_at)}` : ""}
                </div>
              </div>
            )}
          </section>
        </div>

        <section className="panel">
          <h3>Why now</h3>
          <p>{o.why_now}</p>
        </section>

        <section className="panel">
          <h3>Sales angle</h3>
          <p>{o.sales_angle}</p>
          {o.recommended_services.length > 0 && (
            <div className="services">
              {o.recommended_services.map((service) => (
                <span className="service" key={service}>
                  {humanize(service)}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="panel action-panel">
          <h3>Recommended action</h3>
          <p className="action big">{humanize(o.recommended_action)}</p>
          <p className="sub">
            Prepared for a human to act on. This system never sends outreach itself.
          </p>
        </section>

        <div className="cols">
          <section className="panel">
            <h3>Primary contact</h3>
            <ContactCard contact={o.primary_contact} />
          </section>

          <section className="panel">
            <h3>Other relevant contacts</h3>
            {others.length === 0 ? (
              <p className="sub">No other contacts on record for this company.</p>
            ) : (
              others.map((contact) => (
                <div key={contact.id} className="contact-row">
                  <ContactCard contact={contact} />
                </div>
              ))
            )}
            <p className="sub small">
              All contacts are public professional information, each stored with the source it was
              read from and an explicit email status.
            </p>
            <EmailStatusLegend />
          </section>
        </div>
      </article>
    </div>
  );
}
