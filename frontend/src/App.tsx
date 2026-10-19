import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, ArrowUpRight, ArrowRight, BarChart3, CheckCircle2, ClipboardList,
  ExternalLink, Filter, GraduationCap, LayoutDashboard, MapPin,
  Flag, MessageSquare, Radio, RefreshCw, Search, ShieldAlert,
  XCircle,
} from 'lucide-react'
import {
  analyzePending, collectAll, collectBluesky, collectGoogleSearch, collectThematicSearch, collectGoogleCustomSearch, collectGdelt,
  collectGnews, collectYoutube, fetchAnalyses, fetchDrafts, fetchOpportunities, fetchRecords,
  fetchStats, fetchTrendAnalysis, fetchAudienceInsights, fetchEngagementOpportunities, fetchStrategyPartners, fetchContentRecommendations,
  fetchPerformanceLearning, fetchAlerts,
  createContentRecommendation,
  createRecordReplyDraft, addRecordToStrategyRadar, updateRecordSpam,
  generateOpportunityDraft, generatePendingReplies, regenerateDraft, reviewDraft, rebuildDataQuality,
  updateRecordProvenance,
  reviewDuplicateLink,
} from './lib/api'
import type { AudienceInsights, ContentRecommendation, EngagementOpportunity, PerformanceLearning, RankedTrend, RecordAnalysis, ReplyDraft, SocialAlert, SocialRecord, Stats, StrategyPartner, TrainingOpportunity, TrendAnalysis } from './lib/api'
import ActionCenter from './ActionCenter'
import { INDIA_OUTLINE_PATH } from './indiaOutline'
import './App.css'

const navigationGroups = [
  { title: 'MONITOR', items: [
    { label: 'Overview', icon: LayoutDashboard },
    { label: 'Conversations', icon: MessageSquare },
    { label: 'Alerts & Learning', icon: ShieldAlert },
  ] },
  { title: 'UNDERSTAND', items: [
    { label: 'Insights', icon: BarChart3 },
    { label: 'Training Opportunities', icon: GraduationCap },
  ] },
  { title: 'ACT & GROW', items: [
    { label: 'Strategy Radar', icon: Radio },
    { label: 'Engagement Queue', icon: ClipboardList },
    { label: 'Content & Growth', icon: ArrowUpRight },
    { label: 'Reply Center', icon: CheckCircle2 },
  ] },
  { title: 'MEASURE', items: [
    { label: 'Reports', icon: BarChart3 },
  ] },
]
// Primary workflow keeps the core jobs in a predictable order; the sidebar remains
// available for direct access to every detailed tool.
const workflowStages = [
  { label: 'Listen', page: 'Conversations', hint: 'Collect and review public signals' },
  { label: 'Understand', page: 'Insights', hint: 'Explore audiences, needs, and trends' },
  { label: 'Prioritize', page: 'Strategy Radar', hint: 'Choose an opportunity worth acting on' },
  { label: 'Engage', page: 'Engagement Queue', hint: 'Assign an owner and plan follow-up' },
  { label: 'Create', page: 'Content & Growth', hint: 'Build an evidence-linked response' },
  { label: 'Learn', page: 'Reports', hint: 'Track outcomes and improve the next cycle' },
]
const sourceFilters = [
  { label: 'All sources', value: '' },
  { label: 'Bluesky', value: 'bluesky' },
  { label: 'Google Search', value: 'google_search' },
  { label: 'Google Custom Search', value: 'google_custom_search' },
  { label: 'YouTube', value: 'youtube' },
  { label: 'News', value: 'news' },
]
type ConversationFilters = {
  search: string
  period: string
  recordType: string
  relevance: string
  sentiment: string
  intent: string
  priority: string
  scope: string
}
type InsightDateRange = { from: string; to: string }
const EMPTY_CONVERSATION_FILTERS: ConversationFilters = {
  search: '', period: 'all', recordType: '', relevance: '', sentiment: '', intent: '', priority: '', scope: '',
}
const label = (value?: string | null) => value ? value.replace(/_/g, ' ') : '—'
const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : 'Request failed'
const focusArrival = (id: string) => {
  const element = document.getElementById(id)
  if (!element) return
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  element.classList.remove('arrival-highlight')
  // Restart the brief arrival cue when navigating repeatedly to the same record.
  void element.offsetWidth
  element.classList.add('arrival-highlight')
  window.setTimeout(() => element.classList.remove('arrival-highlight'), 3600)
}

