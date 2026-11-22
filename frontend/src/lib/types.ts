// API contracts mirrored from backend/app/schemas (keep in sync; OpenAPI codegen is a planned step).

export type Role = "admin" | "operator" | "customer" | "readonly";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type BusinessStatus =
  | "discovered" | "scored" | "profiled" | "generated" | "published" | "claimed" | "archived";

export interface Business {
  id: string;
  name: string;
  slug: string;
  industry: string | null;
  city: string | null;
  province: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  facebook: string | null;
  status: BusinessStatus;
  score: number | null;
  score_breakdown: { breakdown?: Record<string, number>; reasons?: string[] } | null;
  generate_candidate: boolean;
  created_at: string;
}

export interface DiscoveryRun {
  id: string;
  status: string;
  total_records: number;
  created_count: number;
  duplicate_count: number;
  error_count: number;
  errors: { row: number | null; error: string }[];
}

export type WebsiteStatus = "draft" | "blueprint_ready" | "built" | "published" | "unpublished" | "failed";

export interface Website {
  id: string;
  business_id: string;
  subdomain: string;
  url: string | null;
  status: WebsiteStatus;
  version: number;
  quality_score: number | null;
  quality_report: { score: number; publishable: boolean; issues: string[] } | null;
  is_claimed: boolean;
  published_at: string | null;
}

export interface WebsiteSummary extends Website {
  business_name: string;
  template_slug: string | null;
}

export interface Template {
  id: string;
  slug: string;
  name: string;
  category: string;
  version: number;
  description: string | null;
  status: string;
  is_default: boolean;
  pages: { slug: string; title?: string; sections: { component: string; variant: string }[] }[];
  theme: { palette?: Record<string, string> };
  industries: string[];
}

export type ClaimStatus = "pending_verification" | "manual_review" | "approved" | "rejected" | "expired";

export interface Claim {
  id: string;
  business_id: string;
  claimant_name: string;
  claimant_email: string;
  claimant_phone: string | null;
  method: "email" | "sms" | "business_identity";
  status: ClaimStatus;
  risk_score: number;
  risk_factors: string[];
  evidence: Record<string, string>;
  created_at: string;
  verified_at: string | null;
}

export interface PublicSiteInfo {
  subdomain: string;
  business_name: string;
  industry: string | null;
  city: string | null;
  province: string | null;
  url: string | null;
  is_claimed: boolean;
  masked_email: string | null;
  masked_phone: string | null;
}

export interface Plan {
  code: string;
  name: string;
  description: string | null;
  price_monthly_cents: number;
  currency: string;
  features: Record<string, boolean | string | number>;
}

export interface ContentBlock {
  section_key: string;
  content: Record<string, unknown>;
  source: string;
  updated_at: string;
}

export interface Lead {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  message: string;
  created_at: string;
}

export interface CustomerDashboard {
  customer: { id: string; plan: string; status: string; activated_at: string };
  business: Record<string, string | null>;
  website: {
    id: string; subdomain: string; url: string | null; status: string; version: number;
    quality_score: number | null; seo_score: number | null; published_at: string | null;
  } | null;
  plan: Plan;
  stats: { page_views_30d: number; leads_30d: number; phone_clicks_30d: number };
  recent_leads: Lead[];
  seo: { score: number; content_gaps: ContentGap[] } | null;
}

export interface Overview {
  kpis: Record<string, number>;
  funnel: Record<string, number>;
  page_views_30d: number;
}

export interface Campaign {
  id: string;
  name: string;
  channel: string;
  status: string;
  target_filter: Record<string, string | number>;
  started_at: string | null;
  created_at: string;
}

export interface CampaignStats {
  outreach_sent: number;
  opens: number;
  clicks: number;
  claims: number;
  conversions: number;
  unsubscribes: number;
}

// --- Phase 2 ---------------------------------------------------------------------------------

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  payload: Record<string, unknown>;
  priority: number;
  attempts: number;
  max_attempts: number;
  run_after: string;
  locked_by: string | null;
  finished_at: string | null;
  last_error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface DayPoint {
  day: string;
  discovered: number;
  generated: number;
  published: number;
  claims_started: number;
  claims_completed: number;
  page_views: number;
  leads: number;
}

export interface TemplatePerformance {
  slug: string; name: string; category: string; sites: number; published: number; claimed: number;
  claim_rate: number; avg_quality: number | null;
}

export interface IndustryBreakdown {
  industry: string; businesses: number; candidates: number; sites: number; claimed: number; avg_score: number | null;
}

export interface AiUsage {
  enabled: boolean;
  models: { task: string; model: string; calls: number; accepted: number; prompt_tokens: number;
    completion_tokens: number; avg_latency_ms: number }[];
  ai_section_share: number;
  tokens_total: number;
  tokens_per_site: number;
  library_images: number;
  library_image_uses: number;
}

export interface ContentGap { key: string; message: string; impact: "high" | "medium" | "low"; section: string | null }

export interface Media {
  id: string; mime_type: string; size_bytes: number; width: number | null; height: number | null;
  alt_text: string | null; created_at: string;
}
