export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export interface SocialRecord {
  id: number
  source: string
  record_type: string
  monitoring_scope?: 'brand' | 'thematic'
  query_provenance?: string | null
  external_id: string
  text: string
  normalized_text?: string | null
  content_hash?: string | null
  language_code?: string
  language_method?: string
  is_simulated?: boolean
  is_spam?: boolean
  provenance_note?: string | null
  duplicate_of_record_id?: number | null
  duplicate_match_score?: number | null
  duplicate_match_type?: string | null
  duplicate_review_state?: 'unreviewed' | 'confirmed_duplicate' | 'confirmed_distinct'
  url?: string | null
  author?: string | null
  published_at?: string | null
  collected_at?: string | null
  like_count?: number | null
  reply_count?: number | null
  view_count?: number | null
  keyword_counts?: { term: string; count: number }[]
  sentiment_score?: number
  importance_score?: number
  signal_model?: string
  analysis_available?: boolean
  audience_segment?: string
  audience_need?: string
  audience_confidence?: number
  pain_points?: string[]
  conversation_emotion?: string
}

export interface RecordAnalysis {
  id: number
  record_id: number
  is_relevant: boolean
  relevance_type: string
  topic: string
  intent: string
  sentiment: string
  perception_signal: string
  confidence: number
  priority: string
  rationale: string
  model_name?: string
}

export interface ReplyDraft {
  draft_id: number
  record_id: number
  reply_text: string
  status: string
  original_text?: string | null
  original_url?: string | null
  source?: string | null
  author?: string | null
  published_at?: string | null
  collected_at?: string | null
  record_type?: string | null
  analysis?: RecordAnalysis | null
  audience_segment?: string | null
  audience_need?: string | null
  model_name?: string | null
  generated_at?: string | null
  reviewed_at?: string | null
}

export interface Stats {
  total_records: number
  unique_records?: number
  duplicate_records?: number
  simulated_records?: number
  by_language?: Record<string, number>
  by_source: Record<string, number>
  total_social_mentions?: number
  recent_window_days?: number
  recent_social_mentions?: number
  positive_social_mentions?: number
  analyzed_relevant_social?: number
  high_priority_social_mentions?: number
  by_type?: Record<string, number>
  by_monitoring_scope?: Record<string, number>
  total_news_articles?: number
  direct_brand_mentions?: number
  industry_relevant_records?: number
  sentiment_distribution?: Record<string, number>
  pending_reply_drafts?: number
  analyzed_records?: number
  unanalyzed_records?: number
  latest_collections?: { id: number; source: string; status: string; records_added: number; error_type?: string | null; completed_at: string }[]
}

export interface OpportunityCourse {
  title: string
  category: string
  url: string
}

export interface TrainingOpportunity {
  record_id: number
  source: string
  record_type: string
  monitoring_scope?: string
  text: string
  url?: string | null
  author?: string | null
  published_at?: string | null
  collected_at?: string | null
  request_type: string
  skills: string[]
  location?: string | null
  asks_location: boolean
  is_direct_brand_request?: boolean
  reply_eligible?: boolean
  audience_segment?: string | null
  audience_need?: string | null
  confidence?: number
  topic?: string | null
  suggested_course?: OpportunityCourse | null
  draft?: { draft_id: number; reply_text: string; status: string } | null
}

export interface EngagementOpportunity {
  id: number; record_id: number; reason: string; suggested_action: string; priority_score: number
  status: 'new' | 'assigned' | 'responded' | 'follow_up' | 'closed' | 'dismissed'
  owner?: string | null; follow_up_at?: string | null; notes?: string | null
  action_type: string; pr_objective: string; pr_objective_key?: string; pr_objective_explanation?: string; stakeholder_type?: string | null; partnership_signal: boolean; confidence: number
  audience_segment?: string; audience_need?: string; audience_confidence?: number
  stakeholder_name?: string | null; stakeholder_geography?: string | null; stakeholder_fit_notes?: string | null
  stakeholder_review?: 'not_assessed' | 'verify' | 'verified' | 'not_a_fit'
  manually_added_to_radar?: boolean
  is_stale?: boolean
  opportunity_score?: number; strategic_value?: number; urgency_score?: number
  score_parts?: { evidence_strength: number; confidence: number; strategic_value: number; urgency: number; recency: number }
  score_explanation?: string
  staleness_days?: number
  duplicate_of_record_id?: number | null
  capability_matches?: { capability: string; score: number; matched_terms: string[]; review_required: boolean; match_note: string }[]
  review_state: 'review_required' | 'validated' | 'insufficient_evidence'
  source: string; record_type: string; monitoring_scope?: 'brand' | 'thematic'; text: string; url?: string | null; author?: string | null; published_at?: string | null
}

