"""Google Programmable Search discovery; stores search previews, never full posts."""
import json
import os
import time
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.brand_filter import mentions_tata_strive
from app.data_quality import prepare_record
from app.models import SocialRecord

load_dotenv()

SEARCH_URL = "https://customsearch.googleapis.com/customsearch/v1"
DEFAULT_QUERIES = [
    '"Tata STRIVE" site:reddit.com',
    '"Tata STRIVE" site:x.com OR site:twitter.com',
    '"Tata STRIVE" site:threads.net',
    '"Tata STRIVE" site:instagram.com',
    '"Tata STRIVE" site:linkedin.com',
    '"Tata STRIVE" site:youtube.com',
    '"Tata STRIVE" site:bsky.app',
    '"#tatastrive"',
]


def _queries() -> list[str]:
    configured = os.getenv("GOOGLE_SEARCH_QUERIES", "").strip()
    queries = [item.strip() for item in configured.split(";") if item.strip()] if configured else DEFAULT_QUERIES
    return queries[:10]


def _valid_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.casefold().removeprefix("www.")
        allowed = ("reddit.com", "x.com", "twitter.com", "threads.net", "instagram.com",
                   "linkedin.com", "youtube.com", "youtu.be", "bsky.app")
        if not any(host == domain or host.endswith(f".{domain}") for domain in allowed):
            return None
        return value.split("#", 1)[0]
    except (TypeError, ValueError):
        return None


def collect_google_custom_search(session: Session) -> dict:
    load_dotenv()
    enabled = os.getenv("GOOGLE_SEARCH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"source": "google_custom_search", "status": "disabled", "inserted": 0,
                "content_note": "Google Custom Search is disabled by configuration."}
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_CX", "").strip()
    if not api_key or not cx:
        raise RuntimeError("Google Custom Search requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX.")

    max_results = max(1, min(10, int(os.getenv("GOOGLE_SEARCH_MAX_RESULTS_PER_QUERY", "10"))))
    delay = max(0.0, min(60.0, float(os.getenv("GOOGLE_SEARCH_DELAY_SECONDS", "1"))))
    queries = _queries()
    fetched = inserted = duplicates = invalid = 0
    errors: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(timeout=httpx.Timeout(30, connect=5)) as client:
        for index, query in enumerate(queries):
            if index and delay:
                time.sleep(delay)
            try:
                response = client.get(SEARCH_URL, params={
                    "key": api_key, "cx": cx, "q": query, "num": max_results,
                    "hl": "en", "gl": "in",
                })
                response.raise_for_status()
                payload = response.json()
                results = payload.get("items", []) if isinstance(payload, dict) else []
                if not isinstance(results, list):
                    raise ValueError("Google Custom Search returned an invalid results shape")
            except (httpx.HTTPError, ValueError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                errors.append({"query": query, "error": type(exc).__name__, "status_code": status})
                continue
            fetched += len(results)
            for item in results:
                if not isinstance(item, dict):
                    invalid += 1
                    continue
                url = _valid_url(item.get("link"))
                title = item.get("title") if isinstance(item.get("title"), str) else ""
                snippet = item.get("snippet") if isinstance(item.get("snippet"), str) else ""
                if not url or not (title.strip() or snippet.strip()) or not mentions_tata_strive(f"{title} {snippet}"):
                    invalid += 1
                    continue
                if url in seen or session.exec(select(SocialRecord.id).where(
                    SocialRecord.source == "google_custom_search", SocialRecord.external_id == url,
                )).first():
                    duplicates += 1
                    continue
                seen.add(url)
                record = SocialRecord(
                    source="google_custom_search", record_type="search_result", external_id=url,
                    text="\n\n".join(part.strip() for part in (title, snippet) if part.strip()),
                    url=url, author=urlsplit(url).hostname,
                    raw_json=json.dumps({"query": query, "title": title, "snippet": snippet}, ensure_ascii=False),
                )
                prepare_record(session, record)
                session.add(record)
                inserted += 1
    if errors and not fetched:
        statuses = sorted({str(item["status_code"]) for item in errors if item.get("status_code")})
        suffix = f" (HTTP {', '.join(statuses)})" if statuses else ""
        raise RuntimeError(f"All Google Custom Search requests failed{suffix}")
    session.commit()
    return {"source": "google_custom_search", "status": "partial" if errors else "success",
            "queries_attempted": len(queries), "results_fetched": fetched, "inserted": inserted,
            "duplicates": duplicates, "invalid": invalid, "errors": errors,
            "max_results_per_query": max_results,
            "content_note": "Search titles/snippets are discovery evidence, not full platform posts or comments."}
