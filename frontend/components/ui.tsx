/**
 * Shared presentation pieces.
 *
 * Kept together so score bands, assertion labels and contact display stay
 * consistent everywhere — the assertion label in particular must never look
 * different on one page from another.
 */

import Link from "next/link";
import { ContactRef, Opportunity, SourceRef, humanize } from "@/lib/api";

export function Nav({ active }: { active: "top50" | "brief" }) {
  return (
    <nav className="nav">
      <Link href="/" className={active === "top50" ? "on" : ""}>
        Top 50
      </Link>
      <Link href="/brief" className={active === "brief" ? "on" : ""}>
        Daily brief
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

export function ContactCard({ contact }: { contact: ContactRef | null }) {
  if (!contact) {
    return (
      <div className="role">
        No contact identified yet — research the account before approaching.
      </div>
    );
  }
  return (
    <div className="contact">
      <div className="name">{contact.name}</div>
      <div className="role">
        {contact.job_title ?? "Title unknown"} · {humanize(contact.department)} · quality{" "}
        {contact.contact_score}
      </div>
      {contact.email ? (
        <div className="email">
          <a href={`mailto:${contact.email}`}>{contact.email}</a>{" "}
          <span className={`pill ${contact.email_status}`} title="How this address is known">
            {contact.email_status}
          </span>
        </div>
      ) : (
        <div className="role">No public email on record</div>
      )}
      {contact.linkedin_url && (
        <a href={contact.linkedin_url} target="_blank" rel="noreferrer noopener">
          LinkedIn
        </a>
      )}
    </div>
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
