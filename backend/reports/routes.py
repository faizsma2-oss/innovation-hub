"""Portfolio board and the weekly management report.

Everything in the report is collected from the records by plain code, and every line points
to the request it came from. The AI writes only the executive summary at the top, and a
summary containing a figure that isn't in the collected facts is replaced by a plain one.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db
from ..meetings import calendar
from ..meetings.routes import reminders
from ..research.routes import log_run
from ..scale.assistant import get_assistant

router = APIRouter(tags=["reports"])

STAGES = [
    ("Screening", ("Submitted", "Under review", "Needs clarification")),
    ("Choose a solution", ("Accepted",)),
    ("Research", ("Research",)),
    ("Pilot", ("Pilot planning", "Pilot running")),
    ("Scaling", ("Scaling", "Rolling out")),
    ("In operation", ("In operation",)),
    ("Closed", ("Declined", "Stopped")),
]


def stage_of(status: str) -> str | None:
    return next((name for name, statuses in STAGES if status in statuses), None)


def innovation_records(conn) -> list[dict]:
    """Opportunities only: routine routed requests and linked duplicates aren't part of the portfolio."""
    rows = conn.execute("SELECT * FROM submissions WHERE innovation_track != 'none'"
                        " OR status IN ('Accepted', 'Research', 'Pilot planning', 'Pilot running', 'Scaling',"
                        " 'Rolling out', 'In operation', 'Stopped')").fetchall()
    return [db.to_public(row) for row in rows if row["status"] not in ("Linked", "Routed", "Resolved")]


def owner_of(record: dict) -> str:
    research = record.get("research") or {}
    return (((research.get("scale") or {}).get("rollout") or {}).get("business_owner")
            or ((research.get("pilot") or {}).get("setup") or {}).get("owner") or "UNASSIGNED")


def decisions_needed(records: dict) -> list[dict]:
    """Decisions waiting on people, from the records. Shared by the weekly report and Copilot."""
    decisions = []
    for sid, r in records.items():
        research = r.get("research") or {}
        case = (research.get("scale") or {}).get("business_case")
        if r["status"] == "Scaling" and case and case["status"] == "AWAITING DECISION":
            decisions.append({"id": sid, "title": r["title"], "decision": "Approve or reject the business case",
                              "detail": case["calc"]["verdict"], "who_decides": "Management",
                              "waiting_since": case["prepared_at"][:10]})
        if r["innovation_track"] == "employee_requested" and r["status"] in ("Submitted", "Under review", "Routed", "Needs clarification"):
            decisions.append({"id": sid, "title": r["title"], "decision": "Employee-requested review needs a decision",
                              "detail": (r.get("recommendation") or {}).get("reason", ""), "who_decides": "Innovation team",
                              "waiting_since": r["created_at"][:10]})
        pilot = research.get("pilot") or {}
        evaluations, decided = pilot.get("evaluations") or [], {d["round"] for d in pilot.get("decisions") or []}
        if r["status"] == "Pilot running" and evaluations and evaluations[-1]["round"] not in decided:
            decisions.append({"id": sid, "title": r["title"], "decision": "Decide the pilot: scale, extend, revise or stop",
                              "detail": f"Verdict {evaluations[-1]['verdict']}, recommends {evaluations[-1]['recommendation']}",
                              "who_decides": "Innovation team",
                              "waiting_since": (evaluations[-1].get("evaluated_at") or "")[:10] or None})

    return decisions


@router.get("/api/portfolio")
def portfolio():
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        columns = {name: [] for name, _ in STAGES}
        for record in innovation_records(conn):
            stage = stage_of(record["status"])
            if stage is None:
                continue
            entered = conn.execute("SELECT MAX(created_at) FROM submission_events WHERE submission_pk = ? AND to_status = ?",
                                   (db.parse_pk(record["id"]), record["status"])).fetchone()[0] or record["created_at"]
            research = record.get("research") or {}
            columns[stage].append({
                "id": record["id"], "title": record["title"], "status": record["status"], "score": record["score"],
                "owner": owner_of(record), "days_in_stage": (now - datetime.fromisoformat(entered)).days,
                "approach": (research.get("selected_option") or {}).get("title"),
                "partner": (research.get("pilot") or {}).get("partner"),
                "requested": record["innovation_track"] == "employee_requested"})
        for cards in columns.values():
            cards.sort(key=lambda c: (-(c["score"] or 0)))
    return {"stages": [{"name": name, "cards": columns[name]} for name, _ in STAGES]}


