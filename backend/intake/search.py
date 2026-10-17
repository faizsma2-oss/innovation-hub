"""Searching what already exists: the solutions catalog and earlier submissions.

This is simple keyword matching. A later milestone can replace it with smarter search
(full-text or embeddings) without changing the workflow that calls it.
"""
import re

from .. import db

STOPWORDS = set("""
the and for are but not you all any can had has have this that with from they them there their
what when which who will would could should into than then some very just also about because
been being does doing each few more most other over same such only own too under until while
where why how its our ours use get got make lot lots much many time takes take spend really
often always never every our we us my me your it is was were be to of in on at by an or as so
""".split())


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {stem(word) for word in words if len(word) > 2 and word not in STOPWORDS}


def find_solution(conn, text: str) -> dict | None:
    """Return the catalog entry whose keywords appear most in the text, if any."""
    lowered = (text or "").lower()
    best, best_hits = None, 0
    for row in conn.execute("SELECT * FROM solutions"):
        hits = sum(1 for keyword in row["keywords"].split(",") if keyword in lowered)
        if hits > best_hits:
            best, best_hits = dict(row), hits
    return best


def find_similar_submission(conn, text: str, exclude_pk: int | None = None) -> dict | None:
    """Return the open submission that shares the most meaningful words with the text."""
    wanted = tokens(text)
    best, best_overlap = None, 0
    for row in conn.execute("SELECT * FROM submissions WHERE status != 'Declined' AND pk != ?", (exclude_pk or 0,)):
        existing = tokens(f"{row['title']} {row['description']}")
        overlap = len(wanted & existing)
        # At least 3 shared words, covering at least 30% of the existing request.
        if overlap >= 3 and overlap / max(len(existing), 1) >= 0.3 and overlap > best_overlap:
            best, best_overlap = db.to_public(row), overlap
    return best
