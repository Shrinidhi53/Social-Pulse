"""FastAPI application for evidence-based social listening."""
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
import logging
import os
import re
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.analysis_engine import CLASSIFIER_MODEL
from app.content_engine import CONTENT_MODEL, generate_content_options
from app.database import engine, get_session, init_db
from app.data_quality import detect_language_hint, normalize_text, prepare_record
from app.ingestion.bluesky import collect_bluesky
from app.ingestion.gdelt import collect_gdelt
from app.ingestion.gnews import collect_gnews
from app.ingestion.youtube import collect_youtube
from app.ingestion.serpapi import collect_serpapi
from app.ingestion.google_custom_search import collect_google_custom_search
from app.models import (CampaignOutcome, CollectionRun, ContentRecommendation, EngagementOpportunity,
                        OrganizationProfile, QuickEmailDraft, RecommendationFeedback,
                        RecordAnalysis, ReplyDraft, SocialRecord)
from app.opportunities import COURSE_URL, classify_training_opportunity, match_capabilities
from app.reply_engine import REPLY_MODEL, generate_reply
from app.reply_engine import fallback_opportunity_reply, generate_opportunity_reply
from app.signals import analyze_signals, explicit_audience_mentions

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("social_pulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Social Pulse API", version="1.0.0", lifespan=lifespan)
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])


@app.get("/")
def root():
    return {"app": "Social Pulse", "status": "running"}


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(503, "Database unavailable") from exc
    ollama = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    try:
        response = httpx.get(f"{ollama}/api/tags", timeout=httpx.Timeout(3, connect=2))
        response.raise_for_status()
        models = response.json().get("models", [])
        names = [str(item.get("name", "")) for item in models if isinstance(item, dict)]
        connected = True
    except (httpx.HTTPError, ValueError, TypeError):
        names, connected = [], False
    normalized_names = {name.casefold() for name in names}
    classifier = CLASSIFIER_MODEL.casefold() in normalized_names
    reply = REPLY_MODEL.casefold() in normalized_names
    return {"api": "healthy", "database": "connected", "ollama": "connected" if connected else "unavailable",
            "required_models": {"classifier": classifier, "reply": reply}, "installed_models": names}


