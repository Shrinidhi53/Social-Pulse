"""Shared normalization, language hints, and provenance-aware duplicate linking."""
from difflib import SequenceMatcher
import hashlib
import html
import re
import unicodedata

from sqlmodel import Session, select

from app.models import SocialRecord

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_SCRIPT_LANGUAGES = (
    ("hi", (0x0900, 0x097F)), ("bn", (0x0980, 0x09FF)),
    ("pa", (0x0A00, 0x0A7F)), ("gu", (0x0A80, 0x0AFF)),
    ("or", (0x0B00, 0x0B7F)), ("ta", (0x0B80, 0x0BFF)),
    ("te", (0x0C00, 0x0C7F)), ("kn", (0x0C80, 0x0CFF)),
    ("ml", (0x0D00, 0x0D7F)), ("si", (0x0D80, 0x0DFF)),
)
_ENGLISH_HINTS = {"the", "and", "is", "are", "for", "with", "how", "what", "course", "training", "skills", "job", "please", "where", "when"}


def normalize_text(text: str) -> str:
    """Canonicalize content for matching without changing the stored source text."""
    value = unicodedata.normalize("NFKC", html.unescape(text or "")).casefold()
    value = _URL.sub(" ", value)
    value = value.replace("&", " and ")
    value = " ".join(_TOKEN.findall(value))
    return _SPACE.sub(" ", value).strip()


def detect_language_hint(text: str) -> tuple[str, str]:
    """Return a conservative language hint; never claim unsupported certainty."""
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 8:
        return "und", "insufficient_text"
    for code, (start, end) in _SCRIPT_LANGUAGES:
        if sum(start <= ord(char) <= end for char in letters) >= max(3, len(letters) * 0.18):
            return code, "unicode_script_heuristic"
    if all(ord(char) < 128 for char in letters):
        words = set(re.findall(r"[a-z]+", text.casefold()))
        if len(words & _ENGLISH_HINTS) >= 2:
            return "en", "common_word_heuristic"
    return "und", "uncertain_heuristic"


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence_score = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return max(token_score, sequence_score if min(len(left), len(right)) >= 60 else 0.0)


def prepare_record(session: Session, record: SocialRecord, candidate_records: list[SocialRecord] | None = None) -> dict:
    """Attach derived quality metadata and link a likely duplicate, preserving both rows."""
    canonical = normalize_text(record.text)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else None
    language, language_method = detect_language_hint(record.text)
    record.normalized_text = canonical
    record.content_hash = digest
    record.language_code = language
    record.language_method = language_method
    record.is_simulated = record.is_simulated or record.source.casefold() in {"demo", "simulated", "sample_data"}
    if record.is_simulated and not record.provenance_note:
        record.provenance_note = "Simulated or sample record; not collected from a live public source."
    if record.duplicate_review_state == "confirmed_distinct":
        record.duplicate_of_record_id = None
        record.duplicate_match_score = None
        record.duplicate_match_type = None
        return {"language_code": language, "language_method": language_method,
                "duplicate_of_record_id": None, "duplicate_match_score": None,
                "is_simulated": record.is_simulated}

    # Deliberately cap the scan for a small local app. Exact hashes are cheap;
    # near-duplicate matching avoids comparing very short or unrelated record types.
    candidates = candidate_records if candidate_records is not None else session.exec(select(SocialRecord).where(
        SocialRecord.record_type == record.record_type,
    ).order_by(SocialRecord.collected_at.desc()).limit(3000)).all()
    best: tuple[float, SocialRecord] | None = None
    for candidate in candidates:
        if record.id is not None and candidate.id == record.id:
            continue
        candidate_text = candidate.normalized_text or normalize_text(candidate.text)
        if digest and candidate.content_hash == digest or canonical and candidate_text == canonical:
            score = 1.0
        elif min(len(canonical), len(candidate_text)) >= 50:
            score = _similarity(canonical, candidate_text)
            if score < 0.9:
                continue
        else:
            continue
        if best is None or score > best[0]:
            best = (score, candidate)
    if best:
        record.duplicate_of_record_id = best[1].duplicate_of_record_id or best[1].id
        record.duplicate_match_score = round(best[0], 4)
        record.duplicate_match_type = "exact_text" if best[0] == 1 else "near_text"
    else:
        record.duplicate_of_record_id = None
        record.duplicate_match_score = None
        record.duplicate_match_type = None
    return {"language_code": language, "language_method": language_method,
            "duplicate_of_record_id": record.duplicate_of_record_id,
            "duplicate_match_score": record.duplicate_match_score,
            "is_simulated": record.is_simulated}
