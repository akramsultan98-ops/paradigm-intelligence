/**
 * The follow-up list — who is owed a call today.
 *
 * Every date here was typed by whoever logged the last interaction. Nothing is
 * predicted and nothing is generated: an empty list means nothing was promised.
 */

import Link from "next/link";
import { departmentLabel, fetchFollowUps, formatDate } from "@/lib/api";
import { ContactCard, ErrorPanel, Masthead, Nav } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const rawAsOf = params.as_of;
  const asOf = Array.isArray(rawAsOf) ? rawAsOf[0] : rawAsOf;

  let due;
  let error: string | null = null;
  try {
    due = await fetchFollowUps(asOf);
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "Unknown error";
  }

  if (error || !due) {
    return (
      <div className="wrap">
        <Masthead subtitle="Follow-ups" />
        <Nav active="follow-ups" />
        <ErrorPanel message={error ?? "Unknown error"} />
      </div>
    );
  }

  return (
    <div className="wrap">
      <Masthead subtitle="Relationships owed a next step" />
      <Nav active="follow-ups" />

      {/* Plain GET form: looking ahead is a read, so it is a URL. */}
      <form className="filters" method="get">
        <label>
          Due by
          <input type="date" name="as_of" defaultValue={asOf ?? ""} />
        </label>
        <button type="submit">Show</button>
      </form>

      {due.length === 0 ? (
        <section className="panel">
          <p className="lead">
            Nothing is due{asOf ? ` by ${formatDate(asOf)}` : " today"}.
          </p>
          <p className="sub">
            A contact appears here once an interaction is logged against it with a
            follow-up date. Nothing is scheduled automatically.
          </p>
        </section>
      ) : (
        <section className="panel">
          <p className="sub">
            {due.length} follow-up{due.length === 1 ? "" : "s"} due
            {asOf ? ` by ${formatDate(asOf)}` : " today or earlier"}, oldest first.
          </p>
          {due.map((entry) => (
            <div
              key={`${entry.company_id}-${entry.contact?.id ?? "account"}`}
              className="mini-row"
            >
              <div className="duebox">
                <div className="score">{entry.days_overdue}</div>
                <div className="band">
                  {entry.days_overdue === 0 ? "DUE TODAY" : "DAYS LATE"}
                </div>
              </div>
              <div>
                <div className="v">
                  <Link href={`/companies/${entry.company_id}`}>{entry.company_name}</Link>{" "}
                  <span className="sub small">
                    ·{" "}
                    {entry.contact
                      ? departmentLabel(entry.contact.department)
                      : "promised on the account, no named contact"}{" "}
                    · promised {formatDate(entry.next_follow_up_on)}
                  </span>
                </div>
                {entry.contact ? (
                  <ContactCard contact={entry.contact} />
                ) : (
                  <p className="sub small">
                    Open the company to see the departments to aim for and what was last
                    said.
                  </p>
                )}
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
