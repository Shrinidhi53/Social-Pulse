"""Google search discovery through SerpApi; snippets are not platform comments."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.brand_filter import mentions_tata_strive
from app.data_quality import prepare_record
from app.models import CollectionRun, SocialRecord

load_dotenv()

SEARCH_URL = "https://serpapi.com/search.json"
DEFAULT_QUERIES = [
    '"Tata STRIVE"',
    '"Tata STRIVE" site:instagram.com',
    '"Tata STRIVE" site:linkedin.com',
    '"Tata STRIVE" site:reddit.com',
    '"Tata STRIVE" site:youtube.com',
    '"Tata STRIVE" site:bsky.app',
    '"Tata STRIVE" site:x.com OR site:twitter.com',
    '"Tata STRIVE" site:threads.net',
    '"#tatastrive"',
]
DEFAULT_THEMATIC_QUERIES = [
    'site:linkedin.com/posts (student OR learner) (upskill OR upskilling OR "career skills") India',
    'site:linkedin.com/posts (NGO OR nonprofit OR foundation) (employability OR "skill development" OR "vocational training") India',
    'site:linkedin.com/posts (partnership OR collaboration OR CSR OR "seeking partners") (youth OR employability OR skilling) India',
    'site:reddit.com (student OR learner) (upskill OR "skill development" OR "vocational training") India',
]
_SKILLS_CONTEXT = re.compile(
    r"\b(upskill(?:ing)?|reskill(?:ing)?|skill development|skilling|vocational training|"
    r"employability|job readiness|youth employment|career skills|workforce development|"
    r"apprenticeship|livelihood training|digital skills)\b", re.I)
_LEARNER_CONTEXT = re.compile(
    r"\b(student|learner|upskill|reskill|job seeker|looking to learn|looking for training|"
    r"want to learn|seeking training|career change)\b", re.I)
_ORGANIZATION_CONTEXT = re.compile(
    r"\b(ngo|non.?profit|foundation|social enterprise|training provider|university|college|"
    r"csr|employer|company|organization|organisation|partner|partnership|collaborat|"
    r"initiative|programme|program)\b", re.I)


def _explicit_brand_match(value: str) -> bool:
    return mentions_tata_strive(value)


def _queries() -> list[str]:
    configured = os.getenv("SERPAPI_QUERIES", "").strip()
    queries = [item.strip() for item in configured.split(";") if item.strip()] if configured else DEFAULT_QUERIES
    return queries[:10]


def _thematic_queries() -> list[str]:
    configured = os.getenv("SERPAPI_THEMATIC_QUERIES", "").strip()
    queries = [item.strip() for item in configured.split(";") if item.strip()] if configured else DEFAULT_THEMATIC_QUERIES
    return queries[:8]


def _thematic_signal_kind(text: str) -> str | None:
    if not _SKILLS_CONTEXT.search(text):
        return None
    if _ORGANIZATION_CONTEXT.search(text):
        return "organization_or_ecosystem_activity"
    if _LEARNER_CONTEXT.search(text):
        return "learner_upskilling_interest"
    return "skills_ecosystem_context"


def _safe_result_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        # Do not store Google redirect URLs. Search results are never fetched here.
        host = parsed.hostname.casefold().removeprefix("www.")
        if host == "google.com" or host.endswith(".google.com"):
            return None
        return value.split("#", 1)[0]
    except (TypeError, ValueError):
        return None


def collect_serpapi(session: Session, thematic_only: bool = False, force_thematic: bool = False) -> dict:
    # Read newly added .env values even when this module was imported before configuration.
    load_dotenv()
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if os.getenv("SERPAPI_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"source": "google_search", "status": "disabled", "inserted": 0,
                "content_note": "SerpApi discovery is disabled by configuration."}
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is missing. Add it to backend/.env and restart the backend.")

    query_jobs = [] if thematic_only else [(query, "brand") for query in _queries()]
    thematic_enabled = os.getenv("SERPAPI_THEMATIC_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    thematic_interval_hours = max(0, min(168, int(os.getenv("SERPAPI_THEMATIC_INTERVAL_HOURS", "12"))))
    if thematic_only and not thematic_enabled:
        return {"source": "google_search_thematic", "status": "disabled", "inserted": 0,
                "content_note": "Thematic SerpApi discovery is disabled by configuration."}
    last_thematic_run = session.exec(select(CollectionRun).where(
        CollectionRun.source == "google_search_thematic"
    ).order_by(CollectionRun.completed_at.desc())).first()
    last_thematic_at = last_thematic_run.completed_at if last_thematic_run else None
    if last_thematic_at and last_thematic_at.tzinfo is None:
        last_thematic_at = last_thematic_at.replace(tzinfo=timezone.utc)
    thematic_due = (force_thematic or thematic_interval_hours == 0 or last_thematic_at is None
                    or last_thematic_at <= datetime.now(timezone.utc) - timedelta(hours=thematic_interval_hours))
    if thematic_enabled and thematic_due:
        query_jobs.extend((query, "thematic") for query in _thematic_queries())
    max_results = max(1, min(10, int(os.getenv("SERPAPI_MAX_RESULTS_PER_QUERY", "10"))))
    delay = max(0.0, min(60.0, float(os.getenv("GOOGLE_SEARCH_DELAY_SECONDS", "1"))))
    fetched = inserted = duplicates = invalid = thematic_inserted = 0
    errors: list[dict] = []
    seen: set[str] = set()

    with httpx.Client(timeout=httpx.Timeout(45, connect=5)) as client:
        for query_index, (query, query_scope) in enumerate(query_jobs):
            if query_index and delay:
                time.sleep(delay)
            results = None
            last_error = None
            for attempt in range(2):
                try:
                    response = client.get(SEARCH_URL, params={
                        "engine": "google", "q": query, "api_key": api_key,
                        "hl": "en", "gl": "in", "num": max_results,
                    })
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("SerpApi returned an invalid response shape")
                    if payload.get("error"):
                        raise RuntimeError("SerpApi reported a search error")
                    results = payload.get("organic_results", [])
                    if not isinstance(results, list):
                        raise ValueError("SerpApi response did not contain organic results")
                    break
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    last_error = exc
            if results is None:
                status_code = getattr(getattr(last_error, "response", None), "status_code", None)
                errors.append({"query": query, "error": type(last_error).__name__, "status_code": status_code})
                continue

            fetched += len(results)
            for item in results:
                if not isinstance(item, dict):
                    invalid += 1
                    continue
                url = _safe_result_url(item.get("link"))
                title = item.get("title") if isinstance(item.get("title"), str) else ""
                snippet = item.get("snippet") if isinstance(item.get("snippet"), str) else ""
                if not url or not (title.strip() or snippet.strip()):
                    invalid += 1
                    continue
                visible_text = f"{title} {snippet}".strip()
                direct_brand = _explicit_brand_match(visible_text)
                signal_kind = _thematic_signal_kind(visible_text) if query_scope == "thematic" else None
                # Branded queries need an explicit brand match. Thematic queries
                # retain only visible skills signals and are tagged separately.
                if (query_scope == "brand" and not direct_brand) or (query_scope == "thematic" and not signal_kind):
                    invalid += 1
                    continue
                if url in seen:
                    duplicates += 1
                    continue
                seen.add(url)
                exists = session.exec(select(SocialRecord.id).where(
                    SocialRecord.source == "google_search", SocialRecord.external_id == url,
                )).first()
                if exists:
                    duplicates += 1
                    continue

                text = "\n\n".join(part.strip() for part in (title, snippet) if part.strip())
                record = SocialRecord(
                    source="google_search", record_type="search_result", external_id=url,
                    text=text, url=url, author=urlsplit(url).hostname,
                    monitoring_scope="brand" if direct_brand else "thematic",
                    query_provenance=f"serpapi:{query_scope}:{query}",
                    # Search result dates are omitted unless a source-specific collector supplies one.
                    raw_json=json.dumps({"query": query, "query_scope": query_scope,
                                         "discovery_type": "direct_brand" if direct_brand else signal_kind,
                                         "evidence_limit": "search title/snippet only; review the original page",
                                         "result": item}, ensure_ascii=False),
                )
                prepare_record(session, record)
                session.add(record)
                inserted += 1
                thematic_inserted += int(query_scope == "thematic" and not direct_brand)

    if errors and not fetched:
        statuses = sorted({str(item["status_code"]) for item in errors if item.get("status_code")})
        suffix = f" (HTTP {', '.join(statuses)})" if statuses else ""
        raise RuntimeError(f"All SerpApi searches failed{suffix}")
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"source": "google_search_thematic" if thematic_only else "google_search", "status": "partial" if errors else "success",
            "queries_attempted": len(query_jobs), "brand_queries_attempted": len(_queries()),
            "thematic_queries_attempted": len(_thematic_queries()) if thematic_enabled and thematic_due else 0,
            "thematic_skipped_recently": bool(thematic_enabled and not thematic_due),
            "thematic_interval_hours": thematic_interval_hours,
            "thematic_next_fetch_after": (last_thematic_at + timedelta(hours=thematic_interval_hours)).isoformat() if thematic_enabled and not thematic_due and last_thematic_at else None,
            "results_fetched": fetched, "inserted": inserted, "thematic_inserted": thematic_inserted,
            "duplicates": duplicates, "invalid": invalid, "errors": errors,
            "max_results_per_query": max_results,
            "content_note": "Google titles/snippets are discovery evidence, not full platform comments."}
