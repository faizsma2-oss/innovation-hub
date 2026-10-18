"""The library: everything the Hub knows already exists, searchable by everyone.

Tools, guidance, active projects, earlier pilots and lessons published from the Hub's own requests
(the same catalog the intake chat checks). Search uses SQLite full-text search with word stems,
ranked by relevance (BM25), with the matching words marked. Searches that find nothing are counted:
they point at problems nobody has solved yet.
"""
import re
import sqlite3

from fastapi import APIRouter, Query

from .. import db
from ..intake.search import meaningful

router = APIRouter(tags=["library"])

KINDS = {"tool": "Tool", "guidance": "Guidance", "active_project": "Active project", "previous_pilot": "Earlier pilot"}
MARK_START, MARK_END = "\u0002", "\u0003"        # marks around matched words; the page turns them into <mark>


@router.get("/api/library")
def library(q: str = Query(default="", max_length=200), kind: str = "", team: bool = False):
    """team=true adds links to the Hub request a lesson came from (the team view only)."""
    with db.connect() as conn:
        entries = [dict(row) for row in conn.execute("SELECT * FROM solutions")]
        if kind:
            entries = [e for e in entries if e["kind"] == kind]
        terms = meaningful(q).split()
        results = ranked(entries, terms) if terms else sorted(entries, key=lambda e: (order(e), e["title"]))
        if terms:
            conn.execute("INSERT INTO library_searches (query, results, created_at) VALUES (?, ?, ?)",
                         (q.strip()[:200], len(results), db.now()))
    return {"query": q, "count": len(results), "kinds": KINDS,
            "results": [public(e, team) for e in results]}


def ranked(entries: list[dict], terms: list[str]) -> list[dict]:
    """BM25 relevance over title, summary and keywords, title weighted most. The how-to text is shown but
    not searched: it's instructions ("ask for read access"), not what the entry is about."""
    memory = sqlite3.connect(":memory:")
    try:
        memory.execute("CREATE VIRTUAL TABLE docs USING fts5(title, summary, keywords, how_to UNINDEXED, tokenize='porter unicode61')")
        memory.executemany("INSERT INTO docs (rowid, title, summary, keywords, how_to) VALUES (?, ?, ?, ?, ?)",
                           [(i + 1, e["title"], e["summary"], e["keywords"].replace(",", ", "), e["how_to"])
                            for i, e in enumerate(entries)])
        query = " OR ".join(f'"{t}"' for t in terms)          # quoted: search words, never FTS syntax
        rows = memory.execute(
            f"SELECT rowid, highlight(docs, 0, ?, ?), highlight(docs, 1, ?, ?) FROM docs WHERE docs MATCH ?"
            f" ORDER BY bm25(docs, 5.0, 2.0, 3.0, 0.0)",
            (MARK_START, MARK_END, MARK_START, MARK_END, query)).fetchall()
    finally:
        memory.close()
    return [entries[rowid - 1] | {"title_marked": title, "summary_marked": summary} for rowid, title, summary in rows]


def order(entry: dict) -> int:
    return list(KINDS).index(entry["kind"]) if entry["kind"] in KINDS else 99


def public(entry: dict, team: bool) -> dict:
    lesson = entry["id"].startswith("LES-")
    request = re.search(r"SUB-\d{4}", entry["source"]) if lesson else None
    return {"id": entry["id"], "kind": entry["kind"], "kind_label": KINDS.get(entry["kind"], entry["kind"]),
            "lesson": lesson, "title": entry["title"], "summary": entry["summary"], "how_to": entry["how_to"],
            "source": "Innovation Hub lesson" if lesson and not team else entry["source"],
            "request": request.group(0) if request and team else None,
            "title_marked": entry.get("title_marked"), "summary_marked": entry.get("summary_marked"),
            "keywords": [k.strip() for k in entry["keywords"].split(",") if k.strip()]}


def search_stats(conn) -> dict:
    """For the team's measures: how often the library finds something, and what it doesn't."""
    total = conn.execute("SELECT COUNT(*) FROM library_searches").fetchone()[0]
    empty = [row["query"] for row in conn.execute(
        "SELECT lower(query) AS query FROM library_searches WHERE results = 0 GROUP BY lower(query)"
        " ORDER BY MAX(pk) DESC LIMIT 5")]
    found = conn.execute("SELECT COUNT(*) FROM library_searches WHERE results > 0").fetchone()[0]
    return {"library_searches": total, "library_found_share": round(found / total, 2) if total else None,
            "library_no_results": empty}