export interface StrategyPartner {
  candidate_key: string; name: string; source?: string | null; stakeholder_type: string; radar_score: number
  score_parts: { evidence: number; recency: number; capability_fit: number; observed_engagement: number; actionable_intent: number }
  activity_30_days: number; activity_90_days: number; latest_at?: string | null; signal_count: number
  likes?: number | null; replies?: number | null
  capability_matches: { capability: string; score: number; matched_terms: string[] }[]
  evidence: { record_id: number; text: string; url?: string | null; published_at?: string | null; reason: string; priority_score: number }[]
  opportunities: { id: number; record_id: number; status: string; owner?: string | null; follow_up_at?: string | null }[]
  owner?: string | null; follow_up_at?: string | null; review_state: string; approach_plan: string[]; potential_value: string
  growth_measurement: { content_items: number; published_items: number; measured_items: number; recorded_reach: number; stakeholder_engagements: number; partnership_enquiries: number; media_enquiries: number }
  organization_id?: number | null; organization_verification?: string; organization_website?: string | null
  organization_public_email?: string | null; organization_contact_url?: string | null; organization_verification_evidence?: string | null
}

export interface ContentRecommendation {
  id: number; topic: string; idea: string; messaging: string; call_to_action: string; rationale: string
  pr_objective: string; collaboration_partner?: string | null; target_audience: string; recommended_format: string; hook: string; distribution_channel?: string | null
  priority_score: number; confidence: number; review_state: 'review_required' | 'validated' | 'insufficient_evidence'
  evidence_record_ids: number[]; evidence: { id: number; text: string; source: string; url?: string | null }[]
  status: 'idea' | 'drafting' | 'review' | 'scheduled' | 'published' | 'paused'
  owner?: string | null; channel?: string | null; planned_at?: string | null; published_at?: string | null; content_url?: string | null
  impressions?: number | null; reach?: number | null; likes?: number | null; comments?: number | null; shares?: number | null; follows?: number | null
  saves?: number | null; relevant_stakeholder_engagements?: number | null; partnership_enquiries?: number | null; media_enquiries?: number | null
  strategic_engagement_score?: number | null
  created_at?: string | null; updated_at?: string | null
  outcome_notes?: string | null
  generated_content_options?: { format: string; angle: string; copy: string; call_to_action: string; evidence_record_ids: number[]; review_required: boolean }[]
  evidence_validation?: { score: number; evidence_count: number; original_conversation_count: number; source_diversity: number; linked_sources: number; recent_evidence_count: number; simulated_evidence_count: number; valid_for_generation: boolean; confidence_label: string; review_required: boolean; limitations: string }
  feedback?: { rating: 'useful' | 'not_useful' | 'used'; reason?: string | null; created_at: string }[]
  campaign_outcomes?: { id: number; campaign_name: string; outcome_type: string; value: number; measured_at: string; attribution_method: string; evidence_url?: string | null; notes?: string | null }[]
}

export interface RankedTrend {
  topic: string
  monitoring_scope?: 'brand' | 'thematic'
  audience_segments?: Record<string, number>
  audience_needs?: Record<string, number>
  leading_audience?: string
  leading_need?: string
  score: number
  attention: 'Immediate attention' | 'High priority' | 'Monitor' | 'Low priority'
  count: number
  recent_30_days: number
  previous_30_days: number
  negative: number
  complaints: number
  questions: number
  urgent: number
  latest_at?: string | null
  reasons: string[]
  score_parts: { volume: number; recency: number; risk: number; demand: number; growth: number }
  growth_percent: number | null
  engagement_acceleration_percent?: number | null
  engagement_baseline?: { current_measured_records: number; previous_measured_records: number; current_weighted_interactions_per_record?: number | null; previous_weighted_interactions_per_record?: number | null; formula: string }
  baseline_confidence?: 'low' | 'medium' | 'high'
  velocity_per_week: number
  lifecycle: 'emerging' | 'growing' | 'peak' | 'declining' | 'dormant'
  novelty: boolean
  engagement_coverage: { records_with_metrics: number; by_source: Record<string, { records_with_metrics: number; likes: number; replies: number; views: number }> }
  examples: { record_id: number; text: string; source: string; url?: string | null; published_at?: string | null; collected_at?: string | null; sentiment: string; intent: string; priority: string; confidence: number; audience_segment?: string; audience_need?: string; audience_confidence?: number }[]
}