@app.get("/records")
def get_records(
    source: str | None = None, record_type: str | None = None,
    monitoring_scope: Literal["brand", "thematic"] | None = None,
    include_duplicates: bool = True,
    relevance_type: str | None = None, sentiment: str | None = None,
    intent: str | None = None, priority: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    date_from: datetime | None = None, date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    statement = select(SocialRecord)
    if not include_duplicates:
        statement = statement.where(SocialRecord.duplicate_of_record_id.is_(None))
    if monitoring_scope:
        statement = statement.where(SocialRecord.monitoring_scope == monitoring_scope)
    if source:
        if source.lower() == "news":
            statement = statement.where(SocialRecord.record_type == "news")
        else:
            statement = statement.where(SocialRecord.source == source.lower())
    if record_type:
        statement = statement.where(SocialRecord.record_type == record_type.lower())
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where((SocialRecord.text.ilike(term)) | (SocialRecord.author.ilike(term)) | (SocialRecord.source.ilike(term)))
    if date_from:
        statement = statement.where(SocialRecord.published_at >= _utc(date_from))
    if date_to:
        statement = statement.where(SocialRecord.published_at <= _utc(date_to))
    analysis_filters = [(relevance_type, RecordAnalysis.relevance_type), (sentiment, RecordAnalysis.sentiment), (intent, RecordAnalysis.intent), (priority, RecordAnalysis.priority)]
    if any(value for value, _ in analysis_filters):
        statement = statement.join(RecordAnalysis, RecordAnalysis.record_id == SocialRecord.id)
        for value, column in analysis_filters:
            if value:
                statement = statement.where(column == value.lower())
    total = session.exec(select(func.count()).select_from(statement.subquery())).one()
    records = session.exec(statement.order_by(SocialRecord.published_at.desc().nullslast(), SocialRecord.collected_at.desc()).offset(offset).limit(limit)).all()
    analyses = {item.record_id: item for item in session.exec(select(RecordAnalysis).where(RecordAnalysis.record_id.in_([r.id for r in records]))).all()} if records else {}
    enriched = []
    for record in records:
        item = _utc_dump(record, ("published_at", "collected_at"))
        signal = analyze_signals(record.source, record.record_type, record.text)
        item["keyword_counts"] = signal["keyword_counts"]
        item["sentiment_score"] = signal["sentiment_score"]
        item["importance_score"] = signal["importance_score"]
        item["signal_model"] = signal["signal_model"]
        item["audience_segment"] = signal["audience_segment"]
        item["audience_need"] = signal["audience_need"]
        item["audience_confidence"] = signal["audience_confidence"]
        item["pain_points"] = signal["pain_points"]
        item["conversation_emotion"] = signal["conversation_emotion"]
        item["analysis_available"] = record.id in analyses
        item["normalized_text"] = record.normalized_text or normalize_text(record.text)
        language_code, language_method = detect_language_hint(record.text)
        item["language_code"] = record.language_code if record.language_code != "und" else language_code
        item["language_method"] = record.language_method if record.language_code != "und" else language_method
        enriched.append(item)
    return {"count": total, "records": enriched, "limit": limit, "offset": offset}


@app.get("/data-quality")
def get_data_quality(session: Session = Depends(get_session)):
    """Expose source coverage, language hints, and duplicate links for review."""
    records = session.exec(select(SocialRecord).order_by(SocialRecord.collected_at.desc())).all()
    languages: dict[str, int] = defaultdict(int)
    sources: dict[str, dict[str, int]] = defaultdict(lambda: {"records": 0, "duplicates": 0, "simulated": 0})
    duplicate_examples = []
    for record in records:
        lang = record.language_code if record.language_code != "und" else detect_language_hint(record.text)[0]
        languages[lang] += 1
        source = sources[record.source]
        source["records"] += 1
        source["duplicates"] += int(record.duplicate_of_record_id is not None)
        source["simulated"] += int(record.is_simulated)
        if record.duplicate_of_record_id is not None and len(duplicate_examples) < 30:
            duplicate_examples.append({"record_id": record.id, "duplicate_of_record_id": record.duplicate_of_record_id,
                "source": record.source, "match_type": record.duplicate_match_type,
                "match_score": record.duplicate_match_score, "review_state": record.duplicate_review_state,
                "text": record.text[:280],
                "url": record.url, "provenance_note": record.provenance_note})
    duplicate_count = sum(record.duplicate_of_record_id is not None for record in records)
    return {"total_records": len(records), "unique_records": len(records) - duplicate_count,
            "duplicate_records": duplicate_count,
            "simulated_records": sum(record.is_simulated for record in records),
            "language_counts": dict(languages), "source_coverage": dict(sources),
            "duplicate_examples": duplicate_examples,
            "method": "NFKC/casefold canonical text; URLs removed for matching; same-record-type exact hashes and conservative text similarity (>=0.90). Suspected duplicates remain stored with source provenance and are excluded from trend, audience, and opportunity aggregates."}


@app.post("/data-quality/rebuild")
def rebuild_data_quality(session: Session = Depends(get_session)):
    """Backfill canonical text, language hints, and duplicate links for legacy rows."""
    records = session.exec(select(SocialRecord).order_by(SocialRecord.collected_at, SocialRecord.id)).all()
    known: list[SocialRecord] = []
    duplicates = 0
    for record in records:
        prior = [item for item in known[-3000:] if item.record_type == record.record_type]
        result = prepare_record(session, record, prior)
        duplicates += int(result["duplicate_of_record_id"] is not None)
        session.add(record)
        known.append(record)
    session.commit()
    return {"status": "complete", "records_processed": len(records),
            "duplicate_links": duplicates, "simulated_records": sum(item.is_simulated for item in records)}


class ProvenanceUpdate(BaseModel):
    is_simulated: bool
    provenance_note: str | None = Field(default=None, max_length=1000)


@app.patch("/records/{record_id}/provenance")
def update_record_provenance(record_id: int, request: ProvenanceUpdate, session: Session = Depends(get_session)):
    record = session.get(SocialRecord, record_id)
    if not record:
        raise HTTPException(404, "Record not found")
    record.is_simulated = request.is_simulated
    record.provenance_note = (request.provenance_note or "").strip() or ("Manually marked as simulated/demo data." if request.is_simulated else None)
    session.add(record)
    session.commit()
    return {"id": record.id, "is_simulated": record.is_simulated, "provenance_note": record.provenance_note}


class SpamUpdate(BaseModel):
    is_spam: bool


@app.patch("/records/{record_id}/spam")
def update_record_spam(record_id: int, request: SpamUpdate, session: Session = Depends(get_session)):
    record = session.get(SocialRecord, record_id)
    if not record:
        raise HTTPException(404, "Record not found")
    record.is_spam = request.is_spam
    session.add(record)
    session.commit()
    return {"id": record.id, "is_spam": record.is_spam}


class DuplicateReviewUpdate(BaseModel):
    duplicate_of_record_id: int | None = None


@app.patch("/records/{record_id}/duplicate-review")
def review_duplicate_link(record_id: int, request: DuplicateReviewUpdate, session: Session = Depends(get_session)):
    record = session.get(SocialRecord, record_id)
    if not record:
        raise HTTPException(404, "Record not found")
    if request.duplicate_of_record_id is None:
        record.duplicate_of_record_id = None
        record.duplicate_match_score = None
        record.duplicate_match_type = None
        record.duplicate_review_state = "confirmed_distinct"
    else:
        parent = session.get(SocialRecord, request.duplicate_of_record_id)
        if not parent or parent.id == record.id or parent.record_type != record.record_type:
            raise HTTPException(422, "Choose a different existing record with the same content type")
        root_id = parent.duplicate_of_record_id or parent.id
        if root_id == record.id:
            raise HTTPException(422, "This duplicate link would create a cycle")
        record.duplicate_of_record_id = root_id
        record.duplicate_match_score = 1.0
        record.duplicate_match_type = "human_confirmed"
        record.duplicate_review_state = "confirmed_duplicate"
    session.add(record)
    session.commit()
    return {"id": record.id, "duplicate_of_record_id": record.duplicate_of_record_id,
            "duplicate_review_state": record.duplicate_review_state,
            "duplicate_match_score": record.duplicate_match_score}


@app.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    records = session.exec(select(SocialRecord)).all()
    analyses = session.exec(select(RecordAnalysis)).all()
    drafts = session.exec(select(ReplyDraft)).all()
    collection_runs = session.exec(select(CollectionRun).order_by(CollectionRun.completed_at.desc()).limit(20)).all()
    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in records:
        by_source[record.source] = by_source.get(record.source, 0) + 1
        by_type[record.record_type] = by_type.get(record.record_type, 0) + 1
    analysis_by_id = {item.record_id: item for item in analyses}
    social = [r for r in records if r.record_type in {"social_post", "comment"}]
    analyzable = [r for r in records if r.record_type != "search_result"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent_social = [r for r in social if r.published_at and _utc(r.published_at) >= cutoff]
    social_analysis = [analysis_by_id[r.id] for r in recent_social if r.id in analysis_by_id]
    relevant_social = [a for a in social_analysis if a.is_relevant]
    sentiment_counts: dict[str, int] = {}
    for item in relevant_social:
        sentiment_counts[item.sentiment] = sentiment_counts.get(item.sentiment, 0) + 1
    duplicate_records = sum(record.duplicate_of_record_id is not None for record in records)
    language_counts: dict[str, int] = defaultdict(int)
    for record in records:
        language_counts[record.language_code if record.language_code != "und" else detect_language_hint(record.text)[0]] += 1
    return {"total_records": len(records), "unique_records": len(records) - duplicate_records,
            "duplicate_records": duplicate_records, "simulated_records": sum(record.is_simulated for record in records),
            "by_language": dict(language_counts), "by_source": by_source, "by_type": by_type,
            "by_monitoring_scope": {scope: sum(record.monitoring_scope == scope for record in records) for scope in ("brand", "thematic")},
            "total_social_mentions": len(social), "total_news_articles": by_type.get("news", 0),
            "recent_window_days": 30, "recent_social_mentions": len(recent_social),
            "direct_brand_mentions": sum(a.relevance_type == "direct_brand" for a in analyses),
            "industry_relevant_records": sum(a.relevance_type == "industry" for a in analyses),
            "sentiment_distribution": sentiment_counts, "positive_social_mentions": sentiment_counts.get("positive", 0),
            "analyzed_relevant_social": len(relevant_social),
            "high_priority_social_mentions": sum(a.priority in {"high", "critical"} for a in relevant_social),
            "pending_reply_drafts": sum(d.status == "draft" for d in drafts),
            "analyzed_records": len(analyses), "unanalyzed_records": max(0, len(analyzable) - len(analyses)),
            "latest_collections": [_utc_dump(run, ("completed_at",)) for run in collection_runs]}


@app.get("/trends")
def get_trends(date_from: date | None = None, date_to: date | None = None, session: Session = Depends(get_session)):
    """Rank relevant social posts/comments across all history or a selected activity-date window."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Start date must be on or before end date")
    records = session.exec(select(SocialRecord).where(
        SocialRecord.record_type.in_(["social_post", "comment"]),
        SocialRecord.duplicate_of_record_id.is_(None),
    )).all()
    records = [record for record in records if (
        (date_from is None and date_to is None) or
        ((activity := record.published_at or record.collected_at) is not None and
         (date_from is None or _utc(activity).date() >= date_from) and
         (date_to is None or _utc(activity).date() <= date_to))
    )]
    analyses = {item.record_id: item for item in session.exec(select(RecordAnalysis)).all()}
    now = datetime.combine(date_to, datetime.max.time(), timezone.utc) if date_to else datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=30)
    previous_cutoff = now - timedelta(days=60)
    by_topic: dict[tuple[str, str], list[dict]] = defaultdict(list)
    year_counts: dict[int, int] = defaultdict(int)
    excluded = 0
    dated_count = 0

    for record in records:
        if not record.text.strip():
            continue
        fallback = analyze_signals(record.source, record.record_type, record.text)
        analysis = analyses.get(record.id)
        relevant = analysis.is_relevant if analysis else fallback["is_relevant"]
        if not relevant:
            excluded += 1
            continue
        published = _utc(record.published_at) if record.published_at else None
        collected = _utc(record.collected_at) if record.collected_at else None
        activity_date = published or collected
        if published:
            dated_count += 1
        if activity_date:
            year_counts[activity_date.year] += 1
        topic = _semantic_topic_cluster((analysis.topic if analysis else fallback["topic"]) or "general mention", record.text)
        sentiment = analysis.sentiment if analysis else fallback["sentiment"]
        intent = analysis.intent if analysis else fallback["intent"]
        priority = analysis.priority if analysis else fallback["priority"]
        audience_segment = (analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else fallback["audience_segment"])
        audience_need = (analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else fallback["audience_need"])
        audience_confidence = (analysis.audience_confidence if analysis and analysis.audience_segment not in (None, "", "unclear") and analysis.audience_confidence is not None else fallback["audience_confidence"])
        urgent = bool(re.search(r"\b(urgent|unsafe|danger|scam|fraud|harassment|injury|safety|immediately|emergency)\b", record.text, re.I))
        scope = record.monitoring_scope if record.monitoring_scope in {"brand", "thematic"} else "brand"
        by_topic[(scope, topic)].append({
            "record": record, "date": activity_date, "sentiment": sentiment,
            "intent": intent, "priority": priority, "urgent": urgent,
            "audience_segment": audience_segment, "audience_need": audience_need,
            "audience_confidence": audience_confidence,
        })

    trends = []
    total_relevant = sum(len(items) for items in by_topic.values())
    for (scope, topic), items in by_topic.items():
        dated = [item for item in items if item["date"]]
        latest = max((item["date"] for item in dated), default=None)
        earliest = min((item["date"] for item in dated), default=None)
        current_30 = sum(item["date"] and item["date"] >= recent_cutoff for item in dated)
        previous_30 = sum(item["date"] and previous_cutoff <= item["date"] < recent_cutoff for item in dated)
        negative = sum(item["sentiment"] == "negative" for item in items)
        complaints = sum(item["intent"] == "complaint" for item in items)
        questions = sum(item["intent"] == "question" for item in items)
        high_priority = sum(item["priority"] in {"high", "critical"} for item in items)
        urgent = sum(item["urgent"] for item in items)
        audience_segments: dict[str, int] = defaultdict(int)
        audience_needs: dict[str, int] = defaultdict(int)
        for item in items:
            audience_segments[item["audience_segment"]] += 1
            audience_needs[item["audience_need"]] += 1
        lead_audience = max(audience_segments, key=audience_segments.get)
        lead_need = max(audience_needs, key=audience_needs.get)
        volume_score = round(min(20, 20 * math.sqrt(len(items) / max(total_relevant, 1))))
        recent_score = min(20, current_30 * 5)
        if not current_30 and latest:
            age_days = max(0, (now - latest).days)
            recent_score = 12 if age_days <= 90 else 7 if age_days <= 365 else 2
        risk_score = min(25, urgent * 15 + complaints * 9 + negative * 5 + high_priority * 4)
        demand_score = min(15, questions * 5 + sum(item["intent"] == "suggestion" for item in items) * 3)
        # Smoothed 30-day baseline avoids undefined/infinite growth when the prior window is empty.
        growth_pct = round(((current_30 + 1) / (previous_30 + 1) - 1) * 100, 1)
        metric_current = [item["record"] for item in dated if item["date"] >= recent_cutoff and any(
            value is not None for value in (item["record"].like_count, item["record"].reply_count))]
        metric_previous = [item["record"] for item in dated if previous_cutoff <= item["date"] < recent_cutoff and any(
            value is not None for value in (item["record"].like_count, item["record"].reply_count))]
        current_engagement_rate = (sum((record.like_count or 0) + 2 * (record.reply_count or 0) for record in metric_current) / len(metric_current)) if metric_current else None
        previous_engagement_rate = (sum((record.like_count or 0) + 2 * (record.reply_count or 0) for record in metric_previous) / len(metric_previous)) if metric_previous else None
        engagement_acceleration = round(((current_engagement_rate + 1) / (previous_engagement_rate + 1) - 1) * 100, 1) if current_engagement_rate is not None and previous_engagement_rate is not None else None
        engagement_growth_confirmed = len(metric_current) >= 3 and len(metric_previous) >= 3 and engagement_acceleration is not None and engagement_acceleration >= 30
        # Require both a minimum volume and an accelerating baseline before ranking a topic as rising.
        growth_confirmed = current_30 >= 3 and (current_30 > previous_30 or engagement_growth_confirmed)
        growth_score = min(20, 5 + max(0, current_30 - previous_30) * 3 + (5 if engagement_growth_confirmed else 0)) if growth_confirmed else 0
        velocity_per_week = round(current_30 / (30 / 7), 2)
        if current_30 >= 3 and previous_30 == 0:
            lifecycle = "emerging"
        elif current_30 > previous_30 and current_30 >= 3:
            lifecycle = "growing"
        elif current_30 and previous_30 and current_30 <= previous_30 * 0.6:
            lifecycle = "declining"
        elif current_30 >= 5 and previous_30 >= 5 and abs(current_30 - previous_30) <= max(2, previous_30 * 0.2):
            lifecycle = "peak"
        elif latest and (now - latest).days > 90:
            lifecycle = "dormant"
        elif earliest and earliest >= recent_cutoff:
            lifecycle = "emerging"
        else:
            lifecycle = "declining" if previous_30 else "emerging"
        engagement_by_source: dict[str, dict] = {}
        for entry in items:
            record = entry["record"]
            if not any(value is not None for value in (record.like_count, record.reply_count, record.view_count)):
                continue
            metrics = engagement_by_source.setdefault(record.source, {"records_with_metrics": 0, "likes": 0, "replies": 0, "views": 0, "records_with_likes": 0, "records_with_replies": 0, "records_with_views": 0})
            metrics["records_with_metrics"] += 1
            for field, counter in (("like_count", "likes"), ("reply_count", "replies"), ("view_count", "views")):
                value = getattr(record, field)
                if value is not None:
                    metrics[counter] += value
                    metrics[f"records_with_{counter}"] += 1
        engagement_coverage = {"records_with_metrics": sum(value["records_with_metrics"] for value in engagement_by_source.values()), "by_source": engagement_by_source}
        score = min(100, volume_score + recent_score + risk_score + demand_score + growth_score)
        attention = "Immediate attention" if urgent else "High priority" if score >= 65 and (negative or complaints or high_priority) else "Monitor" if score >= 35 or questions else "Low priority"
        reasons = []
        if current_30:
            reasons.append(f"{current_30} new in the last 30 days")
        if growth_confirmed:
            reasons.append("volume is rising" if current_30 > previous_30 else "measured engagement is accelerating")
        if urgent:
            reasons.append(f"{urgent} urgent or safety signal{'s' if urgent != 1 else ''}")
        if negative or complaints:
            reasons.append(f"{negative} negative, {complaints} complaint signal{'s' if complaints != 1 else ''}")
        if questions:
            reasons.append(f"{questions} direct question{'s' if questions != 1 else ''}")
        if not reasons:
            reasons.append(f"{len(items)} mentions across the full history")
        examples = []
        for item in sorted(items, key=lambda value: (
            value["urgent"], value["priority"] in {"high", "critical"},
            value["sentiment"] == "negative", value["intent"] == "complaint",
            value["intent"] == "question", value["date"] or datetime.min.replace(tzinfo=timezone.utc),
        ), reverse=True)[:2]:
            record = item["record"]
            examples.append({"record_id": record.id, "text": record.text, "source": record.source,
                             "monitoring_scope": record.monitoring_scope, "query_provenance": record.query_provenance, "url": record.url,
                             "published_at": _utc(record.published_at) if record.published_at else None,
                             "sentiment": item["sentiment"], "intent": item["intent"], "priority": item["priority"],
                             "confidence": analyses[record.id].confidence if record.id in analyses else analyze_signals(record.source, record.record_type, record.text)["confidence"],
                             "audience_segment": item["audience_segment"], "audience_need": item["audience_need"],
                             "audience_confidence": item["audience_confidence"]})
        trends.append({
            "topic": topic, "monitoring_scope": scope, "score": score, "attention": attention, "count": len(items),
            "audience_segments": dict(audience_segments), "audience_needs": dict(audience_needs),
            "leading_audience": lead_audience, "leading_need": lead_need,
            "recent_30_days": current_30, "previous_30_days": previous_30,
            "growth_percent": growth_pct, "velocity_per_week": velocity_per_week,
            "engagement_acceleration_percent": engagement_acceleration,
            "engagement_baseline": {"current_measured_records": len(metric_current), "previous_measured_records": len(metric_previous),
                                    "current_weighted_interactions_per_record": round(current_engagement_rate, 2) if current_engagement_rate is not None else None,
                                    "previous_weighted_interactions_per_record": round(previous_engagement_rate, 2) if previous_engagement_rate is not None else None,
                                    "formula": "likes + 2×replies per record; source metrics are incomplete and platform-specific"},
            "baseline_confidence": "high" if len(dated) >= 30 else "medium" if len(dated) >= 10 else "low",
            "lifecycle": lifecycle, "novelty": bool(earliest and earliest >= recent_cutoff),
            "engagement_coverage": engagement_coverage,
            "negative": negative, "complaints": complaints, "questions": questions,
            "urgent": urgent, "latest_at": latest.isoformat() if latest else None,
            "reasons": reasons, "examples": examples,
            "score_parts": {"volume": volume_score, "recency": recent_score, "risk": risk_score,
                            "demand": demand_score, "growth": growth_score},
        })
    level_order = {"Immediate attention": 0, "High priority": 1, "Monitor": 2, "Low priority": 3}
    trends.sort(key=lambda item: (level_order[item["attention"]], -item["score"], -item["count"]))
    return {
        "total_social_records": len(records), "analyzed_with_saved_label": sum(record.id in analyses for record in records),
        "relevant_records": total_relevant, "excluded_as_unrelated": excluded,
        "dated_records": dated_count, "undated_records": max(0, total_relevant - dated_count),
        "years": [{"year": year, "count": count} for year, count in sorted(year_counts.items())],
        "trends": trends,
        "ranking_method": "Volume 20, recency 20, risk 25, demand 15, growth 20. Growth percentage is omitted when the prior 30-day baseline is zero. Lifecycle and velocity are descriptive heuristics; engagement counters are reported by source and do not affect the rank because coverage and metric meaning vary. Immediate attention is reserved for explicit urgent or safety language. Social posts/comments only; search results and news are excluded.",
        "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None,
    }


@app.get("/alerts")
def get_alerts(session: Session = Depends(get_session)):
    """Create explainable alerts from existing trends, risks, and owned follow-ups."""
    now = datetime.now(timezone.utc)
    trend_report = get_trends(session=session)
    alerts: list[dict] = []
    for trend in trend_report["trends"]:
        example = trend["examples"][0] if trend["examples"] else {}
        base = {"topic": trend["topic"], "monitoring_scope": trend["monitoring_scope"],
                "record_id": example.get("record_id"), "source": example.get("source"),
                "url": example.get("url"), "sample_size": trend["count"]}
        if trend["urgent"]:
            alerts.append({**base, "id": f"risk:{trend['monitoring_scope']}:{trend['topic']}",
                "type": "urgent_signal", "severity": "critical",
                "title": f"{trend['urgent']} urgent or safety signal(s) in {trend['topic']}",
                "detail": "Review the linked source promptly; urgency is detected from wording and is not a verified incident."})
        if trend["score_parts"]["growth"] > 0:
            alerts.append({**base, "id": f"growth:{trend['monitoring_scope']}:{trend['topic']}",
                "type": "rising_topic", "severity": "high" if trend["score_parts"]["growth"] >= 15 else "medium",
                "title": f"Conversation activity is rising for {trend['topic']}",
                "detail": f"{trend['recent_30_days']} records in the last 30 days vs {trend['previous_30_days']} in the preceding 30 days. Rule-based signal; assess coverage before acting."})
    records = {item.id: item for item in session.exec(select(SocialRecord)).all()}
    drafts_by_record = {draft.record_id: draft for draft in session.exec(select(ReplyDraft)).all()}
    opportunities = session.exec(select(EngagementOpportunity).where(
        EngagementOpportunity.status.notin_(["closed", "dismissed"]),
        EngagementOpportunity.follow_up_at.is_not(None),
    )).all()
    for item in opportunities:
        due = _utc(item.follow_up_at)
        if due > now + timedelta(days=7):
            continue
        record = records.get(item.record_id)
        days = (now.date() - due.date()).days
        alerts.append({"id": f"followup:{item.id}", "type": "follow_up_due",
            "severity": "high" if days >= 1 else "medium", "title": "Follow-up is overdue" if due < now else "Follow-up due within seven days",
            "detail": f"{record.source if record else 'Conversation'} · {item.owner or 'Unassigned'} · due {due.isoformat()}",
            "record_id": item.record_id, "opportunity_id": item.id,
            "source": record.source if record else None, "url": record.url if record else None,
            "topic": None, "monitoring_scope": record.monitoring_scope if record else None,
            "sample_size": 1})
    for alert in alerts:
        record = records.get(alert.get("record_id"))
        if not record:
            alert.update({"published_at": None, "collected_at": None, "reply_draft_id": None, "training_opportunity": False})
            continue
        draft = drafts_by_record.get(record.id)
        alert.update({"published_at": _utc(record.published_at) if record.published_at else None,
                      "collected_at": _utc(record.collected_at) if record.collected_at else None,
                      "reply_draft_id": draft.id if draft else None,
                      "training_opportunity": bool(classify_training_opportunity(record.text))})
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(key=lambda item: (order.get(item["severity"], 4), item["type"], item["title"]))
    return {"count": len(alerts), "alerts": alerts,
            "method": "Alerts are transparent rules over collected records and tracked follow-ups. They do not establish a crisis, statistically significant trend, or source coverage completeness."}


@app.get("/audience/insights")
def get_audience_insights(
    monitoring_scope: Literal["brand", "thematic"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    """Summarize audience needs expressed in relevant public conversation text."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Start date must be on or before end date")
    statement = select(SocialRecord).where(SocialRecord.record_type.in_(["social_post", "comment"]), SocialRecord.duplicate_of_record_id.is_(None))
    if monitoring_scope:
        statement = statement.where(SocialRecord.monitoring_scope == monitoring_scope)
    records = session.exec(statement.order_by(SocialRecord.published_at.desc().nullslast())).all()
    analyses = {item.record_id: item for item in session.exec(select(RecordAnalysis)).all()}
    groups: dict[str, dict] = {}
    need_counts: dict[str, int] = defaultdict(int)
    pain_counts: dict[str, int] = defaultdict(int)
    emotion_counts: dict[str, int] = defaultdict(int)
    age_groups: dict[str, dict] = {}
    locations: dict[str, dict] = {}
    relevant_count = 0
    for record in records:
        activity = record.published_at or record.collected_at
        if date_from or date_to:
            if not activity or (date_from and _utc(activity).date() < date_from) or (date_to and _utc(activity).date() > date_to):
                continue
        signals = analyze_signals(record.source, record.record_type, record.text)
        analysis = analyses.get(record.id)
        if analysis and not analysis.is_relevant:
            continue
        if not analysis and not signals["is_relevant"]:
            continue
        relevant_count += 1
        explicit_mentions = explicit_audience_mentions(record.text)
        for age_group in explicit_mentions["age_groups"]:
            item = age_groups.setdefault(age_group, {"count": 0, "evidence": []})
            item["count"] += 1
            if len(item["evidence"]) < 2:
                item["evidence"].append({"record_id": record.id, "text": record.text, "source": record.source, "url": record.url,
                    "published_at": _utc(record.published_at) if record.published_at else None,
                    "collected_at": _utc(record.collected_at) if record.collected_at else None})
        for place in explicit_mentions["locations"]:
            item = locations.setdefault(place, {"count": 0, "evidence": []})
            item["count"] += 1
            if len(item["evidence"]) < 2:
                item["evidence"].append({"record_id": record.id, "text": record.text, "source": record.source, "url": record.url,
                    "published_at": _utc(record.published_at) if record.published_at else None,
                    "collected_at": _utc(record.collected_at) if record.collected_at else None})
        segment = analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else signals["audience_segment"]
        need = analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else signals["audience_need"]
        confidence = analysis.audience_confidence if analysis and analysis.audience_segment not in (None, "", "unclear") and analysis.audience_confidence is not None else signals["audience_confidence"]
        group = groups.setdefault(segment, {"audience_segment": segment, "count": 0, "confidence_sum": 0.0,
            "needs": defaultdict(int), "pain_points": defaultdict(int), "emotions": defaultdict(int), "examples": []})
        group["count"] += 1
        group["confidence_sum"] += confidence
        group["needs"][need] += 1
        need_counts[need] += 1
        for point in signals["pain_points"]:
            pain_counts[point] += 1
        emotion_counts[str(signals["conversation_emotion"])] += 1
        for point in signals["pain_points"]:
            group["pain_points"][point] += 1
        group["emotions"][str(signals["conversation_emotion"])] += 1
        if len(group["examples"]) < 2:
            group["examples"].append({"record_id": record.id, "text": record.text, "source": record.source, "url": record.url,
                                      "published_at": _utc(record.published_at) if record.published_at else None,
                                      "collected_at": _utc(record.collected_at) if record.collected_at else None,
                                      "audience_need": need, "pain_points": signals["pain_points"],
                                      "conversation_emotion": signals["conversation_emotion"], "confidence": confidence})

    actions = {
        "learner": "Offer a verified course or skills resource. If access details are missing, ask what skill and location they need.",
        "job_seeker": "Offer verified job-search or career guidance and ask which role or location would make the next step useful; do not promise placement.",
        "employer_workforce": "Verify the organization and workforce need, then assess skill, geography, and training fit before proposing a partnership.",
        "ecosystem_partner": "Confirm the organization, shared objective, geography, and evidence of fit before suggesting collaboration.",
        "community_supporter": "Give the supporter a clear, verified resource they can pass on, and avoid assuming they speak for a learner.",
        "skills_audience_interest": "Use this as a signal for practical skills or careers content. Verify details and do not assume the author is requesting personal help.",
        "unclear": "Ask one clarifying question about the audience's skill, location, or goal before choosing a resource or response.",
    }
    segments = []
    for segment, group in sorted(groups.items(), key=lambda pair: (-pair[1]["count"], pair[0])):
        segments.append({"audience_segment": segment, "count": group["count"],
                         "share_percent": round(group["count"] / max(relevant_count, 1) * 100, 1),
                         "confidence": round(group["confidence_sum"] / group["count"], 2),
                         "needs": dict(sorted(group["needs"].items(), key=lambda pair: -pair[1])),
                         "pain_points": dict(sorted(group["pain_points"].items(), key=lambda pair: -pair[1])),
                         "emotions": dict(sorted(group["emotions"].items(), key=lambda pair: -pair[1])),
                         "recommended_action": actions.get(segment, actions["unclear"]), "examples": group["examples"]})
    age_labels = {"under_18_explicit": "Under 18 explicitly mentioned", "18_24_explicit": "Ages 18–24 explicitly mentioned",
                  "25_34_explicit": "Ages 25–34 explicitly mentioned", "35_plus_explicit": "Ages 35+ explicitly mentioned",
                  "youth_age_unspecified": "Youth mentioned; age range unspecified"}
    age_mentions = [{"group": age_labels.get(group, group), "count": item["count"],
                     "share_percent": round(item["count"] / max(relevant_count, 1) * 100, 1), "evidence": item["evidence"]}
                    for group, item in sorted(age_groups.items(), key=lambda pair: (-pair[1]["count"], pair[0]))]
    location_mentions = [{"place": place, "count": item["count"],
                          "share_percent": round(item["count"] / max(relevant_count, 1) * 100, 1), "evidence": item["evidence"]}
                         for place, item in sorted(locations.items(), key=lambda pair: (-pair[1]["count"], pair[0]))]
    audience_actions = []
    if location_mentions:
        audience_actions.append({"title": "Respond to location demand", "action": "Verify current centre availability for the places mentioned, then share a confirmed local option or ask which city the person needs.",
                                 "basis": f"{sum(item['count'] for item in location_mentions)} relevant conversation(s) explicitly named a recognized place.", "evidence_record_ids": [entry["record_id"] for item in location_mentions for entry in item["evidence"]]})
    if age_mentions:
        audience_actions.append({"title": "Check age-specific eligibility before advising", "action": "Use age references only to guide a human eligibility check against an official course source; do not treat them as the author's age or promise eligibility.",
                                 "basis": f"{sum(item['count'] for item in age_mentions)} relevant conversation(s) explicitly referenced an age group.", "evidence_record_ids": [entry["record_id"] for item in age_mentions for entry in item["evidence"]]})
    if segments:
        lead = segments[0]
        lead_need = next(iter(lead["needs"]), "general_guidance")
        audience_actions.append({"title": f"Prioritize {lead['audience_segment'].replace('_', ' ')} needs",
                                 "action": f"Build the next response or content piece around {lead_need.replace('_', ' ')}; use the linked examples to check the wording and verify programme details.",
                                 "basis": f"This is the largest conversation-level segment ({lead['count']} of {relevant_count} relevant records), not a demographic estimate.",
                                 "evidence_record_ids": [entry["record_id"] for entry in lead["examples"]]})
    return {"sample_size": relevant_count, "monitoring_scope": monitoring_scope or "all",
            "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None,
            "segments": segments,
            "top_needs": [{"need": need, "count": count} for need, count in sorted(need_counts.items(), key=lambda pair: -pair[1])],
            "top_pain_points": [{"pain_point": point, "count": count} for point, count in sorted(pain_counts.items(), key=lambda pair: -pair[1])],
            "conversation_emotions": dict(emotion_counts),
            "age_group_mentions": age_mentions, "location_mentions": location_mentions,
            "audience_actions": audience_actions,
            "method": "Rule-based interpretation of public post/comment wording. Audience segments, topics, pain points and emotions are estimates about the conversation, not verified author identity, demographic data, or clinical emotion labels. Age groups and places appear only when explicitly mentioned in text; place mentions do not establish where an author lives. Confidence and sample size are shown; examples link back to original evidence."}


@app.get("/analyses")
def get_analyses(session: Session = Depends(get_session)):
    analyses = session.exec(select(RecordAnalysis).order_by(RecordAnalysis.analyzed_at.desc())).all()
    return {"count": len(analyses), "analyses": [_utc_dump(item, ("analyzed_at",)) for item in analyses]}


@app.get("/opportunities")
def get_training_opportunities(session: Session = Depends(get_session)):
    # Surface learner demand from every collected public source. Only direct Tata STRIVE
    # requests may use the Reply Center's reply-generation path; broader signals are for
    # audience understanding and evidence-linked content planning.
    records = session.exec(select(SocialRecord).order_by(
        SocialRecord.published_at.desc().nullslast(), SocialRecord.collected_at.desc()
    )).all()
    drafts = {draft.record_id: draft for draft in session.exec(select(ReplyDraft)).all()}
    analyses = {item.record_id: item for item in session.exec(select(RecordAnalysis)).all()}
    opportunities = []
    for record in records:
        if record.duplicate_of_record_id is not None and record.duplicate_review_state != "confirmed_distinct":
            continue
        signals = classify_training_opportunity(record.text, require_brand=False)
        if not signals:
            continue
        draft = drafts.get(record.id)
        analysis = analyses.get(record.id)
        opportunities.append({
            "record_id": record.id, "source": record.source, "record_type": record.record_type,
            "monitoring_scope": record.monitoring_scope,
            "text": record.text, "url": record.url, "author": record.author,
            "published_at": _utc(record.published_at) if record.published_at else None,
            "collected_at": _utc(record.collected_at) if record.collected_at else None,
            "audience_segment": analysis.audience_segment if analysis else None,
            "audience_need": analysis.audience_need if analysis else None,
            "confidence": analysis.audience_confidence if analysis else 0.35,
            "topic": analysis.topic if analysis else None,
            "reply_eligible": bool(signals["is_direct_brand_request"] and record.record_type in {"comment", "social_post"}),
            **signals,
            "draft": ({"draft_id": draft.id, "reply_text": draft.reply_text, "status": draft.status}
                      if draft else None),
        })
    return {"count": len(opportunities), "opportunities": opportunities,
            "course_catalog_url": COURSE_URL}


@app.post("/opportunities/{record_id}/draft")
def draft_opportunity_reply(record_id: int, session: Session = Depends(get_session)):
    record = session.get(SocialRecord, record_id)
    if not record or record.record_type not in {"comment", "social_post"}:
        raise HTTPException(404, "Social comment or post not found")
    signals = classify_training_opportunity(record.text)
    if not signals:
        raise HTTPException(422, "This post is not a direct Tata STRIVE training or course enquiry")
    existing = session.exec(select(ReplyDraft).where(ReplyDraft.record_id == record_id)).first()
    if existing and existing.status != "draft":
        raise HTTPException(409, "A reply draft for this record has already been reviewed")
    try:
        generation_method = REPLY_MODEL
        try:
            reply = generate_opportunity_reply(record.text, signals["request_type"], signals["skills"], signals["location"])
        except RuntimeError as exc:
            logger.warning("Reply model unavailable for opportunity %s (%s); using a rule-based draft", record_id, type(exc).__name__)
            reply = fallback_opportunity_reply(record.text, signals["skills"], signals["location"])
            generation_method = "rule-based fallback"
        course = signals["suggested_course"]
        if course:
            reply += (f" A course that may match your interest is {course['title']} ({course['category']}). "
                      f"Please check current eligibility and centre availability here: {course['url']}")
        else:
            reply += f" Current Tata STRIVE course listings and centre information: {COURSE_URL}"
        draft = existing or ReplyDraft(record_id=record_id, reply_text=reply, status="draft", model_name=generation_method)
        draft.reply_text = reply
        draft.model_name = generation_method
        draft.generated_at = datetime.now(timezone.utc)
        session.add(draft)
        session.commit()
        session.refresh(draft)
    except Exception as exc:
        session.rollback()
        logger.exception("Opportunity draft generation failed for record %s", record_id)
        raise HTTPException(500, "Could not save the reply draft. Please retry.") from exc
    return {"draft_id": draft.id, "record_id": record_id, "reply_text": draft.reply_text,
            "status": draft.status, "suggested_course": signals["suggested_course"]}


def _collect_one(source: str, collector, session: Session):
    try:
        result = collector(session)
        status = result.get("status") if isinstance(result, dict) else None
        if status == "disabled":
            return {"status": "disabled", "result": result}
        if status == "partial":
            return {"status": "partial", "result": result}
        if isinstance(result, dict):
            inserted = result.get("inserted", result.get("saved"))
            if inserted is None and "comments_saved" in result:
                inserted = result.get("comments_saved", 0)
            if inserted is None and "videos_saved" in result:
                inserted = result.get("videos_saved", 0) + result.get("comments_saved", 0)
            if inserted == 0:
                return {"status": "no_new_records", "result": result}
        return {"status": "success", "result": result}
    except Exception as exc:
        session.rollback()
        safe_error = _public_error(exc)
        logger.warning("%s collection failed: %s", source, safe_error)
        return {"status": "failed", "error": safe_error, "error_type": type(exc).__name__}


def _save_collection_run(session: Session, source: str, result: dict):
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    added = payload.get("inserted", payload.get("saved", 0))
    if "comments_saved" in payload:
        added = payload.get("comments_saved", 0)
    if "videos_saved" in payload:
        added = payload.get("videos_saved", 0) + payload.get("comments_saved", 0)
    # Keep the sanitized upstream reason where the Reports UI can show it;
    # the exception class alone (for example, HTTPStatusError) is not actionable.
    session.add(CollectionRun(source=source, status=result.get("status", "failed"), records_added=added or 0, error_type=result.get("error") or result.get("error_type")))
    if source == "google_search" and payload.get("thematic_queries_attempted", 0):
        session.add(CollectionRun(source="google_search_thematic", status=result.get("status", "failed"),
                                  records_added=payload.get("thematic_inserted", 0),
                                  error_type="Some thematic searches failed" if payload.get("errors") else None))


def _single_collect(source: str, collector, session: Session):
    result = _collect_one(source, collector, session)
    _save_collection_run(session, source, result)
    session.commit()
    if result["status"] == "failed":
        raise HTTPException(502, {"source": source, "error": result["error"]})
    return {**result["result"], "status": result["status"]}


@app.post("/collect/gnews")
def run_gnews_collection(session: Session = Depends(get_session)):
    return _single_collect("gnews", collect_gnews, session)


@app.post("/collect/gdelt")
def run_gdelt_collection(session: Session = Depends(get_session)):
    return _single_collect("gdelt", collect_gdelt, session)


@app.post("/collect/youtube")
def run_youtube_collection(session: Session = Depends(get_session)):
    return _single_collect("youtube", collect_youtube, session)


@app.post("/collect/bluesky")
def run_bluesky_collection(session: Session = Depends(get_session)):
    return _single_collect("bluesky", collect_bluesky, session)


@app.post("/collect/google-search")
def run_google_search_collection(session: Session = Depends(get_session)):
    return _single_collect("google_search", collect_serpapi, session)


@app.post("/collect/google-search/thematic")
def run_thematic_google_search_collection(session: Session = Depends(get_session)):
    return _single_collect("google_search_thematic", lambda current: collect_serpapi(current, thematic_only=True, force_thematic=True), session)


@app.post("/collect/google-custom-search")
def run_google_custom_search_collection(session: Session = Depends(get_session)):
    return _single_collect("google_custom_search", collect_google_custom_search, session)


@app.post("/collect/all")
def collect_all_sources(session: Session = Depends(get_session)):
    # Google results add public video URLs to YouTube's cross-channel discovery set.
    collectors = {"gnews": collect_gnews, "gdelt": collect_gdelt, "bluesky": collect_bluesky,
                  "google_search": collect_serpapi, "google_custom_search": collect_google_custom_search,
                  "youtube": collect_youtube}
    results = {source: _collect_one(source, collector, session) for source, collector in collectors.items()}
    for source, result in results.items():
        _save_collection_run(session, source, result)
    session.commit()
    failed = [source for source, item in results.items() if item["status"] == "failed"]
    partial = [source for source, item in results.items() if item["status"] == "partial"]
    all_empty = all(item["status"] == "no_new_records" for item in results.values())
    status = "failed" if len(failed) == len(collectors) else "no_new_records" if all_empty else "partial" if failed or partial else "success"
    return {"status": status, "sources": results, "failed_sources": failed, "partial_sources": partial}


@app.post("/analyze/pending")
def analyze_pending_records(limit: int = Query(default=100, ge=1, le=200), session: Session = Depends(get_session)):
    records = session.exec(select(SocialRecord).order_by(SocialRecord.collected_at.desc())).all()
    analyzed_ids = set(session.exec(select(RecordAnalysis.record_id)).all())
    pending = [record for record in records if record.id not in analyzed_ids][:limit]
    saved, errors = 0, []
    for record in pending:
        try:
            fields = analyze_signals(record.source, record.record_type, record.text)
            model_name = fields.pop("signal_model")
            fields.pop("sentiment_score", None)
            fields.pop("importance_score", None)
            fields.pop("keyword_counts", None)
            session.add(RecordAnalysis(record_id=record.id, model_name=model_name, **fields))
            session.commit()
            saved += 1
        except Exception as exc:
            session.rollback()
            logger.exception("Analysis failed for record %s", record.id)
            errors.append({"record_id": record.id, "error": type(exc).__name__})
    return {"pending_selected": len(pending), "analyses_saved": saved, "errors": errors}


@app.post("/records/{record_id}/reply-draft")
def create_record_reply_draft(record_id: int, session: Session = Depends(get_session)):
    """Create one review-only draft from an eligible public conversation."""
    record = session.get(SocialRecord, record_id)
    if not record or record.record_type not in {"comment", "social_post"}:
        raise HTTPException(422, "Replies can only be drafted for original social comments or posts")
    if record.is_spam:
        raise HTTPException(422, "Spam-marked content cannot receive a reply draft")
    existing = session.exec(select(ReplyDraft).where(ReplyDraft.record_id == record_id)).first()
    if existing:
        if existing.status != "draft":
            raise HTTPException(409, "This conversation already has a reviewed reply")
        return {"draft_id": existing.id, "record_id": record_id, "reply_text": existing.reply_text, "status": existing.status}
    analysis = session.exec(select(RecordAnalysis).where(RecordAnalysis.record_id == record_id)).first()
    signals = analyze_signals(record.source, record.record_type, record.text)
    relevance = analysis.relevance_type if analysis else signals["relevance_type"]
    confidence = analysis.confidence if analysis else signals["confidence"]
    if relevance not in {"direct_brand", "industry"} or confidence < 0.6:
        raise HTTPException(422, "This conversation does not meet reply relevance and confidence checks")
    audience_segment = analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else signals["audience_segment"]
    audience_need = analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else signals["audience_need"]
    try:
        reply_text = generate_reply(record.source, record.record_type, record.text,
            analysis.topic if analysis else signals["topic"],
            analysis.intent if analysis else signals["intent"],
            analysis.sentiment if analysis else signals["sentiment"],
            analysis.perception_signal if analysis else signals["perception_signal"],
            audience_segment, audience_need)
    except Exception as exc:
        logger.exception("Reply draft generation failed for record %s", record_id)
        raise HTTPException(503, "Could not create a reply draft. Check the local reply model and try again.") from exc
    draft = ReplyDraft(record_id=record_id, reply_text=reply_text, status="draft", model_name=REPLY_MODEL)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return {"draft_id": draft.id, "record_id": record_id, "reply_text": reply_text, "status": draft.status}


@app.post("/replies/generate-pending")
def generate_pending_replies(limit: int = Query(default=50, ge=1, le=100), session: Session = Depends(get_session)):
    analyses = session.exec(select(RecordAnalysis).order_by(RecordAnalysis.analyzed_at.desc())).all()
    drafted_ids = set(session.exec(select(ReplyDraft.record_id)).all())
    drafts, errors = [], []
    for analysis in analyses:
        if len(drafts) >= limit:
            break
        if not analysis.is_relevant or analysis.relevance_type not in {"direct_brand", "industry"} or analysis.confidence < 0.6:
            continue
        record = session.get(SocialRecord, analysis.record_id)
        if not record or record.id in drafted_ids or record.record_type not in {"comment", "social_post"}:
            continue
        try:
            audience = analyze_signals(record.source, record.record_type, record.text)
            audience_segment = analysis.audience_segment if analysis.audience_segment not in (None, "", "unclear") else audience["audience_segment"]
            audience_need = analysis.audience_need if analysis.audience_need not in (None, "", "unclear") else audience["audience_need"]
            reply_text = generate_reply(record.source, record.record_type, record.text, analysis.topic, analysis.intent, analysis.sentiment, analysis.perception_signal, audience_segment, audience_need)
            draft = ReplyDraft(record_id=record.id, reply_text=reply_text, status="draft", model_name=REPLY_MODEL)
            session.add(draft)
            session.commit()
            session.refresh(draft)
            drafted_ids.add(record.id)
            drafts.append({"draft_id": draft.id, "record_id": record.id, "source": record.source, "original_text": record.text, "original_url": record.url, "reply_text": reply_text, "status": draft.status})
        except Exception as exc:
            session.rollback()
            logger.exception("Draft generation failed for record %s", record.id)
            errors.append({"record_id": record.id, "error": type(exc).__name__})
    return {"drafts_created": len(drafts), "drafts": drafts, "errors": errors}


class ReviewDraftRequest(BaseModel):
    status: Literal["approved", "rejected"]
    edited_reply: str | None = Field(default=None, max_length=5000)


class EngagementUpdate(BaseModel):
    status: Literal["new", "assigned", "responded", "follow_up", "closed", "dismissed"] | None = None
    owner: str | None = Field(default=None, max_length=120)
    follow_up_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    suggested_action: str | None = Field(default=None, max_length=1000)
    review_state: Literal["review_required", "validated", "insufficient_evidence"] | None = None
    stakeholder_name: str | None = Field(default=None, max_length=200)
    stakeholder_geography: str | None = Field(default=None, max_length=200)
    stakeholder_fit_notes: str | None = Field(default=None, max_length=1000)
    stakeholder_review: Literal["not_assessed", "verify", "verified", "not_a_fit"] | None = None


class StrategyPartnerDismiss(BaseModel):
    opportunity_ids: list[int] = Field(min_length=1, max_length=500)


class ContentRecommendationCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    idea: str = Field(min_length=1, max_length=2000)
    messaging: str = Field(min_length=1, max_length=2000)
    call_to_action: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_record_ids: list[int] = Field(min_length=1, max_length=50)
    pr_objective: str = Field(default="audience_education", max_length=100)
    collaboration_partner: str | None = Field(default=None, max_length=200)
    target_audience: str = Field(default="learners and job seekers", max_length=200)
    recommended_format: str = Field(default="FAQ or carousel", max_length=120)
    hook: str = Field(default="", max_length=500)
    distribution_channel: str | None = Field(default=None, max_length=100)
    priority_score: int = Field(default=50, ge=0, le=100)
    confidence: float = Field(default=0.4, ge=0, le=1)


class ContentRecommendationUpdate(BaseModel):
    topic: str | None = Field(default=None, max_length=160)
    idea: str | None = Field(default=None, max_length=2000)
    messaging: str | None = Field(default=None, max_length=2000)
    call_to_action: str | None = Field(default=None, max_length=1000)
    rationale: str | None = Field(default=None, max_length=2000)
    pr_objective: str | None = Field(default=None, max_length=100)
    collaboration_partner: str | None = Field(default=None, max_length=200)
    target_audience: str | None = Field(default=None, max_length=200)
    recommended_format: str | None = Field(default=None, max_length=120)
    hook: str | None = Field(default=None, max_length=500)
    distribution_channel: str | None = Field(default=None, max_length=100)
    priority_score: int | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_state: Literal["review_required", "validated", "insufficient_evidence"] | None = None
    status: Literal["idea", "drafting", "review", "scheduled", "published", "paused"] | None = None
    owner: str | None = Field(default=None, max_length=120)
    channel: str | None = Field(default=None, max_length=80)
    planned_at: datetime | None = None
    published_at: datetime | None = None
    content_url: str | None = Field(default=None, max_length=2000)
    impressions: int | None = Field(default=None, ge=0)
    reach: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    follows: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    relevant_stakeholder_engagements: int | None = Field(default=None, ge=0)
    partnership_enquiries: int | None = Field(default=None, ge=0)
    media_enquiries: int | None = Field(default=None, ge=0)
    outcome_notes: str | None = Field(default=None, max_length=4000)


class OrganizationProfileSave(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    website: str | None = Field(default=None, max_length=500)
    public_email: str | None = Field(default=None, max_length=254)
    contact_url: str | None = Field(default=None, max_length=500)
    verification_status: Literal["unverified", "review", "verified"] = "unverified"
    verification_evidence: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class RecommendationFeedbackCreate(BaseModel):
    rating: Literal["useful", "not_useful", "used"]
    reason: str | None = Field(default=None, max_length=2000)


class CampaignOutcomeCreate(BaseModel):
    campaign_name: str = Field(min_length=2, max_length=200)
    outcome_type: Literal["learner_enquiry", "application", "placement", "partnership", "media", "stakeholder_engagement", "reach", "other"]
    value: int = Field(default=1, ge=0, le=100000000)
    measured_at: datetime | None = None
    attribution_method: Literal["team_reported", "tracked_link", "platform_report", "self_reported", "uncertain"] = "team_reported"
    evidence_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class QuickEmailDraftCreate(BaseModel):
    target_type: Literal["partner", "audience_template"]
    organization_id: int | None = None
    audience_segment: str | None = Field(default=None, max_length=100)
    recipient_email: str | None = Field(default=None, max_length=254)
    subject: str = Field(min_length=1, max_length=250)
    body: str = Field(min_length=1, max_length=10000)
    evidence_record_ids: list[int] = Field(default_factory=list, max_length=50)


PR_OBJECTIVES = {
    "visibility": {"label": "Visibility", "why": "Increase recognition among relevant learners, employers, and ecosystem stakeholders.", "plays": ["timely evidence-led commentary", "partner amplification", "learner-safe story with consent"], "measures": ["relevant reach", "share of stakeholder interactions", "branded enquiries"]},
    "thought_leadership": {"label": "Thought leadership", "why": "Contribute a useful, differentiated perspective to skills and employability discussions.", "plays": ["expert point of view", "data-backed explainer", "executive byline or interview"], "measures": ["qualified media mentions", "expert invitations", "saves and substantive discussion"]},
    "partnerships": {"label": "Partnerships", "why": "Move a verified mutual need toward a concrete, measurable collaboration.", "plays": ["discovery meeting", "small pilot proposal", "joint outcome case study after consent"], "measures": ["qualified meetings", "pilots started", "learner outcomes"]},
    "csr": {"label": "CSR and social impact", "why": "Connect an evidenced community or skills need to a suitable social-impact programme.", "plays": ["geography and need brief", "funding fit note", "impact measurement plan"], "measures": ["qualified CSR conversations", "funded or in-kind commitments", "beneficiaries served"]},
    "government_relations": {"label": "Government relations", "why": "Track policy and public-programme signals and support informed, appropriate engagement.", "plays": ["verify primary policy source", "prepare neutral briefing", "route through authorized liaison"], "measures": ["verified briefings", "consultation participation", "documented ecosystem outcomes"]},
    "media_attention": {"label": "Media attention", "why": "Offer accurate, timely evidence and subject expertise to relevant journalists.", "plays": ["fact sheet", "expert response", "consent-based learner or employer case"], "measures": ["qualified coverage", "message accuracy", "referral enquiries"]},
    "learner_reach": {"label": "Learner reach", "why": "Help learners discover accurate courses, eligibility, locations, and next steps.", "plays": ["FAQ", "local-language explainer reviewed by a person", "official course link and clear CTA"], "measures": ["course-page visits", "eligible enquiries", "applications"]},
    "ecosystem_influence": {"label": "Ecosystem influence", "why": "Build useful connections across employers, training providers, government, and community groups.", "plays": ["stakeholder roundtable", "shared skills brief", "cross-sector learning note"], "measures": ["relevant stakeholder participation", "repeat collaboration", "documented referrals"]},
    "reputation": {"label": "Reputation and issue response", "why": "Respond accurately and empathetically to verified concerns while protecting people and privacy.", "plays": ["fact-check and route sensitive issue", "approved response", "close the loop with the affected person"], "measures": ["response time", "verified resolution", "recurring issue reduction"]},
}


def _normalized_org_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _pr_objective_key(value: str) -> str:
    text = value.casefold()
    if any(term in text for term in ("reputation", "issue management", "safety")): return "reputation"
    if any(term in text for term in ("partnership", "partner discovery")): return "partnerships"
    if any(term in text for term in ("csr", "philanthropic")): return "csr"
    if any(term in text for term in ("government", "policy")): return "government_relations"
    if any(term in text for term in ("thought leadership", "media visibility")): return "thought_leadership"
    if "media" in text or "press" in text: return "media_attention"
    if any(term in text for term in ("programme awareness", "learner", "audience education")): return "learner_reach"
    if any(term in text for term in ("visibility", "story")): return "visibility"
    return "ecosystem_influence"


def _semantic_topic_cluster(topic: str, text: str) -> str:
    """Collapse common model/rule label variants onto stable, explainable topic groups."""
    value = f"{topic} {text}".casefold()
    clusters = (
        ("training and courses", r"\b(training|course|curricul|vocational|skill development|upskill|reskill|learning)\b"),
        ("jobs and placement", r"\b(job|jobs|employment|employability|placement|career|hiring|vacanc|workforce)\b"),
        ("enrolment and access", r"\b(enrol|admission|application|registration|eligibility|scholarship|fees|centre|center|location)\b"),
        ("learner support and experience", r"\b(support|help|experience|complaint|issue|problem|safety|scam|fraud|harassment)\b"),
        ("partnership and ecosystem", r"\b(partner|partnership|collaborat|csr|foundation|ngo|government|ministry|ecosystem)\b"),
        ("media and public visibility", r"\b(media|press|journalis|visibility|thought leadership|public relations)\b"),
    )
    for canonical, pattern in clusters:
        if re.search(pattern, value):
            return canonical
    return re.sub(r"\s+", " ", topic.strip().casefold()) or "general mention"


@app.get("/strategy/objectives")
def list_pr_objectives():
    return {"objectives": [{"key": key, **value} for key, value in PR_OBJECTIVES.items()]}


@app.get("/strategy/organizations")
def list_organization_profiles(session: Session = Depends(get_session)):
    profiles = session.exec(select(OrganizationProfile).order_by(OrganizationProfile.canonical_name)).all()
    return {"organizations": [{**_utc_dump(item, ("verified_at", "created_at", "updated_at")), "aliases": json.loads(item.aliases_json or "[]")} for item in profiles]}


@app.post("/strategy/organizations")
def save_organization_profile(request: OrganizationProfileSave, session: Session = Depends(get_session)):
    name = request.canonical_name.strip()
    normalized = _normalized_org_name(name)
    if not normalized:
        raise HTTPException(422, "Enter an organization name")
    if request.public_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", request.public_email.strip()):
        raise HTTPException(422, "Enter a valid public organization email")
    if request.verification_status == "verified" and not (request.contact_url or request.verification_evidence):
        raise HTTPException(422, "A source URL is required before marking an organization verified")
    profile = session.exec(select(OrganizationProfile).where(OrganizationProfile.normalized_name == normalized)).first()
    if profile is None:
        profile = OrganizationProfile(canonical_name=name, normalized_name=normalized)
    profile.canonical_name = name
    profile.normalized_name = normalized
    profile.aliases_json = json.dumps(sorted({alias.strip() for alias in request.aliases if alias.strip()}), ensure_ascii=False)
    profile.website = request.website.strip() if request.website else None
    profile.public_email = request.public_email.strip() if request.public_email else None
    profile.contact_url = request.contact_url.strip() if request.contact_url else None
    profile.verification_status = request.verification_status
    profile.verification_evidence = request.verification_evidence.strip() if request.verification_evidence else None
    profile.verified_at = datetime.now(timezone.utc) if request.verification_status == "verified" else None
    profile.notes = request.notes
    profile.updated_at = datetime.now(timezone.utc)
    session.add(profile); session.commit(); session.refresh(profile)
    return {**_utc_dump(profile, ("verified_at", "created_at", "updated_at")), "aliases": json.loads(profile.aliases_json)}


@app.post("/content/recommendations/{recommendation_id}/feedback")
def add_recommendation_feedback(recommendation_id: int, request: RecommendationFeedbackCreate, session: Session = Depends(get_session)):
    if not session.get(ContentRecommendation, recommendation_id):
        raise HTTPException(404, "Content recommendation not found")
    feedback = RecommendationFeedback(recommendation_id=recommendation_id, rating=request.rating, reason=request.reason)
    session.add(feedback); session.commit(); session.refresh(feedback)
    return _utc_dump(feedback, ("created_at",))


@app.post("/content/recommendations/{recommendation_id}/outcomes")
def add_campaign_outcome(recommendation_id: int, request: CampaignOutcomeCreate, session: Session = Depends(get_session)):
    if not session.get(ContentRecommendation, recommendation_id):
        raise HTTPException(404, "Content recommendation not found")
    outcome = CampaignOutcome(recommendation_id=recommendation_id, campaign_name=request.campaign_name.strip(),
        outcome_type=request.outcome_type, value=request.value, measured_at=_utc(request.measured_at) if request.measured_at else datetime.now(timezone.utc),
        attribution_method=request.attribution_method, evidence_url=request.evidence_url, notes=request.notes)
    session.add(outcome); session.commit(); session.refresh(outcome)
    return _utc_dump(outcome, ("measured_at", "created_at"))


@app.post("/quick-email-drafts")
def create_quick_email_draft(request: QuickEmailDraftCreate, session: Session = Depends(get_session)):
    if request.target_type == "partner":
        if not request.organization_id or request.recipient_email is None:
            raise HTTPException(422, "Partner drafts require a verified organization profile and its public email")
        profile = session.get(OrganizationProfile, request.organization_id)
        if not profile or profile.verification_status != "verified" or not profile.public_email:
            raise HTTPException(422, "Only a verified profile with a published organization email can be used")
        if request.recipient_email.strip().casefold() != profile.public_email.casefold():
            raise HTTPException(422, "Recipient must match the verified public organization email")
    elif request.recipient_email:
        raise HTTPException(422, "Audience email templates cannot target an individual address; use an opt-in mailing list")
    ids = list(dict.fromkeys(request.evidence_record_ids))
    available = {record.id for record in session.exec(select(SocialRecord).where(SocialRecord.id.in_(ids))).all()} if ids else set()
    if len(available) != len(ids):
        raise HTTPException(422, "Every linked evidence record must exist")
    draft = QuickEmailDraft(target_type=request.target_type, organization_id=request.organization_id,
        audience_segment=request.audience_segment, recipient_email=request.recipient_email,
        subject=request.subject.strip(), body=request.body.strip(), evidence_record_ids=json.dumps(ids))
    session.add(draft); session.commit(); session.refresh(draft)
    return {**_utc_dump(draft, ("created_at", "updated_at")), "evidence_record_ids": ids, "send_enabled": False}


@app.get("/quick-email-drafts")
def list_quick_email_drafts(session: Session = Depends(get_session)):
    drafts = session.exec(select(QuickEmailDraft).order_by(QuickEmailDraft.updated_at.desc()).limit(100)).all()
    return {"drafts": [{**_utc_dump(item, ("created_at", "updated_at")), "evidence_record_ids": json.loads(item.evidence_record_ids or "[]"), "send_enabled": False} for item in drafts]}


def _tailor_audience_action(action: str, segment: str, need: str, monitoring_scope: str, action_type: str | None = None) -> str:
    if action_type == "escalate":
        return action
    brand_context = monitoring_scope == "brand"
    if segment == "employer_workforce":
        return "Verify the employer, workforce need, and location. Then check whether a suitable skills partnership exists before any outreach."
    if segment == "ecosystem_partner":
        return "Verify the organization and its stated objective, then assess geography and capability fit before suggesting collaboration."
    if segment == "job_seeker":
        return "Offer verified career or job-search guidance. Ask which role or location they need help with; do not imply a placement guarantee."
    if segment == "learner":
        if need == "enrolment_access":
            return ("Check current official eligibility, fees, and application details before replying; ask for location if needed."
                    if brand_context else "Point to an authoritative course or application source and ask for location or eligibility details if needed.")
        return ("Answer the learning question with current official course and location details, and ask which skill they want to build."
                if brand_context else "Answer with an authoritative training resource and ask which skill and location would help.")
    if segment == "community_supporter":
        return "Share a verified resource suitable for the person they are supporting, without assuming the supporter is the learner."
    if segment == "skills_audience_interest":
        return "Treat this as a content-planning signal, not proof the author needs help. If a reply is useful, ask what specific skill or career information they want."
    if segment == "unclear":
        return "Ask one clarifying question about the person's skill, location, or goal before selecting a resource or response."
    return action


def _opportunity_reason(record: SocialRecord, analysis: RecordAnalysis | None) -> dict | None:
    is_thematic_search_result = record.record_type == "search_result" and record.monitoring_scope == "thematic"
    if (record.record_type not in {"comment", "social_post"} and not is_thematic_search_result) or not record.text.strip():
        return None
    signals = analyze_signals(record.source, record.record_type, record.text)
    relevant = analysis.is_relevant if analysis else signals["is_relevant"]
    if not relevant:
        return None
    intent = analysis.intent if analysis else signals["intent"]
    priority = analysis.priority if analysis else signals["priority"]
    sentiment = analysis.sentiment if analysis else signals["sentiment"]
    audience_segment = analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else signals["audience_segment"]
    audience_need = analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else signals["audience_need"]
    audience_confidence = analysis.audience_confidence if analysis and analysis.audience_segment not in (None, "", "unclear") and analysis.audience_confidence is not None else signals["audience_confidence"]
    confidence = analysis.confidence if analysis else 0.45
    text = record.text.casefold()
    is_question = intent == "question" or "?" in record.text
    explicit_collaboration = any(term in text for term in ("partnership", "partner with", "partnering", "collaboration", "collaborate", "joint initiative", "csr grant"))
    employer_need = any(term in text for term in ("skills shortage", "shortage of", "hiring for", "vacancies", "technicians needed", "looking for candidates", "talent demand", "skills gap"))
    organization_activity = is_thematic_search_result and bool(re.search(
        r"\b(ngo|non.?profit|foundation|social enterprise|training provider|university|college|csr|employer|company)\b", text
    )) and bool(re.search(
        r"\b(upskill|reskill|skill development|skilling|vocational|employability|job readiness|youth employment|workforce|apprenticeship|livelihood training|digital skills)\b", text
    ))
    if not (is_question or intent in {"complaint", "suggestion"} or priority in {"high", "critical"}):
        if not (explicit_collaboration or employer_need or organization_activity):
            return None
    urgent = bool(re.search(r"\b(urgent|unsafe|danger|scam|fraud|harassment|injury|safety|emergency|misleading)\b", text))
    training_question = is_question and any(term in text for term in ("course", "training", "skill", "learn", "centre", "center"))
    stakeholder = None
    if any(term in text for term in ("government", "ministry", "policy", "district administration")):
        stakeholder = "government"
    elif any(term in text for term in ("foundation", "csr", "philanthrop", "grant")):
        stakeholder = "CSR or foundation"
    elif any(term in text for term in ("university", "college", "academic", "research institute")):
        stakeholder = "academic or knowledge partner"
    elif any(term in text for term in ("ngo", "non-profit", "nonprofit", "social enterprise")):
        stakeholder = "social sector organization"
    elif any(term in text for term in ("company", "corporate", "employer", "manufacturer", "factory", "industry", "workforce")):
        stakeholder = "corporate or industry"
    if not stakeholder and explicit_collaboration:
        stakeholder = "potential ecosystem partner"
    if not stakeholder and employer_need:
        stakeholder = "corporate or industry"
    partnership_signal = bool((explicit_collaboration and stakeholder) or (stakeholder == "corporate or industry" and employer_need) or organization_activity)
    if urgent:
        action_type, objective = "escalate", "reputation and issue management"
        reason = "Potential safety, misinformation, or reputation risk requires human verification"
        action = "Escalate for a human fact check. Do not treat this signal as verified or reply before checking the source."
        score = 96
    elif partnership_signal:
        action_type, objective = "investigate_partner", "partnership discovery"
        reason = "Public signal suggests aligned organization activity, employer need, or collaboration intent"
        action = "For search previews, open and verify the original page first. Confirm the organization, initiative, geography, and mutual fit before any outreach."
        score = 82
    elif intent == "complaint" or sentiment == "negative":
        action_type, objective = "respond_or_escalate", "reputation and issue management"
        reason = "Concern or negative experience may need a thoughtful response"
        action = "Acknowledge the concern, verify any facts, and route sensitive issues to the appropriate team."
        score = 75
    elif training_question:
        action_type, objective = "promote_resource", "programme awareness"
        reason = "Training enquiry may benefit from a verified official resource"
        action = "Check current course and location details on an official Tata STRIVE source, then share the relevant resource if appropriate."
        score = 70
    elif stakeholder and stakeholder not in {"government", "CSR or foundation", "academic or knowledge partner"} and any(term in text for term in ("thought leadership", "future of work", "green jobs", "policy", "media", "press", "news")):
        action_type, objective = "develop_content", "thought leadership and media visibility"
        reason = "External discussion may support a timely expert or public-interest perspective"
        action = "Check evidence and subject-matter expertise, then consider a reviewed expert comment, explainer, or media angle."
        score = 68
    elif stakeholder == "government":
        action_type, objective = "monitor_or_engage", "government and ecosystem relations"
        reason = "Public policy or government activity may affect the skills ecosystem"
        action = "Verify the policy or initiative from an authoritative source and assess relevance before proposing engagement."
        score = 66
    elif stakeholder == "CSR or foundation":
        action_type, objective = "investigate_partner", "CSR and philanthropic partnership discovery"
        reason = "Public conversation may indicate an aligned social-impact funding or collaboration priority"
        action = "Verify the organization, stated priority, geography, and current partnership fit before outreach."
        score = 68
    elif stakeholder == "academic or knowledge partner":
        action_type, objective = "investigate_partner", "knowledge partnership discovery"
        reason = "Academic or research discussion may indicate a knowledge-sharing opportunity"
        action = "Verify the institution, research focus, and mutual objective before proposing a knowledge partnership."
        score = 64
    elif any(term in text for term in ("learner story", "success story", "graduated", "transformed my life", "impact story")):
        action_type, objective = "develop_content", "learner story and impact visibility"
        reason = "A public learner outcome may be a candidate story angle"
        action = "Seek consent and independently verify the outcome before considering a learner story or impact feature."
        score = 67
    elif is_question:
        action_type, objective = "respond_or_create_faq", "audience education"
        reason = "Audience question may indicate a need for practical guidance"
        action = "Verify the answer, then decide whether a direct response or reusable FAQ/content would help."
        score = 60
    elif intent == "suggestion":
        action_type, objective = "develop_content", "community engagement"
        reason = "Audience suggestion may inform future communication"
        action = "Review the suggestion and consider acknowledging it or feeding it into content planning."
        score = 60
    else:
        action_type, objective = "monitor", "audience understanding"
        reason = "Relevant conversation merits monitoring"
        action = "Monitor for additional evidence or a clearer opportunity before responding."
        score = 45
    if is_thematic_search_result:
        reason = f"Search preview lead · verify the full original source. {reason}"
        confidence = min(confidence, 0.42)
    score += round(max(0, min(confidence, 1)) * 10)
    action = _tailor_audience_action(action, audience_segment, audience_need, record.monitoring_scope, action_type)
    return {"reason": reason, "action": action, "score": min(score, 100), "action_type": action_type,
            "pr_objective": objective, "stakeholder_type": stakeholder, "partnership_signal": partnership_signal,
            "confidence": max(0, min(confidence, 1)), "review_state": "review_required",
            "audience_segment": audience_segment, "audience_need": audience_need,
            "audience_confidence": audience_confidence}


@app.get("/engagement/opportunities")
def list_engagement_opportunities(session: Session = Depends(get_session)):
    records = session.exec(select(SocialRecord).where(
        SocialRecord.record_type.in_(["comment", "social_post", "search_result"]),
        SocialRecord.duplicate_of_record_id.is_(None),
    ).order_by(SocialRecord.published_at.desc().nullslast(), SocialRecord.collected_at.desc())).all()
    analyses = {item.record_id: item for item in session.exec(select(RecordAnalysis)).all()}
    saved = {item.record_id: item for item in session.exec(select(EngagementOpportunity)).all()}
    for record in records:
        item = saved.get(record.id)
        if item:
            continue
        found = _opportunity_reason(record, analyses.get(record.id))
        if not found:
            continue
        item = EngagementOpportunity(record_id=record.id, reason=found["reason"], suggested_action=found["action"],
                                      priority_score=found["score"], action_type=found["action_type"],
                                      pr_objective=found["pr_objective"], stakeholder_type=found["stakeholder_type"],
                                      partnership_signal=found["partnership_signal"], confidence=found["confidence"],
                                      review_state=found["review_state"])
        session.add(item)
        saved[record.id] = item
    session.commit()
    opportunities = [(record, saved[record.id]) for record in records if record.id in saved]
    opportunities.sort(key=lambda pair: (
        pair[1].status in {"closed", "dismissed"},
        -pair[1].priority_score,
        -(_utc(pair[0].published_at).timestamp() if pair[0].published_at else 0),
    ))
    results = []
    for record, item in opportunities:
        audience = analyze_signals(record.source, record.record_type, record.text)
        analysis = analyses.get(record.id)
        segment = analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else audience["audience_segment"]
        need = analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else audience["audience_need"]
        audience_confidence = analysis.audience_confidence if analysis and analysis.audience_segment not in (None, "", "unclear") and analysis.audience_confidence is not None else audience["audience_confidence"]
        activity_at = record.published_at or record.collected_at
        text = record.text.casefold()
        urgency_points = 25 if re.search(r"\b(urgent|unsafe|danger|scam|fraud|harassment|injury|safety|emergency|immediately|deadline)\b", text) else 12 if re.search(r"\b(today|tomorrow|this week|closing soon|limited time)\b", text) else 0
        age_days = max(0, (datetime.now(timezone.utc) - _utc(activity_at)).days) if activity_at else 365
        recency_points = 15 if age_days <= 7 else 12 if age_days <= 30 else 6 if age_days <= 90 else 1
        confidence_points = round(max(0, min(1, item.confidence)) * 25)
        evidence_points = 6 if record.record_type == "search_result" else 20 if record.url and len(record.text) >= 80 else 15 if record.url else 8
        strategic_points = 20 if item.partnership_signal or item.action_type in {"investigate_partner", "escalate"} else 16 if item.pr_objective in {"programme awareness", "thought leadership and media visibility"} else 12
        score_parts = {"evidence_strength": evidence_points, "confidence": confidence_points,
                       "strategic_value": strategic_points, "urgency": urgency_points, "recency": recency_points}
        opportunity_score = min(100, sum(score_parts.values()))
        results.append({**_utc_dump(item, ("created_at", "updated_at", "follow_up_at")),
                        "suggested_action": _tailor_audience_action(item.suggested_action, segment, need, record.monitoring_scope, item.action_type),
                        "opportunity_score": opportunity_score, "score_parts": score_parts,
                        "strategic_value": strategic_points, "urgency_score": urgency_points,
                        "score_explanation": "Evidence strength, saved signal confidence, strategic objective fit, explicit urgency cues, and source recency are combined. This is a review-priority aid, not a predicted outcome.",
                        "pr_objective_key": _pr_objective_key(item.pr_objective),
                        "pr_objective_explanation": PR_OBJECTIVES.get(_pr_objective_key(item.pr_objective), {}).get("why"),
                        "audience_segment": segment, "audience_need": need, "audience_confidence": audience_confidence,
                        "capability_matches": match_capabilities(record.text),
                        "staleness_days": max(0, (datetime.now(timezone.utc) - _utc(item.updated_at)).days),
                        "is_stale": item.status not in {"closed", "dismissed"} and (datetime.now(timezone.utc) - _utc(item.updated_at)).days >= 30,
                        "duplicate_of_record_id": record.duplicate_of_record_id,
                        "source": record.source, "record_type": record.record_type,
                        "monitoring_scope": record.monitoring_scope, "text": record.text,
                        "url": record.url, "author": record.author, "like_count": record.like_count,
                        "reply_count": record.reply_count,
                        "published_at": _utc(record.published_at).isoformat() if record.published_at else None})
    results.sort(key=lambda result: (result["status"] in {"closed", "dismissed"}, -result["opportunity_score"], -(result.get("priority_score") or 0)))
    return {"count": len(results), "opportunities": results}


@app.post("/engagement/opportunities/from-record/{record_id}")
def add_record_to_strategy_radar(record_id: int, session: Session = Depends(get_session)):
    """Pin a conversation into the radar for explicit human assessment."""
    record = session.get(SocialRecord, record_id)
    if not record:
        raise HTTPException(404, "Conversation not found")
    item = session.exec(select(EngagementOpportunity).where(EngagementOpportunity.record_id == record_id)).first()
    if item:
        if item.status in {"closed", "dismissed"}:
            item.status = "new"
        item.manually_added_to_radar = True
        item.updated_at = datetime.now(timezone.utc)
    else:
        analysis = session.exec(select(RecordAnalysis).where(RecordAnalysis.record_id == record_id)).first()
        found = _opportunity_reason(record, analysis)
        if found:
            item = EngagementOpportunity(record_id=record_id, reason=found["reason"],
                suggested_action=found["action"], priority_score=found["score"],
                action_type=found["action_type"], pr_objective=found["pr_objective"],
                stakeholder_type=found["stakeholder_type"], partnership_signal=found["partnership_signal"],
                confidence=found["confidence"], review_state="review_required", manually_added_to_radar=True)
        else:
            signal = analyze_signals(record.source, record.record_type, record.text)
            item = EngagementOpportunity(record_id=record_id,
                reason="Manually added from the conversation stream for human review.",
                suggested_action="Review the original source, relevance, stakeholder identity, and evidence before assigning any outreach or partnership action.",
                priority_score=signal["importance_score"], action_type="manual_radar_review",
                pr_objective="ecosystem influence", stakeholder_type="unassessed stakeholder",
                confidence=signal["confidence"], review_state="review_required", manually_added_to_radar=True)
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id, "record_id": record_id, "manually_added_to_radar": item.manually_added_to_radar,
            "status": item.status, "review_state": item.review_state}


@app.get("/strategy/partners")
def strategy_partner_radar(session: Session = Depends(get_session)):
    """Group public partnership signals into evidence-led, review-required radar cards."""
    opportunity_data = list_engagement_opportunities(session)
    opportunities = opportunity_data["opportunities"]
    candidates: dict[str, dict] = {}
    profiles = session.exec(select(OrganizationProfile)).all()
    profile_aliases: dict[str, OrganizationProfile] = {}
    for profile in profiles:
        profile_aliases[_normalized_org_name(profile.canonical_name)] = profile
        for alias in json.loads(profile.aliases_json or "[]"):
            profile_aliases[_normalized_org_name(alias)] = profile
    for item in opportunities:
        signal_text = item.get("text", "").casefold()
        collaboration_cues = ("partnership", "partner with", "partnering", "collaboration", "collaborate", "joint initiative", "csr grant", "grant opportunity", "seeking partners", "invite partners")
        employer_need_cues = ("skills shortage", "shortage of", "hiring for", "vacancies", "technicians needed", "looking for candidates", "talent demand", "skills gap")
        org_skills_signal = item.get("record_type") == "search_result" and item.get("monitoring_scope") == "thematic" and bool(re.search(
            r"\b(ngo|non.?profit|foundation|social enterprise|training provider|university|college|csr|employer|company)\b", signal_text
        )) and bool(re.search(
            r"\b(upskill|reskill|skill development|skilling|vocational|employability|job readiness|youth employment|workforce|apprenticeship|livelihood training|digital skills)\b", signal_text
        ))
        actionable_signal = any(cue in signal_text for cue in collaboration_cues + employer_need_cues) or org_skills_signal
        if not actionable_signal and item.get("stakeholder_review") != "verified" and not item.get("manually_added_to_radar"):
            continue
        if item.get("stakeholder_review") == "not_a_fit" or item.get("status") in {"closed", "dismissed"}:
            continue
        fallback_name = None if item.get("record_type") == "search_result" else item.get("author")
        display_name = (item.get("stakeholder_name") or fallback_name or "").strip()
        if not display_name:
            display_name = f"Unidentified {item.get('stakeholder_type') or 'stakeholder'} · record #{item['record_id']}"
        profile = profile_aliases.get(_normalized_org_name(display_name))
        canonical_name = profile.canonical_name if profile else display_name
        identity = f"organization::{profile.normalized_name}" if profile else f"{item.get('source', 'unknown').casefold()}::{display_name.casefold()}"
        partner = candidates.setdefault(identity, {
            "candidate_key": identity, "name": canonical_name, "source": item.get("source"),
            "organization_id": profile.id if profile else None,
            "organization_verification": profile.verification_status if profile else "unverified",
            "organization_website": profile.website if profile else None,
            "organization_public_email": profile.public_email if profile and profile.verification_status == "verified" else None,
            "organization_contact_url": profile.contact_url if profile else None,
            "organization_verification_evidence": profile.verification_evidence if profile else None,
            "stakeholder_type": item.get("stakeholder_type") or "potential ecosystem partner",
            "opportunities": [], "evidence": [], "capabilities": {}, "latest_at": None,
            "activity_30_days": 0, "activity_90_days": 0, "likes": 0, "replies": 0,
            "metrics_available": False, "follow_up_at": None, "owner": None,
            "review_state": item.get("stakeholder_review") or "not_assessed",
        })
        published = item.get("published_at")
        published_dt = _utc(datetime.fromisoformat(published)) if published else None
        latest = _utc(datetime.fromisoformat(partner["latest_at"])) if partner["latest_at"] else None
        if published_dt:
            if not latest or published_dt > latest:
                partner["latest_at"] = published_dt.isoformat()
            age_days = max(0, (datetime.now(timezone.utc) - published_dt).days)
            partner["activity_30_days"] += int(age_days <= 30)
            partner["activity_90_days"] += int(age_days <= 90)
        partner["opportunities"].append({"id": item["id"], "record_id": item["record_id"],
            "status": item["status"], "owner": item.get("owner"), "follow_up_at": item.get("follow_up_at")})
        partner["likes"] += item.get("like_count") or 0
        partner["replies"] += item.get("reply_count") or 0
        partner["metrics_available"] = partner["metrics_available"] or item.get("like_count") is not None or item.get("reply_count") is not None
        partner["review_state"] = item.get("stakeholder_review") or partner["review_state"]
        partner["owner"] = partner["owner"] or item.get("owner")
        partner["follow_up_at"] = partner["follow_up_at"] or item.get("follow_up_at")
        for match in item.get("capability_matches") or []:
            stored = partner["capabilities"].setdefault(match["capability"], {"score": 0.0, "terms": set()})
            stored["score"] = max(stored["score"], match["score"])
            stored["terms"].update(match["matched_terms"])
        if len(partner["evidence"]) < 4:
            partner["evidence"].append({"record_id": item["record_id"], "text": item["text"],
                "url": item.get("url"), "published_at": published, "reason": item["reason"],
                "priority_score": item["priority_score"]})

    recommendations = session.exec(select(ContentRecommendation).where(
        ContentRecommendation.collaboration_partner.is_not(None))).all()
    by_partner: dict[str, list[ContentRecommendation]] = defaultdict(list)
    for recommendation in recommendations:
        by_partner[recommendation.collaboration_partner.strip().casefold()].append(recommendation)

    results = []
    for partner in candidates.values():
        capabilities = [{"capability": name, "score": round(value["score"], 2),
                         "matched_terms": sorted(value["terms"])}
                        for name, value in sorted(partner["capabilities"].items(), key=lambda pair: -pair[1]["score"])]
        recent_score = 15 if partner["activity_30_days"] else 8 if partner["activity_90_days"] else 0
        evidence_score = min(20, len(partner["opportunities"]) * 7)
        fit_score = round(max((item["score"] for item in capabilities), default=0) * 25)
        engagement_score = min(10, round(math.log1p(partner["likes"] + partner["replies"]) * 3)) if partner["metrics_available"] else 0
        partner_record_ids = {item["record_id"] for item in partner["opportunities"]}
        linked_content = list(by_partner.get(partner["name"].casefold(), []))
        for recommendation in recommendations:
            if recommendation.collaboration_partner and recommendation not in linked_content:
                try:
                    evidence_ids = set(json.loads(recommendation.evidence_record_ids or "[]"))
                except (ValueError, TypeError):
                    evidence_ids = set()
                if partner_record_ids & evidence_ids:
                    linked_content.append(recommendation)
        signal_texts = " ".join(entry["text"].casefold() for entry in partner["evidence"])
        intent_score = 15 if any(cue in signal_texts for cue in collaboration_cues + employer_need_cues) else 6
        verification_score = 15 if partner["organization_verification"] == "verified" else 0
        score = min(100, evidence_score + recent_score + fit_score + engagement_score + intent_score + verification_score)
        published_content = [entry for entry in linked_content if entry.status == "published"]
        measured_content = [entry for entry in published_content if entry.reach is not None]
        results.append({
            "candidate_key": partner["candidate_key"], "name": partner["name"], "source": partner["source"],
            "stakeholder_type": partner["stakeholder_type"], "radar_score": score,
            "score_parts": {"evidence": evidence_score, "recency": recent_score, "capability_fit": fit_score,
                            "observed_engagement": engagement_score, "actionable_intent": intent_score,
                            "verified_identity": verification_score},
            "activity_30_days": partner["activity_30_days"], "activity_90_days": partner["activity_90_days"],
            "latest_at": partner["latest_at"], "signal_count": len(partner["opportunities"]),
            "likes": partner["likes"] if partner["metrics_available"] else None,
            "replies": partner["replies"] if partner["metrics_available"] else None,
            "capability_matches": capabilities, "evidence": partner["evidence"],
            "organization_id": partner["organization_id"],
            "organization_verification": partner["organization_verification"],
            "organization_website": partner["organization_website"],
            "organization_public_email": partner["organization_public_email"],
            "organization_contact_url": partner["organization_contact_url"],
            "organization_verification_evidence": partner["organization_verification_evidence"],
            "opportunities": partner["opportunities"], "owner": partner["owner"],
            "follow_up_at": partner["follow_up_at"], "review_state": partner["review_state"],
            "approach_plan": [
                "Verify the account, organization, and decision-maker using its public profile or official website.",
                f"Confirm the stated need and geography; assess fit with {capabilities[0]['capability'] if capabilities else 'Tata STRIVE skills and employability capabilities'}.",
                "Design a small, measurable pilot proposal with learner group, delivery owner, safeguards, and success measures.",
                "Use the organization’s published partnership channel for a tailored introduction; do not infer consent from a public post.",
                "Schedule a follow-up and record the response, next decision, and partnership outcome in the opportunity queue.",
            ],
            "potential_value": "A verified fit could connect employer or ecosystem demand to relevant skills pathways, widen learner access, and create credible joint visibility. This is a hypothesis until the partner confirms need and outcomes.",
            "growth_measurement": {"content_items": len(linked_content), "published_items": len(published_content),
                "measured_items": len(measured_content), "recorded_reach": sum(entry.reach or 0 for entry in measured_content),
                "stakeholder_engagements": sum(entry.relevant_stakeholder_engagements or 0 for entry in published_content),
                "partnership_enquiries": sum(entry.partnership_enquiries or 0 for entry in published_content),
                "media_enquiries": sum(entry.media_enquiries or 0 for entry in published_content)},
        })
    results.sort(key=lambda item: (-item["radar_score"], -item["activity_30_days"], item["name"].casefold()))
    return {"partners": results, "count": len(results),
            "method": "Candidate scores combine repeated evidence (20), recency (15), capability overlap (25), recorded engagement (10), explicit actionable intent (15), and human-verified organization identity (15). Missing metric coverage earns no engagement points. These are prioritization heuristics, not partner qualification or predicted impact."}


@app.post("/strategy/partners/dismiss")
def dismiss_strategy_partner(request: StrategyPartnerDismiss, session: Session = Depends(get_session)):
    """Remove a radar candidate by dismissing its linked follow-up opportunities; preserve evidence."""
    opportunity_ids = set(request.opportunity_ids)
    opportunities = session.exec(select(EngagementOpportunity).where(
        EngagementOpportunity.id.in_(opportunity_ids),
    )).all()
    if not opportunities:
        raise HTTPException(404, "No linked strategy opportunities were found")
    for item in opportunities:
        item.status = "dismissed"
        item.updated_at = datetime.now(timezone.utc)
        session.add(item)
    session.commit()
    return {"dismissed": len(opportunities), "preserved_conversations": len(opportunities)}


@app.patch("/engagement/opportunities/{opportunity_id}")
def update_engagement_opportunity(opportunity_id: int, request: EngagementUpdate, session: Session = Depends(get_session)):
    item = session.get(EngagementOpportunity, opportunity_id)
    if not item:
        raise HTTPException(404, "Engagement opportunity not found")
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(item, key, _utc(value) if key == "follow_up_at" and value else value)
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    session.refresh(item)
    return _utc_dump(item, ("created_at", "updated_at", "follow_up_at"))


def _evidence_assessment(records: list[SocialRecord]) -> dict:
    unique = [record for record in records if record.duplicate_of_record_id is None]
    source_count = len({record.source for record in unique})
    original_count = sum(record.record_type in {"social_post", "comment"} for record in unique)
    simulated_count = sum(record.is_simulated for record in unique)
    linked_count = sum(bool(record.url) for record in unique)
    freshness = sum(bool(record.published_at and (datetime.now(timezone.utc) - _utc(record.published_at)).days <= 90) for record in unique)
    score = min(100, (min(30, original_count * 15)) + (min(20, max(0, source_count - 1) * 10)) +
                (min(20, len(unique) * 5)) + (min(15, linked_count * 3)) + (min(15, freshness * 3)) - min(40, simulated_count * 20))
    valid = bool(original_count and not simulated_count)
    return {"score": max(0, score), "evidence_count": len(unique), "original_conversation_count": original_count,
            "source_diversity": source_count, "linked_sources": linked_count, "recent_evidence_count": freshness,
            "simulated_evidence_count": simulated_count, "valid_for_generation": valid,
            "confidence_label": "stronger evidence" if score >= 65 else "limited evidence" if score >= 35 else "weak evidence",
            "review_required": True, "limitations": "Scores reflect evidence breadth, links, and freshness only; they do not validate truth, representativeness, consent, or causal claims."}


CONTENT_IDEA_IDLE_LIMIT = timedelta(minutes=30)


def _pause_inactive_content_ideas(session: Session) -> None:
    """Pause unfinished plans after 30 minutes without an edit, preserving their content."""
    cutoff = datetime.now(timezone.utc) - CONTENT_IDEA_IDLE_LIMIT
    stale_items = session.exec(select(ContentRecommendation).where(
        ContentRecommendation.status.in_(["idea", "drafting", "review"]),
        ContentRecommendation.updated_at <= cutoff,
    )).all()
    if not stale_items:
        return
    for item in stale_items:
        item.status = "paused"
        # Keep updated_at as the last user activity so the idle deadline remains auditable.
        session.add(item)
    session.commit()


@app.get("/content/recommendations")
def list_content_recommendations(session: Session = Depends(get_session)):
    _pause_inactive_content_ideas(session)
    items = session.exec(select(ContentRecommendation).order_by(ContentRecommendation.updated_at.desc())).all()
    results = []
    for item in items:
        data = _utc_dump(item, ("planned_at", "published_at", "created_at", "updated_at"))
        try:
            ids = json.loads(item.evidence_record_ids)
        except (ValueError, TypeError):
            ids = []
        data["evidence_record_ids"] = ids
        try:
            data["generated_content_options"] = json.loads(item.generated_content_options or "[]")
        except (ValueError, TypeError):
            data["generated_content_options"] = []
        data["evidence"] = []
        evidence_records = []
        for record_id in ids:
            record = session.get(SocialRecord, record_id)
            if record:
                evidence_records.append(record)
                data["evidence"].append({"id": record.id, "text": record.text, "source": record.source, "url": record.url})
        data["evidence_validation"] = _evidence_assessment(evidence_records)
        data["feedback"] = [{"rating": feedback.rating, "reason": feedback.reason, "created_at": _utc(feedback.created_at).isoformat()} for feedback in session.exec(select(RecommendationFeedback).where(RecommendationFeedback.recommendation_id == item.id).order_by(RecommendationFeedback.created_at.desc())).all()]
        data["campaign_outcomes"] = [_utc_dump(outcome, ("measured_at", "created_at")) for outcome in session.exec(select(CampaignOutcome).where(CampaignOutcome.recommendation_id == item.id).order_by(CampaignOutcome.measured_at.desc())).all()]
        data["strategic_engagement_score"] = _strategic_engagement_score(item)
        results.append(data)
    return {"count": len(results), "recommendations": results}


@app.post("/content/recommendations")
def create_content_recommendation(request: ContentRecommendationCreate, session: Session = Depends(get_session)):
    _pause_inactive_content_ideas(session)
    open_item = session.exec(select(ContentRecommendation.id).where(
        ContentRecommendation.status.in_(["idea", "drafting", "review", "scheduled"])
    ).limit(1)).first()
    if open_item is not None:
        raise HTTPException(409, "Finish editing the open content item first. Publish or pause it before creating another.")
    evidence_ids = list(dict.fromkeys(request.evidence_record_ids))
    available = {record.id for record in session.exec(select(SocialRecord).where(SocialRecord.id.in_(evidence_ids))).all()} if evidence_ids else set()
    if len(available) != len(evidence_ids):
        raise HTTPException(422, "Every evidence record must exist")
    evidence_records = session.exec(select(SocialRecord).where(SocialRecord.id.in_(evidence_ids))).all() if evidence_ids else []
    assessment = _evidence_assessment(evidence_records)
    item = ContentRecommendation(**request.model_dump(exclude={"evidence_record_ids", "confidence"}), evidence_record_ids=json.dumps(evidence_ids), confidence=min(request.confidence, assessment["score"] / 100))
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id, "status": item.status, "topic": item.topic, "evidence_validation": assessment}


