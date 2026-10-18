import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import analysis_engine, main
from app import reply_engine
from app.ingestion import bluesky, gdelt, gnews, serpapi, youtube
from app.opportunities import COURSE_URL, classify_training_opportunity
from app.models import RecordAnalysis, ReplyDraft, SocialRecord
from app.signals import analyze_signals


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_bluesky_window_and_api_wrapped_posts(monkeypatch, session):
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    old = datetime.now(timezone.utc) - timedelta(days=45)
    post = {"uri": "at://did:plc:abc/app.bsky.feed.post/rkey", "record": {"text": "Tata STRIVE skills training matters", "createdAt": recent.isoformat()},
            "author": {"handle": "person.bsky.social"}, "likeCount": 4, "replyCount": 1}
    stale = {**post, "uri": "at://did:plc:abc/app.bsky.feed.post/old", "record": {"text": "Tata STRIVE old post", "createdAt": old.isoformat()}}

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"posts": [{"post": post}, {"post": stale}]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(bluesky.httpx, "Client", Client)
    result = bluesky.collect_bluesky(session)
    rows = session.exec(select(SocialRecord)).all()
    assert result["window_days"] == 30
    assert result["inserted"] == 1
    assert result["duplicates"] == 1
    assert result["out_of_window"] == 2
    assert len(rows) == 1
    assert rows[0].url == "https://bsky.app/profile/person.bsky.social/post/rkey"
    assert rows[0].published_at.tzinfo is not None


def test_serpapi_results_are_saved_as_discovery_not_comments(monkeypatch, session):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(serpapi, "_queries", lambda: ['"Tata STRIVE" site:reddit.com', '"Tata STRIVE" site:reddit.com'])

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"organic_results": [
            {"title": "Tata STRIVE discussion", "snippet": "A search preview", "link": "https://www.reddit.com/r/example/comments/1"},
            {"title": "Not a social source", "snippet": "Ignore", "link": "https://example.com/story"},
        ]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, params):
            assert params["engine"] == "google"
            assert params["api_key"] == "test-key"
            return Response()

    monkeypatch.setattr(serpapi.httpx, "Client", Client)
    result = serpapi.collect_serpapi(session)
    rows = session.exec(select(SocialRecord)).all()
    assert result["inserted"] == 1
    assert result["duplicates"] == 1
    assert result["invalid"] == 2
    assert rows[0].source == "google_search"
    assert rows[0].record_type == "search_result"
    assert rows[0].published_at is None


def test_serpapi_requires_api_key(monkeypatch, session):
    # An empty process value prevents dotenv from filling a real developer key.
    monkeypatch.setenv("SERPAPI_API_KEY", "")
    with pytest.raises(RuntimeError, match="SERPAPI_API_KEY"):
        serpapi.collect_serpapi(session)


def test_gnews_search_is_headline_only(monkeypatch, session):
    monkeypatch.setattr(gnews, "GNEWS_API_KEY", "test-key")

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"articles": [
                {"title": "Tata STRIVE launches a program", "description": "Youth training", "url": "https://example.com/brand"},
                {"title": "General skills news", "description": "Mentions Tata STRIVE incidentally", "url": "https://example.com/general"},
                {"title": "Supported project implemented by another group with certification by Tata STRIVE", "description": "A company is mentioned at the end", "url": "https://example.com/incidental"},
            ]}

    def get(url, params, timeout):
        assert params["q"] == '"Tata STRIVE"'
        assert params["in"] == "title"
        return Response()

    monkeypatch.setattr(gnews.httpx, "get", get)
    result = gnews.collect_gnews(session)
    records = session.exec(select(SocialRecord)).all()
    assert result["inserted"] == 1
    assert result["rejected_as_unrelated"] == 2
    assert len(records) == 1
    assert records[0].url == "https://example.com/brand"


def test_gdelt_ignores_non_brand_headlines(monkeypatch, session):
    class Response:
        text = ""
        def raise_for_status(self): pass
        def json(self):
            return {"articles": [
                {"title": "Tata STRIVE opens a center", "url": "https://example.com/brand", "domain": "example.com"},
                {"title": "General skills coverage", "url": "https://example.com/general", "domain": "example.com"},
                {"title": "Other project gets certification by Tata STRIVE", "url": "https://example.com/incidental", "domain": "example.com"},
            ]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, params, headers):
            assert params["query"] == '"Tata STRIVE"'
            return Response()

    monkeypatch.setattr(gdelt.httpx, "Client", Client)
    result = gdelt.collect_gdelt(session)
    records = session.exec(select(SocialRecord)).all()
    assert result["saved"] == 1
    assert len(records) == 1
    assert records[0].text == "Tata STRIVE opens a center"


