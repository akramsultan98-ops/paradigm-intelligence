/**
 * API client.
 *
 * Every call runs on the server, so the browser never talks to the API directly,
 * no API URL or key is shipped to the client, and the key stays server-side.
 */

export const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const API_KEY = process.env.API_KEY ?? "";

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
  id: string;
  source_url: string;
  source_title: string | null;
  source_type: string;
  publisher: string | null;
  publication_date: string | null;
  confidence: number;
  ingest_mode: string;
}

export interface ContactRef {
  id: string;
  name: string;
  job_title: string | null;
  department: string;
  email: string | null;
  linkedin_url: string | null;
  email_status: EmailStatus;
  contact_score: number;
  confidence: number;
}

export interface SignalRef {
  id: string;
  type: string;
  title: string;
  summary: string | null;
  business_impact: string | null;
  published_at: string | null;
  evidence_level: string;
  confidence: number;
  source: SourceRef | null;
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
  fact: string | null;
  inference: string | null;
  prediction: string | null;
  why_now: string;
  sales_angle: string;
  recommended_action: string;
  recommended_services: string[];
  opportunity_window: string;
  window_ends_on: string | null;
  recommended_contact_timing: string;
  previous_score: number | null;
  score_changed_at: string | null;
  scored_at: string;
  created_at: string;
  updated_at: string;
  company: {
    id: string;
    name: string;
    sector: string | null;
    city: string | null;
    domain: string | null;
    size_band: string;
    event_potential_score: number | null;
  };
  signal: SignalRef;
  primary_contact: ContactRef | null;
}

export interface OpportunityDetail extends Opportunity {
  contacts: ContactRef[];
}

export interface Top50Response {
  generated_at: string;
  qualifying_threshold: number;
  top_n: number;
  returned: number;
  eligible_total: number;
  items: Opportunity[];
}

export interface CompanyRelative {
  id: string;
  name: string;
  sector: string | null;
}

export interface CompanyDetail {
  id: string;
  name: string;
  domain: string | null;
  website: string | null;
  sector: string | null;
  city: string | null;
  description: string | null;
  size_band: string;
  event_potential_score: number | null;
  created_at: string;
  updated_at: string;
  contacts: ContactRef[];
  recent_signals: SignalRef[];
  opportunities: Opportunity[];
  parent: CompanyRelative | null;
  subsidiaries: CompanyRelative[];
  signal_count: number;
  opportunity_count: number;
  qualified_opportunity_count: number;
  account_score: number | null;
  event_history: SignalRef[];
}

export interface ChangedOpportunity {
  change: "NEW_HOT" | "UPGRADED" | "DOWNGRADED" | "EXPIRED";
  delta: number;
  opportunity: Opportunity;
}

export interface DailyBrief {
  generated_at: string;
  window_hours: number;
  qualifying_threshold: number;
  top_n: number;
  eligible_total: number;
  new_total: number;
  classification_counts: Record<string, number>;
  top_new_opportunities: Opportunity[];
  top_changed_opportunities: ChangedOpportunity[];
  current_top_50: Opportunity[];
  new_hot: Opportunity[];
  upgraded: ChangedOpportunity[];
  downgraded: ChangedOpportunity[];
  expired: ChangedOpportunity[];
}

export interface Filters {
  sector?: string;
  min_score?: string;
  status?: string;
  type?: string;
  date_from?: string;
  search?: string;
  sort?: string;
  order?: string;
  /** Lets buildQuery iterate the object without a cast. */
  [key: string]: string | undefined;
}

function buildQuery(filters: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    // Always live: a cached sales list is a misleading sales list.
    cache: "no-store",
    headers: API_KEY ? { "X-API-Key": API_KEY } : undefined,
  });
  if (!response.ok) {
    throw new Error(`API returned ${response.status} ${response.statusText} for ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchTop50(filters: Filters = {}): Promise<Top50Response> {
  return get<Top50Response>(`/api/v1/opportunities/top50${buildQuery(filters)}`);
}

export function fetchOpportunity(id: string): Promise<OpportunityDetail> {
  return get<OpportunityDetail>(`/api/v1/opportunities/${id}`);
}

export function fetchCompany(id: string): Promise<CompanyDetail> {
  return get<CompanyDetail>(`/api/v1/companies/${id}`);
}

export function fetchBrief(): Promise<DailyBrief> {
  return get<DailyBrief>("/api/v1/brief/daily");
}

export async function fetchSectors(): Promise<string[]> {
  try {
    return await get<string[]>("/api/v1/companies/sectors");
  } catch {
    // A missing sector list must not blank the whole page.
    return [];
  }
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
  "CLIENT_APPRECIATION",
  "PARTNER_EVENT",
  "CONFERENCE",
  "EXHIBITION",
  "WORKSHOP",
  "SEMINAR",
  "TECHNICAL_DAY",
  "TRAINING_EVENT",
  "EXECUTIVE_MEETING",
  "ROUNDTABLE",
  "VIP_DINNER",
  "PRESS_EVENT",
  "MEDIA_EVENT",
  "ROADSHOW",
  "TOWN_HALL",
  "ANNUAL_MEETING",
  "AWARDS",
  "TEAM_BUILDING",
  "CORPORATE_CELEBRATION",
  "ANNIVERSARY",
  "PROJECT_LAUNCH",
  "PROJECT_KICKOFF",
  "PROJECT_COMPLETION_EVENT",
  "GROUNDBREAKING",
  "DELEGATION_EVENT",
  "HOSPITALITY",
] as const;

export const SORT_FIELDS = [
  { value: "score", label: "Opportunity score" },
  { value: "event_probability", label: "Event probability" },
  { value: "commercial_value", label: "Commercial value" },
  { value: "contact_quality", label: "Contact quality" },
  { value: "timing_score", label: "Timing" },
  { value: "evidence_score", label: "Evidence" },
  { value: "created_at", label: "Date found" },
  { value: "company", label: "Company name" },
] as const;

/** Turn an enum value into something readable. */
export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatDate(value: string | null): string {
  if (!value) return "Date unknown";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
