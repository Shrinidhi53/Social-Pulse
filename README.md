# Social Pulse

Evidence-first social listening for public skill-development and employability conversations, initially focused on Tata STRIVE. News coverage and social audience signals are stored and displayed separately. Reply approval is a review decision only; the application does not publish replies.

The product direction is a PR and social-intelligence copilot: connect public evidence to audience needs, emerging signals, a recommended communication objective/action, human-reviewed content planning, and measured follow-up. Current partner signals and PR objectives are heuristic prompts for review; they are not verified leads or a substitute for authorized stakeholder and channel data.

## Requirements

- Python 3.12
- Node.js 20.19+ or 22.12+
- Ollama for local analysis and draft generation (optional for collection and dashboard)
- Optional GNews and YouTube API keys

## Configure

1. From `backend`, copy `.env.example` to `.env` and add credentials only for sources you want to use.
2. Install the Python dependencies: `py -3.12 -m pip install -r requirements.txt`.
3. For local AI, start Ollama and pull `phi3:3.8b` and `llama3.1:8b`. The health endpoint reports Ollama and each configured model separately. The app does not download models automatically.
4. The existing `social_pulse.db` is preserved. New databases and tables are initialized automatically. SQLite relative paths resolve from the backend working directory.

Bluesky keeps direct Tata STRIVE monitoring separate from a new thematic skills and employment stream. Brand records require an explicit `Tata STRIVE` or `#tatastrive` match; thematic records must match both a configured thematic search and an explicit skills/workforce phrase, and retain query provenance. GDELT and GNews still search and validate headlines with Tata STRIVE near the start; YouTube searches matching videos across channels but saves only substantive matching comments and replies (never standalone video records); SerpApi validates the visible result title/snippet. Google-discovered video links can also seed YouTube comment collection. Generic non-thematic posts and other Tata-company matches are discarded. The broader thematic Bluesky stream is a public-search sample, not a census or direct Tata STRIVE signal. Bluesky public search defaults to a rolling 30-day window (`BLUESKY_WINDOW_DAYS`). GNews requires `GNEWS_API_KEY`; YouTube requires `YOUTUBE_API_KEY`; Google search discovery through SerpApi requires `SERPAPI_API_KEY`. GDELT and Bluesky use public endpoints. LinkedIn collection is not automated directly.

Use the persistent **Fetch data** button in the app header to collect from all configured sources immediately. While the frontend stays open, it also runs a full collection every 30 minutes; the dashboard view refreshes from the database every 30 seconds. Automatic collection pauses while the browser tab is hidden and resumes once visible if a run is due. It stops when the app is closed.

SerpApi discovery uses configurable Google queries targeted at Reddit, X, Threads, Instagram, LinkedIn, YouTube and Bluesky. Alongside direct Tata STRIVE searches, it runs separate thematic queries for learner upskilling interest and aligned NGO, foundation, employer, and training-provider activity. Set `SERPAPI_THEMATIC_ENABLED=false` to disable these searches or override them with semicolon-separated `SERPAPI_THEMATIC_QUERIES`. Thematic searches run every 12 hours by default (`SERPAPI_THEMATIC_INTERVAL_HOURS`) to limit search usage; run **Fetch learner & partner leads** in Reports to trigger them manually. Thematic hits are tagged separately and stored only as result links, titles, and snippets; they are discovery leads, not full posts/comments or verified identities. Organization snippets with skills context can enter the Strategy Radar with lower evidence confidence and a requirement to open and verify the original page. Search previews are excluded from sentiment and reply generation. `SERPAPI_ENABLED`, `SERPAPI_MAX_RESULTS_PER_QUERY` (1–10), `SERPAPI_QUERIES`, and `GOOGLE_SEARCH_DELAY_SECONDS` control this collector. An optional Google Programmable Search connector is available at `/collect/google-custom-search`, controlled by `GOOGLE_SEARCH_ENABLED` and its API key/CX. It is disabled by default. Google states that Custom Search JSON API is closed to new customers and that existing users must transition by January 1, 2027, so use SerpApi unless your Google account is already eligible. Both search connectors discover public pages; neither fetches full platform comments. Direct public Bluesky posts matching learner upskilling, student, NGO-skilling, employability, and partner-intent queries are stored as thematic posts and can inform audience and opportunity analysis. YouTube collection searches matching videos across channels at a quota-conscious interval (one page per query by default, every six hours by default; configure with `YOUTUBE_MAX_SEARCH_PAGES` and `YOUTUBE_SEARCH_INTERVAL_HOURS`). Between searches it checks known videos and fresh Google-discovered candidates for comments. Search pages cost 100 YouTube API quota units each, so frequent full pagination can exhaust the daily quota. Google-discovered YouTube links can add videos whose metadata omits Tata STRIVE; each saved comment must still mention Tata STRIVE or `#tatastrive` and contain meaningful text. YouTube's API does not provide a global search over every comment, so this is a candidate-based public-data monitor, not a complete crawl of YouTube. Reddit's Data API has separate commercial-use requirements, and LinkedIn/Instagram comment access is permission-scoped; Social Pulse does not bypass platform access controls or crawl those platforms directly. Use an authorized source integration or user-authorized export when original comments are required.