@app.post("/content/recommendations/{recommendation_id}/generate")
def generate_recommendation_options(recommendation_id: int, session: Session = Depends(get_session)):
    _pause_inactive_content_ideas(session)
    item = session.get(ContentRecommendation, recommendation_id)
    if not item:
        raise HTTPException(404, "Content recommendation not found")
    if item.status == "paused":
        raise HTTPException(409, "This content plan is paused. Resume it from the Status field before generating copy.")
    try:
        ids = json.loads(item.evidence_record_ids or "[]")
    except (ValueError, TypeError):
        ids = []
    records = session.exec(select(SocialRecord).where(SocialRecord.id.in_(ids))).all() if ids else []
    evidence = [{"id": record.id, "text": record.text, "source": record.source, "url": record.url}
                for record in records if record.duplicate_of_record_id is None and not record.is_simulated and record.record_type in {"social_post", "comment"}]
    assessment = _evidence_assessment(records)
    if not evidence:
        raise HTTPException(422, "Link at least one original, non-simulated public post or comment; search snippets are not enough to generate content")
    objective = PR_OBJECTIVES.get(item.pr_objective)
    try:
        options = generate_content_options({"topic": item.topic, "pr_objective": item.pr_objective,
            "target_audience": item.target_audience, "messaging": item.messaging,
            "call_to_action": item.call_to_action, "hook": item.hook,
            "objective_playbook": objective}, evidence)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Content generation failed for recommendation %s", item.id)
        raise HTTPException(502, f"Content options could not be generated with {CONTENT_MODEL}") from exc
    item.generated_content_options = json.dumps(options, ensure_ascii=False)
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    return {"id": item.id, "model_name": CONTENT_MODEL, "options": options, "evidence_validation": assessment,
            "review_required": True, "published": False}


