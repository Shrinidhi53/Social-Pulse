import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, ExternalLink } from 'lucide-react'
import { addCampaignOutcome, createContentRecommendation, deleteContentRecommendation, dismissStrategyPartner, fetchQuickEmailDrafts, generateContentOptions, saveOrganizationProfile, saveQuickEmailDraft, submitRecommendationFeedback, updateContentRecommendation, updateEngagementOpportunity } from './lib/api'
import type { AudienceInsights, ContentRecommendation, EngagementOpportunity, PerformanceLearning, QuickEmailDraft, RankedTrend, SocialAlert, StrategyPartner, TrendAnalysis } from './lib/api'

const label = (value: string) => value.replace(/_/g, ' ')
const localDate = (value?: string | null) => value ? new Date(value).toISOString().slice(0, 16) : ''
const PR_OBJECTIVES = [
  ['visibility', 'Visibility', 'Reach relevant learners and ecosystem stakeholders.', 'Timely evidence-led commentary; partner amplification; consent-based stories.', 'Relevant reach; stakeholder interactions; branded enquiries.'],
  ['thought_leadership', 'Thought leadership', 'Share a differentiated, evidence-backed perspective.', 'Expert point of view; data-backed explainer; executive byline.', 'Qualified media mentions; expert invitations; substantive discussion.'],
  ['partnerships', 'Partnerships', 'Move verified mutual need toward a measurable pilot.', 'Discovery meeting; small pilot proposal; approved case study.', 'Qualified meetings; pilots; learner outcomes.'],
  ['csr', 'CSR and social impact', 'Connect a verified community need to suitable programmes.', 'Geography and need brief; funding fit note; impact plan.', 'Qualified CSR conversations; commitments; beneficiaries served.'],
  ['government_relations', 'Government relations', 'Support informed engagement on verified policy signals.', 'Primary-source review; neutral briefing; authorized liaison.', 'Verified briefings; consultations; documented outcomes.'],
  ['media_attention', 'Media attention', 'Offer timely facts and expertise to relevant media.', 'Fact sheet; expert response; consent-based case.', 'Qualified coverage; message accuracy; referral enquiries.'],
  ['learner_reach', 'Learner reach', 'Help learners find accurate courses and next steps.', 'FAQ; reviewed explainer; official course link and CTA.', 'Course visits; eligible enquiries; applications.'],
  ['ecosystem_influence', 'Ecosystem influence', 'Connect employers, providers, government and communities.', 'Roundtable; shared skills brief; cross-sector learning note.', 'Stakeholder participation; repeat collaboration; referrals.'],
  ['reputation', 'Reputation and issue response', 'Verify and route concerns; respond with care.', 'Fact-check; approved response; close the loop.', 'Response time; verified resolution; recurring issue reduction.'],
] as const
const objectiveKey = (value: string) => PR_OBJECTIVES.find(([key, labelText]) => key === value || value.toLowerCase().includes(labelText.toLowerCase()))?.[0] || 'visibility'

