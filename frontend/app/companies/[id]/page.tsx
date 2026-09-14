/**
 * Company profile (spec §24).
 *
 * Lightweight on purpose: enough to brief an Account Manager, not a CRM record.
 */

import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchCompany, formatDate, humanize } from "@/lib/api";
import {
  AssertionTag,
  ContactCard,
  EmailStatusLegend,
  ErrorPanel,
  Masthead,
  Nav,
  ScoreBadge,
  SourceLine,
} from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let company;
  let error: string | null = null;
  try {
    company = await fetchCompany(id);
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "Unknown error";
    if (message.includes("404")) notFound();
    error = message;
  }

  if (error || !company) {
    return (
      <div className="wrap">
        <Masthead subtitle="Company profile" />
        <Nav active="top50" />
        <ErrorPanel message={error ?? "Not found"} />
      </div>
    );
  }

  return (
    <div className="wrap">
      <Masthead subtitle="Company profile" />
      <Nav active="top50" />

      <p className="crumbs">
        <Link href="/">← Back to Top 50</Link>
      </p>

      <header className="detail-head">
        <div>
          <h2 className="title big">{company.name}</h2>
          <p className="sub">
            {[company.sector, company.city, humanize(company.size_band)]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {company.website && (
            <p>
              <a href={company.website} target="_blank" rel="noreferrer noopener">
                {company.domain ?? company.website}
              </a>
            </p>
          )}
          {company.parent && (
            <p className="sub">
              Subsidiary of{" "}
              <Link href={`/companies/${company.parent.id}`}>{company.parent.name}</Link>
            </p>
          )}
          {company.subsidiaries.length > 0 && (
            <p className="sub">
              Subsidiaries:{" "}
              {company.subsidiaries.map((child, index) => (
                <span key={child.id}>
                  {index > 0 && ", "}
                  <Link href={`/companies/${child.id}`}>{child.name}</Link>
                </span>
              ))}
            </p>
          )}
        </div>
      </header>

      <div className="stats">
        <div className="stat">
          <div className="label">Account score</div>
          <div className="value">{company.account_score ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">Qualified opps</div>
          <div className="value">{company.qualified_opportunity_count}</div>
        </div>
        <div className="stat">
          <div className="label">Opportunities</div>
          <div className="value">{company.opportunity_count}</div>
        </div>
        <div className="stat">
          <div className="label">Signals</div>
          <div className="value">{company.signal_count}</div>
        </div>
        <div className="stat">
          <div className="label">Contacts</div>
          <div className="value">{company.contacts.length}</div>
        </div>
      </div>

      <section className="panel">
        <h3>Current opportunities</h3>
        {company.opportunities.length === 0 ? (
          <p className="sub">No open opportunities for this company.</p>
        ) : (
          company.opportunities.map((o) => (
            <div key={o.id} className="mini-row">
              <ScoreBadge score={o.score} classification={o.classification} />
              <div>
                <div className="v">
                  <Link href={`/opportunities/${o.id}`}>{humanize(o.type)}</Link>{" "}
                  <AssertionTag level={o.assertion_level} />
                </div>
                <div className="sub">
                  {humanize(o.signal.type)} — {o.signal.title}
                </div>
                <div className="sub small">
                  {humanize(o.recommended_action)} · {o.opportunity_window.replace(/_/g, " ")}
                </div>
              </div>
            </div>
          ))
        )}
      </section>

      <div className="cols">
        <section className="panel">
          <h3>Recent signals</h3>
          {company.recent_signals.length === 0 ? (
            <p className="sub">No signals recorded.</p>
          ) : (
            company.recent_signals.map((signal) => (
              <div key={signal.id} className="block">
                <div className="k">
                  {humanize(signal.type)} · {formatDate(signal.published_at)}
                </div>
                <div className="v">{signal.title}</div>
                <div className="sub small">
                  <SourceLine source={signal.source} />
                </div>
              </div>
            ))
          )}
        </section>

        <section className="panel">
          <h3>Relevant contacts</h3>
          {company.contacts.length === 0 ? (
            <p className="sub">No contacts on record.</p>
          ) : (
            company.contacts.map((contact) => (
              <div key={contact.id} className="contact-row">
                <ContactCard contact={contact} />
              </div>
            ))
          )}
          <EmailStatusLegend />
        </section>
      </div>

      <section className="panel">
        <h3>Event history</h3>
        {company.event_history.length === 0 ? (
          <p className="sub">
            No event history on record. Only events a source actually reported are shown here —
            nothing is assumed.
          </p>
        ) : (
          company.event_history.map((signal) => (
            <div key={signal.id} className="block">
              <div className="k">
                {humanize(signal.type)} · {formatDate(signal.published_at)}
              </div>
              <div className="v">{signal.title}</div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