@app.patch("/content/recommendations/{recommendation_id}")
def update_content_recommendation(recommendation_id: int, request: ContentRecommendationUpdate, session: Session = Depends(get_session)):
    _pause_inactive_content_ideas(session)
    item = session.get(ContentRecommendation, recommendation_id)
    if not item:
        raise HTTPException(404, "Content recommendation not found")
    requested_status = request.status
    if requested_status in {"idea", "drafting", "review", "scheduled"}:
        other_open_item = session.exec(select(ContentRecommendation.id).where(
            ContentRecommendation.id != recommendation_id,
            ContentRecommendation.status.in_(["idea", "drafting", "review", "scheduled"]),
        ).limit(1)).first()
        if other_open_item is not None:
            raise HTTPException(409, "Another content item is already open. Publish or pause it before reopening this one.")
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(item, key, _utc(value) if key in {"planned_at", "published_at"} and value else value)
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id, "status": item.status, "topic": item.topic, "updated_at": _utc(item.updated_at)}


@app.delete("/content/recommendations/{recommendation_id}")
def delete_content_recommendation(recommendation_id: int, session: Session = Depends(get_session)):
    """Delete one content plan and its dependent feedback/outcome rows; keep source evidence."""
    item = session.get(ContentRecommendation, recommendation_id)
    if not item:
        raise HTTPException(404, "Content recommendation not found")
    for feedback in session.exec(select(RecommendationFeedback).where(
        RecommendationFeedback.recommendation_id == recommendation_id
    )).all():
        session.delete(feedback)
    for outcome in session.exec(select(CampaignOutcome).where(
        CampaignOutcome.recommendation_id == recommendation_id
    )).all():
        session.delete(outcome)
    session.delete(item)
    session.commit()
    return {"deleted": True, "id": recommendation_id}