export interface TrendAnalysis {
  total_social_records: number
  analyzed_with_saved_label: number
  relevant_records: number
  excluded_as_unrelated: number
  dated_records: number
  undated_records: number
  date_from?: string | null
  date_to?: string | null
  years: { year: number; count: number }[]
  trends: RankedTrend[]
  ranking_method: string
}

export interface AudienceInsights {
  sample_size: number
  monitoring_scope: string
  method: string
  date_from?: string | null
  date_to?: string | null
  segments: { audience_segment: string; count: number; share_percent: number; confidence: number; needs: Record<string, number>; pain_points?: Record<string, number>; emotions?: Record<string, number>; recommended_action: string; examples: { record_id: number; text: string; source: string; url?: string | null; published_at?: string | null; collected_at?: string | null; audience_need: string; pain_points?: string[]; conversation_emotion?: string; confidence: number }[] }[]
  top_needs: { need: string; count: number }[]
  top_pain_points?: { pain_point: string; count: number }[]
  conversation_emotions?: Record<string, number>
  age_group_mentions?: { group: string; count: number; share_percent: number; evidence: { record_id: number; text: string; source: string; url?: string | null; published_at?: string | null; collected_at?: string | null }[] }[]
  location_mentions?: { place: string; count: number; share_percent: number; evidence: { record_id: number; text: string; source: string; url?: string | null; published_at?: string | null; collected_at?: string | null }[] }[]
  audience_actions?: { title: string; action: string; basis: string; evidence_record_ids: number[] }[]
}

export interface PerformanceLearning {
  published_items: number
  measured_items: number
  method: string
  patterns: { pr_objective: string; format: string; audience: string; sample_size: number; mean_score: number; usable_for_direction: boolean; recommendation: string }[]
  recommendation_feedback?: Record<string, number>; attributed_outcomes?: Record<string, number>; outcome_records?: number
}
export interface QuickEmailDraft {
  id: number; target_type: 'partner' | 'audience_template'; organization_id?: number | null; audience_segment?: string | null
  recipient_email?: string | null; subject: string; body: string; evidence_record_ids: number[]; status: string
  send_enabled: false; created_at: string
}

export interface SocialAlert {
  id: string; type: string; severity: 'critical' | 'high' | 'medium' | 'low'; title: string; detail: string
  topic?: string | null; monitoring_scope?: string | null; record_id?: number | null; opportunity_id?: number | null
  source?: string | null; url?: string | null; sample_size: number
  published_at?: string | null; collected_at?: string | null; reply_draft_id?: number | null; training_opportunity?: boolean
}

export type OperationResult = Record<string, unknown>

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, options)
  } catch {
    throw new Error(`Network error: unable to reach the API at ${API_BASE}`)
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Preserve the HTTP status when the server did not return JSON.
    }
    throw new Error(`${path} failed: ${detail}`)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new Error(`${path} returned an invalid JSON response`)
  }
}

function listFrom<T>(data: unknown, key: string): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object') {
    const object = data as Record<string, unknown>
    if (Array.isArray(object[key])) return object[key] as T[]
    if (Array.isArray(object.items)) return object.items as T[]
  }
  throw new Error(`API response did not contain a valid ${key} list`)
}

