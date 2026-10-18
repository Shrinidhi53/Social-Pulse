# Social Pulse: Solution Gap Analysis

**Audit date:** 18 October 2026  
**Audience:** Product and engineering  
**Monitoring scope:** Keep direct Tata STRIVE conversations separate from broader skills, employability, entrepreneurship, and youth-development conversations.

## Executive summary

Social Pulse is moving toward the strategic vision of a PR and social-intelligence copilot: it now connects collected conversations to trends, recommended actions, PR objectives, evidence-linked content briefs, human review, and manually recorded content outcomes. The Action Center adds owner assignment and follow-up tracking for conversation opportunities, tailors next steps to inferred audience needs, and tracks content from evidence through publication.

The largest constraint remains collection scope: thematic search covers Bluesky only, while YouTube and news discovery remain focused on Tata STRIVE. Language hints, audience pain points, trend alerts, PR objectives, opportunity freshness, and capability matches are explainable heuristics, not verified intelligence. The app now links likely cross-source duplicates without deleting evidence, can label simulated records, generates locally grounded content options for review, records meaningful stakeholder outcomes, and uses sufficiently sampled historical format results as a cautious input to later briefs. It still has no authorized social account analytics integration, autonomous publishing, verified automated partner matching, campaign attribution, or model training from outcomes.

The strategic goals document contains the original hackathon requirements plus broader product extensions. This review marks each goal according to current code; heuristic labels and public-source samples should not be treated as verified facts or representative audience research.

## What is implemented today

- **Collection:** Bluesky searches explicit Tata STRIVE phrases and a separate thematic skills/employment query set; thematic records retain scope and query provenance. YouTube video discovery plus matching comments and replies, GNews and GDELT news, and SerpApi Google Search remain brand-focused. Users can fetch all sources on demand; the open frontend also runs collection every 30 minutes and refreshes its stored-data view every 30 seconds. Source-run history and per-source failures are shown in Reports. Scheduled collection stops when the app is closed.
- **Data quality:** New records receive canonical matching text, content hashes, conservative language hints, and simulated-data provenance. A Reports action backfills these fields on older records and links likely same-type exact/near-duplicates across sources without deleting evidence. Suspected duplicates are excluded from trend, audience, and opportunity aggregates.
- **Data separation:** News records and Google Search result snippets are distinguishable from original social comments and posts. Search snippets are not treated as comments or used as audience sentiment evidence.
- **Analysis:** VADER and keyword rules estimate relevance, topic, intent, sentiment, priority, audience need, pain points, and cautious conversation-emotion cues. Script-based language hints appear in records and coverage summaries. These describe likely conversation context, not verified author identity or demographics.
- **Trend view:** Insights ranks unique social posts/comments by volume, recency, risk, demand, and growth; it reports heuristic lifecycle, velocity, novelty, and source counter coverage. The Action Center raises explainable urgent-language, rising-volume, and due-follow-up alerts. Source counters are not treated as interchangeable engagement acceleration.
- **Engagement opportunities:** The Action Center prioritizes relevant questions, complaints, suggestions, risks, and possible partnership signals. It proposes more specific PR objectives, tracks owner/status/follow-up, flags records not updated for 30 days, and surfaces possible capability matches with matched terms and review caveats. These are candidates, not verified partner leads.
- **Content strategy:** Trend ideas include linked evidence, objective, audience, format, hook, message, CTA, distribution suggestion, priority, and confidence. The local model can produce three evidence-linked format/copy alternatives; reviewers edit and track briefs through review and publication states.
- **Performance follow-up:** Teams can record reach, impressions, likes, comments, shares, follows, saves, relevant stakeholder interactions, partnership enquiries, and media enquiries. A transparent weighted score summarizes quality-weighted points per recorded reach. The learning report groups published outcomes by objective, format, and audience; groups with at least three examples can inform later briefs as observational evidence, not causal learning.
- **Reply review:** Reply Center supports editing, regeneration, approval, and rejection. Approval does not publish.

Evidence is primarily in `backend/app/ingestion/`, `backend/app/analysis_engine.py`, `backend/app/signals.py`, `backend/app/main.py`, `backend/app/models.py`, `backend/app/opportunities.py`, `backend/app/database.py`, `frontend/src/ActionCenter.tsx`, and `frontend/src/App.tsx`.

