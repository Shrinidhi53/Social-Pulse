"""Discover brand-related videos across channels and collect substantive mentions."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.brand_filter import mentions_tata_strive
from app.data_quality import prepare_record
from app.models import CollectionRun, SocialRecord

load_dotenv()

BASE_URL = "https://www.googleapis.com/youtube/v3"
SEARCH_TERMS = ('Tata STRIVE', '#tatastrive')
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeAPIError(RuntimeError):
    """Sanitized YouTube API failure with structured status and reason fields."""

    def __init__(self, endpoint: str, status_code: int, reason: str | None, message: str | None):
        self.endpoint = endpoint
        self.status_code = status_code
        self.reason = reason
        detail = f" ({reason})" if reason else ""
        if isinstance(message, str) and message.strip():
            detail += f": {message.strip()[:180]}"
        super().__init__(f"YouTube {endpoint} request failed with HTTP {status_code}{detail}")


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def to_int(value):
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def fetch_json(client, endpoint, params):
    response = client.get(f"{BASE_URL}/{endpoint}", params=params)
    if response.is_error:
        # Do not bubble up httpx's request URL: it contains the API key.
        try:
            error = response.json().get("error", {})
            reasons = error.get("errors", [])
            reason = next((item.get("reason") for item in reasons if isinstance(item, dict) and item.get("reason")), None)
            message = error.get("message")
        except (ValueError, AttributeError):
            reason = None
            message = None
        raise YouTubeAPIError(endpoint, response.status_code, reason, message)
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"YouTube {endpoint} returned an invalid response")
    return payload


def _is_quota_error(exc: YouTubeAPIError) -> bool:
    """Quota failures must stop collection instead of looking like disabled comments."""
    return exc.status_code == 403 and exc.reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


def is_substantive_brand_comment(text: str | None) -> bool:
    """Ignore emoji-only/boilerplate matches; require brand plus a word of substance."""
    if not mentions_tata_strive(text):
        return False
    remainder = re.sub(r"#?tata[\s\-‐‑‒–—]*strive", " ", text or "", flags=re.IGNORECASE)
    words = [word for word in re.findall(r"[a-zA-Z]{3,}", remainder) if word.casefold() not in {"http", "https", "www"}]
    return bool(words)


def _video_id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().removeprefix("www.").removeprefix("m.")
        video_id = None
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif host.endswith("youtube.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            else:
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                    video_id = parts[1]
        return video_id if isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id) else None
    except (TypeError, ValueError):
        return None


def _google_video_candidate_evidence(session: Session) -> dict[str, str]:
    candidates: dict[str, str] = {}
    records = session.exec(select(SocialRecord).where(SocialRecord.source == "google_search")).all()
    for record in records:
        try:
            result = json.loads(record.raw_json or "{}").get("result", {})
        except (ValueError, TypeError):
            continue
        video_id = _video_id_from_url(result.get("link") if isinstance(result, dict) else None)
        visible_text = f"{record.text} {result.get('title', '')} {result.get('snippet', '')}" if isinstance(result, dict) else record.text
        if video_id and mentions_tata_strive(visible_text):
            candidates[video_id] = visible_text.strip()
    return candidates


def _google_video_candidates(session: Session) -> set[str]:
    """Compatibility helper used by tests and callers interested in IDs only."""
    return set(_google_video_candidate_evidence(session))


def _search_video_ids(client, api_key: str, page_limit: int) -> tuple[list[str], int]:
    video_ids: list[str] = []
    seen: set[str] = set()
    pages_fetched = 0
    for term in SEARCH_TERMS:
        page_token = None
        for _ in range(page_limit):
            params = {
                "part": "snippet", "q": f'"{term}"', "type": "video",
                "maxResults": 50, "order": "relevance", "relevanceLanguage": "en",
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = fetch_json(client, "search", params)
            pages_fetched += 1
            for item in payload.get("items", []):
                video_id = item.get("id", {}).get("videoId") if isinstance(item, dict) and isinstance(item.get("id"), dict) else None
                if isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id) and video_id not in seen:
                    seen.add(video_id)
                    video_ids.append(video_id)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    return video_ids, pages_fetched


def _video_details(client, api_key: str, video_ids: list[str]) -> dict[str, dict]:
    videos = {}
    for start in range(0, len(video_ids), 50):
        payload = fetch_json(client, "videos", {
            "part": "snippet,statistics", "id": ",".join(video_ids[start:start + 50]), "key": api_key,
        })
        for item in payload.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                videos[item["id"]] = item
    return videos


def _save_record(session: Session, record: SocialRecord) -> bool:
    existing = session.exec(select(SocialRecord.id).where(
        SocialRecord.source == record.source, SocialRecord.external_id == record.external_id,
    )).first()
    if existing:
        return False
    prepare_record(session, record)
    session.add(record)
    return True


def _save_comment(session: Session, comment: dict, video_id: str, video: dict) -> bool:
    snippet = comment.get("snippet", {})
    comment_id = comment.get("id")
    text = snippet.get("textDisplay") if isinstance(snippet, dict) else None
    if not isinstance(comment_id, str) or not is_substantive_brand_comment(text):
        return False
    video_snippet = video.get("snippet", {})
    title = video_snippet.get("title", "YouTube video") if isinstance(video_snippet, dict) else "YouTube video"
    record = SocialRecord(
        source="youtube", record_type="comment", external_id=f"comment:{comment_id}",
        text=text.strip(), url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
        author=snippet.get("authorDisplayName") if isinstance(snippet, dict) else None,
        published_at=parse_datetime(snippet.get("publishedAt") if isinstance(snippet, dict) else None),
        like_count=to_int(snippet.get("likeCount") if isinstance(snippet, dict) else None),
        reply_count=to_int(comment.get("snippet", {}).get("totalReplyCount")) if isinstance(comment.get("snippet"), dict) else None,
        raw_json=json.dumps({"comment": comment, "video_id": video_id, "video_title": title,
                             "video_channel": video_snippet.get("channelTitle") if isinstance(video_snippet, dict) else None,
                             "video_url": f"https://www.youtube.com/watch?v={video_id}"}, ensure_ascii=False),
    )
    return _save_record(session, record)


def _fetch_matching_comments(client, api_key: str, video_id: str, video: dict, session: Session, counters: dict):
    page_token = None
    while True:
        # YouTube only permits searchTerms with allThreadsRelatedToChannelId,
        # not with videoId. Fetch this video's pages and exact-filter comments here.
        params = {
            "part": "snippet,replies", "videoId": video_id,
            "maxResults": 100, "textFormat": "plainText", "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            payload = fetch_json(client, "commentThreads", params)
        except YouTubeAPIError as exc:
            if _is_quota_error(exc):
                raise RuntimeError("YouTube API quota exceeded while fetching comments") from exc
            if exc.reason == "commentsDisabled":
                counters["videos_comments_disabled"] += 1
                counters["comments_unavailable"] += 1
                break
            if exc.status_code in {403, 404}:
                counters["comments_unavailable"] += 1
                break
            raise
        counters["comment_pages"] += 1
        for thread in payload.get("items", []):
            if not isinstance(thread, dict):
                continue
            thread_snippet = thread.get("snippet", {})
            if not isinstance(thread_snippet, dict):
                continue
            top = thread_snippet.get("topLevelComment")
            if isinstance(top, dict):
                counters["comments_fetched"] += 1
                if _save_comment(session, top, video_id, video):
                    counters["comments_saved"] += 1
            thread_id = thread.get("id")
            if isinstance(thread_id, str):
                counters["threads_seen"].add(thread_id)
            replies = thread.get("replies", {}).get("comments", []) if isinstance(thread.get("replies"), dict) else []
            for reply in replies:
                if isinstance(reply, dict):
                    counters["comments_fetched"] += 1
                    if _save_comment(session, reply, video_id, video):
                        counters["comments_saved"] += 1
            top_id = thread_snippet.get("topLevelComment", {}).get("id") if isinstance(thread_snippet.get("topLevelComment"), dict) else None
            total_replies = to_int(thread_snippet.get("totalReplyCount")) or 0
            if isinstance(top_id, str) and total_replies > len(replies):
                reply_token = None
                while True:
                    reply_params = {"part": "snippet", "parentId": top_id, "maxResults": 100,
                                    "textFormat": "plainText", "key": api_key}
                    if reply_token:
                        reply_params["pageToken"] = reply_token
                    try:
                        reply_payload = fetch_json(client, "comments", reply_params)
                    except YouTubeAPIError as exc:
                        if _is_quota_error(exc):
                            raise RuntimeError("YouTube API quota exceeded while fetching replies") from exc
                        if exc.reason == "commentsDisabled":
                            counters["videos_comments_disabled"] += 1
                            counters["comments_unavailable"] += 1
                            break
                        if exc.status_code in {403, 404}:
                            counters["comments_unavailable"] += 1
                            break
                        raise
                    counters["comment_pages"] += 1
                    for reply in reply_payload.get("items", []):
                        if isinstance(reply, dict):
                            counters["comments_fetched"] += 1
                            if _save_comment(session, reply, video_id, video):
                                counters["comments_saved"] += 1
                    reply_token = reply_payload.get("nextPageToken")
                    if not reply_token:
                        break
        page_token = payload.get("nextPageToken")
        if not page_token:
            break


def collect_youtube(session: Session) -> dict:
    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is missing from .env")
    page_limit = max(1, min(int(os.getenv("YOUTUBE_MAX_SEARCH_PAGES", "1")), 20))
    counters = {"comment_pages": 0, "comments_fetched": 0, "comments_saved": 0,
                "videos_comments_disabled": 0,
                "comments_unavailable": 0, "matching_videos": 0, "threads_seen": set()}
    google_candidates = _google_video_candidate_evidence(session)
    google_video_ids = set(google_candidates)

    search_interval_hours = max(0, min(int(os.getenv("YOUTUBE_SEARCH_INTERVAL_HOURS", "6")), 168))
    last_search = session.exec(
        select(CollectionRun)
        .where(CollectionRun.source == "youtube")
        .order_by(CollectionRun.completed_at.desc())
    ).first()
    last_search_at = last_search.completed_at if last_search else None
    if last_search_at and last_search_at.tzinfo is None:
        last_search_at = last_search_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    search_due = (
        search_interval_hours == 0
        or last_search_at is None
        or last_search_at <= now - timedelta(hours=search_interval_hours)
    )
    # search.list costs 100 quota units per page. The UI refreshes every 30 minutes,
    # so throttle discovery and continue checking known/Google-discovered videos meanwhile.
    known_video_ids = set()
    for record in session.exec(select(SocialRecord).where(SocialRecord.source == "youtube")).all():
        try:
            raw = json.loads(record.raw_json or "{}")
            video_id = raw.get("video_id")
            if isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id):
                known_video_ids.add(video_id)
        except (ValueError, TypeError):
            continue

    with httpx.Client(timeout=httpx.Timeout(40, connect=5)) as client:
        searched_ids, search_pages = _search_video_ids(client, api_key, page_limit) if search_due else ([], 0)
        video_ids = list(dict.fromkeys([*searched_ids, *sorted(google_video_ids), *sorted(known_video_ids)]))
        videos = _video_details(client, api_key, video_ids)
        for video_id in video_ids:
            video = videos.get(video_id)
            if not video:
                continue
            snippet = video.get("snippet", {})
            if not isinstance(snippet, dict):
                snippet = {}
            title = snippet.get("title")
            description = snippet.get("description")
            if not isinstance(title, str) or not title.strip():
                continue
            description = description.strip() if isinstance(description, str) else ""
            metadata_mentions_brand = mentions_tata_strive(f"{title} {description}")
            # A Google result can discover a video whose comment discusses Tata
            # STRIVE even when the uploader left the brand out of its metadata.
            # Comments still have to contain a substantive, exact brand mention.
            if not metadata_mentions_brand and video_id not in google_candidates:
                continue
            if metadata_mentions_brand:
                counters["matching_videos"] += 1
            _fetch_matching_comments(client, api_key, video_id, video, session, counters)

    session.commit()
    return {
        "source": "youtube", "search_queries": list(SEARCH_TERMS),
        "search_pages_fetched": search_pages, "video_search_page_limit_per_query": page_limit,
        "search_skipped_recently": not search_due,
        "next_search_after": (last_search_at + timedelta(hours=search_interval_hours)).isoformat() if not search_due and last_search_at else None,
        "videos_discovered_by_youtube_search": len(searched_ids),
        "additional_video_candidates_from_google": len(google_video_ids),
        "videos_examined": len(video_ids), "matching_videos": counters["matching_videos"],
        "comment_threads_seen": len(counters["threads_seen"]),
        "comments_fetched": counters["comments_fetched"], "comments_saved": counters["comments_saved"],
        "comments_unavailable": counters["comments_unavailable"],
        "videos_comments_disabled": counters["videos_comments_disabled"],
        "comment_pages_fetched": counters["comment_pages"],
        "content_note": "Public comments and replies mentioning Tata STRIVE are collected from matching videos across channels. YouTube does not expose global comment search; video search and Google-discovered video links are the candidate set.",
    }