export async function fetchRecords(
  source?: string,
  limit = 500,
  offset = 0,
): Promise<SocialRecord[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (source) query.set('source', source)
  return listFrom(await request<unknown>(`/records?${query}`), 'records')
}
export function updateRecordProvenance(id: number, is_simulated: boolean, provenance_note?: string) {
  return request<{ id: number; is_simulated: boolean; provenance_note?: string | null }>(`/records/${id}/provenance`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_simulated, provenance_note }),
  })
}
export function updateRecordSpam(id: number, is_spam: boolean) {
  return request<{ id: number; is_spam: boolean }>(`/records/${id}/spam`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_spam }) })
}
export function createRecordReplyDraft(recordId: number) {
  return request<{ draft_id: number; record_id: number; reply_text: string; status: string }>(`/records/${recordId}/reply-draft`, { method: 'POST' })
}
export function addRecordToStrategyRadar(recordId: number) {
  return request<{ id: number; record_id: number; manually_added_to_radar: boolean; status: string; review_state: string }>(`/engagement/opportunities/from-record/${recordId}`, { method: 'POST' })
}
export function reviewDuplicateLink(id: number, duplicate_of_record_id: number | null) {
  return request<{ id: number; duplicate_of_record_id: number | null; duplicate_review_state: string; duplicate_match_score: number | null }>(`/records/${id}/duplicate-review`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duplicate_of_record_id }),
  })
}

export async function fetchStats(): Promise<Stats> {
  return request<Stats>('/stats')
}

export async function fetchTrendAnalysis(dates: { from?: string; to?: string } = {}): Promise<TrendAnalysis> {
  const params = new URLSearchParams()
  if (dates.from) params.set('date_from', dates.from)
  if (dates.to) params.set('date_to', dates.to)
  return request<TrendAnalysis>(`/trends${params.size ? `?${params}` : ''}`)
}

export async function fetchAudienceInsights(dates: { from?: string; to?: string } = {}): Promise<AudienceInsights> {
  const params = new URLSearchParams()
  if (dates.from) params.set('date_from', dates.from)
  if (dates.to) params.set('date_to', dates.to)
  return request<AudienceInsights>(`/audience/insights${params.size ? `?${params}` : ''}`)
}

export async function fetchOpportunities(): Promise<TrainingOpportunity[]> {
  return listFrom(await request<unknown>('/opportunities'), 'opportunities')
}