## Strategic goals alignment

| Goal | Status | Current implementation | Remaining gap |
|---|---|---|---|
| **G1 Unified external intelligence** | **Partial** | Multiple sources, brand/thematic scopes, provenance, canonical text, conservative language hints, simulated-data labels, and reviewable cross-source duplicate links. | Broaden thematic coverage beyond Bluesky; improve language/region detection; add human duplicate review and source-coverage measurement. |
| **G2 Audience intelligence** | **Partial** | Audience and need estimates include pain-point and cautious emotional wording cues, confidence, sample counts, and evidence. | Labels remain English keyword heuristics; they need human audit, multilingual taxonomy, regional context, and representative audience validation. |
| **G3 Emerging trend intelligence** | **Partial** | Topic volume, 30-day change, velocity, heuristic lifecycle/novelty, source counter coverage, and explainable urgent/rising/follow-up alerts. | No semantic clustering, repeated engagement snapshots/acceleration, capability-fit scoring, or validated lifecycle model. |
| **G4 Engagement opportunity detection** | **Partial** | Opportunities receive action/objective suggestions, priority, confidence, evidence, review state, owner/follow-up, stale flags, and duplicate links. Response status and notes can be recorded. | Detection and scoring remain rules-based; response outcomes are manual; stale and duplicate decisions require review; collection coverage is limited. |
| **G5 PR objective intelligence** | **Partial** | Rules distinguish programme education, issue management, partnership, government/ecosystem relations, knowledge partners, thought leadership/media, learner stories, and community engagement. | Objectives are not model-validated, campaign-linked, or evaluated against an agreed communications strategy. |
| **G6 Stakeholder and partnership discovery** | **Partial** | A capability catalogue returns keyword matches, matched terms, and candidate scores; reviewers can verify organization, geography, and fit. | Matching is not entity resolution, current capability retrieval, geographic availability checking, or a qualified-lead workflow. |
| **G7 Strategic content generation** | **Partial** | Evidence-linked briefs can generate three local-model copy/format alternatives with evidence IDs and claim constraints; reviewers can edit and publication-track them. | No verified capability feed, campaign sequences, executive briefing pack, spokesperson approval workflow, or media database integration. |
| **G8 Meaningful audience/ecosystem growth** | **Partial** | Manual outcomes include relevant stakeholder interactions, partnership/media enquiries, saves, and a quality-weighted score when reach is present. | No authorized channel analytics, verified stakeholder weighting, longitudinal growth snapshots, or validated score weights. |
| **G9 Performance learning loop** | **Partial** | Published results are summarized by objective, format, and target audience; sampled observational patterns can seed format suggestions in later briefs. | No causal attribution, controlled evaluation, automated model training, or automatic ranking changes based on outcomes. |

The original brief's end-to-end flow is now represented as collection → analysis → trend/opportunity → recommended action/content brief → human follow-up → manually recorded result. The flow is reviewable but not fully automated or real-time: source collection runs on demand or on a 30-minute schedule while the frontend remains open; publication/analytics are not integrated.

## Source coverage and interpretation limits

- **Bluesky:** Public search has a strict direct Tata STRIVE stream plus a separately labeled thematic skills/employment stream within the configured rolling time window. The thematic stream still covers only a small set of English queries and has no regional/language normalization. Current records include likes and reply counts where returned.
- **YouTube:** Search discovers candidate videos across channels and then collects substantive comments/replies mentioning Tata STRIVE. YouTube does not offer global comment search; candidate discovery, quotas, deleted content, and disabled comments limit completeness. Comment records can include like and reply counts, but those are not video reach or impressions.
- **GNews and GDELT:** These provide news coverage, not audience comments. News is stored separately and excluded from audience-feedback trends.
- **SerpApi / Google Search:** This stores visible result URLs, titles, and snippets. It does not fetch the underlying Instagram, LinkedIn, Reddit, or other site comments. Snippets are not verified original social comments.
- **Instagram, LinkedIn, and Reddit:** There is no direct comment collector in this project. Access is subject to platform APIs, permissions, and applicable usage terms. Use authorized integrations or user-authorized exports when comment-level data is required.
- **Engagement and growth:** Some source counters are stored on records; content reach, impressions, interactions, and follows can be entered on a recommendation after publication. These are not authorized live integrations or longitudinal channel snapshots. Missing counters remain missing, not zero.
- **Representativeness:** Public search results and accessible posts are a sample, not a census of audience opinion. Every dashboard insight should retain source, date window, sample size, and coverage context.