function App() {
  const [activeNav, setActiveNav] = useState('Overview')
  const [insightDates, setInsightDates] = useState<InsightDateRange>({ from: '', to: '' })
  const [focusRecordId, setFocusRecordId] = useState<number | null>(null)
  const [activeSource, setActiveSource] = useState('')
  const [conversationFilters, setConversationFilters] = useState<ConversationFilters>(EMPTY_CONVERSATION_FILTERS)
  const [filterNow, setFilterNow] = useState(0)
  const [records, setRecords] = useState<SocialRecord[]>([])
  const [analyses, setAnalyses] = useState<RecordAnalysis[]>([])
  const [drafts, setDrafts] = useState<ReplyDraft[]>([])
  const [approvedReplies, setApprovedReplies] = useState<ReplyDraft[]>([])
  const [opportunities, setOpportunities] = useState<TrainingOpportunity[]>([])
  const [engagementItems, setEngagementItems] = useState<EngagementOpportunity[]>([])
  const [strategyPartners, setStrategyPartners] = useState<StrategyPartner[]>([])
  const [recommendations, setRecommendations] = useState<ContentRecommendation[]>([])
  const [trendAnalysis, setTrendAnalysis] = useState<TrendAnalysis | null>(null)
  const [audienceInsights, setAudienceInsights] = useState<AudienceInsights | null>(null)
  const [performanceLearning, setPerformanceLearning] = useState<PerformanceLearning | null>(null)
  const [alerts, setAlerts] = useState<SocialAlert[]>([])
  const [stats, setStats] = useState<Stats>({ total_records: 0, by_source: {} })
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState<string[]>([])
  const [operation, setOperation] = useState('')
  const [operationMessage, setOperationMessage] = useState('')
  const lastAutoFetchAt = useRef(0)
  const operationInProgress = useRef(false)
  const refreshSequence = useRef(0)

  const loadDashboard = useCallback(async () => {
    const sequence = ++refreshSequence.current
    setLoading(true)
    const results = await Promise.allSettled([
      fetchRecords(activeSource === 'news' ? undefined : activeSource || undefined),
      fetchAnalyses(),
      fetchDrafts(),
      fetchStats(),
      fetchOpportunities(),
      fetchTrendAnalysis(insightDates),
      fetchEngagementOpportunities(),
      fetchContentRecommendations(),
      fetchAudienceInsights(insightDates),
      fetchPerformanceLearning(),
      fetchAlerts(),
      fetchDrafts('approved'),
    ])
    // A slower response for an earlier filter/source selection must not replace newer data.
    if (sequence !== refreshSequence.current) return
    const nextErrors: string[] = []
    if (results[0].status === 'fulfilled') setRecords(results[0].value)
    else nextErrors.push(`Conversations: ${errorMessage(results[0].reason)}`)
    if (results[1].status === 'fulfilled') setAnalyses(results[1].value)
    else nextErrors.push(`Insights: ${errorMessage(results[1].reason)}`)
    if (results[2].status === 'fulfilled') setDrafts(results[2].value)
    else nextErrors.push(`Reply Center: ${errorMessage(results[2].reason)}`)
    if (results[3].status === 'fulfilled') setStats(results[3].value)
    else nextErrors.push(`Stats: ${errorMessage(results[3].reason)}`)
    if (results[4].status === 'fulfilled') setOpportunities(results[4].value)
    else nextErrors.push(`Training opportunities: ${errorMessage(results[4].reason)}`)
    if (results[5].status === 'fulfilled') setTrendAnalysis(results[5].value)
    else nextErrors.push(`Trend analysis: ${errorMessage(results[5].reason)}`)
    if (results[6].status === 'fulfilled') setEngagementItems(results[6].value)
    else nextErrors.push(`Engagement queue: ${errorMessage(results[6].reason)}`)
    if (results[7].status === 'fulfilled') setRecommendations(results[7].value)
    else nextErrors.push(`Content recommendations: ${errorMessage(results[7].reason)}`)
    if (results[8].status === 'fulfilled') setAudienceInsights(results[8].value)
    else nextErrors.push(`Audience insights: ${errorMessage(results[8].reason)}`)
    if (results[9].status === 'fulfilled') setPerformanceLearning(results[9].value)
    else nextErrors.push(`Performance learning: ${errorMessage(results[9].reason)}`)
    if (results[10].status === 'fulfilled') setAlerts(results[10].value.alerts)
    else nextErrors.push(`Alerts: ${errorMessage(results[10].reason)}`)
    if (results[11].status === 'fulfilled') setApprovedReplies(results[11].value)
    else nextErrors.push(`Approved reply history: ${errorMessage(results[11].reason)}`)
    // The radar reads opportunities populated by the previous request, so run it after that request commits.
    const strategyResult = await Promise.allSettled([fetchStrategyPartners()])
    if (sequence !== refreshSequence.current) return
    if (strategyResult[0].status === 'fulfilled') setStrategyPartners(strategyResult[0].value.partners)
    else nextErrors.push(`Strategy radar: ${errorMessage(strategyResult[0].reason)}`)
    setErrors(nextErrors)
    setLoading(false)
  }, [activeSource, insightDates])

  const analysisByRecord = useMemo(
    () => new Map(analyses.map((analysis) => [analysis.record_id, analysis])),
    [analyses],
  )
  const filteredRecords = useMemo(() => records.filter((record) => {
    const matchesSource = activeSource !== 'news' || ['gnews', 'gdelt'].includes(record.source.toLowerCase())
    const term = conversationFilters.search.toLowerCase().trim()
    return matchesSource && (!term || `${record.text} ${record.author || ''} ${record.source}`.toLowerCase().includes(term))
  }), [records, conversationFilters.search, activeSource])
  const runOperation = useCallback(async (name: string, action: () => Promise<Record<string, unknown>>) => {
    if (operationInProgress.current) return
    operationInProgress.current = true
    setOperation(name); setOperationMessage('')
    try {
      const result = await action()
      const status = typeof result.status === 'string' ? result.status : 'complete'
      setOperationMessage(/fetch|collect/i.test(name) ? `${name}: ${status}. Collection history has the per-source results.` : `${name}: ${status}.`)
      await loadDashboard()
    } catch (caught) {
      setOperationMessage(caught instanceof Error ? caught.message : `${name} failed`)
    } finally {
      operationInProgress.current = false
      setOperation('')
    }
  }, [loadDashboard])
  const collectionBusy = /fetch|collect/i.test(operation)

  const createSignalContentIdea = useCallback(async (input: { topic: string; text: string; recordId: number; audience: string; objective: string; format: string; confidence: number; priority: number; partner?: string }) => {
    if (recommendations.some((item) => ['idea', 'drafting', 'review', 'scheduled'].includes(item.status))) {
      setOperationMessage('There is already one open content item. Edit it in Content & Growth, or publish or pause it before creating another.')
      setActiveNav('Content & Growth')
      return
    }
    setOperation('Creating evidence-linked content idea')
    setOperationMessage('')
    try {
      await createContentRecommendation({
        topic: input.topic,
        idea: `Create a reviewed ${input.format.toLowerCase()} for ${input.audience}, using this public signal as evidence. Verify all claims, current programme details, consent, and contact routes before publishing.`,
        messaging: 'Respond to the need expressed in the linked conversation with accurate, practical guidance. Do not infer the author’s identity or imply an unconfirmed partnership.',
        call_to_action: input.objective === 'learner_reach' ? 'Invite learners to review the official course information or ask a follow-up question.' : 'Invite relevant stakeholders to explore the evidence and start a conversation through an approved channel.',
        rationale: `Created from a ${input.topic} signal. The source is a public conversation, not a representative audience survey. Validate the wording and programme details with the responsible team before use.`,
        evidence_record_ids: [input.recordId], pr_objective: input.objective, collaboration_partner: input.partner,
        target_audience: input.audience, recommended_format: input.format, hook: input.text.slice(0, 220),
        distribution_channel: 'Select after audience, consent, and channel review', priority_score: input.priority, confidence: input.confidence,
      })
      await loadDashboard()
      setActiveNav('Content & Growth')
      setOperationMessage(`Evidence-linked content idea saved for “${input.topic}”. Review and edit it in Content & Growth.`)
    } catch (error) {
      setOperationMessage(errorMessage(error))
    } finally { setOperation('') }
  }, [recommendations, loadDashboard])

  useEffect(() => {
    // Fetch current DB contents on open and keep the view in sync with collection runs.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadDashboard()
    if (!lastAutoFetchAt.current) lastAutoFetchAt.current = Date.now()
    const refreshTimer = window.setInterval(loadDashboard, 30000)
    const autoCollect = () => {
      const now = Date.now()
      if (document.visibilityState !== 'visible' || operationInProgress.current || now - lastAutoFetchAt.current < 30 * 60 * 1000) return
      lastAutoFetchAt.current = now
      void runOperation('Scheduled fetch (30 min)', collectAll)
    }
    const autoFetchTimer = window.setInterval(autoCollect, 60000)
    document.addEventListener('visibilitychange', autoCollect)
    return () => {
      window.clearInterval(refreshTimer)
      window.clearInterval(autoFetchTimer)
      document.removeEventListener('visibilitychange', autoCollect)
    }
  }, [loadDashboard, runOperation])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Activity size={22} /></div><div><h1>Social Pulse</h1><span>SOCIAL LISTENING</span></div></div>
        <nav className="navigation" aria-label="Main navigation">{navigationGroups.map((group) => <div className="nav-group" key={group.title}><div className="workspace-label">{group.title}</div>{group.items.map(({ label: item, icon: Icon }) => <button key={item} title={item} aria-current={activeNav === item ? 'page' : undefined} className={`nav-item ${activeNav === item ? 'active' : ''}`} onClick={() => setActiveNav(item)}><Icon size={18} /><span>{item}</span>{item === 'Reply Center' && drafts.length > 0 && <span className="nav-count">{drafts.length}</span>}{item === 'Training Opportunities' && opportunities.length > 0 && <span className="nav-count">{opportunities.length}</span>}</button>)}</div>)}</nav>
        <div className="sidebar-bottom"><div className="profile"><div className="avatar">SP</div><div className="profile-copy"><strong>Social Pulse</strong><span>Tata STRIVE workspace</span></div></div></div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div className="breadcrumbs"><span>Social Pulse</span><span className="breadcrumb-separator">/</span><strong>{activeNav}</strong></div><div className="topbar-actions"><button className="primary-button" disabled={Boolean(operation)} onClick={() => void runOperation('Fetch live data', collectAll)}>{collectionBusy ? <RefreshCw className="spin" size={15} /> : <RefreshCw size={15} />}{collectionBusy ? 'Fetching…' : 'Fetch data'}</button><button className="icon-button" aria-label="Refresh data" title="Refresh data" onClick={() => void loadDashboard()}><RefreshCw size={17} /></button></div></header>
        <div className="page-content">
          <nav className="workflow-strip" aria-label="Social Pulse workflow">
            <div className="workflow-strip-heading"><span>WORKFLOW</span><small>{workflowStages.find((stage) => stage.page === activeNav)?.hint || 'Start with a snapshot, then follow signals through to outcomes'}</small></div>
            <div className="workflow-stage-list">{workflowStages.map((stage, index) => <button key={stage.page} type="button" className={`workflow-stage ${activeNav === stage.page ? 'current' : ''}`} aria-current={activeNav === stage.page ? 'step' : undefined} onClick={() => setActiveNav(stage.page)}><span className="workflow-stage-number">{String(index + 1).padStart(2, '0')}</span><span>{stage.label}</span>{index < workflowStages.length - 1 && <span className="workflow-stage-connector" aria-hidden="true" />}</button>)}</div>
          </nav>
          {errors.length > 0 && <div className="notice-stack">{errors.map((item) => <div className="notice error" key={item}><XCircle size={15} /> {item}</div>)}</div>}
          {operationMessage && <div className="notice"><CheckCircle2 size={15} /> {operationMessage}</div>}
          {activeNav === 'Overview' && <OverviewDashboard stats={stats} trends={trendAnalysis} audience={audienceInsights} alerts={alerts} drafts={drafts} partners={strategyPartners} records={records} analyses={analysisByRecord} onNavigate={setActiveNav} onOpenSentiment={(sentiment) => { setActiveSource(''); setFilterNow(Date.now()); setConversationFilters({ ...EMPTY_CONVERSATION_FILTERS, scope: 'brand', period: '30', sentiment }); setActiveNav('Conversations') }} onOpenConversation={(id) => { setFocusRecordId(id); setActiveNav('Conversations') }} />}
          {activeNav === 'Conversations' && <ConversationPanel focusRecordId={focusRecordId} records={filteredRecords} totalRecords={records.length} analyses={analysisByRecord} filters={conversationFilters} setFilters={setConversationFilters} filterNow={filterNow} setFilterNow={setFilterNow} activeSource={activeSource} setActiveSource={setActiveSource} loading={loading} pendingReplyRecordIds={new Set(drafts.map((draft) => draft.record_id))} strategyRecordIds={new Set(strategyPartners.flatMap((partner) => partner.evidence.map((item) => item.record_id)))} onCreateReply={async (id) => { try { await createRecordReplyDraft(id); setFocusRecordId(id); await loadDashboard(); setActiveNav('Reply Center'); setOperationMessage('Reply draft is ready for review in Reply Center.') } catch (error) { setOperationMessage(errorMessage(error)) } }} onAddToStrategy={async (id) => { try { await addRecordToStrategyRadar(id); setFocusRecordId(id); await loadDashboard(); setActiveNav('Strategy Radar'); setOperationMessage('Conversation added to Strategy Radar for human review.') } catch (error) { setOperationMessage(errorMessage(error)) } }} />}
          {activeNav === 'Insights' && <Insights data={trendAnalysis} audience={audienceInsights} dates={insightDates} onDatesChange={setInsightDates} onCreateContentIdea={(trend) => void createSignalContentIdea({ topic: trend.topic, text: trend.examples[0]?.text || trend.topic, recordId: trend.examples[0]?.record_id, audience: trend.leading_audience || 'people whose needs are reflected in the linked evidence', objective: /training|course|skill|employment|job|placement/i.test(trend.topic) ? 'learner_reach' : 'ecosystem_influence', format: trend.questions >= 2 ? 'FAQ carousel or short explainer' : 'Evidence-led short explainer', confidence: Math.min(0.8, trend.examples[0]?.confidence || 0.4), priority: trend.score })} onOpenConversation={(id) => { setFocusRecordId(id); setActiveSource(''); setConversationFilters(EMPTY_CONVERSATION_FILTERS); setActiveNav('Conversations') }} />}
          {activeNav === 'Reply Center' && <ReplyCenter focusRecordId={focusRecordId} drafts={drafts} approvedReplies={approvedReplies} analyses={analysisByRecord} records={records} onRefresh={loadDashboard} onOpenConversation={(id) => { setFocusRecordId(id); setActiveSource(''); setConversationFilters(EMPTY_CONVERSATION_FILTERS); setActiveNav('Conversations') }} />}
          {activeNav === 'Training Opportunities' && <OpportunityPanel focusRecordId={focusRecordId} opportunities={opportunities} hasOpenContentItem={recommendations.some((item) => ['idea', 'drafting', 'review', 'scheduled'].includes(item.status))} onCreateContentIdea={(opportunity) => void createSignalContentIdea({ topic: `Learner content: ${opportunity.skills.join(', ') || opportunity.request_type}`, text: opportunity.text, recordId: opportunity.record_id, audience: 'people asking about training, skills, or course access', objective: 'learner_reach', format: opportunity.suggested_course ? 'Course guidance explainer' : 'Training enquiry FAQ', confidence: 0.65, priority: 72 })} onRefresh={loadDashboard} onOpenReplyCenter={(id) => { setFocusRecordId(id); setActiveNav('Reply Center') }} onOpenConversation={(id) => { setFocusRecordId(id); setActiveSource(''); setConversationFilters(EMPTY_CONVERSATION_FILTERS); setActiveNav('Conversations') }} />}
          {['Strategy Radar', 'Engagement Queue', 'Content & Growth', 'Alerts & Learning'].includes(activeNav) && <ActionCenter activePage={activeNav} focusRecordId={focusRecordId} focusSection={activeNav === 'Strategy Radar' ? 'strategy-radar' : activeNav === 'Engagement Queue' ? 'engagement-queue' : activeNav === 'Content & Growth' ? 'content-growth' : 'alerts-learning'} onOpenConversation={(id) => { setFocusRecordId(id); setActiveSource(''); setConversationFilters(EMPTY_CONVERSATION_FILTERS); setActiveNav('Conversations') }} onOpenReplyCenter={(id) => { setFocusRecordId(id); setActiveNav('Reply Center') }} onOpenTrainingOpportunity={(id) => { setFocusRecordId(id); setActiveNav('Training Opportunities') }} opportunities={engagementItems} recommendations={recommendations} partners={strategyPartners} trends={trendAnalysis} audienceInsights={audienceInsights} learning={performanceLearning} alerts={alerts} onRefresh={loadDashboard} />}
          {activeNav === 'Reports' && <Operations operation={operation} runOperation={runOperation} runs={stats.latest_collections || []} />}
          <footer className="page-footer"><span>SOCIAL PULSE</span><span>Public conversation monitoring for Tata STRIVE</span></footer>
        </div>
      </main>
    </div>
  )
}

