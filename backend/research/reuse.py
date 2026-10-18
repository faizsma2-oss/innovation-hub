"""Reusing supplier research from earlier requests, instead of paying to rediscover the same suppliers.

  - Earlier comparisons are offered when the chosen approach is similar (word-stem overlap, as in intake).
  - A reused supplier keeps only findings for factors this request also uses, with their original sources
    and date; other factors are "unknown". Older than 90 days: flagged to re-check.
  - Everything is ranked again with this request's own weights and must-haves.
Plain code: no AI.
"""
import json
from datetime import datetime, timezone

from ..intake.search import stems

STALE_DAYS = 90


def approach_text(research: dict) -> str:
    option = research.get("selected_option") or {}
    return f"{option.get('title', '')} {option.get('summary', '')}"


def earlier_runs(conn, submission_pk: int, research: dict) -> list[dict]:
    """Supplier comparisons from other requests whose chosen approach is similar, most similar first."""
    rows = [row for row in conn.execute("SELECT pk, title, research_json FROM submissions WHERE pk != ? AND research_json"
                                        " IS NOT NULL", (submission_pk,))
            if (json.loads(row["research_json"]).get("suppliers") or {}).get("suppliers")]
    if not rows:
        return []
    found = stems({"this": approach_text(research)} | {row["pk"]: approach_text(json.loads(row["research_json"])) for row in rows})
    wanted = found.pop("this")
    runs = []
    for row in rows:
        other = json.loads(row["research_json"])
        shared = wanted & found[row["pk"]]
        score = len(shared) / max(len(wanted | found[row["pk"]]), 1)
        if len(shared) >= 2 and score >= 0.25:
            run = other["suppliers"]
            runs.append({"submission_id": f"SUB-{row['pk']:04d}", "title": row["title"],
                         "approach": (other.get("selected_option") or {}).get("title"), "similarity": round(score, 2),
                         "run_at": run.get("run_at"), "age_days": age_days(run.get("run_at")),
                         "factors": [f["name"] for f in (run.get("setup") or {}).get("factors", [])],
                         "suppliers": [{"name": s["name"], "rank": s.get("rank"), "fit_score": s.get("fit_score")}
                                       for s in run["suppliers"]]})
    return sorted(runs, key=lambda r: -r["similarity"])


def age_days(stamp: str | None) -> int | None:
    if not stamp:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).days


def reused_suppliers(conn, submission_ids: list[str], setup: dict) -> list[dict]:
    """The suppliers of the chosen earlier runs, adapted to this request's factors and cost policy."""
    factors = {f["key"] for f in setup["factors"]}
    result, seen = [], set()
    for sid in submission_ids:
        row = conn.execute("SELECT research_json FROM submissions WHERE pk = ?", (int(sid[4:]),)).fetchone()
        run = (json.loads(row["research_json"]).get("suppliers") or {}) if row else {}
        for supplier in run.get("suppliers", []):
            if supplier["name"].lower() in seen:
                continue
            seen.add(supplier["name"].lower())
            age = age_days(run.get("run_at"))
            findings = {key: dict(finding) | {"reused": True} for key, finding in supplier["findings"].items() if key in factors}
            for key in factors - set(findings):
                findings[key] = {"rating": None, "finding": "Not covered by the earlier research.", "evidence": "not found",
                                 "sources": [], "must_have_met": "unknown"}
            cost = dict(supplier.get("cost") or {})
            if setup["cost_policy"] != "estimates":
                cost["estimate"] = None
            if setup["cost_policy"] == "relative":
                cost["published_price"], cost["price_is_published"] = None, False
            result.append({k: supplier.get(k) for k in ("name", "website", "headquarters", "uae_presence", "offering",
                                                        "questions_for_supplier")}
                          | {"findings": findings, "cost": cost,
                             "reused_from": {"submission_id": sid, "run_at": run.get("run_at"), "age_days": age,
                                             "stale": age is not None and age > STALE_DAYS}})
    return result


def merge(fresh: list[dict], reused: list[dict]) -> list[dict]:
    """Fresh web results win for the same company; reused ones not found again are added."""
    names = {s["name"].lower() for s in fresh}
    return fresh + [s for s in reused if s["name"].lower() not in names]