export default function ActionCenter({ opportunities, recommendations, partners, trends, audienceInsights, learning, alerts, onRefresh, activePage, focusRecordId, focusSection, onOpenConversation, onOpenReplyCenter, onOpenTrainingOpportunity }: {
  opportunities: EngagementOpportunity[]; recommendations: ContentRecommendation[]; partners: StrategyPartner[]; trends: TrendAnalysis | null; audienceInsights: AudienceInsights | null; learning: PerformanceLearning | null; alerts: SocialAlert[]; onRefresh: () => Promise<void>
  activePage: string; focusRecordId?: number | null; focusSection?: string
  onOpenConversation: (recordId: number) => void; onOpenReplyCenter: (recordId: number) => void; onOpenTrainingOpportunity: (recordId: number) => void
}) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState('')
  const [editingRecommendationId, setEditingRecommendationId] = useState<number | null>(null)
  const [now, setNow] = useState(0)
  const [emailDrafts, setEmailDrafts] = useState<QuickEmailDraft[]>([])
  const expiryHandledRef = useRef(new Set<number>())
  useEffect(() => {
    const updateClock = () => setNow(Date.now())
    updateClock()
    const interval = window.setInterval(updateClock, 60_000)
    return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    if (!now) return
    const expired = recommendations.filter((item) => ['idea', 'drafting', 'review'].includes(item.status)
      && !expiryHandledRef.current.has(item.id)
      && now - new Date(item.updated_at || item.created_at || now).getTime() >= 30 * 60 * 1000)
    for (const item of expired) {
      expiryHandledRef.current.add(item.id)
      void updateContentRecommendation(item.id, { status: 'paused' })
        .then(async () => { setMessage(`“${item.topic}” was paused after 30 minutes without edits. Its draft is saved; resume it from the Status field to continue.`); await onRefresh() })
        .catch(() => { expiryHandledRef.current.delete(item.id) })
    }
  }, [now, recommendations, onRefresh])
  useEffect(() => {
    if (!focusSection) return
    const timer = window.setTimeout(() => {
      const target = activePage === 'Strategy Radar' && focusRecordId != null
        ? document.getElementById(`strategy-evidence-${focusRecordId}`)
        : null
      const element = target || document.getElementById(focusSection)
      element?.scrollIntoView({ behavior: 'smooth', block: target ? 'center' : 'start' })
      if (target) {
        target.classList.add('arrival-highlight')
        window.setTimeout(() => target.classList.remove('arrival-highlight'), 3600)
      }
    }, 80)
    return () => window.clearTimeout(timer)
  }, [focusSection, focusRecordId, activePage])
  useEffect(() => {
    if (activePage !== 'Strategy Radar' && activePage !== 'Content & Growth') return
    void fetchQuickEmailDrafts().then(setEmailDrafts).catch(() => setEmailDrafts([]))
  }, [activePage])
  async function refreshEmailDrafts() { setEmailDrafts(await fetchQuickEmailDrafts()) }
  async function copyEmailDraft(draft: QuickEmailDraft) {
    try { await navigator.clipboard.writeText(`To: ${draft.recipient_email || 'Opt-in audience list'}\nSubject: ${draft.subject}\n\n${draft.body}`); setMessage('Email draft copied to clipboard.') }
    catch { setMessage('Clipboard access is unavailable. Expand the draft and copy its text manually.') }
  }
  const active = opportunities.filter((item) => !['closed', 'dismissed'].includes(item.status))
  const hasOpenContentItem = recommendations.some((item) => ['idea', 'drafting', 'review', 'scheduled'].includes(item.status))
  const showStrategy = activePage === 'Strategy Radar'
  const showEngagement = activePage === 'Engagement Queue'
  const showContent = activePage === 'Content & Growth'
  const showAlerts = activePage === 'Alerts & Learning'
  const contentTrendGroups = Object.values((trends?.trends || []).reduce<Record<string, { trend: RankedTrend; streams: Map<string, { count: number; recent: number }> }>>((groups, trend) => {
    const key = trend.topic.trim().toLocaleLowerCase()
    const group = groups[key] || (groups[key] = { trend, streams: new Map() })
    const scope = trend.monitoring_scope || 'brand'
    const current = group.streams.get(scope) || { count: 0, recent: 0 }
    group.streams.set(scope, { count: current.count + trend.count, recent: current.recent + trend.recent_30_days })
    if (trend.score > group.trend.score) group.trend = trend
    return groups
  }, {})).slice(0, 8)
  const followUps = active
    .filter((item) => item.follow_up_at)
    .map((item) => ({ item, due: new Date(item.follow_up_at as string).getTime() }))
    .filter(({ due }) => Number.isFinite(due) && due <= now + 7 * 24 * 60 * 60 * 1000)
    .sort((a, b) => a.due - b.due)
  const published = recommendations.filter((item) => item.status === 'published')
  const measured = published.filter((item) => item.reach != null || item.impressions != null || item.likes != null || item.comments != null || item.shares != null || item.follows != null)
  const total = (key: 'reach' | 'impressions' | 'likes' | 'comments' | 'shares' | 'follows') => measured.reduce((sum, item) => sum + (item[key] ?? 0), 0)
  const byFormat = Object.values(measured.reduce<Record<string, { format: string; channel: string; count: number; reachItems: number; reach: number; interactions: number }>>((groups, item) => {
    const format = item.recommended_format || 'Unspecified'
    const channel = item.channel || 'channel not recorded'
    const key = `${format} · ${channel}`
    const group = groups[key] || (groups[key] = { format, channel, count: 0, reachItems: 0, reach: 0, interactions: 0 })
    group.count += 1
    if (item.reach != null) { group.reachItems += 1; group.reach += item.reach; group.interactions += (item.likes ?? 0) + (item.comments ?? 0) + (item.shares ?? 0) }
    return groups
  }, {}))

  async function saveOpportunity(event: React.FormEvent<HTMLFormElement>, item: EngagementOpportunity) {
    event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(`o${item.id}`)
    try {
      await updateEngagementOpportunity(item.id, { status: String(form.get('status')) as EngagementOpportunity['status'], owner: String(form.get('owner') || '').trim() || null, follow_up_at: String(form.get('follow_up_at') || '') || null, notes: String(form.get('notes') || '').trim() || null, stakeholder_name: String(form.get('stakeholder_name') || '').trim() || null, stakeholder_geography: String(form.get('stakeholder_geography') || '').trim() || null, stakeholder_fit_notes: String(form.get('stakeholder_fit_notes') || '').trim() || null, stakeholder_review: String(form.get('stakeholder_review') || 'not_assessed') as EngagementOpportunity['stakeholder_review'] })
      setMessage('Conversation follow-up saved.'); await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save follow-up') } finally { setBusy('') }
  }

  async function savePartnerPlan(event: React.FormEvent<HTMLFormElement>, partner: StrategyPartner) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const organization = String(form.get('organization') || '').trim()
    const owner = String(form.get('owner') || '').trim() || null
    const followUp = String(form.get('follow_up_at') || '') || null
    const review = String(form.get('stakeholder_review') || 'verify') as EngagementOpportunity['stakeholder_review']
    setBusy(`partner-${partner.candidate_key}`)
    try {
      if (organization) await saveOrganizationProfile({
        canonical_name: organization,
        aliases: [...new Set([partner.name, ...String(form.get('aliases') || '').split(',').map((item) => item.trim()).filter(Boolean)])],
        website: String(form.get('website') || '').trim() || undefined,
        public_email: String(form.get('public_email') || '').trim() || undefined,
        contact_url: String(form.get('contact_url') || '').trim() || undefined,
        verification_status: review === 'verified' ? 'verified' : review === 'verify' ? 'review' : 'unverified',
        verification_evidence: String(form.get('verification_evidence') || '').trim() || undefined,
      })
      await Promise.all(partner.opportunities.map((item) => updateEngagementOpportunity(item.id, {
        stakeholder_name: organization || null, stakeholder_review: review, owner,
        follow_up_at: followUp, status: followUp ? 'follow_up' : 'assigned',
        stakeholder_fit_notes: `Partner radar review: validate public account and organization identity, confirm need/geography, then assess capability fit. Candidate: ${partner.name}.`,
      })))
      setMessage(`Saved verification, owner, and follow-up across ${partner.opportunities.length} linked signal(s).`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save partner follow-up') } finally { setBusy('') }
  }

  async function removeStrategyPartner(partner: StrategyPartner) {
    const confirmed = window.confirm(`Remove ${partner.name} from Strategy Radar? Its linked follow-ups will be dismissed. The original conversations, organization profile, and content plans will be kept.`)
    if (!confirmed) return
    const opportunityIds = partner.opportunities.map((item) => item.id)
    if (!opportunityIds.length) { setMessage('This candidate has no linked opportunity records to remove.'); return }
    setBusy(`remove-partner-${partner.candidate_key}`)
    try {
      const result = await dismissStrategyPartner(opportunityIds)
      setMessage(`Removed ${partner.name} from Strategy Radar. ${result.dismissed} linked follow-up(s) were dismissed; conversation evidence was preserved.`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not remove this radar candidate') } finally { setBusy('') }
  }

  async function removePartnerFollowUps(partner: StrategyPartner) {
    const scheduled = partner.opportunities.filter((item) => item.follow_up_at)
    if (!scheduled.length) return
    const confirmed = window.confirm(`Remove ${scheduled.length} scheduled follow-up(s) for ${partner.name}? The opportunity records and conversation evidence will be kept.`)
    if (!confirmed) return
    setBusy(`clear-followups-${partner.candidate_key}`)
    try {
      await Promise.all(scheduled.map((item) => updateEngagementOpportunity(item.id, {
        follow_up_at: null,
        ...(item.status === 'follow_up' ? { status: 'assigned' as const } : {}),
      })))
      setMessage(`Removed ${scheduled.length} scheduled follow-up(s) for ${partner.name}. Opportunity records and evidence were kept.`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not remove these follow-ups') } finally { setBusy('') }
  }

  async function savePartnerEmail(event: React.FormEvent<HTMLFormElement>, partner: StrategyPartner) {
    event.preventDefault()
    if (!partner.organization_id || partner.organization_verification !== 'verified' || !partner.organization_public_email) {
      setMessage('Verify the organization and enter its published public contact email before creating a partner email draft.'); return
    }
    const form = new FormData(event.currentTarget)
    setBusy(`email-${partner.candidate_key}`)
    try {
      await saveQuickEmailDraft({ target_type: 'partner', organization_id: partner.organization_id,
        recipient_email: partner.organization_public_email, subject: String(form.get('subject') || ''),
        body: String(form.get('body') || ''), evidence_record_ids: partner.evidence.map((item) => item.record_id) })
      setMessage(`Email draft saved for ${partner.name}. Social Pulse does not send it.`); await refreshEmailDrafts()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save email draft') } finally { setBusy('') }
  }

  async function saveAudienceEmail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy('audience-email')
    try {
      await saveQuickEmailDraft({ target_type: 'audience_template', audience_segment: String(form.get('audience_segment') || 'learners'),
        subject: String(form.get('subject') || ''), body: String(form.get('body') || ''), evidence_record_ids: [] })
      setMessage('Audience email template saved. Use only with an existing opt-in audience list; no individual addresses are collected.'); await refreshEmailDrafts()
      event.currentTarget.reset()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save audience template') } finally { setBusy('') }
  }

  async function generatePlanEmail(item: ContentRecommendation) {
    setBusy(`plan-email-${item.id}`)
    const subject = `${item.topic}: ${item.recommended_format || 'a useful next step'}`.slice(0, 250)
    const evidenceLines = item.evidence.slice(0, 3).map((evidence) => `${evidence.source}${evidence.url ? `: ${evidence.url}` : ` · conversation #${evidence.id}`}`).join('\n')
    const body = [
      `Hello ${item.target_audience || 'there'},`,
      '',
      item.hook ? `A question we are hearing: “${item.hook.replace(/[\r\n]+/g, ' ').slice(0, 220)}”` : `We are preparing a resource about ${item.topic}.`,
      '',
      item.idea,
      '',
      item.messaging,
      '',
      `Suggested next step: ${item.call_to_action}`,
      item.content_url ? `\nReviewed resource: ${item.content_url}` : '',
      evidenceLines ? `\nEvidence to review before use:\n${evidenceLines}` : '',
      '',
      'Please verify programme details, links, audience fit, and approvals before sending. This draft is based on a limited public-conversation sample and is not an individual response.',
      '',
      'Regards,\nTata STRIVE',
    ].filter(Boolean).join('\n')
    try {
      await saveQuickEmailDraft({ target_type: 'audience_template', audience_segment: item.target_audience.slice(0, 100), subject,
        body: body.slice(0, 10000), evidence_record_ids: item.evidence.map((evidence) => evidence.id).filter((id) => Number.isInteger(id)).slice(0, 50) })
      setMessage(`Audience email draft generated from “${item.topic}”. Review it before use; Social Pulse does not send email.`)
      await refreshEmailDrafts()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not generate audience email draft') } finally { setBusy('') }
  }

  async function rateRecommendation(id: number, rating: 'useful' | 'not_useful' | 'used') {
    const reason = window.prompt('Optional: what made this suggestion useful or not useful?') || ''
    try { await submitRecommendationFeedback(id, rating, reason); setMessage('Recommendation feedback saved.'); await onRefresh() }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save recommendation feedback') }
  }

  async function saveOutcome(event: React.FormEvent<HTMLFormElement>, item: ContentRecommendation) {
    event.preventDefault(); const form = new FormData(event.currentTarget)
    setBusy(`outcome-${item.id}`)
    try {
      await addCampaignOutcome(item.id, { campaign_name: String(form.get('campaign_name') || ''), outcome_type: String(form.get('outcome_type') || 'other'),
        value: Number(form.get('value') || 0), attribution_method: String(form.get('attribution_method') || 'team_reported'),
        evidence_url: String(form.get('evidence_url') || '') || undefined, notes: String(form.get('notes') || '') || undefined })
      setMessage('Campaign outcome linked to this content recommendation. Attribution strength is recorded for review.'); await onRefresh(); event.currentTarget.reset()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save campaign outcome') } finally { setBusy('') }
  }

  async function deleteRecommendation(item: ContentRecommendation) {
    const confirmed = window.confirm(`Delete the content plan “${item.topic}”? Its feedback and campaign attribution will also be deleted. Linked conversations and partner profiles will be kept.`)
    if (!confirmed) return
    setBusy(`delete-recommendation-${item.id}`)
    try {
      await deleteContentRecommendation(item.id)
      if (editingRecommendationId === item.id) setEditingRecommendationId(null)
      setMessage(`Deleted content plan: ${item.topic}. Linked evidence was preserved.`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not delete this content plan') } finally { setBusy('') }
  }

  async function createPartnerContentPlan(partner: StrategyPartner) {
    if (hasOpenContentItem) { setMessage('Edit the open content item below, or publish/pause it before creating the next one.'); return }
    const evidence = partner.evidence[0]
    if (!evidence) return
    setBusy(`partner-content-${partner.candidate_key}`)
    const capability = partner.capability_matches[0]?.capability || 'skills and employability pathways'
    try {
      await createContentRecommendation({
        topic: `Collaboration opportunity: ${partner.name}`,
        idea: `Develop a co-created, evidence-led pilot story with ${partner.name} around ${capability}. Confirm both organizations' approval, learner consent, delivery details, and outcome evidence before publication.`,
        messaging: `Explore how a verified collaboration could connect ${partner.name}'s stated need with relevant skills pathways. Do not imply a partnership exists until both parties approve it.`,
        call_to_action: 'Invite organizations with a similar verified skills need to start a conversation through an approved partnership channel.',
        rationale: `${partner.signal_count} public signal(s), ${partner.activity_30_days} in the last 30 days. Radar score ${partner.radar_score}/100 is a prioritization heuristic, not a qualified lead or forecast. Measure relevant stakeholder interactions, referral enquiries, partnership enquiries, reach, saves, shares, and learner outcomes after approval.`,
        evidence_record_ids: partner.evidence.map((item) => item.record_id),
        pr_objective: 'partnerships', collaboration_partner: partner.name,
        target_audience: `${partner.stakeholder_type} and relevant learners`, recommended_format: 'Co-created pilot case study or partner spotlight',
        hook: evidence.text.slice(0, 220), distribution_channel: 'Agree with verified partner before distribution',
        priority_score: partner.radar_score, confidence: Math.min(0.7, partner.signal_count * 0.12),
      })
      setMessage(`Collaboration content and outcome-tracking plan created for ${partner.name}.`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not create collaboration content plan') } finally { setBusy('') }
  }

  async function makeIdea(trend: RankedTrend) {
    if (hasOpenContentItem) { setMessage('Edit the open content item below, or publish/pause it before creating the next one.'); return }
    const example = trend.examples[0]
    if (!example) return
    setBusy(`t${trend.topic}`)
    try {
      const training = /training|course|skill|employment|job|placement/i.test(trend.topic)
      const prObjective = training ? 'learner_reach' : 'ecosystem_influence'
      const audienceTargets: Record<string, string> = { learner: 'people asking about skills or training', job_seeker: 'people asking for job-search support', employer_workforce: 'employers describing a workforce skills need', ecosystem_partner: 'organizations exploring skills-sector collaboration', community_supporter: 'supporters seeking resources for learners', skills_audience_interest: 'people engaging with skills and career topics', unclear: 'the audience indicated by the supporting evidence' }
      const audienceProfile = audienceInsights?.segments[0]
      const audience = audienceTargets[trend.leading_audience || ''] || (audienceProfile ? `${label(audienceProfile.audience_segment)} in the conversation sample` : 'people whose needs are shown in the linked evidence')
      const audienceNeed = label(trend.leading_need || audienceInsights?.top_needs[0]?.need || 'general guidance')
      const locationSignal = audienceInsights?.location_mentions?.[0]
      const ageSignal = audienceInsights?.age_group_mentions?.[0]
      const learnedFormat = learning?.patterns.find((pattern) => pattern.usable_for_direction && pattern.pr_objective === prObjective && pattern.audience === audience)
      const format = learnedFormat?.format || (trend.questions >= 2 ? 'FAQ carousel or short explainer video' : 'learner story or practical short video')
      const directBrand = trend.monitoring_scope !== 'thematic'
      const reviewOwner = directBrand ? 'relevant Tata STRIVE team' : 'relevant skills and employment stakeholders'
      const message = directBrand ? 'Address the question or concern visible in the supporting conversation. Confirm programme details with an official source before including them.' : 'Use the conversation as a signal about the wider skills and employment ecosystem. Validate facts and avoid implying Tata STRIVE involvement unless independently confirmed.'
      const learnedNote = learnedFormat ? ` A similar objective has ${learnedFormat.sample_size} published item(s) with a mean observed strategic engagement score of ${learnedFormat.mean_score}; this is descriptive evidence, not proof that the format caused the result.` : ''
      const audienceEvidenceNote = audienceProfile ? ` Aggregate audience signal: ${audienceProfile.count} of ${audienceInsights?.sample_size} relevant records are labelled ${label(audienceProfile.audience_segment)} from wording; it is not a verified identity.` : ''
      const locationNote = locationSignal ? ` ${locationSignal.count} relevant record(s) explicitly mention ${locationSignal.place}; verify current delivery availability there before tailoring logistics.` : ''
      const ageNote = ageSignal ? ` Age wording explicitly appears (${ageSignal.group}); treat it only as a prompt to verify official eligibility, never as an author demographic.` : ''
      await createContentRecommendation({ topic: trend.topic, idea: `Create an evidence-led ${format.toLowerCase()} for ${audience}, focused on ${audienceNeed}. Treat the linked conversation as a prompt and validate the message with ${reviewOwner}.${locationNote}`, messaging: message, call_to_action: directBrand ? 'Invite people to share their question or check verified Tata STRIVE information.' : 'Invite people to share a practical question or consult an authoritative skills or employment resource.', rationale: `${trend.count} relevant ${trend.monitoring_scope || 'brand'}-stream records appear in the stored history, including ${trend.recent_30_days} in the last 30 days. The leading audience/need are inferred from wording at the conversation level, not verified identities. This is a content hypothesis; the sample may not represent the full audience.${audienceEvidenceNote}${locationNote}${ageNote}${learnedNote}`, evidence_record_ids: [example.record_id], pr_objective: prObjective, target_audience: audience, recommended_format: format, hook: example.text.slice(0, 220), distribution_channel: 'Select channel after audience and format review', priority_score: trend.score, confidence: example.audience_confidence ?? example.confidence })
      setMessage(`Content idea saved for ${trend.topic}.`); await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save idea') } finally { setBusy('') }
  }

  async function saveRecommendation(event: React.FormEvent<HTMLFormElement>, item: ContentRecommendation) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const value = (name: string) => String(form.get(name) || '').trim()
    const number = (name: string) => value(name) ? Number(value(name)) : null
    setBusy(`r${item.id}`)
    try {
      await updateContentRecommendation(item.id, { status: value('status') as ContentRecommendation['status'], review_state: value('review_state') as ContentRecommendation['review_state'], pr_objective: value('pr_objective'), collaboration_partner: value('collaboration_partner') || null, target_audience: value('target_audience'), recommended_format: value('recommended_format'), hook: value('hook'), owner: value('owner') || null, distribution_channel: value('distribution_channel') || null, channel: value('channel') || null, planned_at: value('planned_at') || null, published_at: value('published_at') || null, content_url: value('content_url') || null, idea: value('idea'), messaging: value('messaging'), call_to_action: value('call_to_action'), rationale: value('rationale'), priority_score: number('priority_score') ?? item.priority_score, confidence: number('confidence') ?? item.confidence, impressions: number('impressions'), reach: number('reach'), likes: number('likes'), comments: number('comments'), shares: number('shares'), follows: number('follows'), saves: number('saves'), relevant_stakeholder_engagements: number('relevant_stakeholder_engagements'), partnership_enquiries: number('partnership_enquiries'), media_enquiries: number('media_enquiries'), outcome_notes: value('outcome_notes') || null })
      setMessage('Content workflow and outcome metrics saved. The strategy plan is locked until you choose Edit plan.'); setEditingRecommendationId(null); await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save content item') } finally { setBusy('') }
  }

  async function generateOptions(item: ContentRecommendation) {
    setBusy(`g${item.id}`)
    try {
      const result = await generateContentOptions(item.id)
      setMessage(`${result.options.length} evidence-linked copy and format options generated. Review claims before use.`)
      await onRefresh()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not generate content options') } finally { setBusy('') }
  }

  return <div className="action-center">
    {message && <div className="notice">{message}</div>}
    {(showStrategy || showContent) && emailDrafts.length > 0 && <details className="saved-email-drafts"><summary>Saved email drafts · {emailDrafts.length}</summary>{emailDrafts.map((draft) => <article className="email-draft-item" key={draft.id}><div><strong>{draft.subject}</strong><span>{draft.target_type === 'partner' ? `To: ${draft.recipient_email}` : `Audience template: ${label(draft.audience_segment || 'learners')} · use with opt-in list`}</span><p>{draft.body}</p></div><div className="evidence-actions"><button className="secondary-button" onClick={() => void copyEmailDraft(draft)}>Copy</button>{draft.recipient_email && <a href={`mailto:${encodeURIComponent(draft.recipient_email)}?subject=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(draft.body)}`}>Open in mail app</a>}</div></article>)}</details>}

    {showAlerts && <article id="alerts-learning" className="panel"><div className="panel-header"><div><div className="section-kicker">ALERTS</div><h3>Signals that may need attention</h3><p>Review urgent language, rising topic activity, and scheduled follow-ups. Open the source before acting.</p></div><span className="opportunity-total">{alerts.length} active signals</span></div>{alerts.length ? <div className="trend-idea-list">{alerts.slice(0, 8).map((alert) => <div className="trend-idea" key={alert.id}><div><strong>{alert.severity.toUpperCase()} · {alert.title}</strong><span>{alert.detail}</span><span>{alert.published_at ? `Published ${new Date(alert.published_at).toLocaleString()}` : "Published date unavailable"} · {alert.collected_at ? `Collected ${new Date(alert.collected_at).toLocaleString()}` : "Collection date unavailable"}</span><span>{alert.topic ? `${label(alert.monitoring_scope || 'brand')} stream · ${alert.sample_size} records` : ''}</span></div><div className="alert-actions">{alert.record_id && <button className="secondary-button" onClick={() => onOpenConversation(alert.record_id!)}>Open conversation</button>}{alert.reply_draft_id && alert.record_id && <button className="secondary-button" onClick={() => onOpenReplyCenter(alert.record_id!)}>Open reply draft</button>}{alert.training_opportunity && alert.record_id && <button className="secondary-button" onClick={() => onOpenTrainingOpportunity(alert.record_id!)}>Training enquiry</button>}{alert.url && <a href={alert.url} target="_blank" rel="noopener noreferrer">Open evidence <ExternalLink size={12} /></a>}</div></div>)}<p className="panel-footer">Alerts are based on collected data and transparent rules; they do not establish a crisis or statistically significant trend.</p></div> : <div className="empty-feed follow-up-empty"><h4>No alert conditions met</h4><p>Alerts appear when the stored data meets a risk, growth, or follow-up rule.</p></div>}</article>}

    {showAlerts && <article id="learning" className="panel"><div className="panel-header"><div><div className="section-kicker">PERFORMANCE LEARNING</div><h3>What published outcomes suggest</h3><p>{learning?.measured_items ?? 0} of {learning?.published_items ?? 0} published items have reach-based metrics. {learning?.outcome_records ?? 0} attributed outcome record(s); recommendation feedback: {Object.values(learning?.recommendation_feedback || {}).reduce((sum, value) => sum + value, 0)}. Patterns with fewer than three items are exploratory; results are observational.</p></div></div>{learning?.patterns.length ? <div className="trend-idea-list">{learning.patterns.slice(0, 6).map((pattern) => <div className="trend-idea" key={`${pattern.pr_objective}-${pattern.format}-${pattern.audience}`}><div><strong>{pattern.format} · {label(pattern.pr_objective)}</strong><span>{pattern.sample_size} items · {pattern.mean_score} quality-weighted points per 100 reach · audience: {pattern.audience}</span><span>{pattern.recommendation}</span></div><span>{pattern.usable_for_direction ? 'Candidate signal' : 'Needs more data'}</span></div>)}{Object.entries(learning?.attributed_outcomes || {}).map(([type, count]) => <div className="trend-idea" key={type}><div><strong>Attributed {label(type)}</strong><span>{count.toLocaleString()} outcome(s) recorded across linked campaigns.</span></div></div>)}<p className="panel-footer">{learning.method}</p></div> : <div className="empty-feed follow-up-empty"><h4>No outcome patterns yet</h4><p>Mark published items and record reach plus meaningful interactions. Social Pulse will summarize comparable results after data is available.</p></div>}</article>}

    {showStrategy && <article id="strategy-radar" className="panel opportunities-panel"><div className="panel-header"><div><div className="section-kicker">STRATEGY RADAR · PARTNERS</div><h3>Potential partners from public activity</h3><p>Repeated public signals are grouped by account or reviewed organization. Scores prioritize evidence, recency, capability overlap, and recorded engagement; they do not qualify a lead or predict impact.</p></div><span className="opportunity-total">{partners.length} candidates</span></div>
      {partners.length ? <div className="action-list">{partners.map((partner) => <article className="action-card" key={partner.candidate_key}>
        <div className="opportunity-meta"><span className="source-chip">{partner.name}</span><span>{label(partner.stakeholder_type)}</span><span>{partner.source || 'source unknown'}</span><span>Radar {partner.radar_score}/100</span><span>{partner.signal_count} signal(s) · {partner.activity_30_days} in 30d · {partner.activity_90_days} in 90d</span><span>Identity review: {label(partner.review_state)}</span></div>
        <div className="trend-score-parts"><span>Evidence <strong>{partner.score_parts.evidence}/25</strong></span><span>Recency <strong>{partner.score_parts.recency}/20</strong></span><span>Capability overlap <strong>{partner.score_parts.capability_fit}/30</strong></span><span>Observed likes/replies <strong>{partner.score_parts.observed_engagement}/15</strong>{partner.likes == null && partner.replies == null ? ' · unavailable' : ''}</span><span>Actionable intent <strong>{partner.score_parts.actionable_intent}/10</strong></span></div>
        {partner.capability_matches.length ? <div className="capability-matches"><strong>Possible capability fit · verify with program teams</strong>{partner.capability_matches.map((match) => <span key={match.capability}>{match.capability} · {Math.round(match.score * 100)}% keyword match · terms: {match.matched_terms.join(', ')}</span>)}</div> : <p className="action-rationale">No capability overlap was detected in the collected text. Review the full source before deciding fit.</p>}
        <div className="action-rationale"><strong>Why this may help</strong><p>{partner.potential_value}</p></div>
        <section className="partner-approach-flow" aria-label={`Suggested approach plan for ${partner.name}`}><div className="partner-approach-heading"><div><span className="section-kicker">RECOMMENDED NEXT STEPS</span><h4>Suggested approach plan</h4></div><span>{partner.approach_plan.length} steps</span></div><ol>{partner.approach_plan.map((step, index) => <li key={`${partner.candidate_key}-${index}`}><span className="approach-step-marker" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span><div className="approach-step-copy"><span className="approach-step-label">{['Verify identity', 'Confirm mutual fit', 'Shape a small pilot', 'Make a tailored introduction', 'Follow up and learn'][index] || `Next step ${index + 1}`}</span><p>{step}</p></div></li>)}</ol><p className="approach-flow-note">Move forward only when the previous step is verified. Record the owner and follow-up below.</p></section>
        {partner.evidence.map((item) => <div id={`strategy-evidence-${item.record_id}`} className="evidence-link" key={item.record_id}><span>Evidence #{item.record_id} · {item.published_at ? new Date(item.published_at).toLocaleDateString() : 'date unavailable'} · {item.reason}<br />{item.text}</span><div className="evidence-actions"><button type="button" className="text-link" onClick={() => onOpenConversation(item.record_id)}>Conversation <ArrowUpRight size={13} /></button>{item.url && <a href={item.url} target="_blank" rel="noopener noreferrer">Source <ExternalLink size={12} /></a>}</div></div>)}
        <div className="trend-score-parts"><span>Identity match <strong>{partner.organization_verification === 'verified' ? 'verified' : 'unverified'}</strong></span>{partner.organization_website && <a href={partner.organization_website} target="_blank" rel="noopener noreferrer">Official website <ExternalLink size={12} /></a>}{partner.organization_contact_url && <a href={partner.organization_contact_url} target="_blank" rel="noopener noreferrer">Contact source <ExternalLink size={12} /></a>}</div>
        <form className="workflow-form" onSubmit={(event) => void savePartnerPlan(event, partner)}><label className="workflow-wide">Organization name · verify before outreach<input name="organization" defaultValue={partner.name.startsWith('Unidentified ') ? '' : partner.name} placeholder="Official organization name" /></label><label className="workflow-wide">Known account or name aliases<input name="aliases" placeholder="Comma-separated names or public handles" /></label><label>Partner review<select name="stakeholder_review" defaultValue={partner.review_state === 'verified' ? 'verified' : 'verify'}>{['verify','verified','not_a_fit'].map((state) => <option key={state} value={state}>{label(state)}</option>)}</select></label><label>Owner<input name="owner" defaultValue={partner.owner || ''} placeholder="Partnership lead" /></label><label>Official website<input name="website" type="url" defaultValue={partner.organization_website || ''} placeholder="https://organization.org" /></label><label>Published public email<input name="public_email" type="email" defaultValue={partner.organization_public_email || ''} placeholder="partnerships@organization.org" /></label><label>Official contact page<input name="contact_url" type="url" defaultValue={partner.organization_contact_url || ''} placeholder="https://organization.org/contact" /></label><label>Verification source URL<input name="verification_evidence" type="url" defaultValue={partner.organization_verification_evidence || ''} placeholder="Official page confirming identity/contact" /></label><label>Follow-up date<input name="follow_up_at" type="datetime-local" defaultValue={localDate(partner.follow_up_at)} /></label><button className="primary-button" disabled={busy === `partner-${partner.candidate_key}`}>{busy === `partner-${partner.candidate_key}` ? 'Saving…' : `Save verified profile & ${partner.opportunities.length} follow-up(s)`}</button></form>
        {partner.organization_verification === 'verified' && partner.organization_public_email && <form className="workflow-form recommendation-form" onSubmit={(event) => void savePartnerEmail(event, partner)}><div className="workflow-wide"><strong>Quick partner email · draft only</strong><p>To: {partner.organization_public_email} · public contact from the verified organization profile</p></div><label className="workflow-wide">Subject<input name="subject" defaultValue={`Exploring skills partnership with Tata STRIVE`} required /></label><label className="workflow-wide">Message<textarea name="body" defaultValue={`Hello ${partner.name} team,\n\nI noticed your public conversation about skills and workforce needs. I’d welcome a brief discussion to understand your priorities and assess whether a small, measurable skills partnership could be useful.\n\nWould you be open to an introductory conversation?\n\nRegards,\nTata STRIVE`} required /></label><button className="secondary-button" disabled={busy === `email-${partner.candidate_key}`}>{busy === `email-${partner.candidate_key}` ? 'Saving…' : 'Save email draft'}</button></form>}
        <div className="action-rationale"><strong>Collaboration growth tracking</strong><p>{partner.growth_measurement.content_items ? `${partner.growth_measurement.published_items} published item(s), ${partner.growth_measurement.measured_items} with reach, ${partner.growth_measurement.recorded_reach.toLocaleString()} recorded reach, ${partner.growth_measurement.stakeholder_engagements} stakeholder interactions, ${partner.growth_measurement.partnership_enquiries} partnership enquiries, and ${partner.growth_measurement.media_enquiries} media enquiries.` : 'No collaboration content or outcome baseline is recorded yet. Create a content plan, then enter observed reach, relevant stakeholder interactions, enquiries, and learner outcomes after publication.'}</p><span>These are manually tracked observed outcomes; compare with a pre-collaboration baseline and do not attribute growth to the partnership without a suitable evaluation.</span></div>
        <div className="strategy-partner-actions"><button className="secondary-button" disabled={Boolean(busy) || hasOpenContentItem} onClick={() => void createPartnerContentPlan(partner)}>{busy === `partner-content-${partner.candidate_key}` ? 'Creating…' : hasOpenContentItem ? 'Edit open idea below' : 'Add content plan from Radar'}</button>{partner.opportunities.some((item) => item.follow_up_at) && <button type="button" className="secondary-button danger-button" disabled={Boolean(busy)} onClick={() => void removePartnerFollowUps(partner)}>{busy === `clear-followups-${partner.candidate_key}` ? 'Removing…' : 'Remove scheduled follow-ups'}</button>}<button type="button" className="secondary-button danger-button" disabled={Boolean(busy) || !partner.opportunities.length} onClick={() => void removeStrategyPartner(partner)}>{busy === `remove-partner-${partner.candidate_key}` ? 'Removing…' : 'Remove from Strategy Radar'}</button></div>
      </article>)}</div> : <div className="empty-feed"><h4>No partner signals identified yet</h4><p>Collect and analyze public posts/comments about employer skills needs, CSR, grants, research, government programs, or ecosystem collaboration. Candidate discovery is limited by source coverage and public author metadata.</p></div>}
      <div className="panel-footer"><span>Public accounts are leads for review, not confirmed organizations. Use published partnership channels and record consent before co-branded content.</span></div>
    </article>}

    {showEngagement && <article id="follow-up-radar" className="panel follow-up-panel"><div className="panel-header"><div><div className="section-kicker">FOLLOW-UP RADAR</div><h3>Due and overdue conversations</h3><p>Open opportunities with a follow-up scheduled in the past or next seven days.</p></div><span className="opportunity-total">{followUps.filter(({ due }) => due <= now).length} due · {followUps.length} shown</span></div>
      {followUps.length ? <div className="follow-up-list">{followUps.slice(0, 8).map(({ item, due }) => {
        const daysLate = Math.floor((now - due) / (24 * 60 * 60 * 1000))
        const daysUntil = Math.ceil((due - now) / (24 * 60 * 60 * 1000))
        const dueLabel = due < now && daysLate >= 1 ? `Overdue by ${daysLate} day${daysLate === 1 ? '' : 's'}` : due <= now ? 'Overdue · today' : daysUntil <= 1 ? 'Due today' : `Due in ${daysUntil} days`
        return <div className="follow-up-item" key={item.id}><div className="follow-up-copy"><span className={due <= now ? 'follow-up-due overdue' : 'follow-up-due'}>{dueLabel}</span><strong>{item.owner ? `Owner: ${item.owner}` : 'Unassigned follow-up'} · {item.source}</strong><span>{item.text}</span></div><div className="follow-up-actions"><time>{new Date(due).toLocaleString()}</time><button className="text-link" onClick={() => onOpenConversation(item.record_id)}>Conversation <ArrowUpRight size={13} /></button>{item.url && <a href={item.url} target="_blank" rel="noopener noreferrer">Source <ExternalLink size={12} /></a>}</div></div>
      })}</div> : <div className="empty-feed follow-up-empty"><h4>No follow-ups due soon</h4><p>Set a follow-up date on an open conversation to add it to this list.</p></div>}
    </article>}

    {showEngagement && <article id="engagement-queue" className="panel opportunities-panel"><div className="panel-header"><div><div className="section-kicker">HUMAN REVIEW QUEUE</div><h3>Conversation opportunities</h3><p>Questions, concerns, suggestions, and explicit collaboration signals from public posts/comments plus clearly labeled thematic search leads.</p></div></div>
      {active.length ? <div className="action-list">{active.map((item) => <article className="action-card" key={item.id}>
        <div className="opportunity-meta"><span className="source-chip">{item.source} · {label(item.record_type)} · opportunity {item.opportunity_score ?? item.priority_score}/100</span><span>Evidence {item.score_parts?.evidence_strength ?? "—"} · confidence {item.score_parts?.confidence ?? "—"} · strategic value {item.score_parts?.strategic_value ?? "—"} · urgency {item.score_parts?.urgency ?? "—"} · recency {item.score_parts?.recency ?? "—"}</span><span>Action: {label(item.action_type)}</span><span>PR objective: {label(item.pr_objective_key || item.pr_objective)}</span>{item.pr_objective_explanation && <span>{item.pr_objective_explanation}</span>}<span>{item.author || 'Public commenter'}</span><span>{item.published_at ? new Date(item.published_at).toLocaleString() : 'Date unavailable'}</span>{item.is_stale && <span className="quality-badge duplicate-badge">Stale · {item.staleness_days} days without update</span>}{item.duplicate_of_record_id && <span className="quality-badge duplicate-badge">Possible duplicate of record #{item.duplicate_of_record_id}</span>}</div><p className="opportunity-comment">{item.text}</p>{item.record_type === 'search_result' && <div className="notice discovery-evidence-note">Search title/snippet only. Open the linked page and verify the person, organization, activity, and current fit before acting.</div>}<div className="action-rationale"><strong>{item.reason}</strong><p>{item.suggested_action}</p><span>Likely audience need: {label(item.audience_segment || 'unclear')} · {label(item.audience_need || 'unclear')} · {Math.round((item.audience_confidence || 0) * 100)}% text confidence</span><span>Signal confidence: {Math.round(item.confidence * 100)}% · Human review: {label(item.review_state)}</span>{item.capability_matches?.length ? <div className="capability-matches"><strong>Possible capability fit · verify</strong>{item.capability_matches.map((match) => <span key={match.capability}>{match.capability} · {Math.round(match.score * 100)}% keyword fit · terms: {match.matched_terms.join(', ')}</span>)}</div> : null}{item.stakeholder_type && <span>Possible stakeholder: {item.stakeholder_type}{item.partnership_signal ? ' · potential partnership signal; verify independently' : ''}</span>}</div>{item.url && <a className="action-source" href={item.url} target="_blank" rel="noopener noreferrer">{item.record_type === 'search_result' ? 'Open discovered page · verify source' : 'Open original conversation'} <ExternalLink size={12} /></a>}
        <div className="opportunity-actions"><button type="button" className="secondary-button" onClick={() => onOpenConversation(item.record_id)}>Open conversation</button>{item.url && <a href={item.url} target="_blank" rel="noopener noreferrer">Original source <ExternalLink size={12} /></a>}{opportunities.some((opportunity) => opportunity.record_id === item.record_id) && <button type="button" className="secondary-button" onClick={() => onOpenTrainingOpportunity(item.record_id)}>Training opportunity</button>}</div><form className="workflow-form" onSubmit={(event) => void saveOpportunity(event, item)}><label>Status<select name="status" defaultValue={item.status}>{['new','assigned','responded','follow_up','closed','dismissed'].map((status) => <option key={status} value={status}>{label(status)}</option>)}</select></label><label>Evidence review<select name="review_state" defaultValue={item.review_state}>{['review_required','validated','insufficient_evidence'].map((state) => <option key={state} value={state}>{label(state)}</option>)}</select></label><label>Owner<input name="owner" defaultValue={item.owner || ''} placeholder="Team member" /></label><label>Follow-up date<input name="follow_up_at" type="datetime-local" defaultValue={localDate(item.follow_up_at)} /></label>{item.partnership_signal && <><label>Organization to verify<input name="stakeholder_name" defaultValue={item.stakeholder_name || ''} placeholder="Confirm from original source" /></label><label>Geography<input name="stakeholder_geography" defaultValue={item.stakeholder_geography || ''} placeholder="City / region" /></label><label>Partner review<select name="stakeholder_review" defaultValue={item.stakeholder_review || 'not_assessed'}>{['not_assessed','verify','verified','not_a_fit'].map((state) => <option key={state} value={state}>{label(state)}</option>)}</select></label><label className="workflow-wide">Capability and fit notes<textarea name="stakeholder_fit_notes" defaultValue={item.stakeholder_fit_notes || ''} placeholder="Need, evidence, geography, and possible fit to validate" /></label></>}<label className="workflow-wide">Follow-up notes<textarea name="notes" defaultValue={item.notes || ''} placeholder="Response made, facts to verify, next step…" /></label><button className="primary-button" disabled={busy === `o${item.id}`}>{busy === `o${item.id}` ? 'Saving…' : 'Save follow-up'}</button></form>
      </article>)}</div> : <div className="empty-feed"><h4>No conversation opportunities yet</h4><p>Collect and analyze relevant public posts or comments. The queue identifies questions, suggestions, complaints, and high-priority items.</p></div>}
    </article>}

    {showContent && <article id="content-growth" className="panel opportunities-panel"><div className="panel-header"><div><div className="section-kicker">CONTENT PLANNING & GROWTH</div><h3>Evidence-linked content ideas</h3><p>Turn a trend into a reviewable content hypothesis with supporting conversation evidence.</p></div></div>
      <details className="quick-email-panel"><summary><span><strong>Audience email</strong><small>Build a draft for an opt-in list</small></span><span className="content-plan-summary-action">Open</span></summary><div className="quick-email-body"><p>Personal addresses are not discovered or stored. Drafts are never sent automatically.</p><form className="workflow-form recommendation-form" onSubmit={(event) => void saveAudienceEmail(event)}><label>Audience segment<select name="audience_segment" defaultValue="learners">{(audienceInsights?.segments.length ? audienceInsights.segments.map((segment) => segment.audience_segment) : ['learners', 'job_seekers', 'employers']).map((segment) => <option value={segment} key={segment}>{label(segment)}</option>)}</select></label><label>Subject<input name="subject" required placeholder="A useful next step for your skills journey" /></label><label className="workflow-wide">Email body<textarea name="body" required placeholder="Write a helpful, fact-checked message and include an official resource link." /></label><button className="secondary-button" disabled={busy === 'audience-email'}>{busy === 'audience-email' ? 'Saving…' : 'Save audience email template'}</button></form></div></details>
      <div className="trend-coverage content-growth-coverage"><span><strong>{published.length}</strong> marked published</span><span><strong>{measured.length}</strong> with manual outcome metrics</span>{measured.some((item) => item.reach != null) && <span><strong>{total('reach').toLocaleString()}</strong> recorded reach</span>}{measured.some((item) => item.impressions != null) && <span><strong>{total('impressions').toLocaleString()}</strong> recorded impressions</span>}<span><strong>{(total('likes') + total('comments') + total('shares')).toLocaleString()}</strong> recorded interactions</span></div>
      {byFormat.length > 0 && <details className="content-format-review"><summary><span>Published format review</span><small>{measured.length} measured item(s)</small></summary><div className="trend-idea-list"><div className="section-kicker">OBSERVATIONAL FORMAT REVIEW</div>{byFormat.map((group) => <div className="trend-idea" key={`${group.format}-${group.channel}`}><div><strong>{group.format} · {group.channel}</strong><span>{group.count} measured item{group.count === 1 ? '' : 's'} · {group.reachItems} with reach · {group.reach > 0 ? `${Math.round(group.interactions / group.reach * 100)} interactions per 100 recorded reach` : 'rate unavailable'}</span></div></div>)}<p className="panel-footer">Manual metrics are not independently verified. Small samples and different audiences/channels do not establish causation or prove that a format performs better.</p></div></details>}
      {hasOpenContentItem && <div className="notice">One content item is open. Edit it below; publish or pause it to unlock the next idea.</div>}
      {contentTrendGroups.length ? <details className="content-trend-details"><summary><span>Trend ideas</span><small>{contentTrendGroups.length} topics · expand to browse</small></summary><div className="trend-idea-list">{contentTrendGroups.map(({ trend, streams }) => <div className="trend-idea" key={trend.topic.toLocaleLowerCase()}><div><strong>{label(trend.topic)}</strong><span>{Array.from(streams, ([scope, counts]) => `${label(scope)}: ${counts.count} records · ${counts.recent} recent`).join(' · ')} · {trend.attention}</span></div><button className="secondary-button" disabled={Boolean(busy) || hasOpenContentItem} onClick={() => void makeIdea(trend)}>{busy === `t${trend.topic}` ? 'Saving…' : hasOpenContentItem ? 'Edit open idea below' : 'Create content idea'}</button></div>)}</div></details> : <div className="empty-feed"><h4>No trends to turn into content yet</h4><p>Collect and analyze social posts or comments to build evidence-backed ideas.</p></div>}
      <div className="content-plan-list-heading"><span>Saved content plans</span><small>{recommendations.length} · expand a plan to review or edit</small></div>{recommendations.length > 0 && <div className="recommendation-list">{recommendations.map((item) => <article className="recommendation-card" key={item.id}><details className="content-plan-details" open={editingRecommendationId === item.id}><summary><span><strong>{label(item.topic)}</strong><small>{label(item.status)} · {label(item.pr_objective)} · Priority {item.priority_score}/100 · confidence {Math.round(item.confidence * 100)}%</small></span><span className="content-plan-summary-action">View plan</span></summary><div className="content-plan-body">
        <div className="opportunity-meta"><span className="source-chip">{label(item.topic)}</span>{item.collaboration_partner && <span>Collaboration: {item.collaboration_partner}</span>}<span>Status: {label(item.status)}</span><span>Created {item.created_at ? new Date(item.created_at).toLocaleString() : "date unavailable"}</span><span>Evidence review: {label(item.review_state)}</span><span>Priority {item.priority_score}/100 · confidence {Math.round(item.confidence * 100)}%</span><span>{item.strategic_engagement_score == null ? 'Strategic score: unavailable until reach is recorded' : `Strategic score: ${item.strategic_engagement_score} quality-weighted points per 100 reach`}</span><button type="button" className="secondary-button" disabled={Boolean(busy) || item.status === 'paused'} title={item.status === 'paused' ? 'Resume this plan in the Status field before generating copy' : undefined} onClick={() => void generateOptions(item)}>{busy === `g${item.id}` ? 'Generating…' : item.generated_content_options?.length ? 'Regenerate copy options' : 'Generate copy options'}</button><button type="button" className="secondary-button danger-button" disabled={Boolean(busy)} onClick={() => void deleteRecommendation(item)}>{busy === `delete-recommendation-${item.id}` ? 'Deleting…' : 'Delete content plan'}</button></div>
        <div className="content-plan-lock">{editingRecommendationId === item.id ? <span>Editing plan · save to lock this strategy again.</span> : <><span>Strategy plan is locked after saving.</span><button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => setEditingRecommendationId(item.id)}>Edit plan</button></>}</div>
        <div className="content-email-action"><button type="button" className="secondary-button" disabled={busy === `plan-email-${item.id}`} onClick={() => void generatePlanEmail(item)}>{busy === `plan-email-${item.id}` ? 'Generating email…' : 'Generate audience email draft from this plan'}</button><span>Creates a reviewable opt-in audience template with the plan CTA and evidence. It does not send email.</span></div>        <form className="workflow-form recommendation-form" onSubmit={(event) => void saveRecommendation(event, item)}><fieldset className="recommendation-fields" disabled={editingRecommendationId !== item.id}><label className="workflow-wide">Content idea<textarea name="idea" defaultValue={item.idea} /></label><label>PR objective<select name="pr_objective" defaultValue={objectiveKey(item.pr_objective)}>{PR_OBJECTIVES.map(([key, objectiveLabel]) => <option key={key} value={key}>{objectiveLabel}</option>)}</select></label><details className="workflow-wide pr-playbooks"><summary>Objective playbooks and measures</summary>{PR_OBJECTIVES.map(([key, objectiveLabel, why, plays, measures]) => <p key={key}><strong>{objectiveLabel}:</strong> {why} Recommended plays: {plays} Measures: {measures}</p>)}</details><label>Collaboration partner<input name="collaboration_partner" defaultValue={item.collaboration_partner || ""} placeholder="Optional · exact radar candidate name" /></label><label>Target audience<input name="target_audience" defaultValue={item.target_audience} /></label><label>Recommended format<input name="recommended_format" defaultValue={item.recommended_format} /></label><label className="workflow-wide">Hook / opening<textarea name="hook" defaultValue={item.hook} /></label><label>Key message<input name="messaging" defaultValue={item.messaging} /></label><label>Call to action<input name="call_to_action" defaultValue={item.call_to_action} /></label><label>Evidence rationale<input name="rationale" defaultValue={item.rationale} /></label><label>Status<select name="status" defaultValue={item.status}>{['idea','drafting','review','scheduled','published','paused'].map((status) => <option key={status} value={status}>{label(status)}</option>)}</select></label><label>Human verification<select name="review_state" defaultValue={item.review_state}>{['review_required','validated','insufficient_evidence'].map((state) => <option key={state} value={state}>{label(state)}</option>)}</select></label><label>Owner<input name="owner" defaultValue={item.owner || ''} placeholder="Team member" /></label><label>Priority score<input name="priority_score" type="number" min="0" max="100" defaultValue={item.priority_score} /></label><label>Confidence<input name="confidence" type="number" min="0" max="1" step="0.01" defaultValue={item.confidence} /></label><label>Suggested distribution<input name="distribution_channel" defaultValue={item.distribution_channel || ''} /></label><label>Channel<input name="channel" defaultValue={item.channel || ''} placeholder="e.g. Instagram" /></label><label>Planned date<input name="planned_at" type="datetime-local" defaultValue={localDate(item.planned_at)} /></label><label>Published date<input name="published_at" type="datetime-local" defaultValue={localDate(item.published_at)} /></label><label>Published content URL<input name="content_url" type="url" defaultValue={item.content_url || ''} placeholder="https://…" /></label><div className="metric-entry">{(['impressions','reach','likes','comments','shares','follows'] as const).map((metric) => <label key={metric}>{label(metric)}<input name={metric} type="number" min="0" defaultValue={item[metric] ?? ''} placeholder="Not recorded" /></label>)}</div><label>Relevant stakeholder interactions<input name="relevant_stakeholder_engagements" type="number" min="0" defaultValue={item.relevant_stakeholder_engagements ?? ''} placeholder="Not recorded" /></label><label>Partnership enquiries<input name="partnership_enquiries" type="number" min="0" defaultValue={item.partnership_enquiries ?? ''} placeholder="Not recorded" /></label><label>Media enquiries<input name="media_enquiries" type="number" min="0" defaultValue={item.media_enquiries ?? ''} placeholder="Not recorded" /></label><label>Saves<input name="saves" type="number" min="0" defaultValue={item.saves ?? ''} placeholder="Not recorded" /></label><label className="workflow-wide">Outcome notes<textarea name="outcome_notes" defaultValue={item.outcome_notes || ''} placeholder="Observation period, metric source, and what the team learned…" /></label><button className="primary-button" disabled={busy === `r${item.id}`}>{busy === `r${item.id}` ? 'Saving…' : 'Save strategy & results'}</button></fieldset></form><div className="feedback-tools"><span>Evidence: {item.evidence_validation?.score ?? '—'}/100 · {item.evidence_validation?.confidence_label || 'not assessed'} · {item.evidence_validation?.original_conversation_count ?? item.evidence.length} original conversation(s)</span><div><button type="button" className="text-link" onClick={() => void rateRecommendation(item.id, 'useful')}>Useful</button><button type="button" className="text-link" onClick={() => void rateRecommendation(item.id, 'not_useful')}>Not useful</button><button type="button" className="text-link" onClick={() => void rateRecommendation(item.id, 'used')}>Used</button></div></div>{item.feedback?.length ? <small>{item.feedback.length} feedback response(s) · latest: {label(item.feedback[0].rating)}</small> : null}<details className="campaign-attribution"><summary>Add campaign outcome attribution</summary><form className="workflow-form recommendation-form" onSubmit={(event) => void saveOutcome(event, item)}><label>Campaign name<input name="campaign_name" required placeholder="Campaign or activation" /></label><label>Outcome<select name="outcome_type">{['learner_enquiry','application','placement','partnership','media','stakeholder_engagement','reach','other'].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label><label>Observed count<input name="value" type="number" min="0" defaultValue="1" /></label><label>Attribution method<select name="attribution_method">{['team_reported','tracked_link','platform_report','self_reported','uncertain'].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label><label className="workflow-wide">Evidence URL<input name="evidence_url" type="url" placeholder="Optional report or tracked link" /></label><label className="workflow-wide">Notes<textarea name="notes" placeholder="Measurement window, source, and attribution limits" /></label><button className="secondary-button" disabled={busy === `outcome-${item.id}`}>{busy === `outcome-${item.id}` ? 'Saving…' : 'Save attributed outcome'}</button></form>{item.campaign_outcomes?.map((outcome) => <div className="evidence-link" key={outcome.id}><span>{outcome.campaign_name} · {label(outcome.outcome_type)}: {outcome.value} · {label(outcome.attribution_method)} · {new Date(outcome.measured_at).toLocaleDateString()}</span>{outcome.evidence_url && <a href={outcome.evidence_url} target="_blank" rel="noopener noreferrer">Evidence <ExternalLink size={12} /></a>}</div>)}</details>{item.generated_content_options?.length ? <div className="generated-options"><div className="section-kicker">COPY OPTIONS · REVIEW BEFORE USE</div>{item.generated_content_options.map((option, index) => <article className="generated-option" key={`${item.id}-${index}`}><div className="opportunity-meta"><strong>{index + 1}. {option.format}</strong><span>{option.angle}</span><span>Evidence: {option.evidence_record_ids.map((id) => `#${id}`).join(', ') || 'no citations returned; verify against linked evidence'}</span></div><p>{option.copy}</p><span>Suggested CTA: {option.call_to_action}</span></article>)}</div> : null}{item.evidence.map((evidence) => <div className="evidence-link" key={evidence.id}><span>Evidence · {evidence.source}: {evidence.text}</span><div className="evidence-actions">{evidence.id && <button type="button" className="text-link" onClick={() => onOpenConversation(evidence.id)}>Conversation #{evidence.id} <ArrowUpRight size={13} /></button>}{evidence.url && <a href={evidence.url} target="_blank" rel="noopener noreferrer">Source <ExternalLink size={12} /></a>}</div></div>)}
        </div></details></article>)}</div>}
      <div className="panel-footer"><span>Metrics are entered by the team; blank means unavailable. Results show association, not proof of causation.</span></div>
    </article>}
  </div>
}
