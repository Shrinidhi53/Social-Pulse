
import json
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.brand_filter import headline_is_tata_strive_focused
from app.data_quality import prepare_record
from app.models import SocialRecord

load_dotenv()

GNEWS_API_URL = "https://gnews.io/api/v4/search"
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

# Exact brand-specific search, restricted to article headlines.
GNEWS_QUERY = '"Tata STRIVE"'
GNEWS_MAX_RESULTS = 10
REQUEST_TIMEOUT = 20.0


def contains_tata_strive(title: str | None, description: str | None) -> bool:
    """
    Accept only a Tata STRIVE mention in the headline. Description-only
    mentions can be incidental references to unrelated news.
    """
    return headline_is_tata_strive_focused(title)



from datetime import datetime, timezone


def parse_published_at(value: str | None) -> datetime | None:
    """Parse a publication timestamp and always return timezone-aware UTC."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            # GNews timestamps should include a timezone. If they don't,
            # treat the timestamp as UTC rather than local computer time.
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def collect_gnews(session: Session) -> dict[str, Any]:
    """
    Fetch GNews articles, accept only verified brand mentions,
    and insert new records into the existing social_records table.
    """
    if not GNEWS_API_KEY:
        raise RuntimeError(
            "GNEWS_API_KEY is missing. Add it to backend/.env "
            "and restart the backend."
        )

    params = {
        "q": GNEWS_QUERY,
        "lang": "en",
        "country": "in",
        "in": "title",
        "max": GNEWS_MAX_RESULTS,
        "sortby": "publishedAt",
        "apikey": GNEWS_API_KEY,
    }

    try:
        response = httpx.get(
            GNEWS_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("GNews returned an invalid response shape")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        if status_code == 401:
            raise RuntimeError(
                "GNews rejected the API key. Check GNEWS_API_KEY."
            ) from exc

        if status_code == 403:
            raise RuntimeError(
                "GNews access denied. Check API plan, permissions, "
                "and request limits."
            ) from exc

        if status_code == 429:
            raise RuntimeError(
                "GNews rate limit or quota reached. Try again later."
            ) from exc

        raise RuntimeError(
            f"GNews returned HTTP {status_code}."
        ) from exc

    except httpx.RequestError as exc:
        raise RuntimeError(
            f"Could not connect to GNews: {exc}"
        ) from exc

    except ValueError as exc:
        raise RuntimeError(
            "GNews returned an invalid JSON response."
        ) from exc

    articles = payload.get("articles", [])

    if not isinstance(articles, list):
        raise RuntimeError(
            "GNews response did not contain a valid articles list."
        )

    fetched = len(articles)
    accepted = 0
    rejected = 0
    inserted = 0
    duplicates = 0
    rejected_samples: list[str] = []

    for article in articles:
        if not isinstance(article, dict):
            rejected += 1
            continue

        title_value = article.get("title")
        description_value = article.get("description")
        url_value = article.get("url")
        title = title_value.strip() if isinstance(title_value, str) else ""
        description = description_value.strip() if isinstance(description_value, str) else ""
        article_url = url_value.strip() if isinstance(url_value, str) else ""

        # Reject incomplete articles and results without an explicit URL.
        if not _safe_http_url(article_url) or not (title or description):
            rejected += 1
            if len(rejected_samples) < 5:
                rejected_samples.append(title or "[Missing title]")
            continue

        # Critical relevance gate: generic industry articles are rejected.
        if not contains_tata_strive(title, description):
            rejected += 1

            if len(rejected_samples) < 5:
                rejected_samples.append(title or "[Missing title]")

            continue

        article_url = article_url.split("#", 1)[0]
        accepted += 1

        existing = session.exec(
            select(SocialRecord).where(
                SocialRecord.source == "gnews",
                SocialRecord.external_id == article_url,
            )
        ).first()

        if existing:
            duplicates += 1
            continue

        source_info = article.get("source") or {}
        publisher = (
            source_info.get("name", "Unknown publisher")
            if isinstance(source_info, dict)
            else "Unknown publisher"
        )

        text_parts = [part for part in (title, description) if part]
        article_text = "\n\n".join(text_parts)

        record = SocialRecord(
            source="gnews",
            record_type="news",
            external_id=article_url,
            text=article_text,
            url=article_url,
            author=publisher,
            published_at=parse_published_at(
                article.get("publishedAt")
            ),
            raw_json=json.dumps(article, ensure_ascii=False),
        )

        prepare_record(session, record)
        session.add(record)
        inserted += 1

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "source": "gnews",
        "query": GNEWS_QUERY,
        "fetched": fetched,
        "accepted_as_brand_relevant": accepted,
        "rejected_as_unrelated": rejected,
        "inserted": inserted,
        "duplicates_skipped": duplicates,
        "rejected_title_samples": rejected_samples,
    }


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (TypeError, ValueError):
        return False