def test_youtube_saves_only_brand_videos_and_comments(monkeypatch, session):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    search_calls = []

    def fetch(client, endpoint, params):
        if endpoint == "search":
            search_calls.append(params.copy())
            assert params["q"] in {'"Tata STRIVE"', '"#tatastrive"'}
            assert params["maxResults"] == 50
            assert "regionCode" not in params
            assert params["relevanceLanguage"] == "en"
            if params["q"] == '"Tata STRIVE"' and "pageToken" not in params:
                return {"items": [{"id": {"videoId": "brandvideo1"}}], "nextPageToken": "page-2"}
            if params.get("pageToken") == "page-2":
                return {"items": [{"id": {"videoId": "othervideo1"}}]}
            return {"items": [{"id": {"videoId": "brandvideo1"}}]}
        if endpoint == "videos":
            return {"items": [
                {"id": "brandvideo1", "snippet": {"title": "Tata STRIVE training", "description": "About its program"}, "statistics": {}},
                {"id": "othervideo1", "snippet": {"title": "Other Tata company", "description": "General news"}, "statistics": {}},
            ]}
        assert endpoint == "commentThreads"
        assert params["videoId"] == "brandvideo1"
        assert "searchTerms" not in params
        return {"items": [
            {"id": "brand-comment", "snippet": {"topLevelComment": {"id": "brand-comment", "snippet": {"textDisplay": "Tata STRIVE helped me", "authorDisplayName": "A", "publishedAt": "2026-01-01T00:00:00Z"}}}},
            {"id": "emoji-comment", "snippet": {"topLevelComment": {"id": "emoji-comment", "snippet": {"textDisplay": "Tata STRIVE 👍", "authorDisplayName": "Emoji", "publishedAt": "2026-01-01T00:00:00Z"}}}},
            {"id": "other-comment", "snippet": {"topLevelComment": {"id": "other-comment", "snippet": {"textDisplay": "Great video", "authorDisplayName": "B", "publishedAt": "2026-01-01T00:00:00Z"}}}},
        ]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

    monkeypatch.setattr(youtube, "fetch_json", fetch)
    monkeypatch.setattr(youtube.httpx, "Client", Client)
    result = youtube.collect_youtube(session)
    records = session.exec(select(SocialRecord)).all()
    assert len(search_calls) == 3
    assert result["matching_videos"] == 1
    assert result["comments_saved"] == 1
    assert {record.record_type for record in records} == {"comment"}
    assert all("tata strive" in record.text.casefold() for record in records)


def test_youtube_google_result_video_is_added_as_cross_channel_candidate(session):
    session.add(SocialRecord(source="google_search", record_type="search_result", external_id="result1",
        text="Tata STRIVE video", url="https://www.youtube.com/watch?v=AbCdEf12345",
        raw_json=json.dumps({"result": {"link": "https://www.youtube.com/watch?v=AbCdEf12345", "title": "Tata STRIVE", "snippet": "related post"}})))
    session.commit()
    assert youtube._google_video_candidates(session) == {"AbCdEf12345"}


def test_youtube_google_candidate_can_find_brand_comments_without_brand_in_video_metadata(monkeypatch, session):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    session.add(SocialRecord(source="google_search", record_type="search_result", external_id="result1",
        text="Tata STRIVE student discussion", url="https://www.youtube.com/watch?v=AbCdEf12345",
        raw_json=json.dumps({"result": {"link": "https://www.youtube.com/watch?v=AbCdEf12345",
                                        "title": "Tata STRIVE student discussion", "snippet": ""}})))
    session.commit()

    def fetch(client, endpoint, params):
        if endpoint == "search":
            return {"items": []}
        if endpoint == "videos":
            return {"items": [{"id": "AbCdEf12345", "snippet": {"title": "Student experiences", "description": "A discussion"}}]}
        assert endpoint == "commentThreads"
        return {"items": [{"id": "thread1", "snippet": {"topLevelComment": {"id": "comment1", "snippet": {
            "textDisplay": "Tata STRIVE helped me find a job", "authorDisplayName": "Student"}}}}]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

    monkeypatch.setattr(youtube, "fetch_json", fetch)
    monkeypatch.setattr(youtube.httpx, "Client", Client)
    result = youtube.collect_youtube(session)
    comments = session.exec(select(SocialRecord).where(SocialRecord.record_type == "comment")).all()
    videos = session.exec(select(SocialRecord).where(SocialRecord.record_type == "video")).all()
    assert result["comments_saved"] == 1
    assert len(comments) == 1
    assert comments[0].url.endswith("&lc=comment1")
    assert videos == []


def test_database_rejects_duplicate_source_id(session):
    session.add(SocialRecord(source="bluesky", record_type="social_post", external_id="same", text="first"))
    session.commit()
    session.add(SocialRecord(source="bluesky", record_type="social_post", external_id="same", text="duplicate"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_analysis_validates_structured_output(monkeypatch):
    good = {"is_relevant": True, "relevance_type": "industry", "topic": "training", "intent": "discussion", "sentiment": "neutral",
            "perception_signal": "No clear opinion", "confidence": .8, "priority": "low", "rationale": "Mentions vocational training."}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": json.dumps(good)}
    monkeypatch.setattr(analysis_engine.httpx, "post", lambda *a, **kw: Response())
    result = analysis_engine.analyse_record("bluesky", "social_post", "Vocational training")
    assert result["relevance_type"] == "industry"


def test_direct_brand_requires_an_explicit_mention(monkeypatch):
    direct = {"is_relevant": True, "relevance_type": "direct_brand", "topic": "training", "intent": "discussion", "sentiment": "neutral",
              "perception_signal": "No clear opinion", "confidence": .8, "priority": "low", "rationale": "Mentions the brand."}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": json.dumps(direct)}
    monkeypatch.setattr(analysis_engine.httpx, "post", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError, match="bounded retry"):
        analysis_engine.analyse_record("bluesky", "social_post", "Vocational training")


def test_explicit_brand_mention_is_a_direct_brand_signal(monkeypatch):
    output = {"is_relevant": True, "relevance_type": "industry", "topic": "training", "intent": "discussion", "sentiment": "neutral",
              "perception_signal": "No clear opinion", "confidence": .8, "priority": "low", "rationale": "Discusses training."}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": json.dumps(output)}
    monkeypatch.setattr(analysis_engine.httpx, "post", lambda *a, **kw: Response())
    result = analysis_engine.analyse_record("gnews", "news", "Tata STRIVE training program")
    assert result["is_relevant"] is True
    assert result["relevance_type"] == "direct_brand"
    assert "explicitly contains" in result["rationale"]


@pytest.mark.parametrize("failure", ["malformed", "unavailable"])
def test_analysis_failure_is_not_converted_to_a_guess(monkeypatch, failure):
    def call(*args, **kwargs):
        if failure == "unavailable":
            raise analysis_engine.httpx.ConnectError("offline")
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"response": "not json"}
        return Response()
    monkeypatch.setattr(analysis_engine.httpx, "post", call)
    with pytest.raises(RuntimeError):
        analysis_engine.analyse_record("bluesky", "social_post", "Skills")


def _record(session, source, record_type, text):
    item = SocialRecord(source=source, record_type=record_type, external_id=f"{source}:{record_type}:{text}", text=text)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _analysis(session, record, relevance_type="direct_brand", confidence=.9):
    item = RecordAnalysis(record_id=record.id, is_relevant=True, relevance_type=relevance_type, topic="training", intent="question",
                          sentiment="neutral", perception_signal="Asks about training", confidence=confidence, priority="low",
                          rationale="The post asks about training.", model_name="phi3:3.8b")
    session.add(item)
    session.commit()
    return item


def test_replies_only_generate_for_reliable_relevant_social(monkeypatch, session):
    allowed = _record(session, "bluesky", "social_post", "Is there training?")
    _analysis(session, allowed)
    news = _record(session, "gnews", "news", "Tata STRIVE launches a course")
    _analysis(session, news)
    low = _record(session, "bluesky", "comment", "Maybe training")
    _analysis(session, low, confidence=.4)
    monkeypatch.setattr(main, "generate_reply", lambda *args: "Please check the official source for details.")
    result = main.generate_pending_replies(limit=10, session=session)
    assert result["drafts_created"] == 1
    assert result["drafts"][0]["record_id"] == allowed.id
    assert session.exec(select(ReplyDraft)).all()[0].status == "draft"


def test_approval_is_review_only(session):
    record = _record(session, "bluesky", "comment", "Question")
    draft = ReplyDraft(record_id=record.id, reply_text="A draft", model_name="llama3.1:8b")
    session.add(draft)
    session.commit()
    response = main.review_reply(draft.id, main.ReviewDraftRequest(status="approved"), session)
    assert response["status"] == "approved"
    assert response["published"] is False


def test_training_opportunity_detection_requires_direct_brand_and_a_real_request():
    found = classify_training_opportunity("Tata STRIVE, I want AWS cloud training in Pune. Where can I join?")
    assert found is not None
    assert found["request_type"] == "course_location"
    assert found["location"] == "Pune"
    assert found["suggested_course"]["title"] == "AWS re/start"
    assert found["suggested_course"]["url"] == COURSE_URL
    assert classify_training_opportunity("Tata STRIVE training changed my life.") is None
    assert classify_training_opportunity("Where can I learn cloud skills?") is None
    assert classify_training_opportunity("Tata STRIVE sent me a WhatsApp job message. Is it legit?") is None
    assert classify_training_opportunity("Tata STRIVE courses offered by us; join the training immediately.") is None


def test_opportunity_draft_is_saved_with_catalog_match_and_reply_center_status(monkeypatch, session):
    record = _record(session, "youtube", "comment", "Tata STRIVE, I want AWS cloud training. Where can I join in Pune?")
    monkeypatch.setattr(main, "generate_opportunity_reply", lambda *args: "Cloud training sounds like the direction you are exploring.")
    result = main.draft_opportunity_reply(record.id, session)
    assert result["status"] == "draft"
    assert result["suggested_course"]["title"] == "AWS re/start"
    assert "AWS re/start" in result["reply_text"]
    assert COURSE_URL in result["reply_text"]
    listed = main.get_training_opportunities(session)
    assert listed["count"] == 1
    assert listed["opportunities"][0]["draft"]["draft_id"] == result["draft_id"]


def test_reply_engine_retries_unauthorized_first_person_claims(monkeypatch):
    outputs = [
        {"reply_text": "At Tata STRIVE, we focus on job training."},
        {"reply_text": "Practical skills can help connect learning with workplace needs."},
    ]
    prompts = []

    class Response:
        def __init__(self, output): self.output = output
        def raise_for_status(self): pass
        def json(self): return {"response": json.dumps(self.output)}

    def post(*args, **kwargs):
        prompts.append(kwargs["json"]["prompt"])
        return Response(outputs.pop(0))

    monkeypatch.setattr(reply_engine.httpx, "post", post)
    result = reply_engine.generate_reply("bluesky", "social_post", "Skill training helps", "training", "discussion", "neutral", "skills")
    assert result == "Practical skills can help connect learning with workplace needs."
    assert len(prompts) == 2
    assert "Correction" in prompts[1]


def test_collection_does_not_report_zero_insert_as_success(session):
    result = main._collect_one("test", lambda db: {"inserted": 0, "duplicates": 2}, session)
    assert result["status"] == "no_new_records"


def test_signal_analysis_reports_repetition_sentiment_and_importance():
    result = analyze_signals("bluesky", "comment", "Tata STRIVE training is great, great! Need urgent help?")
    assert result["relevance_type"] == "direct_brand"
    assert result["sentiment"] == "positive"
    assert result["sentiment_score"] > 0
    assert result["keyword_counts"][0] == {"term": "great", "count": 2}
    assert result["importance_score"] >= 70
    assert result["priority"] == "high"
    assert result["signal_model"] == "vader-rules-v1"


def test_search_snippet_estimate_is_not_reply_eligible(monkeypatch, session):
    record = _record(session, "google_search", "search_result", "Tata STRIVE training feedback")
    fields = analyze_signals(record.source, record.record_type, record.text)
    fields.pop("signal_model")
    fields.pop("sentiment_score")
    fields.pop("importance_score")
    fields.pop("keyword_counts")
    session.add(RecordAnalysis(record_id=record.id, model_name="vader-rules-v1", **fields))
    session.commit()
    monkeypatch.setattr(main, "generate_reply", lambda *args: "Draft")
    result = main.generate_pending_replies(limit=10, session=session)
    assert result["drafts_created"] == 0