## Run

Terminal 1:

```powershell
cd backend
py -3.12 -m uvicorn app.main:app --reload
```

Or activate any Python 3.12 virtual environment and run `python -m uvicorn app.main:app --reload`.

Terminal 2:

```powershell
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` in `frontend/.env.local` if the backend is not at `http://127.0.0.1:8000`. Add deployed frontend origins to backend `CORS_ORIGINS`.

## Workflow

1. Open Reports and collect all sources or an individual source. Credentials and remote availability determine which collectors can succeed; failures are shown per source.
2. Analyze pending records in bounded batches. Failed records remain eligible for retry. Each saved analysis includes the local model name and analysis timestamp.
3. Review stored evidence in Conversations and AI Insights. Filters operate on collected records. Sentiment summaries are based on analyzed social posts/comments; news articles are excluded.
4. Generate reply drafts. Drafts are limited to relevant social posts/comments that pass the confidence threshold. Edit, regenerate, approve, or reject them in Reply Center. Approval does not publish.
5. Use **Action Center** to triage detected questions, complaints, suggestions, and high-priority conversations. Assign an owner, set a follow-up date, record what happened, or close/dismiss the item. These candidates are decision support and require human review.
6. Create an evidence-linked content idea from a ranked trend. Track its owner, channel, planning/review/scheduled/published status, publication date, and URL. Enter available reach, impressions, likes, comments, shares, and follows manually, with outcome notes. Blank metrics mean unavailable; the Action Center summarizes measured published items and compares observed interaction rates by format when reach is recorded. These manual comparisons are observational, small samples may mislead, and they do not establish causation. Social Pulse does not publish content or retrieve private channel analytics.

The Action Center labels candidate actions such as responding, sharing a verified resource, creating an FAQ/content item, monitoring, escalating for verification, or investigating a possible workforce partnership signal. It raises explainable alerts for urgent wording, rising conversation volume, and due follow-ups; flags open opportunities without an update for 30 days; and suggests capability matches with matched terms and a review caveat. PR-objective, alert, and stakeholder labels are heuristic and remain review-required by default. Partner candidates still require independent verification and are not qualified leads.

The Action Center's **Strategy Radar** groups actionable public employer/collaboration signals by source account or a human-entered organization name. It shows evidence, recent activity, a weighted and explainable priority score, keyword capability overlap, an approach checklist, and a value hypothesis. Save verification, owner, and follow-up to the linked engagement opportunities. **Create collaboration content & growth plan** creates an evidence-linked recommendation tied to the candidate; its outcome tracker captures published reach, relevant stakeholder engagements, partnership/media enquiries, and learning notes. These are observed metrics entered by a human, not predicted growth or proof that a collaboration caused the outcome. Generic workforce commentary is not enough to trigger outreach; explicit employer need or collaboration intent is required unless the partner is human-verified.

Insights includes an audience lens based on post wording: learner, job seeker, employer/workforce, ecosystem partner, community supporter, skills-interest, or unclear signals, plus the needs and evidence behind each. It also summarizes likely friction points such as fees, eligibility, location, language, job search, and safety, with cautious wording-based emotion cues. Language is a conservative script/common-word hint, not translation or reliable language identification. Action Center opportunities and trend-based content ideas use these signals to tailor the suggested next step. These are estimates of conversation context, not verified author identities or demographic data.

Reports includes **Rebuild provenance & duplicate links** for legacy records. It canonicalizes text, marks simulated records, and links probable same-type duplicates across sources without deleting source records. In Conversations, review each flagged pair against its evidence and mark false positives as distinct; that decision persists through future rebuilds. Duplicate-linked rows are excluded from trend, audience, and opportunity aggregates.

Content ideas can use the local Ollama model to generate three alternative format/angle/copy options from the brief and linked evidence. The output stores evidence IDs where the model returns them and remains a human-reviewed draft. It cannot publish. Published items can record saves, relevant stakeholder engagements, partnership enquiries, and media enquiries alongside reach and standard platform counters. Action Center calculates quality-weighted interaction points per 100 recorded reach using explicit code weights; this is a product assumption, not a validated KPI. Its learning summary compares published items by PR objective, format, and audience. Groups with at least three measured items may inform later brief format suggestions, but results remain observational and do not train a model or establish causation.

The **Training Opportunities** sidebar page automatically finds direct Tata STRIVE comments/posts that ask about skills, courses, training or learning locations. It matches explicit skill keywords to a small list based on the [official Tata STRIVE course catalogue](https://tatastrive.com/what-we-do/courses/). It suggests one course only when there is a clear keyword match; otherwise the draft asks for the missing skill area or city and links to the catalogue. Availability, eligibility and centre locations must be checked on the official page. Opportunity reply drafts are saved in Reply Center for human review and are never published automatically.

## Verify

From `backend`, run `python -m pytest -q`. From `frontend`, run `npm run build` and `npm run lint`.

The application is a monitoring sample from accessible public sources, not a census of public opinion. Source quotas, deleted posts, disabled YouTube comments, model availability, and the limited search windows affect coverage. No data is fabricated when a source or model is unavailable.