## Recommended implementation roadmap

### 1. Separate brand and thematic monitoring

The first pass is implemented for Bluesky: direct brand and thematic records have separate scopes, provenance, dashboard filtering, summary counts, and trend rankings. Extend the thematic query catalog and this separation to additional authorized sources; refine taxonomy, region/language support, and coverage measurement.

**Acceptance checks:** Direct-brand and thematic records can be filtered and counted separately; general theme matches never become direct Tata STRIVE mentions; each collection run reports its queries, date window, source, and failures.

### 2. Strengthen audience-interest analysis

Define a stable topic taxonomy covering the requested themes and audience needs. Support multiple relevant topics where appropriate, preserve existing sentiment/intent/priority outputs, and expose evidence, confidence, analysis method, and sample size. Show changes over time only when there is enough dated data to support them.

**Acceptance checks:** Analysts can see top interests by stream and source; low-confidence labels are visible; small samples are not presented as reliable audience-wide trends; rule-based estimates are identified as estimates.

### 3. Add source-aware engagement analysis

Use likes, replies, and views only where the source supplies them. Establish source-specific measures and comparisons, record metric observation time if repeated snapshots are collected, and avoid treating absent metrics as zero. Separate popularity signals from conversation volume and urgency.

**Acceptance checks:** The dashboard states metric coverage and denominator; rankings only compare compatible source/record types; missing metrics are excluded from rate calculations; high-engagement examples link to their original content.

### 4. Validate opportunity and partnership signals

Improve the rules with audited labels, deduplication, staleness handling, source provenance, stakeholder verification, and a Tata STRIVE capability catalogue. Keep replies and partner outreach as optional human-reviewed actions, never automatic.

**Acceptance checks:** Opportunity cards are traceable to source records; duplicate or stale opportunities are handled; unrelated content is excluded; no reply is published automatically.

### 5. Extend strategic content planning

Build beyond the current evidence-linked content brief with validated audience/tone/channel options, alternative formats, thought-leadership and media angles, and grounded copy generation. Keep evidence, generated suggestions, review state, and unsupported claims clearly separated.

**Acceptance checks:** Each recommendation links to supporting records and states its data window; unsupported claims and fabricated audience preferences are not presented as facts; a reviewer can edit, accept, or dismiss suggestions.

### 6. Close the outcome and learning loop

Add authorized channel-level metrics and dated snapshots for relevant reach, stakeholder engagement, and other available outcomes. Track which recommendations were published and associate results where platform identifiers allow. Start with transparent reporting and reviewed learning; do not promise growth or imply causation.

**Acceptance checks:** Growth charts show source, observation date, and missing-data periods; outcomes can be tied to a recommendation or published content only when identifiers are available; the UI labels correlation as observational rather than causal.

## Suggested measures of success

- **Coverage:** Number of successful source runs, records by source and monitoring scope, query/date-window coverage, and visible failure/quota counts.
- **Relevance quality:** Audited precision for direct-brand versus thematic classification, plus the share of records with confidence and source evidence.
- **Audience insight quality:** Topic-label audit results, sentiment review samples, and trend stability with the analyzed sample size shown.
- **Engagement analysis:** Share of eligible records with each metric, source-specific engagement distributions, and the number of recommendations backed by measured engagement.
- **Opportunity usefulness:** Human-rated relevance, actionability, and stale/duplicate rate for surfaced opportunities.
- **Content recommendations:** Percentage with traceable evidence, reviewer acceptance/edit/dismissal, and later performance where authorized metrics exist.
- **Audience growth:** Change in available channel audience metrics over time, with observation coverage and no causal attribution unless supported by an appropriate evaluation design.

## Implementation note

This document describes the current repository implementation and a recommended direction. It does not itself add collection sources, change APIs or database schemas, enable platform publishing, or guarantee access to third-party data. Schema/API changes should be designed during the corresponding roadmap stage after source availability and metric semantics are confirmed.
