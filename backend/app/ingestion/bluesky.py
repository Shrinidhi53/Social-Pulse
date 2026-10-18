"""Public Bluesky search ingestion with local date validation."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import Session, select

from app.brand_filter import mentions_tata_strive
from app.data_quality import prepare_record
from app.models import SocialRecord

SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
BRAND_QUERIES = ['"Tata STRIVE"', '"#tatastrive"']
THEMATIC_QUERIES = [
    '"looking to upskill"', '"student" upskilling India', '"skill development"',
    '"vocational training"', '"youth employability" India', 'NGO skilling India',
    '"seeking partners" skills India',
    '"AWS course"', '"AWS certification"', '"cloud course"', '"cloud training"',
    '"interested in AWS"', '"course suggestions" skills', "CyberSecurity"
]
THEMATIC_TERMS = re.compile(
    r"\b(skill development|vocational training|employability|job readiness|youth employment|"
    r"workforce development|career training|apprenticeship|technical skills|entrepreneurship|"
    r"upskill(?:ing)?|reskill(?:ing)?|digital skills|career skills|skilling|livelihood training|"
    r"AWS|Amazon Web Services|cloud computing|cloud course|cloud training|course suggestions|"
    r"course recommendation|certification course)\b",
    re.IGNORECASE,
)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def collect_bluesky(session: Session) -> dict:
    days = max(1, min(int(os.getenv("BLUESKY_WINDOW_DAYS", "30")), 365))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    fetched = inserted = duplicates = invalid = out_of_window = 0
    errors: list[dict] = []
    seen: set[str] = set()

    with httpx.Client(timeout=httpx.Timeout(25, connect=5)) as client:
        query_jobs = [(query, "brand") for query in BRAND_QUERIES] + [(query, "thematic") for query in THEMATIC_QUERIES]
        for query, query_scope in query_jobs:
            try:
                response = client.get(SEARCH_URL, params={"q": query, "sort": "latest", "limit": 100, "lang": "en"}, headers={"User-Agent": "SocialPulse/1.0"})
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Bluesky response had an invalid shape")
                posts = payload.get("posts", [])
                if not isinstance(posts, list):
                    raise ValueError("Bluesky response did not contain a posts list")
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({"query": query, "error": type(exc).__name__})
                continue

            fetched += len(posts)
            for item in posts:
                post = item.get("post", item) if isinstance(item, dict) else {}
                if not isinstance(post, dict):
                    invalid += 1
                    continue
                record_data = post.get("record") or {}
                if not isinstance(record_data, dict):
                    invalid += 1
                    continue
                uri = post.get("uri")
                text = record_data.get("text")
                author_data = post.get("author") or {}
                if not isinstance(author_data, dict):
                    author_data = {}
                published = parse_datetime(record_data.get("createdAt") or post.get("indexedAt"))
                if not isinstance(uri, str) or not uri or not isinstance(text, str) or not text.strip() or not published:
                    invalid += 1
                    continue
                if published < cutoff or published > now + timedelta(minutes=5):
                    out_of_window += 1
                    continue
                direct_brand = mentions_tata_strive(text)
                thematic = bool(THEMATIC_TERMS.search(text))
                if not direct_brand and not (query_scope == "thematic" and thematic):
                    invalid += 1
                    continue
                if uri in seen:
                    duplicates += 1
                    continue
                seen.add(uri)
                existing = session.exec(select(SocialRecord.id).where(SocialRecord.source == "bluesky", SocialRecord.external_id == uri)).first()
                if existing:
                    duplicates += 1
                    continue

                handle = author_data.get("handle")
                rkey = uri.rsplit("/", 1)[-1]
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else None
                record = SocialRecord(
                    source="bluesky", record_type="social_post", external_id=uri,
                    monitoring_scope="brand" if direct_brand else "thematic",
                    query_provenance=f"bluesky:{query}",
                    text=text.strip(), url=url, author=handle or author_data.get("did"),
                    published_at=published,
                    like_count=_metric(post.get("likeCount")),
                    reply_count=_metric(post.get("replyCount")),
                    raw_json=json.dumps(post, ensure_ascii=False),
                )
                prepare_record(session, record)
                session.add(record)
                inserted += 1

    if errors and not fetched:
        raise RuntimeError("All Bluesky searches failed")
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"source": "bluesky", "status": "partial" if errors else "success", "window_days": days,
            "queries_attempted": len(query_jobs), "brand_queries": BRAND_QUERIES,
            "thematic_queries": THEMATIC_QUERIES, "posts_fetched": fetched, "inserted": inserted,
            "duplicates": duplicates, "invalid": invalid, "out_of_window": out_of_window, "errors": errors}


def _metric(value):
    return value if isinstance(value, int) and value >= 0 else None
