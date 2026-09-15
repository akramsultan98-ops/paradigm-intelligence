/**
 * Log an interaction.
 *
 * Deliberately a plain HTML form posting to a server action: it works without
 * client-side JavaScript, and the fields are exactly the ones an Account Manager
 * fills in between calls — what was done, to whom, about what, and when to come
 * back.
 */

import { recordOutreach } from "@/app/companies/[id]/actions";
import {
  ContactRef,
  OUTREACH_ACTIONS,
  OUTREACH_STATUSES,
  Opportunity,
  humanize,
} from "@/lib/api";

export function OutreachForm({
  companyId,
  contacts,
  opportunities,
}: {
  companyId: string;
  contacts: ContactRef[];
  opportunities: Opportunity[];
}) {
  return (
    <form action={recordOutreach} className="outreach-form">
      <input type="hidden" name="company_id" value={companyId} />

      <div className="field">
        <label htmlFor="action">What did you do?</label>
        <select id="action" name="action" required defaultValue="EMAIL_SENT">
          {OUTREACH_ACTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="contact_id">Who</label>
        <select id="contact_id" name="contact_id" defaultValue="">
          <option value="">Company, no named contact</option>
          {contacts.map((contact) => (
            <option key={contact.id} value={contact.id}>
              {contact.name}
              {contact.job_title ? ` — ${contact.job_title}` : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="opportunity_id">About</label>
        <select id="opportunity_id" name="opportunity_id" defaultValue="">
          <option value="">The account generally</option>
          {opportunities.map((opportunity) => (
            <option key={opportunity.id} value={opportunity.id}>
              {humanize(opportunity.type)} · {opportunity.timing_class.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="status_after">Where it stands now</label>
        <select id="status_after" name="status_after" defaultValue="">
          <option value="">Let the action decide</option>
          {OUTREACH_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="next_follow_up_on">Next follow-up</label>
        <input id="next_follow_up_on" name="next_follow_up_on" type="date" />
      </div>

      <div className="field">
        <label htmlFor="logged_by">Logged by</label>
        <input id="logged_by" name="logged_by" type="text" maxLength={120} />
      </div>

      <div className="field wide">
        <label htmlFor="note">What was said</label>
        <textarea id="note" name="note" rows={3} maxLength={4000} />
      </div>

      <button type="submit">Log interaction</button>
    </form>
  );
}
