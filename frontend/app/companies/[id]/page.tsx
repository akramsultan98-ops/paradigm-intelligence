/**
 * Company profile — the page an Account Manager actually works from.
 *
 * Ordered as the job is done: who they are, why they are a target, what events are
 * in play and whether anything can still be won, then who to approach and what to
 * say, then what has already been said. The contact block is first-class rather
 * than a footnote, because a target nobody can reach is not a target.
 *
 * Nothing on this page is invented. Where a fact is missing it says UNKNOWN.
 */

import Link from "next/link";
import { notFound } from "next/navigation";
import { departmentLabel, fetchCompany, formatDate, humanize } from "@/lib/api";
import { OutreachForm } from "@/components/outreach-form";
import {
  AssertionTag,
  ContactCard,
  EmailStatusLegend,
  ErrorPanel,
  Masthead,
  Nav,
  OutreachStatusBadge,
  OutreachTimeline,
  RankedContactRow,
  ScoreBadge,
  SourceLine,
  TimingBadge,
  TimingLegend,
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

  const intel = company.contact_intelligence;
  const routingFor = company.opportunities.find(
    (o) => o.id === company.routing_opportunity_id,
  );
  const missing = intel.missing_departments;

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
          {company.website ? (
            <p>
              <a href={company.website} target="_blank" rel="noreferrer noopener">
                {company.domain ?? company.website}
              </a>
            </p>
          ) : (
            <p className="sub small">Website UNKNOWN</p>
          )}
          {company.description && <p className="desc">{company.description}</p>}
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
        {company.outreach && (
          <div className="relationship">
            <div className="label">Relationship</div>
            <OutreachStatusBadge status={company.outreach.status} />
            <div className="sub small">
              {company.outreach.interactions} interaction
              {company.outreach.interactions === 1 ? "" : "s"}
              {company.outreach.last_contacted_at
                ? ` · last contact ${formatDate(company.outreach.last_contacted_at)}`
                : " · never contacted"}
            </div>
            <div className={`sub small ${company.outreach.overdue ? "overdue" : ""}`}>
              {company.outreach.next_follow_up_on
                ? `Next follow-up ${formatDate(company.outreach.next_follow_up_on)}${
                    company.outreach.overdue ? " — OVERDUE" : ""
                  }`
                : "No follow-up scheduled"}
            </div>
          </div>
        )}
      </header>

      {company.recommended_first_action && (
        <section className="panel first-action">
          <h3>Recommended first action</h3>
          <p className="lead">{company.recommended_first_action}</p>
          {routingFor && (
            <p className="sub small">
              Based on{" "}
              <Link href={`/opportunities/${routingFor.id}`}>
                {humanize(routingFor.type)}
              </Link>{" "}
              <TimingBadge
                timing={routingFor.timing_class}
                eventDate={routingFor.event_date}
              />
              {routingFor.timing_rationale ? ` — ${routingFor.timing_rationale}` : ""}
            </p>
          )}
        </section>
      )}

      <div className="stats">
        <div className="stat">
          <div className="label">Account score</div>
          <div className="value">{company.account_score ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">Bid now</div>
          <div className="value">{company.immediate_opportunity_count}</div>
        </div>
        <div className="stat">
          <div className="label">Build account</div>
          <div className="value">{company.future_account_opportunity_count}</div>
        </div>
        <div className="stat">
          <div className="label">Past events</div>
          <div className="value">{company.historical_opportunity_count}</div>
        </div>
        <div className="stat">
          <div className="label">Named people</div>
          <div className="value">{intel.named_individuals}</div>
        </div>
        <div className="stat">
          <div className="label">Dept. routes</div>
          <div className="value">{intel.department_routes}</div>
        </div>
        <div className="stat">
          <div className="label">Signals</div>
          <div className="value">{company.signal_count}</div>
        </div>
      </div>

      <section className="panel">
        <h3>Who to contact, for this company&rsquo;s events</h3>
        {company.contacts.length === 0 ? (
          <div className="unknown-box">
            <p className="lead">No public contact is on record — UNKNOWN.</p>
            <p className="sub">
              Nothing is filled in here from a pattern, a broker or a guess. Look for
              the departments below on the company&rsquo;s own site, or run contact
              discovery against its published contact page.
            </p>
          </div>
        ) : (
          <>
            {!intel.has_any_route && (
              <div className="unknown-box">
                <p className="lead">
                  No direct email, phone or LinkedIn is on record — every channel below
                  reads UNKNOWN.
                </p>
                <p className="sub">
                  What we do have is the company&rsquo;s own published page for each
                  department, linked as the source. Use the page. Nothing has been
                  guessed to fill the gap.
                </p>
              </div>
            )}
            {routingFor && (
              <p className="sub">
                Ranked for {humanize(routingFor.type)} — the route depends on the job, so
                this order changes with the event.
              </p>
            )}
            {company.recommended_contacts.map((ranked) => (
              <RankedContactRow key={ranked.contact.id} ranked={ranked} />
            ))}
          </>
        )}

        <div className="departments">
          <div className="legend-title">Departments this company&rsquo;s events need</div>
          {company.relevant_departments.length === 0 ? (
            <p className="sub small">
              No events on record yet, so no department is suggested. Nothing is assumed.
            </p>
          ) : (
            <ul className="dept-list">
              {company.relevant_departments.map((entry) => (
                <li key={entry.department} className={entry.have_contact ? "have" : "lack"}>
                  <strong>{departmentLabel(entry.department)}</strong>{" "}
                  <span className="pill">{entry.have_contact ? "HAVE" : "MISSING"}</span>
                  <div className="sub small">{entry.why}</div>
                </li>
              ))}
            </ul>
          )}
          {missing.length > 0 && (
            <p className="sub small">
              No contact on record for: {missing.map(departmentLabel).join(", ")}.
            </p>
          )}
        </div>
      </section>

      <section className="panel">
        <h3>Events and what can still be done about them</h3>
        {company.opportunities.length === 0 ? (
          <p className="sub">No opportunities recorded for this company.</p>
        ) : (
          company.opportunities.map((o) => (
            <div key={o.id} className="mini-row">
              <ScoreBadge score={o.score} classification={o.classification} />
              <div>
                <div className="v">
                  <Link href={`/opportunities/${o.id}`}>{humanize(o.type)}</Link>{" "}
                  <AssertionTag level={o.assertion_level} />{" "}
                  <TimingBadge timing={o.timing_class} eventDate={o.event_date} />
                </div>
                <div className="sub">
                  {humanize(o.signal.type)} — {o.signal.title}
                </div>
                <div className="sub small">{o.why_now}</div>
                {o.timing_rationale && (
                  <div className="sub small timing-why">{o.timing_rationale}</div>
                )}
                <div className="sub small">
                  {humanize(o.recommended_action)} ·{" "}
                  {o.opportunity_window.replace(/_/g, " ")}
                </div>
              </div>
            </div>
          ))
        )}
        <TimingLegend />
      </section>

      <div className="cols">
        <section className="panel">
          <h3>Outreach history</h3>
          <OutreachTimeline entries={company.outreach_history} />
        </section>

        <section className="panel">
          <h3>Log an interaction</h3>
          <OutreachForm
            companyId={company.id}
            contacts={company.contacts}
            opportunities={company.opportunities}
          />
          <p className="sub small">
            Recorded against the account, so a relationship can be built before there is
            a named person — and continued after an event has been won by somebody else.
          </p>
        </section>
      </div>

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
          <h3>Every contact on record</h3>
          {company.contacts.length === 0 ? (
            <p className="sub">No contacts on record — UNKNOWN.</p>
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
            No event history on record. Only events a source actually reported are shown
            here — nothing is assumed.
          </p>
        ) : (
          company.event_history.map((signal) => (
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
    </div>
  );
}
