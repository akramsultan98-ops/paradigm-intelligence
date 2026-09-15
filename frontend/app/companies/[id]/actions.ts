"use server";

/**
 * The one write path in the UI.
 *
 * A plain server action behind a plain form: no client-side JavaScript, no API key
 * in the browser, and the profile re-renders from the database rather than from
 * optimistic local state.
 */

import { revalidatePath } from "next/cache";
import { OutreachAction, OutreachStatus, logOutreach } from "@/lib/api";

function text(form: FormData, key: string): string | undefined {
  const value = form.get(key);
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

export async function recordOutreach(formData: FormData): Promise<void> {
  const companyId = text(formData, "company_id");
  const action = text(formData, "action") as OutreachAction | undefined;
  if (!companyId || !action) return;

  await logOutreach(companyId, {
    action,
    contact_id: text(formData, "contact_id"),
    opportunity_id: text(formData, "opportunity_id"),
    status_after: text(formData, "status_after") as OutreachStatus | undefined,
    next_follow_up_on: text(formData, "next_follow_up_on"),
    note: text(formData, "note"),
    logged_by: text(formData, "logged_by"),
  });

  revalidatePath(`/companies/${companyId}`);
  revalidatePath("/follow-ups");
}
