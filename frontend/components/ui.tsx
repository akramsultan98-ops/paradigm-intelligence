/**
 * Shared presentation pieces.
 *
 * Kept together so score bands, assertion labels and contact display stay
 * consistent everywhere — the assertion label in particular must never look
 * different on one page from another.
 */

import Link from "next/link";
import {
  ContactRef,
  Opportunity,
  OutreachLogEntry,
  RankedContact,
  SourceRef,
  departmentLabel,
  formatDate,
  humanize,
} from "@/lib/api";

export function Nav({ active }: { active: "top50" | "brief" | "follow-ups" }) {
  return (
    <nav className="nav">
      <Link href="/" className={active === "top50" ? "on" : ""}>
        Top 50
      </Link>
      <Link href="/brief" className={active === "brief" ? "on" : ""}>
        Daily brief
      </Link>
      <Link href="/follow-ups" className={active === "follow-ups" ? "on" : ""}>
        Follow-ups
      </Link>
    </nav>
  );
}

export function Masthead({ subtitle }: { subtitle: string }) {
  return (
    <header className="masthead">
      <h1>
        <Link href="/">PARADIGM INTELLIGENCE</Link>
      </h1>
      <p>{subtitle}</p>
    </header>
  );
}

export function ScoreBadge({
  score,
  classification,
  rank,
}: {
  score: number;
  classification: string;
  rank?: number | null;
}) {
  return (
    <div className="rankbox">
      {rank ? <div className="rank">#{rank}</div> : null}
      <div className="score">{score}</div>
      <div className={`band ${classification}`}>{classification.replace(/_/g, " ")}</div>
    </div>
  );
}

/** The FACT / INFERENCE / PREDICTION label. Never styled as a neutral tag. */
export function AssertionTag({ level }: { level: string }) {
  const title =
    level === "FACT"
      ? "The source states this event"
      : level === "INFERENCE"
        ? "Follows strongly from the source, not stated"
        : "Expected, not stated and not confirmed";
  return (
    <span className={`tag assert-${level}`} title={title}>
      {level}
    </span>
  );
}

/**
 * What can still be done about this event.
 *
 * The distinction an Account Manager acts on, and the reason the badge exists: an
 * event two weeks out is usually already contracted, and a past event is not an
 * opportunity at all. Neither may look like "upcoming".
 */
const TIMING_LABEL: Record<string, string> = {
  IMMEDIATE: "BID NOW",
  FUTURE_ACCOUNT: "BUILD ACCOUNT",
  HISTORICAL: "PAST EVENT",
};

const TIMING_MEANING: Record<string, string> = {
  IMMEDIATE: "Far enough out that procurement is plausibly still open.",
  FUTURE_ACCOUNT:
    "Upcoming but too close to win, or undated. Production is very likely already contracted — worth the relationship.",
  HISTORICAL: "Already happened. Account research only, never a live opportunity.",
};

export function TimingBadge({
  timing,
  eventDate,
}: {
  timing: string;
  eventDate?: string | null;
}) {
  return (
    <span className={`tag timing-${timing}`} title={TIMING_MEANING[timing] ?? timing}>
      {TIMING_LABEL[timing] ?? timing.replace(/_/g, " ")}
      {eventDate ? ` · ${formatDate(eventDate)}` : ""}
    </span>
  );
}

export function TimingLegend() {
  return (
    <div className="legend">
      <div className="legend-title">Event timing</div>
      {(["IMMEDIATE", "FUTURE_ACCOUNT", "HISTORICAL"] as const).map((timing) => (
        <div className="legend-row" key={timing}>
          <TimingBadge timing={timing} />
          <span>{TIMING_MEANING[timing]}</span>
        </div>
      ))}
      <p className="sub small">
        A date is only ever read from a source. Where none was published the timing is
        inferred from the reported window and says so.
      </p>
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: number }) {
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

export function ScorePanel({ o }: { o: Opportunity }) {
  return (
    <>
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
      <p className="formula">
        35% event · 25% value · 20% contact · 10% timing · 10% evidence, then decay.
        Base {o.base_score} × {o.decay_factor.toFixed(2)} = <strong>{o.score}</strong>
      </p>
    </>
  );
}

/**
 * How an email address is known. Rendered for every contact, including when the
 * answer is UNKNOWN — an absent badge would read as "fine", and the whole point is
 * that an Account Manager can tell a verified address from a guessed one at a
 * glance.
 */
const EMAIL_STATUS_MEANING: Record<string, string> = {
  VERIFIED: "Checked by a verification step. Safe to use.",
  PUBLIC: "Published on a public page by the organisation itself.",
  INFERRED: "Derived, not published. Treat as unconfirmed — it may bounce.",
  UNKNOWN: "No address on record. Use the source page or the switchboard.",
};

export function EmailStatusBadge({ status }: { status: string }) {
  return (
    <span className={`pill ${status}`} title={EMAIL_STATUS_MEANING[status] ?? status}>
      {status}
    </span>
  );
}

/** The four states, explained. Shown wherever contacts are listed in detail. */
export function EmailStatusLegend() {
  return (
    <div className="legend">
      <div className="legend-title">Email status</div>
      {(["VERIFIED", "PUBLIC", "INFERRED", "UNKNOWN"] as const).map((status) => (
        <div className="legend-row" key={status}>
          <EmailStatusBadge status={status} />
          <span>{EMAIL_STATUS_MEANING[status]}</span>
        </div>
      ))}
      <p className="sub small">
        An inferred address is never shown as verified, and an address is never
        generated from a name pattern.
      </p>
    </div>
  );
}

/**
 * Whether this is a person or an official route.
 *
 * Read from the stored ``contact_kind`` rather than guessed from the name, so a
 * departmental inbox can never be mistaken for somebody we can ask for by name.
 */
const CONTACT_KIND_LABEL: Record<string, string> = {
  NAMED_INDIVIDUAL: "NAMED PERSON",
  DEPARTMENT_ROUTE: "DEPARTMENT ROUTE",
  UNKNOWN: "UNCLASSIFIED",
};

const CONTACT_KIND_MEANING: Record<string, string> = {
  NAMED_INDIVIDUAL: "A named individual published by the company itself.",
  DEPARTMENT_ROUTE:
    "An official department address or line — not a person. Ask for the events owner.",
  UNKNOWN: "Not yet classified as a person or a department route.",
};

export function ContactKindBadge({ kind }: { kind: string }) {
  return (
    <span className={`pill kind-${kind}`} title={CONTACT_KIND_MEANING[kind] ?? kind}>
      {CONTACT_KIND_LABEL[kind] ?? kind}
    </span>
  );
}

export function OutreachStatusBadge({ status }: { status: string }) {
  return (
    <span className={`pill status-${status}`}>{status.replace(/_/g, " ")}</span>
  );
}

/**
 * One contact, in full.
 *
 * Everything an Account Manager has to decide whether to use it: what kind of
 * contact it is, every public route we hold, how the email is known, where it was
 * read from, when it was last confirmed, and where the relationship stands.
 * Absent facts are printed as UNKNOWN rather than left blank — a blank reads as
 * "fine".
 */
export function ContactCard({ contact }: { contact: ContactRef | null }) {
  if (!contact) {
    return (
      <div className="contact">
        <div className="role">
          No contact identified yet. <EmailStatusBadge status="UNKNOWN" />
        </div>
        <div className="sub small">
          Research the account before approaching, or run contact discovery against its
          public contact page.
        </div>
      </div>
    );
  }
  return (
    <div className="contact">
      <div className="name">
        {contact.name} <ContactKindBadge kind={contact.contact_kind} />
      </div>
      <div className="role">
        {contact.job_title ?? "Title unknown"} · {departmentLabel(contact.department)} ·
        quality {contact.contact_score}
      </div>
      <div className="routes">
        <div className="route">
          <span className="k">Email</span>
          {contact.email ? (
            <a href={`mailto:${contact.email}`}>{contact.email}</a>
          ) : (
            <span className="muted">No address published</span>
          )}{" "}
          <EmailStatusBadge status={contact.email_status} />
        </div>
        <div className="route">
          <span className="k">Phone</span>
          {contact.phone ? (
            <a href={`tel:${contact.phone.replace(/[^+\d]/g, "")}`}>{contact.phone}</a>
          ) : (
            <span className="muted">No number published</span>
          )}
        </div>
        <div className="route">
          <span className="k">LinkedIn</span>
          {contact.linkedin_url ? (
            <a href={contact.linkedin_url} target="_blank" rel="noreferrer noopener">
              Profile
            </a>
          ) : (
            <span className="muted">No profile on record</span>
          )}
        </div>
      </div>
      <div className="sub small">
        <span className="k">Source</span> <SourceLine source={contact.source} />
      </div>
      <div className="sub small">
        <span className="k">Last verified</span>{" "}
        {contact.last_verified_at ? formatDate(contact.last_verified_at) : "UNKNOWN"}
        {" · "}
        <OutreachStatusBadge status={contact.outreach_status} />
        {contact.last_contacted_at
          ? ` · last contacted ${formatDate(contact.last_contacted_at)}`
          : " · never contacted"}
        {contact.next_follow_up_on
          ? ` · follow up ${formatDate(contact.next_follow_up_on)}`
          : ""}
      </div>
    </div>
  );
}

/** A contact, positioned for one specific event. Carries why this department. */
export function RankedContactRow({ ranked }: { ranked: RankedContact }) {
  return (
    <div className={`ranked ${ranked.is_preferred_department ? "fit" : "nofit"}`}>
      <div className="rankno">#{ranked.rank}</div>
      <div className="rankbody">
        <ContactCard contact={ranked.contact} />
        <p className="why-dept">
          <strong>{ranked.is_preferred_department ? "Right route" : "Fallback route"}:</strong>{" "}
          {ranked.reason}
        </p>
      </div>
    </div>
  );
}

const ACTION_LABEL: Record<string, string> = {
  EMAIL_SENT: "Email sent",
  CALL_MADE: "Call made",
  CALL_ATTEMPTED: "Call attempted",
  LINKEDIN_MESSAGE: "LinkedIn message",
  MEETING_HELD: "Meeting held",
  PROPOSAL_SENT: "Proposal sent",
  INTRODUCTION_REQUESTED: "Introduction requested",
  NOTE: "Note",
};

/** What was actually done, newest first. */
export function OutreachTimeline({ entries }: { entries: OutreachLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="sub">
        Nothing logged yet. The first interaction recorded here becomes the account
        history.
      </p>
    );
  }
  return (
    <ol className="timeline">
      {entries.map((entry) => (
        <li key={entry.id}>
          <div className="v">
            {ACTION_LABEL[entry.action] ?? humanize(entry.action)}
            {entry.contact_name ? ` · ${entry.contact_name}` : ""}{" "}
            <OutreachStatusBadge status={entry.status_after} />
          </div>
          <div className="sub small">
            {formatDate(entry.occurred_at)}
            {entry.opportunity_type ? ` · ${humanize(entry.opportunity_type)}` : ""}
            {entry.logged_by ? ` · ${entry.logged_by}` : ""}
            {entry.next_follow_up_on
              ? ` · next follow-up ${formatDate(entry.next_follow_up_on)}`
              : ""}
          </div>
          {entry.note && <p className="note">{entry.note}</p>}
        </li>
      ))}
    </ol>
  );
}

export function SourceLine({ source }: { source: SourceRef | null }) {
  if (!source) return <span className="sub">No source on record</span>;
  return (
    <span>
      <a href={source.source_url} target="_blank" rel="noreferrer noopener">
        {source.source_title ?? source.source_url}
      </a>
      <span className="sub">
        {" "}
        — {source.publisher ?? humanize(source.source_type)}
        {source.publication_date
          ? ` · ${new Date(source.publication_date).toLocaleDateString()}`
          : " · date unknown"}
        {` · confidence ${source.confidence.toFixed(2)}`}
        {source.ingest_mode !== "AUTOMATED" ? ` · ${source.ingest_mode.toLowerCase()}` : ""}
      </span>
    </span>
  );
}

export function TruthBlock({ o }: { o: Opportunity }) {
  if (!o.fact && !o.inference && !o.prediction) return null;
  return (
    <div className="truth">
      {o.fact && (
        <div className="truth-row">
          <span className="truth-key fact">FACT</span>
          <span>{o.fact}</span>
        </div>
      )}
      {o.inference && (
        <div className="truth-row">
          <span className="truth-key inference">INFERENCE</span>
          <span>{o.inference}</span>
        </div>
      )}
      {o.prediction && (
        <div className="truth-row">
          <span className="truth-key prediction">PREDICTION</span>
          <span>{o.prediction}</span>
        </div>
      )}
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="error">
      <h2>Could not reach the API</h2>
      <p>{message}</p>
      <p>
        Check the backend is running and that <code>API_BASE_URL</code> (and{" "}
        <code>API_KEY</code>, if set) point at it.
      </p>
    </div>
  );
}