export async function fetchEngagementOpportunities(): Promise<EngagementOpportunity[]> {
  return listFrom(await request<unknown>('/engagement/opportunities'), 'opportunities')
}
export async function fetchStrategyPartners(): Promise<{ partners: StrategyPartner[]; count: number; method: string }> {
  return request<{ partners: StrategyPartner[]; count: number; method: string }>('/strategy/partners')
}
export function dismissStrategyPartner(opportunityIds: number[]) {
  return request<{ dismissed: number; preserved_conversations: number }>('/strategy/partners/dismiss', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ opportunity_ids: opportunityIds }) })
}
export function updateEngagementOpportunity(id: number, values: Partial<Pick<EngagementOpportunity, 'status' | 'owner' | 'follow_up_at' | 'notes' | 'suggested_action' | 'review_state' | 'stakeholder_name' | 'stakeholder_geography' | 'stakeholder_fit_notes' | 'stakeholder_review'>>) {
  return request(`/engagement/opportunities/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export async function fetchContentRecommendations(): Promise<ContentRecommendation[]> {
  return listFrom(await request<unknown>('/content/recommendations'), 'recommendations')
}
export async function fetchPerformanceLearning(): Promise<PerformanceLearning> {
  return request<PerformanceLearning>('/performance/learning')
}
export function saveOrganizationProfile(values: { canonical_name: string; aliases: string[]; website?: string; public_email?: string; contact_url?: string; verification_status: 'unverified' | 'review' | 'verified'; verification_evidence?: string; notes?: string }) {
  return request<{ id: number; canonical_name: string; normalized_name: string; verification_status: string; public_email?: string | null }>('/strategy/organizations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export function saveQuickEmailDraft(values: { target_type: 'partner' | 'audience_template'; organization_id?: number; audience_segment?: string; recipient_email?: string; subject: string; body: string; evidence_record_ids: number[] }) {
  return request<{ id: number; status: string; send_enabled: false }>('/quick-email-drafts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export async function fetchQuickEmailDrafts(): Promise<QuickEmailDraft[]> {
  return listFrom(await request<unknown>('/quick-email-drafts'), 'drafts')
}
export function submitRecommendationFeedback(id: number, rating: 'useful' | 'not_useful' | 'used', reason: string) {
  return request(`/content/recommendations/${id}/feedback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rating, reason }) })
}
export function addCampaignOutcome(id: number, values: { campaign_name: string; outcome_type: string; value: number; attribution_method: string; evidence_url?: string; notes?: string }) {
  return request(`/content/recommendations/${id}/outcomes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export async function fetchAlerts(): Promise<{ count: number; alerts: SocialAlert[]; method: string }> {
  return request('/alerts')
}
export function rebuildDataQuality() {
  return request<{ status: string; records_processed: number; duplicate_links: number; simulated_records: number }>('/data-quality/rebuild', { method: 'POST' })
}
export function createContentRecommendation(values: { topic: string; idea: string; messaging: string; call_to_action: string; rationale: string; evidence_record_ids: number[]; pr_objective: string; collaboration_partner?: string | null; target_audience: string; recommended_format: string; hook: string; distribution_channel: string; priority_score: number; confidence: number }) {
  return request<{ id: number; status: string; topic: string }>('/content/recommendations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export function generateContentOptions(id: number) {
  return request<{ id: number; model_name: string; options: NonNullable<ContentRecommendation['generated_content_options']>; review_required: true; published: false }>(`/content/recommendations/${id}/generate`, { method: 'POST' })
}
export function updateContentRecommendation(id: number, values: Partial<ContentRecommendation>) {
  return request<{ id: number; status: string; topic: string }>(`/content/recommendations/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
}
export function deleteContentRecommendation(id: number) {
  return request<{ deleted: boolean; id: number }>(`/content/recommendations/${id}`, { method: 'DELETE' })
}

export function generateOpportunityDraft(recordId: number) {
  return request<{ draft_id: number; record_id: number; reply_text: string; status: string; suggested_course?: OpportunityCourse | null }>(
    `/opportunities/${recordId}/draft`, { method: 'POST' },
  )
}

export async function fetchAnalyses(): Promise<RecordAnalysis[]> {
  return listFrom(await request<unknown>('/analyses'), 'analyses')
}

export async function fetchDrafts(status = 'draft'): Promise<ReplyDraft[]> {
  return listFrom(await request<unknown>(`/replies?status=${encodeURIComponent(status)}`), 'replies')
}

export async function reviewDraft(
  id: number,
  status: 'approved' | 'rejected',
  editedReply?: string,
): Promise<{ draft_id: number; published: false; status: string; reply_text: string }> {
  return request(`/replies/${id}/review`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      status,
      ...(editedReply !== undefined ? { edited_reply: editedReply } : {}),
    }),
  })
}

export function collectAll() {
  return request<OperationResult>('/collect/all', { method: 'POST' })
}
export function collectBluesky() {
  return request<OperationResult>('/collect/bluesky', { method: 'POST' })
}
export function collectGoogleSearch() {
  return request<OperationResult>('/collect/google-search', { method: 'POST' })
}
export function collectThematicSearch() {
  return request<OperationResult>('/collect/google-search/thematic', { method: 'POST' })
}
export function collectGoogleCustomSearch() {
  return request<OperationResult>('/collect/google-custom-search', { method: 'POST' })
}
export function collectYoutube() {
  return request<OperationResult>('/collect/youtube', { method: 'POST' })
}
export function collectGnews() {
  return request<OperationResult>('/collect/gnews', { method: 'POST' })
}
export function collectGdelt() {
  return request<OperationResult>('/collect/gdelt', { method: 'POST' })
}
export function analyzePending() {
  return request<OperationResult>('/analyze/pending', { method: 'POST' })
}
export function generatePendingReplies() {
  return request<OperationResult>('/replies/generate-pending', { method: 'POST' })
}
export function regenerateDraft(id: number) {
  return request<{ draft_id: number; reply_text: string; status: string; model_name: string }>(`/replies/${id}/regenerate`, { method: 'POST' })
}
export interface HealthStatus {
  api: string
  database: string
  ollama: string
  required_models: {
    classifier: boolean
    reply: boolean
  }
  installed_models: string[]
}

export function checkHealth() {
  return request<HealthStatus>('/health')
}