def _strategic_engagement_score(item: ContentRecommendation) -> float | None:
    """Transparent quality-weighted interaction points per 100 recorded reach."""
    if item.reach is None or item.reach <= 0:
        return None
    weighted = ((item.likes or 0) * 0.5 + (item.comments or 0) * 3 + (item.shares or 0) * 4
        + (item.saves or 0) * 3 + (item.follows or 0) * 5
        + (item.relevant_stakeholder_engagements or 0) * 6
        + (item.partnership_enquiries or 0) * 10 + (item.media_enquiries or 0) * 8)
    return round(min(100, weighted / item.reach * 100), 2)


@app.get("/performance/learning")
def get_performance_learning(session: Session = Depends(get_session)):
    """Summarize manually recorded outcomes without claiming causal learning."""
    items = session.exec(select(ContentRecommendation).where(
        ContentRecommendation.status == "published",
    )).all()
    measured = [item for item in items if _strategic_engagement_score(item) is not None]
    groups: dict[tuple[str, str, str], list[ContentRecommendation]] = defaultdict(list)
    for item in measured:
        groups[(item.pr_objective, item.recommended_format, item.target_audience)].append(item)
    patterns = []
    for (objective, content_format, audience), entries in groups.items():
        scores = [_strategic_engagement_score(item) for item in entries]
        patterns.append({"pr_objective": objective, "format": content_format,
            "audience": audience, "sample_size": len(entries),
            "mean_score": round(sum(score for score in scores if score is not None) / len(entries), 2),
            "usable_for_direction": len(entries) >= 3,
            "recommendation": ("Use as a candidate for the next reviewed brief; validate with fresh evidence." if len(entries) >= 3 else "Collect more comparable published results before drawing a pattern.")})
    patterns.sort(key=lambda item: (-item["mean_score"], -item["sample_size"]))
    feedback_rows = session.exec(select(RecommendationFeedback)).all()
    feedback_counts: dict[str, int] = defaultdict(int)
    for feedback in feedback_rows:
        feedback_counts[feedback.rating] += 1
    outcomes = session.exec(select(CampaignOutcome)).all()
    attributed: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        attributed[outcome.outcome_type] += outcome.value
    return {"published_items": len(items), "measured_items": len(measured),
        "patterns": patterns,
        "recommendation_feedback": dict(feedback_counts),
        "attributed_outcomes": dict(attributed),
        "outcome_records": len(outcomes),
        "method": "Strategic engagement points per 100 reach = likes×0.5 + comments×3 + shares×4 + saves×3 + follows×5 + relevant stakeholder interactions×6 + partnership enquiries×10 + media enquiries×8, divided by reach and multiplied by 100 (capped at 100). Separate campaign outcomes retain the named campaign, measurement source, evidence link and attribution method. Manual reports are observational, not proof of causation or automatic model training."}


