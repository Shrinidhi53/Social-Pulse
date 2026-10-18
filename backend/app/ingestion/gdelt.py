
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from app.brand_filter import headline_is_tata_strive_focused
from app.data_quality import prepare_record
from app.models import SocialRecord

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def collect_gdelt(session: Session) -> dict:
    params = {
        "query": '"Tata STRIVE"',
        "mode": "artlist",
        "format": "json",
        "timespan": "7d",
        "maxrecords": 25,
        "sort": "datedesc",
    }

    with httpx.Client(timeout=40) as client:
        response = client.get(
            GDELT_URL,
            params=params,
            headers={"User-Agent": "SocialPulse/0.1"},
        )

    response.raise_for_status()

    # GDELT may return a plain-text error instead of JSON.
    try:
        data = response.json()
    except ValueError as exc:
        preview = response.text[:500]
        raise RuntimeError(
            f"GDELT returned a non-JSON response: {preview}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("GDELT returned an invalid response shape")

    articles = data.get("articles", [])
    if not isinstance(articles, list):
        raise RuntimeError("GDELT did not return a valid articles list")
    fetched = len(articles)
    saved = 0
    skipped = 0
    known_titles = {
        _normalize_title(title)
        for title in session.exec(
            select(SocialRecord.text)
            .where(SocialRecord.source == "gdelt")
            .order_by(SocialRecord.collected_at.desc())
            .limit(500)
        ).all()
        if isinstance(title, str) and title.strip()
    }

    for article in articles:
        if not isinstance(article, dict):
            skipped += 1
            continue
        url = article.get("url")
        title = article.get("title")

        if not _safe_http_url(url) or not isinstance(title, str) or not title.strip():
            skipped += 1
            continue
        if not headline_is_tata_strive_focused(title):
            skipped += 1
            continue

        normalized_title = _normalize_title(title)
        if any(SequenceMatcher(None, normalized_title, prior).ratio() >= 0.92 for prior in known_titles):
            skipped += 1
            continue

        url = url.split("#", 1)[0]
        existing = session.exec(
            select(SocialRecord).where(
                SocialRecord.source == "gdelt",
                SocialRecord.external_id == url,
            )
        ).first()

        if existing:
            skipped += 1
            continue

        domain = article.get("domain")

        record = SocialRecord(
            source="gdelt",
            record_type="news",
            external_id=url,
            text=title,
            url=url,
            author=domain,
            # GDELT's seendate is not necessarily the publication date.
            published_at=None,
            collected_at=datetime.now(timezone.utc),
            like_count=None,
            reply_count=None,
            view_count=None,
            raw_json=json.dumps(article, ensure_ascii=False),
        )

        prepare_record(session, record)
        session.add(record)
        known_titles.add(normalized_title)
        saved += 1

    session.commit()

    return {
        "source": "gdelt",
        "fetched": fetched,
        "saved": saved,
        "skipped": skipped,
    }


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (TypeError, ValueError):
        return False


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", value.casefold())).strip()
