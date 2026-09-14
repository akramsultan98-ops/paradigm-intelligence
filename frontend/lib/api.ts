/**
 * API client.
 *
 * Every call runs on the server, so the browser never talks to the API directly
 * and no API URL is shipped to the client.
 */

export const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export type AssertionLevel = "FACT" | "INFERENCE" | "PREDICTION";

export type Classification =
  | "EXCEPTIONAL"
  | "HOT"
  | "VERY_HIGH"
  | "HIGH"
  | "QUALIFIED"
  | "NOT_ELIGIBLE";

export type EmailStatus = "VERIFIED" | "PUBLIC" | "INFERRED" | "UNKNOWN";

export interface SourceRef {
  source_url: string;
  source_title: string | null;
  source_type: string;
  publisher: string | null;
  publication_date: string | null;
  confidence: number;
}

export interface Opportunity {
  id: string;
  rank: number | null;
  score: number;
  classification: Classification;
  type: string;
  assertion_level: AssertionLevel;
  status: string;
  event_probability: number;
  commercial_value: number;
  commercial_value_band: string;
  contact_quality: number;
  timing_score: number;
  evidence_score: number;
  base_score: number;
  decay_factor: number;
  why_now: string;
  sales_angle: string;
  recommended_action: string;
  recommended_services: string[];
  opportunity_window: string;
  window_ends_on: string | null;
  recommended_contact_timing: string;
  created_at: string;
  company: {
    id: string;
    name: string;
    sector: string | null;
    city: string | null;
    size_band: string;
  };
  signal: {
    type: string;
    title: string;
    summary: string | null;
    published_at: string | null;
    source: SourceRef | null;
  };
  primary_contact: {
    name: string;
    job_title: string | null;
    department: string;
    email: string | null;
    linkedin_url: string | null;
    email_status: EmailStatus;
    contact_score: number;
  } | null;
}

export interface Top50Response {
  generated_at: string;
  qualifying_threshold: number;
  top_n: number;
  returned: number;
  eligible_total: number;
  items: Opportunity[];
}

export interface Filters {
  sector?: string;
  min_score?: string;
  status?: string;
  type?: string;
  date_from?: string;
}

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Fetch the Top 50. Throws with a readable message so the page can show it. */
export async function fetchTop50(filters: Filters = {}): Promise<Top50Response> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/opportunities/top50${buildQuery(filters)}`,
    // Always live: a cached sales list is a misleading sales list.
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`API returned ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function fetchSectors(): Promise<string[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/companies/sectors`, {
    cache: "no-store",
  });
  if (!response.ok) return [];
  return response.json();
}

export const OPPORTUNITY_STATUSES = [
  "NEW",
  "QUALIFIED",
  "CONTACTED",
  "MEETING",
  "WON",
  "LOST",
  "NURTURE",
] as const;

export const OPPORTUNITY_TYPES = [
  "PRODUCT_LAUNCH",
  "CUSTOMER_EVENT",
  "CONFERENCE",
  "EXHIBITION",
  "WORKSHOP",
  "SEMINAR",
  "TRAINING_EVENT",
  "PARTNER_EVENT",
  "PRESS_EVENT",
  "ROADSHOW",
  "GROUNDBREAKING",
  "PROJECT_KICKOFF",
  "PROJECT_COMPLETION_EVENT",
  "ANNIVERSARY",
  "CORPORATE_CELEBRATION",
  "EXECUTIVE_MEETING",
  "VIP_DINNER",
  "AWARDS",
  "TEAM_BUILDING",
  "HOSPITALITY",
] as const;

/** Turn an enum value into something readable. */
export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
