
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now():
    return datetime.now(timezone.utc)


class SocialRecord(SQLModel, table=True):
    __tablename__ = "social_records"

    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_id",
            name="uq_source_external_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    source: str = Field(index=True)
    record_type: str = Field(index=True)
    monitoring_scope: str = Field(default="brand", index=True)
    query_provenance: str | None = None
    external_id: str

    text: str
    normalized_text: str | None = Field(default=None, index=True)
    content_hash: str | None = Field(default=None, index=True)
    language_code: str = Field(default="und", index=True)
    language_method: str = "uncertain_heuristic"
    is_simulated: bool = Field(default=False, index=True)
    is_spam: bool = Field(default=False, index=True)
    provenance_note: str | None = None
    duplicate_of_record_id: int | None = Field(default=None, index=True)
    duplicate_match_score: float | None = None
    duplicate_match_type: str | None = None
    duplicate_review_state: str = Field(default="unreviewed", index=True)
    url: str | None = None
    author: str | None = None

    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)

    like_count: int | None = None
    reply_count: int | None = None
    view_count: int | None = None

    # Raw API response, serialized as JSON text when available.
    raw_json: str | None = None

class RecordAnalysis(SQLModel, table=True):
    __tablename__ = "record_analyses"

    id: int | None = Field(default=None, primary_key=True)

    record_id: int = Field(
        foreign_key="social_records.id",
        index=True,
        unique=True,
    )

    is_relevant: bool
    relevance_type: str
    topic: str
    intent: str
    sentiment: str
    perception_signal: str
    confidence: float
    priority: str
    rationale: str
    audience_segment: str = Field(default="unclear", index=True)
    audience_need: str = Field(default="unclear", index=True)
    audience_confidence: float = 0.35

    model_name: str
    analyzed_at: datetime = Field(default_factory=utc_now)

class ReplyDraft(SQLModel, table=True):
    __tablename__ = "reply_drafts"

    id: int | None = Field(default=None, primary_key=True)

    record_id: int = Field(
        foreign_key="social_records.id",
        index=True,
        unique=True,
    )

    reply_text: str
    status: str = Field(default="draft", index=True)
    model_name: str
    generated_at: datetime = Field(default_factory=utc_now)
    reviewed_at: datetime | None = None


class CollectionRun(SQLModel, table=True):
    __tablename__ = "collection_runs"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    status: str = Field(index=True)
    records_added: int = 0
    error_type: str | None = None
    completed_at: datetime = Field(default_factory=utc_now, index=True)


class EngagementOpportunity(SQLModel, table=True):
    __tablename__ = "engagement_opportunities"

    id: int | None = Field(default=None, primary_key=True)
    record_id: int = Field(foreign_key="social_records.id", index=True, unique=True)
    reason: str
    suggested_action: str
    priority_score: int = 0
    action_type: str = Field(default="monitor", index=True)
    pr_objective: str = Field(default="audience_education", index=True)
    stakeholder_type: str | None = None
    stakeholder_name: str | None = None
    stakeholder_geography: str | None = None
    stakeholder_fit_notes: str | None = None
    stakeholder_review: str = Field(default="not_assessed", index=True)
    partnership_signal: bool = False
    manually_added_to_radar: bool = Field(default=False, index=True)
    confidence: float = 0.45
    review_state: str = Field(default="review_required", index=True)
    status: str = Field(default="new", index=True)
    owner: str | None = None
    follow_up_at: datetime | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ContentRecommendation(SQLModel, table=True):
    __tablename__ = "content_recommendations"

    id: int | None = Field(default=None, primary_key=True)
    topic: str = Field(index=True)
    idea: str
    messaging: str
    call_to_action: str
    rationale: str
    evidence_record_ids: str = "[]"
    generated_content_options: str | None = None
    pr_objective: str = Field(default="audience_education", index=True)
    collaboration_partner: str | None = Field(default=None, index=True)
    target_audience: str = "learners and job seekers"
    recommended_format: str = "FAQ or carousel"
    hook: str = ""
    distribution_channel: str | None = None
    priority_score: int = 50
    confidence: float = 0.4
    review_state: str = Field(default="review_required", index=True)
    status: str = Field(default="idea", index=True)
    owner: str | None = None
    channel: str | None = None
    planned_at: datetime | None = None
    published_at: datetime | None = None
    content_url: str | None = None
    impressions: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    follows: int | None = None
    saves: int | None = None
    relevant_stakeholder_engagements: int | None = None
    partnership_enquiries: int | None = None
    media_enquiries: int | None = None
    outcome_notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OrganizationProfile(SQLModel, table=True):
    __tablename__ = "organization_profiles"
    id: int | None = Field(default=None, primary_key=True)
    canonical_name: str = Field(index=True, unique=True)
    normalized_name: str = Field(index=True, unique=True)
    aliases_json: str = "[]"
    website: str | None = None
    public_email: str | None = None
    contact_url: str | None = None
    verification_status: str = Field(default="unverified", index=True)
    verification_evidence: str | None = None
    verified_at: datetime | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RecommendationFeedback(SQLModel, table=True):
    __tablename__ = "recommendation_feedback"
    id: int | None = Field(default=None, primary_key=True)
    recommendation_id: int = Field(foreign_key="content_recommendations.id", index=True)
    rating: str = Field(index=True)
    reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class CampaignOutcome(SQLModel, table=True):
    __tablename__ = "campaign_outcomes"
    id: int | None = Field(default=None, primary_key=True)
    recommendation_id: int = Field(foreign_key="content_recommendations.id", index=True)
    campaign_name: str
    outcome_type: str = Field(index=True)
    value: int = 0
    measured_at: datetime = Field(default_factory=utc_now, index=True)
    attribution_method: str = "team_reported"
    evidence_url: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class QuickEmailDraft(SQLModel, table=True):
    __tablename__ = "quick_email_drafts"
    id: int | None = Field(default=None, primary_key=True)
    target_type: str = Field(index=True)  # partner or audience_template
    organization_id: int | None = Field(default=None, foreign_key="organization_profiles.id", index=True)
    audience_segment: str | None = None
    recipient_email: str | None = None
    subject: str
    body: str
    evidence_record_ids: str = "[]"
    status: str = Field(default="draft", index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
