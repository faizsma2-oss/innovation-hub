"""Portfolio board and the weekly management report.

Everything in the report is collected from the records by plain code, and every line points
to the request it came from. The AI writes only the executive summary at the top, and a
summary containing a figure that isn't in the collected facts is replaced by a plain one.
"""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

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


# The weekly report is due every Monday from 08:00 UAE time and covers the week before (Monday to Sunday).
DUE_WEEKDAY, DUE_HOUR = 0, 8


@router.post("/api/reports/weekly")
def weekly_report():
    """Prepared on request: the last 7 days up to today."""
    end = calendar.today()
    return build_report(end - timedelta(days=7), end, "manual")


def week_due(now: datetime) -> datetime:
    """The most recent Monday 08:00 (UAE time) at or before `now`."""
    monday = (now - timedelta(days=(now.weekday() - DUE_WEEKDAY) % 7)).replace(hour=DUE_HOUR, minute=0, second=0, microsecond=0)
    return monday if monday <= now else monday - timedelta(days=7)


def ensure_weekly_report() -> dict | None:
    """Prepare this week's report if it's due and not prepared yet. Returns the new report, or None."""
    sunday = week_due(calendar.now_local()).date() - timedelta(days=1)
    with db.connect() as conn:
        # Already covered: any report (automatic or on request) that runs up to last Sunday or later.
        if conn.execute("SELECT 1 FROM reports WHERE period_end >= ?", (sunday.isoformat(),)).fetchone():
            return None
    return build_report(sunday - timedelta(days=6), sunday, "automatic")


def next_due() -> str:
    return (week_due(calendar.now_local()) + timedelta(days=7)).isoformat(timespec="minutes")


@router.post("/api/reports/due")
def prepare_if_due():
    """Called when the team opens the Hub: on a server that sleeps, this is how Monday's report appears."""
    return {"prepared": ensure_weekly_report() is not None, "next_due": next_due()}


@router.post("/api/reports/{report_id}/sent")
def mark_sent(report_id: int):
    """A person checked the report and sent it (from Outlook). Clears the Today reminder."""
    with db.connect() as conn:
        row = conn.execute("SELECT report_json FROM reports WHERE pk = ?", (report_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Report not found")
        report = json.loads(row["report_json"]) | {"status": "SENT", "sent_at": db.now()}
        conn.execute("UPDATE reports SET report_json = ? WHERE pk = ?", (json.dumps(report), report_id))
    return report | {"id": report_id}


def build_report(start: date, end: date, trigger: str) -> dict:
    # The period is in UAE days; records are stamped in UTC. Only what happened inside the period counts.
    since = datetime.combine(start, datetime.min.time(), calendar.DUBAI).astimezone(timezone.utc).isoformat(timespec="seconds")
    until = datetime.combine(end + timedelta(days=1), datetime.min.time(), calendar.DUBAI).astimezone(timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        records = {r["id"]: r for r in innovation_records(conn)}
        title = lambda sid: (records.get(sid) or {}).get("title") or sid
        events = [dict(row) | {"id": f"SUB-{row['submission_pk']:04d}"} for row in conn.execute(
            "SELECT * FROM submission_events WHERE created_at >= ? AND created_at < ? ORDER BY pk", (since, until))]

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
            if case.get("status") == "APPROVED" and since <= (case.get("decision") or {}).get("at", "") < until:
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
                         for m in conn.execute("SELECT * FROM meetings WHERE status = 'held' AND updated_at >= ? AND updated_at < ?", (since, until))]
        overdue = [{"id": f"SUB-{a['submission_pk']:04d}", "action": a["action"], "owner": a["owner"], "due": a["due"]}
                   for a in conn.execute("SELECT * FROM meeting_actions WHERE status = 'open' AND due IS NOT NULL AND due < ?",
                                         (end.isoformat(),))]
        ai_spend = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_runs WHERE created_at >= ? AND created_at < ?", (since, until)).fetchone()[0]

    blockers = [item for item in reminders()["items"] if item["severity"] == "high"]
    pipeline = [{"stage": stage["name"], "count": len(stage["cards"])} for stage in portfolio()["stages"]]
    facts = {"period": f"{start.isoformat()} to {end.isoformat()}", "pipeline": pipeline, "decisions_needed": decisions,
             "moved": moved, "results": results, "budgets_approved": approved, "benefits_realised": realised,
             "meetings_held": meetings_held, "overdue_actions": overdue, "blockers": [b["text"] for b in blockers],
             "ai_spend_usd": round(ai_spend, 2)}
    assistant, meter = get_assistant(), []
    summary = assistant.report_summary(facts, meter)
    report = facts | {"summary": summary, "status": "DRAFT", "generated_at": db.now(), "trigger": trigger,
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


async def scheduler(interval_seconds: int = 600):
    """On an always-on server: check every 10 minutes whether Monday's report is due."""
    import asyncio
    from starlette.concurrency import run_in_threadpool
    while True:
        try:
            await run_in_threadpool(ensure_weekly_report)
        except Exception as error:                    # never let one failure stop the schedule
            print(f"Weekly report scheduler: {error}")
        await asyncio.sleep(interval_seconds)