@router.post("/api/reports/weekly")
def weekly_report():
    end = calendar.today()
    start = end - timedelta(days=7)
    since = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        records = {r["id"]: r for r in innovation_records(conn)}
        title = lambda sid: (records.get(sid) or {}).get("title") or sid
        events = [dict(row) | {"id": f"SUB-{row['submission_pk']:04d}"} for row in conn.execute(
            "SELECT * FROM submission_events WHERE created_at >= ? ORDER BY pk", (since,))]

        # One line per request: where it started the week and where it is now, with the number of steps between.
        moved = {}
        for e in events:
            if e["to_status"] and e["from_status"] and e["from_status"] != e["to_status"]:
                line = moved.setdefault(e["id"], {"id": e["id"], "title": title(e["id"]), "from": e["from_status"], "steps": 0})
                line |= {"to": e["to_status"], "date": e["created_at"][:10], "steps": line["steps"] + 1}
        moved = list(moved.values())

        decisions = decisions_needed(records)

        results = []
        for e in events:
            if e["event"] in ("pilot_evaluated", "benefits_checkin", "business_case_approved", "handed_over",
                              "pilot_scale", "pilot_stop", "lesson_published"):
                results.append({"id": e["id"], "title": title(e["id"]), "what": e["event"].replace("_", " "),
                                "detail": e["details"], "date": e["created_at"][:10]})

        approved = []
        for sid, r in records.items():
            case = ((r.get("research") or {}).get("scale") or {}).get("business_case") or {}
            if case.get("status") == "APPROVED" and (case.get("decision") or {}).get("at", "") >= since:
                approved.append({"id": sid, "title": r["title"], "currency": case["calc"]["currency"],
                                 "one_off": case["calc"]["one_off_total"], "yearly": case["calc"]["yearly_cost_total"]})
        realised = []
        for sid, r in records.items():
            checkins = [c for c in ((r.get("research") or {}).get("scale") or {}).get("checkins", []) if c.get("result")]
            if checkins:
                result = checkins[-1]["result"]
                realised.append({"id": sid, "title": r["title"], "verdict": result["verdict"],
                                 "annual": result["realised_annual_value"], "currency": result["currency"]})

        meetings_held = [{"id": f"SUB-{m['submission_pk']:04d}", "supplier": m["supplier"], "date": (m["start_at"] or "")[:10]}
                         for m in conn.execute("SELECT * FROM meetings WHERE status = 'held' AND updated_at >= ?", (since,))]
        overdue = [{"id": f"SUB-{a['submission_pk']:04d}", "action": a["action"], "owner": a["owner"], "due": a["due"]}
                   for a in conn.execute("SELECT * FROM meeting_actions WHERE status = 'open' AND due IS NOT NULL AND due < ?",
                                         (end.isoformat(),))]
        ai_spend = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_runs WHERE created_at >= ?", (since,)).fetchone()[0]

    blockers = [item for item in reminders()["items"] if item["severity"] == "high"]
    pipeline = [{"stage": stage["name"], "count": len(stage["cards"])} for stage in portfolio()["stages"]]
    facts = {"period": f"{start.isoformat()} to {end.isoformat()}", "pipeline": pipeline, "decisions_needed": decisions,
             "moved": moved, "results": results, "budgets_approved": approved, "benefits_realised": realised,
             "meetings_held": meetings_held, "overdue_actions": overdue, "blockers": [b["text"] for b in blockers],
             "ai_spend_usd": round(ai_spend, 2)}
    assistant, meter = get_assistant(), []
    summary = assistant.report_summary(facts, meter)
    report = facts | {"summary": summary, "status": "DRAFT", "generated_at": db.now(),
                      "generated_by": f"{assistant.name} {assistant.version}"}
    with db.connect() as conn:
        cursor = conn.execute("INSERT INTO reports (period_start, period_end, report_json, created_at) VALUES (?, ?, ?, ?)",
                              (start.isoformat(), end.isoformat(), json.dumps(report), db.now()))
        log_run(conn, "weekly_report", "portfolio", assistant, meter, {"report": cursor.lastrowid})
    return report | {"id": cursor.lastrowid}


@router.get("/api/reports")
def list_reports():
    with db.connect() as conn:
        rows = conn.execute("SELECT pk, report_json FROM reports ORDER BY pk DESC LIMIT 10").fetchall()
    return [json.loads(row["report_json"]) | {"id": row["pk"]} for row in rows]
