"""Searching what already exists: the solutions catalog (tools, guidance, active projects, lessons
from earlier pilots) and earlier submissions.

Full-text search with SQLite FTS5 and its Porter stemmer: words are compared by their stem, so
"combining", "combined" and "combine" match, and keyword phrases match in any word order. Similar
requests are weighted by how rare each shared word is, so telling words ("chiller", "permit") count
more than common ones ("week", "team"). Plain code: instant, free, the same answer every time.
"""
import math
import re
import sqlite3

from .. import db

STOPWORDS = set("""
the and for are but not you all any can had has have this that with from they them there their
what when which who will would could should into than then some very just also about because
been being does doing each few more most other over same such only own too under until while
where why how its our ours use get got make lot lots much many time takes take spend really
often always never every our we us my me your it is was were be to of in on at by an or as so
""".split()) | {
    # Workplace filler: in almost every complaint, so it says nothing about which problem this is.
    "must", "before", "after", "need", "needs", "people", "team", "staff", "day", "days", "week", "weeks",
}


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {stem(word) for word in words if len(word) > 2 and word not in STOPWORDS}


def stems(texts: dict) -> dict:
    """The Porter stems of each text, by key, using a throwaway in-memory FTS5 index."""
    memory = sqlite3.connect(":memory:")
    try:
        memory.execute("CREATE VIRTUAL TABLE docs USING fts5(body, tokenize='porter unicode61')")
        memory.execute("CREATE VIRTUAL TABLE terms USING fts5vocab(docs, 'instance')")
        keys = list(texts)
        memory.executemany("INSERT INTO docs (rowid, body) VALUES (?, ?)",
                           [(i + 1, meaningful(texts[key])) for i, key in enumerate(keys)])
        found = {key: set() for key in keys}
        for term, doc in memory.execute("SELECT term, doc FROM terms"):
            found[keys[doc - 1]].add(term)
        return found
    finally:
        memory.close()


def meaningful(text: str) -> str:
    """Drop short and very common words before indexing."""
    return " ".join(w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOPWORDS)


def find_solution(conn, text: str) -> dict | None:
    """The catalog entry with the most keyword phrases whose words all appear in the text (as stems,
    any order). Ties go to the entry whose matched phrases are longer, i.e. more specific."""
    rows = [dict(row) for row in conn.execute("SELECT * FROM solutions")]
    phrases = {(i, j): phrase for i, row in enumerate(rows) for j, phrase in enumerate(row["keywords"].split(","))}
    found = stems({"text": text} | phrases)
    words = found.pop("text")
    best, best_score = None, (0, 0)
    for i, row in enumerate(rows):
        matched = [found[key] for key in phrases if key[0] == i and found[key] and found[key] <= words]
        score = (len(matched), sum(len(m) for m in matched))
        if score > best_score:
            best, best_score = row, score
    return best


def find_similar_submission(conn, text: str, exclude_pk: int | None = None) -> dict | None:
    """The open submission sharing the most telling words with the text.
    A link needs at least 3 shared word stems covering at least 30% of the other request's words,
    each word weighted by how rare it is across all requests."""
    rows = conn.execute("SELECT * FROM submissions WHERE status NOT IN ('Declined', 'Stopped', 'In operation')"
                        " AND pk != ?", (exclude_pk or 0,)).fetchall()
    if not rows:
        return None
    # Closed or finished work isn't "being reviewed": it reaches new requests through its published lesson.
    found = stems({"text": text} | {row["pk"]: f"{row['title']} {row['description']}" for row in rows})
    wanted = found.pop("text")
    count = len(found)
    frequency = {}
    for terms in found.values():
        for term in terms:
            frequency[term] = frequency.get(term, 0) + 1
    weight = lambda term: math.log((count + 1) / (frequency.get(term, 0) + 1)) + 1
    best, best_score = None, 0.0
    for row in rows:
        existing = found[row["pk"]]
        shared = wanted & existing
        coverage = sum(weight(t) for t in shared) / max(sum(weight(t) for t in existing), 1e-9)
        if len(shared) >= 3 and coverage >= 0.3 and coverage > best_score:
            best, best_score = db.to_public(row), coverage
    return best