@app.get("/replies")
def list_replies(status: str | None = None, session: Session = Depends(get_session)):
    statement = select(ReplyDraft)
    if status:
        if status not in {"draft", "approved", "rejected"}:
            raise HTTPException(422, "Invalid review status")
        statement = statement.where(ReplyDraft.status == status)
    drafts = session.exec(statement.order_by(ReplyDraft.generated_at.desc())).all()
    results = []
    for draft in drafts:
        record = session.get(SocialRecord, draft.record_id)
        analysis = session.exec(select(RecordAnalysis).where(RecordAnalysis.record_id == draft.record_id)).first()
        results.append({"draft_id": draft.id, "record_id": draft.record_id, "reply_text": draft.reply_text, "status": draft.status,
                        "original_text": record.text if record else None, "original_url": record.url if record else None,
                        "source": record.source if record else None, "record_type": record.record_type if record else None,
                        "author": record.author if record else None, "published_at": _utc(record.published_at) if record and record.published_at else None,
                        "collected_at": _utc(record.collected_at) if record else None,
                        "analysis": _utc_dump(analysis, ("analyzed_at",)) if analysis else None,
                        "audience_segment": (analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else analyze_signals(record.source, record.record_type, record.text)["audience_segment"]) if record else "unclear",
                        "audience_need": (analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else analyze_signals(record.source, record.record_type, record.text)["audience_need"]) if record else "unclear",
                        "model_name": draft.model_name,
                        "generated_at": _utc(draft.generated_at),
                        "reviewed_at": _utc(draft.reviewed_at) if draft.reviewed_at else None})
    return results


