"""Strict shared match for content that explicitly names Tata STRIVE."""
import re


_TATA_STRIVE = re.compile(r"\btata[\s\-‐‑‒–—]+strive\b|#tatastrive\b", re.IGNORECASE)


def mentions_tata_strive(text: str | None) -> bool:
    return bool(text and _TATA_STRIVE.search(text.replace("\u00a0", " ")))


def headline_is_tata_strive_focused(text: str | None) -> bool:
    """Reject articles that only mention the company incidentally near the end."""
    if not text:
        return False
    match = _TATA_STRIVE.search(text.replace("\u00a0", " "))
    return bool(match and match.start() <= 20)
