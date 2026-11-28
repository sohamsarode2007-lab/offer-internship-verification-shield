export type CheckStatus = 'pass' | 'fail' | 'not_applicable' | 'insufficient_information'

export interface CheckResult {
  check_name: string
  status: CheckStatus
  score?: number | null
  details?: string | null
}

// Mirrors every model in app/schemas/schemas.py; datetimes arrive as ISO 8601 strings.

export interface VerificationResultSchema {
  id?: number | null
  offer_id?: number | null
  overall_risk_score: number
  completeness_percentage: number
  created_at?: string | null
  check_results: CheckResult[]
}

export interface OfferSchema {
  id?: number | null
  title?: string | null
  company_name?: string | null
  raw_text?: string | null
  file_path?: string | null
  created_at?: string | null
}

export interface AnalyzeResponse {
  offer_id?: number | null
  overall_risk_score: number
  completeness_percentage: number
  checks: CheckResult[]
  summary: string
  risk_band?: string | null
  risk_factors: string[]
  /** Plain-language 'Why' rows with score impact ('+65', '−10' or null). */
  reasons?: { text: string; impact: string | null }[]
  scoring_model?: string | null
  next_steps: string[]
  complaint_summary: string
  report_token?: string | null
  reportable_indicators: ReportableIndicator[]
  /** Traceability only; never displayed. "synthetic" marks demo-only fictional registry data. */
  registry_source?: string | null
  /** Company name extracted from the offer text, if any (not stored server-side). */
  company_name?: string | null
  /** What the person could add to strengthen the check. */
  evidence_hints?: { id: string; title: string; why: string; how: string }[]
  /** Official look-ups the person can run themselves (e.g. the Udyam number page). */
  evidence_meta?: { check_name: string; source: string; affects: string; confidence: string; freshness: string; rule_version: string; checked_at: string }[]
  safety_actions?: { id: string; title: string; steps: string[]; urgent: boolean; helpline?: string; url?: string }[]
  employer_message?: { title: string; why: string; steps: string[]; subject: string; body: string; caution: string } | null
  self_checks?: { id: string; title: string; number: string; url: string; why: string; steps: string[]; caution: string }[]
}

export interface ReportableIndicator {
  id: string
  indicator_type: 'upi' | 'bank' | 'phone' | 'email' | 'domain' | 'telegram'
  masked: string
}

export interface ReportRequest {
  report_token: string
  consent: true
  consent_version: 4
  selected_indicators: string[]
}

export interface ReportResponse { status: 'reported'; withdrawal_code: string }
export interface WithdrawRequest { code: string }
export interface WithdrawResponse { status: 'withdrawn' }
export type DisputeIndicatorType = 'upi' | 'bank' | 'phone' | 'email' | 'domain' | 'telegram'
export interface DisputeRequest {
  indicator_type: DisputeIndicatorType
  value: string
  contact_email: string
  reason_code: "our_business_detail" | "reported_in_error" | "someone_else_misused_it" | "other"
}
export interface DisputeResponse { status: 'under_review'; message: string }

export type RiskBand = 'likely legitimate' | 'insufficient evidence, verify manually' | 'high risk'
export type ScamCategory = 'registration_fee' | 'security_deposit' | 'training_or_kit_fee' |
  'fake_government_scheme' | 'task_or_chat_scam' | 'free_mailbox_impersonation' | 'lookalike_domain' |
  'sender_spoofing' | 'no_red_flags' | 'other'
export type DashboardCount = number | '<5'
export interface WeekBandCount { week: string; band: RiskBand; count: DashboardCount }
export interface WeekCategoryCount { week: string; category: ScamCategory; count: DashboardCount }
export interface TopSender {
  indicator: string
  indicator_type: DisputeIndicatorType
  reports: number
  first_week: string | null
  last_week: string | null
  most_common_category: ScamCategory
  dispute_status: string | null
}
export interface CategorySummaryRow {
  category: ScamCategory
  total: DashboardCount
  last_4_weeks: DashboardCount
  previous_8_weeks: DashboardCount
  /** null when the 12-week total is below five (no trend shown for suppressed counts). */
  trend: 'Rising' | 'Falling' | 'Steady' | null
}
export interface InstitutionDashboard {
  institution: string
  category_summary: CategorySummaryRow[]
  sender_threshold: number
  top_senders: TopSender[]
  weeks: string[]
  by_week_band: WeekBandCount[]
  by_week_category: WeekCategoryCount[]
}

export interface DataSources {
  scoring_model: string
  sources: { id: string; name: string; updated: string | null; age_days: number | null; status: 'current' | 'stale' | 'demo' | 'unknown'; detail: string }[]
  optional_lookups: Record<string, boolean>
  request_budgets: { id: string; status: 'available' | 'paused' }[]
}