@app.patch("/replies/{draft_id}/review")
def review_reply(draft_id: int, request: ReviewDraftRequest, session: Session = Depends(get_session)):
    draft = session.get(ReplyDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Reply draft not found")
    if draft.status != "draft":
        raise HTTPException(409, "Only pending drafts can be reviewed")
    if request.edited_reply is not None:
        if not request.edited_reply.strip():
            raise HTTPException(422, "Edited reply cannot be empty")
        draft.reply_text = request.edited_reply.strip()
    draft.status = request.status
    draft.reviewed_at = datetime.now(timezone.utc)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return {"draft_id": draft.id, "status": draft.status, "reply_text": draft.reply_text, "published": False}


@app.post("/replies/{draft_id}/regenerate")
def regenerate_reply(draft_id: int, session: Session = Depends(get_session)):
    draft = session.get(ReplyDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Reply draft not found")
    if draft.status != "draft":
        raise HTTPException(409, "Only pending drafts can be regenerated")
    record = session.get(SocialRecord, draft.record_id)
    analysis = session.exec(select(RecordAnalysis).where(RecordAnalysis.record_id == draft.record_id)).first()
    if not record or record.record_type not in {"comment", "social_post"}:
        raise HTTPException(422, "Replies are only available for social posts and comments")
    # Existing drafts can outlive their analysis row (for example, after database
    # cleanup or a partial migration). Recompute explainable signals in that case
    # so a saved, eligible draft remains regeneratable.
    signals = analyze_signals(record.source, record.record_type, record.text)
    is_relevant = analysis.is_relevant if analysis else signals["is_relevant"]
    relevance_type = analysis.relevance_type if analysis else signals["relevance_type"]
    confidence = analysis.confidence if analysis else signals["confidence"]
    if not is_relevant or relevance_type not in {"direct_brand", "industry"} or confidence < 0.6:
        raise HTTPException(422, "Record does not meet the reply eligibility policy")
    try:
        audience_segment = analysis.audience_segment if analysis and analysis.audience_segment not in (None, "", "unclear") else signals["audience_segment"]
        audience_need = analysis.audience_need if analysis and analysis.audience_need not in (None, "", "unclear") else signals["audience_need"]
        draft.reply_text = generate_reply(
            record.source, record.record_type, record.text,
            analysis.topic if analysis else signals["topic"],
            analysis.intent if analysis else signals["intent"],
            analysis.sentiment if analysis else signals["sentiment"],
            analysis.perception_signal if analysis else signals["perception_signal"],
            audience_segment, audience_need,
        )
        draft.generated_at = datetime.now(timezone.utc)
        draft.model_name = REPLY_MODEL
        session.add(draft)
        session.commit()
        session.refresh(draft)
    except Exception as exc:
        session.rollback()
        logger.exception("Draft regeneration failed for record %s", record.id)
        raise HTTPException(502, "Reply model could not generate a draft") from exc
    return {"draft_id": draft.id, "reply_text": draft.reply_text, "status": draft.status, "model_name": draft.model_name}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _utc_dump(model, fields: tuple[str, ...]) -> dict:
    result = model.model_dump()
    for name in fields:
        value = result.get(name)
        if isinstance(value, datetime):
            result[name] = _utc(value)
    return result


def _public_error(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    for name in ("GNEWS_API_KEY", "YOUTUBE_API_KEY", "SERPAPI_API_KEY", "GOOGLE_SEARCH_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(r"(?i)(apikey|key)=([^&\s]+)", r"\1=[redacted]", message)
    return f"{type(exc).__name__}: {message[:240]}"