function OverviewDashboard({ stats, trends, audience, alerts, drafts, partners, records, analyses, onNavigate, onOpenSentiment, onOpenConversation }: {
  stats: Stats; trends: TrendAnalysis | null; audience: AudienceInsights | null; alerts: SocialAlert[];
  drafts: ReplyDraft[]; partners: StrategyPartner[]; records: SocialRecord[]; analyses: Map<number, RecordAnalysis>;
  onNavigate: (page: string) => void; onOpenSentiment: (sentiment: string) => void; onOpenConversation: (id: number) => void
}) {
  // The trend API can return the same topic once per monitoring scope. Show one
  // radar row per normalized topic, combining its scope counts and keeping the
  // strongest score/lifecycle for ranking.
  const topTrends = Object.values((trends?.trends || []).reduce<Record<string, { trend: RankedTrend; streams: Map<string, number> }>>((groups, trend) => {
    const key = trend.topic.trim().toLocaleLowerCase()
    const group = groups[key] || (groups[key] = { trend, streams: new Map() })
    const scope = trend.monitoring_scope || 'brand'
    group.streams.set(scope, Math.max(group.streams.get(scope) || 0, trend.count))
    if (trend.score > group.trend.score) group.trend = trend
    return groups
  }, {})).map(({ trend, streams }) => ({ ...trend, count: [...streams.values()].reduce((sum, count) => sum + count, 0) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
  const topNeeds = audience?.top_needs.slice(0, 5) || []
  const maxTrendScore = Math.max(1, ...topTrends.map((item) => item.score))
  const maxNeedCount = Math.max(1, ...topNeeds.map((item) => item.count))
  const [sentimentDays, setSentimentDays] = useState<7 | 30 | 90>(7)
  const sentimentCutoff = Date.now() - sentimentDays * 86400000
  const brandSignals = records.filter((record) => {
    const activityDate = record.published_at || record.collected_at
    const analysis = analyses.get(record.id)
    return (record.monitoring_scope || 'brand') === 'brand' && !record.is_simulated && !record.duplicate_of_record_id && ['social_post', 'comment'].includes(record.record_type) && Boolean(activityDate && new Date(activityDate).getTime() >= sentimentCutoff) && Boolean(analysis?.sentiment)
  })
  const sentimentOrder = ['positive', 'neutral', 'mixed', 'negative', 'uncertain']
  const sentimentCounts = sentimentOrder.map((sentiment) => ({ sentiment, count: brandSignals.filter((record) => analyses.get(record.id)?.sentiment === sentiment).length })).filter((item) => item.count > 0)
  const sentimentTotal = sentimentCounts.reduce((sum, item) => sum + item.count, 0)
  const sentimentAction: Record<string, { summary: string; page: string; action: string }> = {
    negative: { summary: 'Triage complaints and concerns; verify the source and urgency, then draft a careful response or assign follow-up.', page: 'Engagement Queue', action: 'Open response queue' },
    mixed: { summary: 'Review context and evidence before responding; clarify what is working and what needs attention.', page: 'Insights', action: 'Review insight context' },
    neutral: { summary: 'Look for questions or information gaps and share a verified resource where it helps.', page: 'Engagement Queue', action: 'Find conversations to help' },
    positive: { summary: 'Identify suitable stories or themes; obtain consent and verify claims before planning content.', page: 'Content & Growth', action: 'Plan positive-story content' },
    uncertain: { summary: 'Check original source context and analysis confidence before taking action.', page: 'Conversations', action: 'Inspect source conversations' },
  }
  const shortcuts = [
    { page: 'Conversations', title: 'Review conversations', detail: `${stats.total_social_mentions || 0} social posts and comments`, Icon: MessageSquare },
    { page: 'Insights', title: 'Explore insights', detail: `${trends?.trends.length || 0} topic groups · audience needs`, Icon: BarChart3 },
    { page: 'Engagement Queue', title: 'Manage engagement', detail: `${stats.high_priority_social_mentions || 0} high-priority signals`, Icon: ClipboardList },
    { page: 'Content & Growth', title: 'Plan content', detail: `${stats.pending_reply_drafts ?? drafts.length} reply drafts · ${partners.length} partner leads`, Icon: ArrowUpRight },
  ]
  return <div className="overview-dashboard">
    <section className="overview-heading"><div><span className="section-kicker">TATA STRIVE · SOCIAL INTELLIGENCE</span><h1>Overview</h1><p>Recent activity, audience signals, and the next actions for your team.</p></div><button className="secondary-button" onClick={() => onNavigate('Reports')}>View collection history <ArrowRight size={14} /></button></section>
    <section className="overview-metrics" aria-label="Workspace summary">
      <button className="overview-metric" onClick={() => onNavigate('Conversations')}><span>Unique records</span><strong>{stats.unique_records ?? stats.total_records ?? 0}</strong><small>{stats.duplicate_records || 0} likely duplicates · {stats.simulated_records || 0} sample records</small></button>
      <button className="overview-metric" onClick={() => onNavigate('Insights')}><span>Relevant conversations</span><strong>{trends?.relevant_records ?? '—'}</strong><small>{stats.recent_social_mentions || 0} social records in the last 30 days</small></button>
      <button className="overview-metric" onClick={() => onNavigate('Alerts & Learning')}><span>Needs attention</span><strong>{alerts.length}</strong><small>Risk, growth, and due follow-up signals</small></button>
      <button className="overview-metric" onClick={() => onNavigate('Strategy Radar')}><span>Partner candidates</span><strong>{partners.length}</strong><small>Public signals requiring verification</small></button>
    </section>
    <section className="overview-grid">
      <article className="overview-card"><div className="overview-card-heading"><div><span className="section-kicker">TREND RADAR</span><h2>Topics to review</h2><p>Ranked conversation signals from the selected date range.</p></div><button className="text-link" onClick={() => onNavigate('Insights')}>All insights <ArrowRight size={14} /></button></div>
        {topTrends.length ? <div className="overview-bars" role="list" aria-label="Highest priority trends">{topTrends.map((item) => <button className="overview-bar-row" key={`${item.monitoring_scope}-${item.topic}`} onClick={() => onNavigate('Insights')} role="listitem"><span>{label(item.topic)}<small>{item.count} records · {item.lifecycle}</small></span><i><b style={{ width: `${Math.max(5, item.score / maxTrendScore * 100)}%` }} /></i><strong>{item.score}</strong></button>)}</div> : <p className="overview-empty">Trend analysis will appear after relevant conversations are collected.</p>}
      </article>
      <article className="overview-card"><div className="overview-card-heading"><div><span className="section-kicker">AUDIENCE INTELLIGENCE</span><h2>What people need</h2><p>Common needs in relevant public conversations.</p></div><button className="text-link" onClick={() => onNavigate('Insights')}>Audience insights <ArrowRight size={14} /></button></div>
        {topNeeds.length ? <div className="overview-needs">{topNeeds.map((item) => <div className="overview-need" key={item.need}><div><span>{label(item.need)}</span><strong>{item.count}</strong></div><i><b style={{ width: `${Math.max(5, item.count / maxNeedCount * 100)}%` }} /></i></div>)}</div> : <p className="overview-empty">Audience needs will appear after relevant conversations are analyzed.</p>}
        <div className="overview-audience-note">{audience?.sample_size ?? 0} relevant posts/comments in the selected insight window. Estimates describe conversation wording, not verified author identities.</div>
      </article>
    </section>
    <section className="overview-sentiment-card" aria-labelledby="brand-sentiment-title">
      <div className="overview-card-heading"><div><span className="section-kicker">BRAND SENTIMENT</span><h2 id="brand-sentiment-title">Recent Tata STRIVE conversations</h2><p>Sentiment labels from analyzed public posts and comments. They are model estimates, not verified opinions.</p></div><div className="sentiment-window" aria-label="Sentiment date window">{([7, 30, 90] as const).map((days) => <button key={days} className={sentimentDays === days ? 'selected' : ''} onClick={() => setSentimentDays(days)}>{days} days</button>)}</div></div>
      {sentimentTotal > 0 ? <>
        <div className="sentiment-summary"><div className="sentiment-stacked-bar" role="img" aria-label={sentimentCounts.map((item) => `${item.sentiment}: ${item.count}`).join(', ')}>{sentimentCounts.map((item) => <i key={item.sentiment} className={`sentiment-segment ${item.sentiment}`} style={{ width: `${item.count / sentimentTotal * 100}%` }} title={`${label(item.sentiment)}: ${item.count}`} />)}</div><span>{sentimentTotal} analyzed brand posts/comments · last {sentimentDays} days</span></div>
        <div className="sentiment-actions-list">{sentimentCounts.map(({ sentiment, count }) => { const plan = sentimentAction[sentiment] || sentimentAction.uncertain; return <article className="sentiment-action-row" key={sentiment}><div className={`sentiment-indicator ${sentiment}`} /><div className="sentiment-action-copy"><strong>{label(sentiment)} <span>{count} · {Math.round(count / sentimentTotal * 100)}%</span></strong><p>{plan.summary}</p></div><div className="sentiment-action-buttons"><button className="text-link" onClick={() => onOpenSentiment(sentiment)}>Review mentions <ArrowRight size={13} /></button><button className="secondary-button" onClick={() => onNavigate(plan.page)}>{plan.action} <ArrowUpRight size={13} /></button></div></article> })}</div>
      </> : <div className="sentiment-empty"><strong>No analyzed brand conversations in the last {sentimentDays} days.</strong><span>Fetch data and analyze eligible public posts or comments to populate this view.</span><button className="text-link" onClick={() => onNavigate('Conversations')}>Open conversations <ArrowRight size={13} /></button></div>}
      <div className="sentiment-footnote">Date uses publication time when available, otherwise first collection time. Sample coverage and sentiment classification can be incomplete or inaccurate.</div>
    </section>
    <section className="overview-grid overview-lower-grid">
      <article className="overview-card"><div className="overview-card-heading"><div><span className="section-kicker">TEAM ACTIONS</span><h2>Signals needing review</h2></div><button className="text-link" onClick={() => onNavigate('Alerts & Learning')}>Open alerts <ArrowRight size={14} /></button></div>
        {alerts.length ? <div className="overview-alerts">{alerts.slice(0, 4).map((alert) => <div className="overview-alert" key={alert.id}><div><span className={`attention-badge ${alert.severity === 'critical' ? 'immediate-attention' : alert.severity === 'high' ? 'high-priority' : 'monitor'}`}>{alert.severity}</span><strong>{alert.title}</strong><small>{alert.detail}</small></div><div className="overview-alert-actions">{alert.record_id && <button className="text-link" onClick={() => onOpenConversation(alert.record_id!)}>Conversation <ArrowRight size={13} /></button>}{alert.reply_draft_id && alert.record_id && <button className="text-link" onClick={() => onNavigate('Reply Center')}>Reply draft <ArrowRight size={13} /></button>}</div></div>)}</div> : <p className="overview-empty">No alert conditions are currently met.</p>}
      </article>
      <article className="overview-card"><div className="overview-card-heading"><div><span className="section-kicker">WORKSPACE</span><h2>Go to a work area</h2></div></div><div className="overview-shortcuts">{shortcuts.map(({ page, title, detail, Icon }) => <button className="overview-shortcut" key={page} onClick={() => onNavigate(page)}><span className="shortcut-icon"><Icon size={17} /></span><span><strong>{title}</strong><small>{detail}</small></span><ArrowRight size={15} /></button>)}<button className="overview-shortcut" onClick={() => onNavigate('Training Opportunities')}><span className="shortcut-icon"><GraduationCap size={17} /></span><span><strong>Training enquiries</strong><small>Review requests for courses, skills, and locations</small></span><ArrowRight size={15} /></button></div></article>
    </section>
  </div>
}

function ConversationPanel({ focusRecordId, records, totalRecords, analyses, filters, setFilters, filterNow, setFilterNow, activeSource, setActiveSource, loading, pendingReplyRecordIds, strategyRecordIds, onCreateReply, onAddToStrategy }: { focusRecordId: number | null; records: SocialRecord[]; totalRecords: number; analyses: Map<number, RecordAnalysis>; filters: ConversationFilters; setFilters: (filters: ConversationFilters) => void; filterNow: number; setFilterNow: (value: number) => void; activeSource: string; setActiveSource: (value: string) => void; loading: boolean; pendingReplyRecordIds: Set<number>; strategyRecordIds: Set<number>; onCreateReply: (recordId: number) => Promise<void>; onAddToStrategy: (recordId: number) => Promise<void> }) {
  useEffect(() => {
    if (focusRecordId == null) return
    const timer = window.setTimeout(() => focusArrival(`conversation-${focusRecordId}`), 100)
    return () => window.clearTimeout(timer)
  }, [focusRecordId, records])
  const setFilter = <K extends keyof ConversationFilters>(key: K, value: ConversationFilters[K]) => setFilters({ ...filters, [key]: value })
  const cutoff = filters.period === 'all' ? null : filterNow - Number(filters.period) * 86400000
  const visibleRecords = records.filter((record) => {
    const analysis = analyses.get(record.id)
    if (record.source === 'youtube' && record.record_type !== 'comment') return false
    if (filters.recordType && record.record_type !== filters.recordType) return false
    if (filters.scope && (record.monitoring_scope || 'brand') !== filters.scope) return false
    if (filters.relevance && analysis?.relevance_type !== filters.relevance) return false
    if (filters.sentiment && analysis?.sentiment !== filters.sentiment) return false
    if (filters.intent && analysis?.intent !== filters.intent) return false
    if (filters.priority && analysis?.priority !== filters.priority) return false
    const activityDate = record.published_at || record.collected_at
    if (cutoff && (!activityDate || new Date(activityDate).getTime() < cutoff)) return false
    return true
  })
  const emptyTitle = loading ? 'Loading conversations…' : totalRecords === 0 ? 'No records collected yet' : 'No matching conversations'
  const emptyDescription = loading ? 'Fetching evidence from the FastAPI backend.' : totalRecords === 0 ? 'Use the operational controls to collect records from a configured source.' : 'Try another source or search term.'
  const activeFilterCount = Object.entries(filters).filter(([, value]) => Boolean(value)).length
  return <article className="panel conversation-panel"><div className="panel-header"><div><div className="section-kicker">LIVE MONITORING</div><h3>Conversation stream</h3><p>{activeSource === 'youtube' ? 'YouTube shows comment text with a link to that comment in its video.' : 'Brand and thematic posts are labeled separately from search previews and news.'}</p></div><span className="live-badge"><span className="status-dot" /> {loading ? 'REFRESHING' : `${visibleRecords.length} MATCHING RECORDS`}</span></div><div className="feed-toolbar"><div className="source-tabs">{sourceFilters.map((source) => <button key={source.value} className={`source-tab ${activeSource === source.value ? 'selected' : ''}`} onClick={() => setActiveSource(source.value)}><Filter size={14} />{source.label}</button>)}</div><div className="feed-search"><Search size={15} /><input value={filters.search} onChange={(event) => setFilter('search', event.target.value)} placeholder="Search mentions or authors..." /></div></div><div className="filter-row"><select aria-label="Monitoring scope" value={filters.scope} onChange={(e) => setFilter('scope', e.target.value)}><option value="">All monitoring scopes</option><option value="brand">Direct Tata STRIVE</option><option value="thematic">Broader themes</option></select><select aria-label="Date range" value={filters.period} onChange={(e) => { setFilterNow(Date.now()); setFilter('period', e.target.value) }}><option value="all">All dates</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select><select aria-label="Content type" value={filters.recordType} onChange={(e) => setFilter('recordType', e.target.value)}><option value="">All content types</option><option value="social_post">Social posts</option><option value="comment">Comments</option><option value="news">News</option><option value="search_result">Google search results</option></select><select aria-label="Relevance" value={filters.relevance} onChange={(e) => setFilter('relevance', e.target.value)}><option value="">All relevance</option><option value="direct_brand">Direct brand</option><option value="industry">Industry</option><option value="unrelated">Unrelated</option></select><select aria-label="Sentiment" value={filters.sentiment} onChange={(e) => setFilter('sentiment', e.target.value)}><option value="">All sentiment</option>{['positive','negative','neutral','mixed','uncertain'].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select><select aria-label="Intent" value={filters.intent} onChange={(e) => setFilter('intent', e.target.value)}><option value="">All intent</option>{['question','complaint','praise','suggestion','discussion','news','other'].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select><select aria-label="Priority" value={filters.priority} onChange={(e) => setFilter('priority', e.target.value)}><option value="">All priority</option>{['low','medium','high'].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select><button className="secondary-button" disabled={!activeFilterCount} onClick={() => setFilters(EMPTY_CONVERSATION_FILTERS)}>Clear filters{activeFilterCount ? ` (${activeFilterCount})` : ''}</button></div><div className="record-list">{visibleRecords.length ? visibleRecords.map((record) => <RecordItem key={record.id} record={record} analysis={analyses.get(record.id)} hasPendingReply={pendingReplyRecordIds.has(record.id)} inStrategyRadar={strategyRecordIds.has(record.id)} onCreateReply={onCreateReply} onAddToStrategy={onAddToStrategy} />) : <div className="empty-feed"><div className="empty-icon"><Radio size={24} /></div><h4>{records.length ? 'No matching conversations' : emptyTitle}</h4><p>{records.length ? 'Adjust the filters or search term.' : emptyDescription}</p></div>}</div><div className="panel-footer"><span>DATA SOURCE: FASTAPI</span><span>RECORDS: {visibleRecords.length} shown · {totalRecords} loaded</span></div></article>
}

function RecordItem({ record, analysis, hasPendingReply, inStrategyRadar, onCreateReply, onAddToStrategy }: { record: SocialRecord; analysis?: RecordAnalysis; hasPendingReply: boolean; inStrategyRadar: boolean; onCreateReply: (recordId: number) => Promise<void>; onAddToStrategy: (recordId: number) => Promise<void> }) {
  const isSearchResult = record.record_type === 'search_result'
  const [simulated, setSimulated] = useState(Boolean(record.is_simulated))
  const [duplicateOf, setDuplicateOf] = useState<number | null>(record.duplicate_of_record_id ?? null)
  const [duplicateSaving, setDuplicateSaving] = useState(false)
  const [provenanceSaving, setProvenanceSaving] = useState(false)
  const [spamSaving, setSpamSaving] = useState(false)
  const [actionBusy, setActionBusy] = useState('')
  const [isSpam, setIsSpam] = useState(Boolean(record.is_spam))
  const [provenanceError, setProvenanceError] = useState('')
  async function toggleSimulation() {
    setProvenanceSaving(true); setProvenanceError('')
    try {
      const next = !simulated
      await updateRecordProvenance(record.id, next)
      setSimulated(next)
    } catch (error) { setProvenanceError(errorMessage(error)) } finally { setProvenanceSaving(false) }
  }
  async function markDistinct() {
    setDuplicateSaving(true)
    try { await reviewDuplicateLink(record.id, null); setDuplicateOf(null) } catch (error) { setProvenanceError(errorMessage(error)) } finally { setDuplicateSaving(false) }
  }
  async function toggleSpam() {
    setSpamSaving(true); setProvenanceError('')
    try { const result = await updateRecordSpam(record.id, !isSpam); setIsSpam(result.is_spam) }
    catch (error) { setProvenanceError(errorMessage(error)) }
    finally { setSpamSaving(false) }
  }
  return <div id={`conversation-${record.id}`} className={`record-item ${isSpam ? 'record-item-spam' : ''}`}><div className="record-meta"><span className="source-chip">{record.source} · {isSearchResult ? 'Google search result' : record.record_type}</span><span>{label(record.monitoring_scope || 'brand')} stream</span><span>Language: {record.language_code || 'und'}</span>{isSpam && <span className="spam-badge">Marked as spam</span>}{duplicateOf && <span className="quality-badge duplicate-badge">{record.duplicate_review_state === 'confirmed_duplicate' ? 'Confirmed duplicate' : 'Possible duplicate'} of #{duplicateOf} · {Math.round((record.duplicate_match_score || 0) * 100)}%</span>}{record.duplicate_review_state === 'confirmed_distinct' && <span className="quality-badge">Reviewed · distinct</span>}{simulated && <span className="quality-badge simulated-badge">Simulated data</span>}{record.query_provenance && <span>Query: {record.query_provenance.replace('bluesky:', '')}</span>}<span>Published {record.published_at ? new Date(record.published_at).toLocaleString() : 'date unavailable'} · collected {record.collected_at ? new Date(record.collected_at).toLocaleString() : 'date unavailable'}</span></div><p>{record.text}</p><div className="record-details">{record.author && <span>{isSearchResult ? `Result page: ${record.author}` : record.author}</span>}<span>Likely audience/need: {label(record.audience_segment || 'unclear')} · {label(record.audience_need || 'unclear')} · {Math.round((record.audience_confidence || 0) * 100)}% text confidence</span><span>Relevance: {label(analysis?.relevance_type || 'estimated')}</span><span>Sentiment: {label(analysis?.sentiment || 'estimated')} · Score {record.sentiment_score?.toFixed(2) ?? '—'}</span><span>Topic: {label(analysis?.topic || 'estimated from keywords')}</span><span>Intent: {label(analysis?.intent || 'estimated')}</span><span>Priority: {label(analysis?.priority || 'estimated')} · {record.importance_score ?? '—'}/100</span><span>Repeated keywords: {record.keyword_counts?.length ? record.keyword_counts.map((item) => `${item.term} ×${item.count}`).join(', ') : 'none detected'}</span>{analysis && <span>{analysis.rationale}</span>}{isSearchResult && <span>Search snippet estimate only · not an original comment</span>}{record.like_count != null && <span>Likes: {record.like_count}</span>}{record.reply_count != null && <span>Replies: {record.reply_count}</span>}{record.view_count != null && <span>Views: {record.view_count}</span>}{record.provenance_note && <span>{record.provenance_note}</span>}{provenanceError && <span className="record-action-error">{provenanceError}</span>}{duplicateOf && <button type="button" className="secondary-button" disabled={duplicateSaving} onClick={() => void markDistinct()}>{duplicateSaving ? 'Saving…' : 'Mark these as distinct'}</button>}<button type="button" className="secondary-button" disabled={provenanceSaving} onClick={() => void toggleSimulation()}>{provenanceSaving ? 'Saving…' : simulated ? 'Unmark simulated' : 'Mark simulated/demo'}</button><button type="button" className={`secondary-button ${isSpam ? 'spam-action' : ''}`} disabled={spamSaving} onClick={() => void toggleSpam()}>{spamSaving ? 'Saving…' : <><Flag size={13} />{isSpam ? 'Undo spam mark' : 'Mark as spam'}</>}</button><button type="button" className="secondary-button" disabled={Boolean(actionBusy) || isSpam || !['comment','social_post'].includes(record.record_type)} title={isSpam ? 'Spam-marked content cannot receive a reply' : !['comment','social_post'].includes(record.record_type) ? 'Only original posts or comments can receive a reply' : 'Create a review-only reply draft'} onClick={async () => { setActionBusy('reply'); setProvenanceError(''); try { await onCreateReply(record.id) } catch (error) { setProvenanceError(errorMessage(error)) } finally { setActionBusy('') } }}>{actionBusy === 'reply' ? 'Creating…' : hasPendingReply ? <><MessageSquare size={13} /> Open reply draft</> : <><MessageSquare size={13} /> Create reply</>}</button><button type="button" className="secondary-button" disabled={Boolean(actionBusy) || isSpam} title={isSpam ? 'Unmark spam before adding to Strategy Radar' : 'Add this conversation for human review in Strategy Radar'} onClick={async () => { setActionBusy('strategy'); setProvenanceError(''); try { await onAddToStrategy(record.id) } catch (error) { setProvenanceError(errorMessage(error)) } finally { setActionBusy('') } }}>{actionBusy === 'strategy' ? 'Adding…' : <><Radio size={13} />{inStrategyRadar ? 'View in Strategy Radar' : 'Add to Strategy Radar'}</>}</button>{record.url && <a href={record.url} target="_blank" rel="noopener noreferrer">{record.source === 'youtube' && record.record_type === 'comment' ? 'Open comment in video' : 'Open source'} <ExternalLink size={12} /></a>}</div></div>
}

const INSIGHT_PLACE_COORDINATES: Record<string, [number, number]> = {
  'new delhi': [77.21, 28.61], delhi: [77.21, 28.61], mumbai: [72.88, 19.08], bengaluru: [77.59, 12.97], bangalore: [77.59, 12.97], chennai: [80.27, 13.08], hyderabad: [78.49, 17.39], kolkata: [88.36, 22.57], pune: [73.86, 18.52], ahmedabad: [72.57, 23.02], jaipur: [75.79, 26.91], lucknow: [80.95, 26.85], patna: [85.14, 25.59], bhopal: [77.41, 23.26], indore: [75.86, 22.72], surat: [72.83, 21.17], vadodara: [73.18, 22.31], nagpur: [79.09, 21.15], kochi: [76.27, 9.93], thiruvananthapuram: [76.94, 8.52], bhubaneswar: [85.82, 20.30], chandigarh: [76.78, 30.73], noida: [77.39, 28.54], gurugram: [77.03, 28.46], gurgaon: [77.03, 28.46], ghaziabad: [77.45, 28.67], varanasi: [82.97, 25.32], ranchi: [85.31, 23.34], dehradun: [78.03, 30.32], mysuru: [76.64, 12.30], mysore: [76.64, 12.30], mangaluru: [74.86, 12.91], mangalore: [74.86, 12.91], coimbatore: [76.96, 11.02], visakhapatnam: [83.22, 17.69], guwahati: [91.74, 26.14], jamshedpur: [86.20, 22.80], nashik: [73.79, 19.99], amritsar: [74.87, 31.63],
}

function InsightLocationMap({ locations, onOpenConversation }: { locations: NonNullable<AudienceInsights['location_mentions']>; onOpenConversation: (recordId: number) => void }) {
  const points = locations.flatMap((item) => {
    const coords = INSIGHT_PLACE_COORDINATES[item.place.toLocaleLowerCase()]
    return coords ? [{ ...item, longitude: coords[0], latitude: coords[1] }] : []
  })
  const maxCount = Math.max(1, ...points.map((point) => point.count))
  const project = (longitude: number, latitude: number) => ({ x: 35 + (longitude - 68) / 30 * 330, y: 20 + (37 - latitude) / 32 * 365 })
  return <section className="insight-location-panel">
    <div className="insight-location-heading"><div><h4>Where conversations mention places</h4><p>Mapped place mentions from the selected date range. Markers show conversation volume.</p></div><span>{points.reduce((sum, point) => sum + point.count, 0)} mapped mentions</span></div>
    {points.length ? <div className="insight-location-layout"><div className="insight-map-wrap"><svg className="insight-india-map" viewBox="0 0 400 410" role="img" aria-label={`Map of India with ${points.length} cities referenced in conversations`}>
      <path className="insight-map-land" d={INDIA_OUTLINE_PATH} />
      <text x="162" y="205" className="insight-map-label">INDIA</text>
      {points.map((point) => { const { x, y } = project(point.longitude, point.latitude); const radius = 5 + Math.sqrt(point.count / maxCount) * 8; return <g key={point.place} className="insight-map-marker" role="button" tabIndex={0} aria-label={`${point.place}: ${point.count} mentions; open supporting conversation`} onClick={() => point.evidence[0] && onOpenConversation(point.evidence[0].record_id)} onKeyDown={(event) => { if ((event.key === 'Enter' || event.key === ' ') && point.evidence[0]) { event.preventDefault(); onOpenConversation(point.evidence[0].record_id) } }}><title>{point.place}: {point.count} mentions</title><circle className="insight-map-marker-halo" cx={x} cy={y} r={radius + 5} /><circle className="insight-map-marker-dot" cx={x} cy={y} r={radius} /><text x={x + radius + 4} y={y + 3}>{point.place}</text></g> })}
    </svg><span className="insight-map-caption">Approximate city positions · select a marker to view evidence</span></div><div className="insight-location-list" aria-label="Mapped locations">{[...points].sort((a, b) => b.count - a.count).map((point) => <button type="button" className="insight-location-row" key={point.place} onClick={() => point.evidence[0] && onOpenConversation(point.evidence[0].record_id)}><span><strong>{point.place}</strong><small>{point.share_percent}% of relevant records</small></span><b>{point.count}</b></button>)}</div></div> : <p className="insight-location-empty">No recognized city names in this date range can be placed on the map. Location mentions such as “India” or “near me” are not plotted as cities.</p>}
    <p className="insight-location-note">Places are extracted from conversation wording. They do not indicate the author’s verified location. City coordinates are approximate; unrecognized places are not plotted.</p>
  </section>
}

function Insights({ data, audience, dates, onDatesChange, onCreateContentIdea, onOpenConversation }: { data: TrendAnalysis | null; audience: AudienceInsights | null; dates: InsightDateRange; onDatesChange: (dates: InsightDateRange) => void; onCreateContentIdea: (trend: RankedTrend) => void; onOpenConversation: (recordId: number) => void }) {
  const years = data?.years || []
  const maxYearCount = Math.max(1, ...years.map((item) => item.count))
  const attentionClass = (attention: string) => attention.toLowerCase().replaceAll(' ', '-')
  const dateValue = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
  const setRecentRange = (days: number) => { const end = new Date(); const start = new Date(end); start.setDate(end.getDate() - days + 1); onDatesChange({ from: dateValue(start), to: dateValue(end) }) }
  return <>
    <article className="panel trends-panel">
      <div className="panel-header"><div><div className="section-kicker">DATE-FILTERED ANALYSIS</div><h3>What needs attention</h3><p>Ranked relevant public conversations and audience needs for the selected activity dates.</p></div><span className="trend-total">{data?.relevant_records ?? '—'} relevant records</span></div>
      <div className="insight-date-filter"><div className="insight-date-presets"><button className="secondary-button" onClick={() => onDatesChange({ from: '', to: '' })}>All dates</button><button className="secondary-button" onClick={() => setRecentRange(7)}>7 days</button><button className="secondary-button" onClick={() => setRecentRange(30)}>30 days</button><button className="secondary-button" onClick={() => setRecentRange(90)}>90 days</button></div><label>From<input aria-label="Insights start date" type="date" value={dates.from} max={dates.to || undefined} onChange={(event) => onDatesChange({ ...dates, from: event.target.value })} /></label><label>To<input aria-label="Insights end date" type="date" value={dates.to} min={dates.from || undefined} onChange={(event) => onDatesChange({ ...dates, to: event.target.value })} /></label><span>Uses published date; falls back to first collected date. The collection date shows when Social Pulse stored the record.</span></div>
      <div className="trend-coverage">{data ? <><span><strong>{data.total_social_records}</strong> social comments and posts scanned</span><span><strong>{data.dated_records}</strong> with published dates</span><span><strong>{data.excluded_as_unrelated}</strong> excluded as unrelated</span><span>Search snippets and news are not counted as audience feedback.</span><span>Window: {dates.from || "earliest available"} → {dates.to || "latest available"}</span></> : <span>Loading complete social history…</span>}</div>
      <section className="audience-insights"><div className="ranked-trends-heading"><div><h4>Who is this conversation useful for?</h4><p>Audience needs are inferred from post wording, not verified author identity or demographics.</p></div><span>{audience?.sample_size ?? '—'} relevant posts/comments</span></div>{audience?.segments.length ? <div className="audience-profile-list">{audience.segments.map((profile) => <article className="audience-profile" key={profile.audience_segment}><div className="audience-profile-heading"><strong>{label(profile.audience_segment)}</strong><span>{profile.count} records · {profile.share_percent}% · confidence {Math.round(profile.confidence * 100)}%</span></div><div className="audience-needs">Top needs: {Object.entries(profile.needs).slice(0, 3).map(([need, count]) => `${label(need)} (${count})`).join(' · ')}</div>{Object.keys(profile.pain_points || {}).length > 0 && <div className="audience-needs">Common friction: {Object.entries(profile.pain_points || {}).slice(0, 3).map(([point, count]) => `${label(point)} (${count})`).join(' · ')}</div>}<div className="audience-needs">Conversation signals: {Object.entries(profile.emotions || {}).slice(0, 2).map(([emotion, count]) => `${label(emotion)} (${count})`).join(' · ') || 'emotion unclear'}</div><p>{profile.recommended_action}</p>{profile.examples.slice(0, 1).map((example) => <div className="audience-evidence" key={example.record_id}><span>Evidence: “{example.text.slice(0, 220)}{example.text.length > 220 ? '…' : ''}” · {example.source} · need: {label(example.audience_need)} · published {example.published_at ? new Date(example.published_at).toLocaleDateString() : 'date unavailable'} · collected {example.collected_at ? new Date(example.collected_at).toLocaleDateString() : 'date unavailable'}</span><div className="evidence-actions"><button type="button" className="text-link" onClick={() => onOpenConversation(example.record_id)}>Conversation <ArrowRight size={13} /></button>{example.url && <a href={example.url} target="_blank" rel="noopener noreferrer">Source <ExternalLink size={11} /></a>}</div></div>)}</article>)}</div> : <div className="empty-feed"><h4>No audience signals yet</h4><p>Collect relevant public posts or comments to estimate which needs appear in the conversation.</p></div>}
        {audience?.location_mentions?.length ? <InsightLocationMap locations={audience.location_mentions} onOpenConversation={onOpenConversation} /> : null}
        <div className="audience-signal-grid"><article className="audience-signal-card"><h5>Age groups explicitly mentioned</h5><p>Conversation references only; this does not identify the author's age.</p>{audience?.age_group_mentions?.length ? audience.age_group_mentions.map((item) => <div className="audience-signal-row" key={item.group}><strong>{item.group}</strong><span>{item.count} · {item.share_percent}% of relevant records</span>{item.evidence[0] && <small>“{item.evidence[0].text.slice(0, 150)}{item.evidence[0].text.length > 150 ? '…' : ''}” · {item.evidence[0].source}{item.evidence[0].url ? <> · <a href={item.evidence[0].url} target="_blank" rel="noopener noreferrer">source</a></> : null}</small>}</div>) : <span className="audience-signal-empty">No explicit age-group references in this date range.</span>}</article><article className="audience-signal-card"><h5>Places mentioned</h5><p>Place names in conversation text; these do not establish anyone’s location.</p>{audience?.location_mentions?.length ? audience.location_mentions.slice(0, 8).map((item) => <div className="audience-signal-row" key={item.place}><strong>{item.place}</strong><span>{item.count} · {item.share_percent}% of relevant records</span>{item.evidence[0] && <small>“{item.evidence[0].text.slice(0, 150)}{item.evidence[0].text.length > 150 ? '…' : ''}” · {item.evidence[0].source}{item.evidence[0].url ? <> · <a href={item.evidence[0].url} target="_blank" rel="noopener noreferrer">source</a></> : null}</small>}</div>) : <span className="audience-signal-empty">No recognized place names in this date range.</span>}</article></div>
        {audience?.audience_actions?.length ? <div className="audience-action-list"><h5>Actions informed by these signals</h5>{audience.audience_actions.map((item) => <article key={item.title}><strong>{item.title}</strong><p>{item.action}</p><small>{item.basis} · evidence records {item.evidence_record_ids.join(', ') || '—'}</small></article>)}</div> : null}<p className="audience-method">{audience?.method || 'Audience labels are estimates from conversation wording.'}</p></section>
      {years.length > 0 && <section className="trend-history"><div className="trend-chart-heading"><div><h4>Relevant comments by year</h4><p>Full available history, grouped by published date (collection date if missing)</p></div><span>{years.reduce((sum, item) => sum + item.count, 0)} records</span></div><div className="year-chart" role="img" aria-label={`Relevant comments by year: ${years.map((item) => `${item.year}: ${item.count}`).join(', ')}`}>{years.map((item) => <div className="year-column" key={item.year} title={`${item.year}: ${item.count} comments`}><strong>{item.count}</strong><i style={{ height: `${Math.max(4, item.count / maxYearCount * 100)}%` }} /><span>{item.year}</span></div>)}</div></section>}
      <div className="ranked-trends-heading"><div><h4>Trend priority ranking</h4><p>Higher scores and urgent risk signals rise to the top.</p></div><span>Importance · 0–100</span></div>
      {data?.trends.length ? <div className="ranked-trends">{data.trends.map((trend, index) => <article className="ranked-trend" key={`${trend.monitoring_scope || 'brand'}-${trend.topic}`}>
        <div className="ranked-trend-top"><div className="trend-rank">{index + 1}</div><div className="ranked-trend-title"><span className={`attention-badge ${attentionClass(trend.attention)}`}>{trend.attention}</span><h4>{label(trend.topic)}</h4><span>{label(trend.monitoring_scope || 'brand')} stream</span><span className="trend-count">{trend.count} records across all available history</span></div><div className="trend-score"><strong>{trend.score}</strong><span>/100</span></div></div>
        <div className="trend-score-track"><i style={{ width: `${trend.score}%` }} /></div>
        <div className="trend-reasons">{trend.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
        <div className="trend-score-parts"><span>Volume <strong>{trend.score_parts.volume}/20</strong></span><span>Recency <strong>{trend.score_parts.recency}/20</strong></span><span>Risk <strong>{trend.score_parts.risk}/25</strong></span><span>Demand <strong>{trend.score_parts.demand}/15</strong></span><span>Growth <strong>{trend.score_parts.growth}/20</strong></span><span>30d: {trend.recent_30_days} · prior 30d: {trend.previous_30_days}</span><span>Lifecycle <strong>{label(trend.lifecycle)}</strong></span><span>Velocity <strong>{trend.velocity_per_week}/week</strong></span><span>Volume change <strong>{trend.growth_percent == null ? 'baseline unavailable' : `${trend.growth_percent}% (smoothed)`}</strong></span><span>Engagement acceleration <strong>{trend.engagement_acceleration_percent == null ? 'insufficient comparable metrics' : `${trend.engagement_acceleration_percent}%`}</strong> · {trend.engagement_baseline?.current_measured_records ?? 0} current / {trend.engagement_baseline?.previous_measured_records ?? 0} prior records</span><span>Baseline confidence <strong>{label(trend.baseline_confidence || 'low')}</strong></span><span>New topic in window: <strong>{trend.novelty ? 'yes' : 'no'}</strong></span><span>Records with any engagement counter: <strong>{trend.engagement_coverage.records_with_metrics}</strong> (by source; not included in rank)</span></div>
        {trend.examples.length > 0 && <div className="ranked-trend-actions"><button type="button" className="secondary-button" onClick={() => onCreateContentIdea(trend)}>Create evidence-linked content idea</button><span>Uses conversation #{trend.examples[0].record_id}; review the saved idea in Content &amp; Growth.</span></div>}
        {trend.examples.length > 0 && <div className="trend-examples">{trend.examples.map((example, exampleIndex) => <div className="trend-example" key={`${trend.topic}-${exampleIndex}`}><p>{example.text}</p><div><span>{example.source} · {example.published_at ? new Date(example.published_at).toLocaleDateString() : 'Publication date unavailable'} · First collected {example.collected_at ? new Date(example.collected_at).toLocaleDateString() : 'date unavailable'} · {label(example.sentiment)} · {label(example.intent)}</span>{example.url && <a href={example.url} target="_blank" rel="noopener noreferrer">Open original <ExternalLink size={12} /></a>}</div></div>)}</div>}
      </article>)}</div> : data ? <div className="empty-feed"><h4>No relevant social comments or posts found</h4><p>Once relevant public comments are collected, this page will group them by topic and rank them for attention.</p></div> : <div className="chart-empty">Trend analysis is unavailable. Check the API connection and refresh.</div>}
      <details className="ranking-method"><summary>How the attention score works</summary><p>{data?.ranking_method || 'The score uses volume (20), recency (20), risk (25), demand (15), and growth (20). Immediate attention is reserved for explicit urgent or safety wording. Scores are estimates based on text analysis.'}</p></details>
      <div className="panel-footer"><span>Topics use saved analysis when available and rule-based text signals otherwise.</span><span>Ranking covers the full stored social history.</span></div>
    </article>
  </>
}
function ReplyCenter({ focusRecordId, drafts, approvedReplies, analyses, records, onRefresh, onOpenConversation }: { focusRecordId: number | null; drafts: ReplyDraft[]; approvedReplies: ReplyDraft[]; analyses: Map<number, RecordAnalysis>; records: SocialRecord[]; onRefresh: () => Promise<void>; onOpenConversation: (recordId: number) => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  const [edited, setEdited] = useState<Record<number, string>>({})
  const [message, setMessage] = useState('')
  const focusedDraft = drafts.some((draft) => draft.record_id === focusRecordId)
  useEffect(() => {
    if (focusRecordId == null) return
    const timer = window.setTimeout(() => focusArrival(`${focusedDraft ? 'reply-record' : 'reply-context-record'}-${focusRecordId}`), 100)
    return () => window.clearTimeout(timer)
  }, [focusRecordId, focusedDraft, drafts])
  async function review(draft: ReplyDraft, status: 'approved' | 'rejected') {
    const text = edited[draft.draft_id] ?? draft.reply_text
    if (!text.trim()) { setMessage('Reply text cannot be empty.'); return }
    setBusy(draft.draft_id); setMessage('')
    try { const result = await reviewDraft(draft.draft_id, status, text); setMessage(`${status} successfully. Published: ${String(result.published)}`); await onRefresh() } catch (error) { setMessage(error instanceof Error ? error.message : 'Review failed') } finally { setBusy(null) }
  }
  async function copyApprovedReply(reply: ReplyDraft) {
    try {
      await navigator.clipboard.writeText(reply.reply_text)
      setMessage(`Approved reply for conversation #${reply.record_id} copied.`)
    } catch {
      setMessage('Clipboard access is unavailable. Select and copy the approved reply text manually.')
    }
  }
  async function regenerate(draft: ReplyDraft) {
    setBusy(draft.draft_id); setMessage('')
    try { const result = await regenerateDraft(draft.draft_id); setEdited({ ...edited, [draft.draft_id]: result.reply_text }); setMessage('Draft regenerated. Review and edit before approval.'); await onRefresh() } catch (error) { setMessage(error instanceof Error ? error.message : 'Regeneration failed') } finally { setBusy(null) }
  }
  return <div className="reply-center-view"><article className="panel reply-panel"><div className="panel-header"><div><div className="section-kicker">HUMAN REVIEW</div><h3>Reply center</h3><p>Review and edit suggested replies. Approval does not publish automatically.</p></div></div>{message && <div className="notice">{message}</div>}{focusRecordId != null && !focusedDraft && records.find((record) => record.id === focusRecordId) && (() => { const record = records.find((item) => item.id === focusRecordId)!; return <div id={`reply-context-record-${focusRecordId}`} className="reply-context-card"><div className="record-meta"><span className="source-chip">{record.source} · {record.record_type}</span><span>Selected from Training Opportunities</span></div><h4>Signal opened in Reply Center</h4><p className="original-text">{record.text}</p><p className="reply-context-note">There is no reply draft for this signal. Reply drafts are available only for eligible direct Tata STRIVE comments and posts. Use the source conversation to review context, or create an evidence-linked content idea from Training Opportunities.</p><button type="button" className="secondary-button" onClick={() => onOpenConversation(record.id)}>Open source conversation <ArrowRight size={13} /></button>{record.url && <a href={record.url} target="_blank" rel="noopener noreferrer">Original source <ExternalLink size={12} /></a>}</div> })()}{drafts.length ? drafts.map((draft) => { const record = records.find((item) => item.id === draft.record_id); const analysis = draft.analysis || analyses.get(draft.record_id); const source = draft.source || record?.source || 'Unknown source'; const originalUrl = draft.original_url || record?.url; const audienceSegment = draft.audience_segment || record?.audience_segment || 'unclear'; const audienceNeed = draft.audience_need || record?.audience_need || 'unclear'; return <div id={`reply-record-${draft.record_id}`} className="draft-card" key={draft.draft_id}><div className="record-meta"><span className="source-chip">{source} · {draft.record_type || record?.record_type || 'post'}</span><span>Status: {label(draft.status)}</span><span>Author: {draft.author || record?.author || 'Unknown author'}</span><span>Draft created {draft.generated_at ? new Date(draft.generated_at).toLocaleString() : 'date unavailable'}</span><span>Record collected {draft.collected_at ? new Date(draft.collected_at).toLocaleString() : 'date unavailable'}</span></div><p className="original-text">{draft.original_text || record?.text || 'Original text unavailable'}</p><div className="record-details"><span>Relevance: {label(analysis?.relevance_type)}</span><span>Sentiment: {label(analysis?.sentiment)}</span><span>Intent: {label(analysis?.intent)}</span><span>Priority: {label(analysis?.priority)}</span><span>{analysis?.rationale || 'Analysis rationale unavailable'}</span>{originalUrl && <a href={originalUrl} target="_blank" rel="noopener noreferrer">View original <ExternalLink size={12} /></a>}</div><div className="record-details"><strong>Audience signal</strong><span>{label(audienceSegment)}</span><span>Likely need: {label(audienceNeed)}</span><span>Inferred from wording; not a verified identity.</span></div><label className="reply-label" htmlFor={`reply-${draft.draft_id}`}>Suggested reply · editable</label><textarea id={`reply-${draft.draft_id}`} value={edited[draft.draft_id] ?? draft.reply_text} onChange={(event) => setEdited({ ...edited, [draft.draft_id]: event.target.value })} aria-label="Edit reply" /><div className="draft-actions"><button className="secondary-button" disabled={busy === draft.draft_id} onClick={() => void regenerate(draft)}>{busy === draft.draft_id ? 'Working…' : <><RefreshCw size={13} /> Regenerate</>}</button><button className="secondary-button" disabled={busy === draft.draft_id} onClick={() => void review(draft, 'rejected')}>{busy === draft.draft_id ? 'Saving…' : 'Reject'}</button><button className="primary-button" disabled={busy === draft.draft_id} onClick={() => void review(draft, 'approved')}>{busy === draft.draft_id ? 'Saving…' : 'Approve'}</button><span className="publish-note">Approval is review-only; publishing is disabled.</span></div></div> }) : !focusRecordId || focusedDraft ? <div className="empty-feed"><h4>No pending drafts</h4><p>Generate drafts from analyzed relevant social records.</p></div> : null}</article>
    <details className="panel approved-reply-history"><summary><span><strong>Approved reply history</strong><small>Saved replies are retained for reference and follow-up.</small></span><b>{approvedReplies.length}</b></summary>
      {approvedReplies.length ? <div className="approved-history-list">{approvedReplies.map((reply) => <article className="approved-history-item" key={reply.draft_id}><div className="record-meta"><span className="source-chip">{reply.source || 'Unknown source'} · {reply.record_type || 'post'}</span><span>{reply.reviewed_at ? `Approved ${new Date(reply.reviewed_at).toLocaleString()}` : 'Approved time unavailable (older record)'}</span><span>{reply.author || 'Unknown author'}</span></div><p className="original-text">{reply.original_text || 'Original conversation unavailable'}</p><div className="approved-reply-text"><span>APPROVED REPLY</span><p>{reply.reply_text}</p></div><div className="approved-history-actions"><button type="button" className="secondary-button" onClick={() => void copyApprovedReply(reply)}>Copy reply</button><button type="button" className="text-link" onClick={() => onOpenConversation(reply.record_id)}>Open source conversation <ArrowRight size={13} /></button>{reply.original_url && <a href={reply.original_url} target="_blank" rel="noopener noreferrer">Original post <ExternalLink size={12} /></a>}</div></article>)}</div> : <p className="approved-history-empty">Approved replies will appear here after review.</p>}
    </details></div>
}

function OpportunityPanel({ focusRecordId, opportunities, hasOpenContentItem, onCreateContentIdea, onRefresh, onOpenReplyCenter, onOpenConversation }: { focusRecordId: number | null; opportunities: TrainingOpportunity[]; hasOpenContentItem: boolean; onCreateContentIdea: (opportunity: TrainingOpportunity) => void; onRefresh: () => Promise<void>; onOpenReplyCenter: (recordId: number) => void; onOpenConversation: (recordId: number) => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [generated, setGenerated] = useState<Record<number, string>>({})
  const [sourceFilter, setSourceFilter] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  useEffect(() => {
    if (focusRecordId == null) return
    const timer = window.setTimeout(() => focusArrival(`training-record-${focusRecordId}`), 100)
    return () => window.clearTimeout(timer)
  }, [focusRecordId, opportunities])
  async function createDraft(recordId: number) {
    setBusy(recordId); setMessage('')
    try {
      const result = await generateOpportunityDraft(recordId)
      setGenerated((current) => ({ ...current, [recordId]: result.reply_text }))
      setMessage('Reply draft created. Review it in Reply Center before using it.')
      await onRefresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not generate reply draft')
    } finally { setBusy(null) }
  }
  const sources = [...new Set(opportunities.map((opportunity) => opportunity.source))].sort()
  const directRequests = opportunities.filter((opportunity) => opportunity.is_direct_brand_request).length
  const visibleOpportunities = opportunities.filter((opportunity) => {
    const matchesSource = !sourceFilter || opportunity.source === sourceFilter
    const term = searchTerm.trim().toLocaleLowerCase()
    return matchesSource && (!term || `${opportunity.text} ${opportunity.author || ''} ${opportunity.skills.join(' ')} ${opportunity.location || ''}`.toLocaleLowerCase().includes(term))
  })
  return <article className="panel opportunities-panel">
    <div className="panel-header"><div><div className="section-kicker">LEARNER & SKILLS SIGNALS · ALL SOURCES</div><h3>Training opportunities</h3><p>Questions and skills interests from public social posts, comments, search results, and news. Broader signals help shape audience insight and content; they are not treated as direct requests to Tata STRIVE.</p></div><span className="opportunity-total">{opportunities.length} signals</span></div>
    {message && <div className="notice opportunity-notice">{message}</div>}
    {opportunities.length ? <><div className="training-signal-summary"><div><strong>{opportunities.length}</strong><span>learner and skills signals</span></div><div><strong>{sources.length}</strong><span>public source{sources.length === 1 ? '' : 's'}</span></div><div><strong>{directRequests}</strong><span>direct Tata STRIVE requests</span></div><p>Audience and location clues come from text and may be incomplete. Verify the original source before outreach.</p></div><div className="training-filter-bar"><label><Search size={14} /><input aria-label="Search training opportunities" value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Search skill, course, location, or text" /></label><select aria-label="Filter training signals by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">All sources ({opportunities.length})</option>{sources.map((source) => <option key={source} value={source}>{source} ({opportunities.filter((item) => item.source === source).length})</option>)}</select><span>{visibleOpportunities.length} shown</span></div><div className="opportunity-list">{visibleOpportunities.map((opportunity) => {
      const replyText = generated[opportunity.record_id] || opportunity.draft?.reply_text
      return <article id={`training-record-${opportunity.record_id}`} className="opportunity-card" key={opportunity.record_id}>
        <div className="opportunity-meta"><span className="source-chip">{opportunity.source} · {label(opportunity.record_type)}</span><span className={`training-signal-badge ${opportunity.is_direct_brand_request ? 'direct' : ''}`}>{opportunity.is_direct_brand_request ? 'Direct Tata STRIVE request' : 'Broader learner signal'}</span><span>{label(opportunity.monitoring_scope || 'public')} stream · {label(opportunity.request_type)}</span><span>{opportunity.author || 'Public author unavailable'}</span><span>Published {opportunity.published_at ? new Date(opportunity.published_at).toLocaleDateString() : 'date unavailable'} · collected {opportunity.collected_at ? new Date(opportunity.collected_at).toLocaleDateString() : 'date unavailable'}</span></div>
        <p className="opportunity-comment">{opportunity.text}</p>
        <div className="opportunity-signals"><div><strong>Skills and topics</strong><span>{opportunity.skills.join(' · ') || opportunity.topic || 'Training guidance'}</span></div><div><strong>Location signal</strong><span>{opportunity.location || (opportunity.asks_location ? 'Not specified — ask which city' : 'Not mentioned')}</span></div><div><strong>Likely audience</strong><span>{label(opportunity.audience_segment || 'unclear')} · {label(opportunity.audience_need || 'learning interest')}</span></div><div><strong>Text confidence</strong><span>{Math.round((opportunity.confidence ?? 0.35) * 100)}% · inferred, not verified</span></div></div>
        {opportunity.suggested_course ? <div className="course-match"><div><span className="section-kicker">POSSIBLE COURSE MATCH</span><strong>{opportunity.suggested_course.title}</strong><span>{opportunity.suggested_course.category} · verify current eligibility and centre availability</span></div><a href={opportunity.suggested_course.url} target="_blank" rel="noopener noreferrer">Official course list <ExternalLink size={13} /></a></div> : <div className="course-unmatched"><MapPin size={15} /><span>No specific course matched confidently. The reply will ask for the skill area and preferred location before suggesting one.</span></div>}
        <div className="opportunity-actions"><button className="secondary-button" onClick={() => onOpenConversation(opportunity.record_id)}>Open conversation</button><button className="secondary-button" disabled={hasOpenContentItem} title={hasOpenContentItem ? 'Edit or close the open content item first' : 'Create an evidence-linked learner content draft'} onClick={() => onCreateContentIdea(opportunity)}>{hasOpenContentItem ? 'Edit open idea in Content & Growth' : 'Create learner content idea'}</button>{opportunity.reply_eligible ? <>{replyText ? <><button className="secondary-button" onClick={() => onOpenReplyCenter(opportunity.record_id)}>Review draft in Reply Center</button>{opportunity.draft?.status === 'draft' && <button className="secondary-button" disabled={busy !== null} onClick={() => void createDraft(opportunity.record_id)}>{busy === opportunity.record_id ? 'Regenerating…' : 'Regenerate tailored reply'}</button>}<span className="draft-status">{label(opportunity.draft?.status || 'draft')}</span></> : <button className="primary-button" disabled={busy !== null} onClick={() => void createDraft(opportunity.record_id)}>{busy === opportunity.record_id ? <><RefreshCw className="spin" size={14} /> Generating…</> : <>Draft a reply</>}</button>}</> : <><button className="secondary-button" onClick={() => onOpenReplyCenter(opportunity.record_id)}>Open in Reply Center</button><span className="training-reply-note">{opportunity.is_direct_brand_request ? 'Search preview · open the original before drafting a reply' : 'Broader signal · use for insight or content planning, not a direct reply'}</span></>}{opportunity.url && <a href={opportunity.url} target="_blank" rel="noopener noreferrer">View source <ExternalLink size={12} /></a>}</div>
        {replyText && <div className="opportunity-reply"><span>REPLY DRAFT · REVIEW BEFORE USE</span><p>{replyText}</p></div>}
      </article>
    })}</div></> : <div className="empty-feed"><div className="empty-icon"><GraduationCap size={23} /></div><h4>No learner or skills signals found</h4><p>Signals appear when collected public content asks for course, training, skill, upskilling, or location guidance. Broader signals can come from thematic search and social sources.</p></div>}
    {opportunities.length > 0 && !visibleOpportunities.length && <div className="empty-feed training-filter-empty"><h4>No signals match these filters</h4><p>Try another source or search term.</p></div>}
    <div className="panel-footer"><span>Signals are inferred from public text across collected sources. Only direct Tata STRIVE requests can generate a reply draft.</span><a href="https://tatastrive.com/what-we-do/courses/" target="_blank" rel="noopener noreferrer">Tata STRIVE course catalogue <ExternalLink size={12} /></a></div>
  </article>
}

function Operations({ operation, runOperation, runs }: { operation: string; runOperation: (name: string, action: () => Promise<Record<string, unknown>>) => Promise<void>; runs: NonNullable<Stats['latest_collections']> }) {
  const actions = [['Rebuild provenance & duplicate links', rebuildDataQuality], ['Collect all sources', collectAll], ['Collect Bluesky', collectBluesky], ['SerpApi social search', collectGoogleSearch], ['Fetch learner & partner leads', collectThematicSearch], ['Google Custom Search', collectGoogleCustomSearch], ['Collect YouTube comments', collectYoutube], ['Collect GNews', collectGnews], ['Collect GDELT', collectGdelt], ['Analyze pending', analyzePending], ['Generate reply drafts', generatePendingReplies]] as const
  return <article className="panel operations-panel"><div className="panel-header"><div><div className="section-kicker">OPERATIONS</div><h3>Ingestion & analysis controls</h3><p>Run a collection on demand here or with Fetch data. All sources are also fetched every 30 minutes while this app is open; source access and quotas still apply.</p></div></div><div className="operation-grid">{actions.map(([name, action]) => <button key={name} className="operation-button" disabled={Boolean(operation)} onClick={() => void runOperation(name, action)}>{operation === name ? <RefreshCw className="spin" size={15} /> : <ArrowUpRight size={15} />}{name}</button>)}</div><div className="panel-header"><div><div className="section-kicker">COLLECTION HISTORY</div><h3>Recent source runs</h3></div></div>{runs.length ? <div className="record-list">{runs.map((run) => <div className="record-item" key={run.id}><div className="record-meta"><span className="source-chip">{run.source}</span><span>{new Date(run.completed_at).toLocaleString()}</span><strong>{label(run.status)}</strong><span>{run.records_added} new records</span></div>{run.error_type && <div className="record-details">{run.error_type}</div>}</div>)}</div> : <div className="empty-feed"><h4>No collection runs yet</h4><p>Run a source above to record its status and results.</p></div>}</article>
}

export default App

