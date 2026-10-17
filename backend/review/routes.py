"""Review API: what the innovation team and the employee can do after a request is saved.

Status changes happen ONLY here (and in screening's policy declines), along these paths:

  Submitted / Routed / Under review / Needs clarification
     ├─ accept ──▶ Accepted
     ├─ ask ─────▶ Needs clarification ── employee replies ──▶ Under review
     ├─ decline ─▶ Declined ── employee appeals (once) ──▶ Under review
     └─ link ────▶ Linked (kept as its own record, attached to a shared opportunity)
  Routed ── employee confirms it's fixed ──▶ Resolved

Reviewer corrections (route, rubric scores, feasibility) are logged, because they are how
routing accuracy and the screening's usefulness are measured.
"""
import json
import statistics
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .. import db
from ..models import (DEMO_USER, INNOVATION_ROUTES, OPEN_STATUSES, ROUTES, ROUTINE_ROUTES, Feasibility, Route,
                      SubmissionOut)
from . import screening
from .screening import CRITERIA

router = APIRouter(tags=["review"])

# Demo only: there's no sign-in yet, so every reviewer action is recorded as this person.
DEMO_REVIEWER = "demo-reviewer"
NEW_STATUS = {"accept": "Accepted", "ask": "Needs clarification", "decline": "Declined", "link": "Linked"}


class ReviewIn(BaseModel):
    decision: Literal["accept", "ask", "decline", "link"]
    reason_code: str | None = None                               # required for decline
    message: str | None = Field(default=None, max_length=1000)   # the question, or the explanation
    link_to: str | None = None                                   # required for link
    review_seconds: int | None = Field(default=None, ge=0, le=86400)

    @model_validator(mode="after")
    def check(self):
        self.message = (self.message or "").strip() or None
        if self.decision == "ask" and not self.message:
            raise ValueError("Asking needs a question for the employee")
        if self.decision == "decline":
            if self.reason_code not in CRITERIA:
                raise ValueError(f"Declining needs a reason: one of {', '.join(CRITERIA)}")
            if not self.message:
                raise ValueError("Declining needs a message telling the employee why")
        if self.decision == "link" and not self.link_to:
            raise ValueError("Linking needs the request to link to")
        return self


class RerouteIn(BaseModel):
    route: Route
    reason: str = Field(min_length=1, max_length=500)


class ScoreIn(BaseModel):
    criterion: Literal["business_impact", "frequency_reach", "alignment", "experimentation"]
    value: int | None = Field(default=None, ge=0, le=5)   # None = unknown (not zero)
    reason: str = Field(min_length=1, max_length=500)


class FeasibilityIn(BaseModel):
    label: Feasibility


class EmployeeText(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class OptionalText(BaseModel):
    text: str | None = Field(default=None, max_length=2000)


# ── Reviewer ─────────────────────────────────────────────────────────────────

@router.get("/api/review/criteria")
def list_criteria():
    return [{"code": code, "name": c["name"], "auto": c["auto"], "message": c["message"]}
            for code, c in CRITERIA.items()]


@router.post("/api/submissions/{submission_id}/review", response_model=SubmissionOut)
def review(submission_id: str, body: ReviewIn):
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] not in OPEN_STATUSES:
            raise HTTPException(409, f"Can't {body.decision} a request that is {record['status']}")
        pk, new_status = db.parse_pk(submission_id), NEW_STATUS[body.decision]

        if body.decision == "link":
            parent = db.get_submission(conn, body.link_to)
            if parent is None or parent["id"] == record["id"]:
                raise HTTPException(422, "Link to a different, existing request")
            conn.execute("UPDATE submissions SET supporters = supporters + 1 WHERE pk = ?", (db.parse_pk(parent["id"]),))
            db.add_event(conn, db.parse_pk(parent["id"]), DEMO_REVIEWER, "linked", None, None,
                         f"{record['id']} linked by reviewer")

        final = body.decision != "ask"
        conn.execute(
            "UPDATE submissions SET status = ?, review_question = COALESCE(?, review_question),"
            " decision_reason = ?, decision_message = ?, decided_by = ?, review_outcome = ?,"
            " linked_to = COALESCE(?, linked_to), review_seconds = COALESCE(?, review_seconds) WHERE pk = ?",
            (new_status, None if final else body.message,
             body.reason_code if body.decision == "decline" else None,
             body.message if final else None,
             DEMO_REVIEWER if final else record["decided_by"], compare(record, body),
             body.link_to if body.decision == "link" else None,
             body.review_seconds if final else None, pk))
        details = {"accept": body.message or "Accepted for discovery", "ask": body.message,
                   "decline": f"{CRITERIA.get(body.reason_code, {}).get('name')}: {body.message}",
                   "link": f"Linked to {body.link_to}"}[body.decision]
        db.add_event(conn, pk, DEMO_REVIEWER,
                     {"accept": "accepted", "ask": "asked", "decline": "declined", "link": "linked"}[body.decision],
                     record["status"], new_status, details)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/reroute", response_model=SubmissionOut)
def reroute(submission_id: str, body: RerouteIn):
    """Reviewer correction: send the request to a different first owner."""
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] not in OPEN_STATUSES:
            raise HTTPException(409, "Only open requests can be re-routed")
        track = record["innovation_track"]
        if track != "employee_requested":
            track = "screening" if body.route in INNOVATION_ROUTES else "none" if body.route in ROUTINE_ROUTES else track
        status = record["status"]
        if status in ("Submitted", "Routed"):
            status = "Routed" if body.route in ROUTINE_ROUTES else "Submitted"
        conn.execute("UPDATE submissions SET route = ?, route_reason = ?, innovation_track = ?, status = ? WHERE pk = ?",
                     (body.route, f"{body.reason} (reviewer correction)", track, status, db.parse_pk(submission_id)))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "rerouted", record["status"], status,
                     f"{ROUTES.get(record['route'] or '', 'none')} → {ROUTES[body.route]}: {body.reason}")
        screening.screen(conn, submission_id, allow_auto=False)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/scores", response_model=SubmissionOut)
def correct_score(submission_id: str, body: ScoreIn):
    """Reviewer correction of one rubric criterion. The priority is recalculated."""
    with db.connect() as conn:
        record = load(conn, submission_id)
        brief = record["brief"] or {}
        criteria = (brief.get("priority") or {}).get("criteria")
        if not criteria:
            raise HTTPException(409, "This request has no priority to correct")
        old = criteria[body.criterion]
        criteria[body.criterion] = old | {"value": body.value, "reason": f"{body.reason} (reviewer correction)",
                                          "corrected_by": DEMO_REVIEWER}
        conn.execute("UPDATE submissions SET brief_json = ? WHERE pk = ?", (json.dumps(brief), db.parse_pk(submission_id)))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "score_corrected", None, None,
                     f"{old['name']}: {old['value']} → {body.value if body.value is not None else 'unknown'}. {body.reason}")
        screening.screen(conn, submission_id, allow_auto=False)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/feasibility", response_model=SubmissionOut)
def set_feasibility(submission_id: str, body: FeasibilityIn):
    with db.connect() as conn:
        record = load(conn, submission_id)
        brief = record["brief"] or {}
        brief["feasibility_set_by"] = DEMO_REVIEWER
        conn.execute("UPDATE submissions SET feasibility = ?, brief_json = ? WHERE pk = ?",
                     (body.label, json.dumps(brief), db.parse_pk(submission_id)))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "feasibility_set", None, None,
                     f"{record['feasibility']} → {body.label}")
        screening.screen(conn, submission_id, allow_auto=False)
        return db.get_submission(conn, submission_id)


# ── Employee ─────────────────────────────────────────────────────────────────

@router.post("/api/submissions/{submission_id}/request-review", response_model=SubmissionOut)
def request_review(submission_id: str, body: OptionalText):
    """Employee override: guarantees a human innovation decision (not funding)."""
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] not in OPEN_STATUSES:
            raise HTTPException(409, "Only open requests can be sent for innovation review")
        if record["innovation_track"] == "employee_requested":
            raise HTTPException(409, "An innovation review has already been requested")
        conn.execute("UPDATE submissions SET innovation_track = 'employee_requested' WHERE pk = ?",
                     (db.parse_pk(submission_id),))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_USER, "review_requested", None, None,
                     (body.text or "").strip() or "Employee requested an innovation review")
        screening.screen(conn, submission_id, allow_auto=False)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/resolve", response_model=SubmissionOut)
def confirm_resolved(submission_id: str):
    """The employee confirms a routed request was fixed. Counted as a confirmed resolution."""
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] != "Routed":
            raise HTTPException(409, "Only a routed request can be marked as resolved")
        conn.execute("UPDATE submissions SET status = 'Resolved', resolution_confirmed = 1 WHERE pk = ?",
                     (db.parse_pk(submission_id),))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_USER, "resolved", "Routed", "Resolved",
                     "Employee confirmed it was resolved")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/reply", response_model=SubmissionOut)
def employee_reply(submission_id: str, body: EmployeeText):
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] != "Needs clarification":
            raise HTTPException(409, "There's no open question to reply to")
        conn.execute("UPDATE submissions SET status = 'Under review' WHERE pk = ?", (db.parse_pk(submission_id),))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_USER, "replied", record["status"], "Under review",
                     body.text.strip())
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/appeal", response_model=SubmissionOut)
def appeal(submission_id: str, body: EmployeeText):
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] != "Declined":
            raise HTTPException(409, "Only a declined request can be appealed")
        if record["appealed"]:
            raise HTTPException(409, "This request has already had a human review")
        conn.execute("UPDATE submissions SET status = 'Under review', appealed = 1 WHERE pk = ?",
                     (db.parse_pk(submission_id),))
        db.add_event(conn, db.parse_pk(submission_id), DEMO_USER, "appealed", "Declined", "Under review",
                     body.text.strip())
        return db.get_submission(conn, submission_id)


@router.get("/api/submissions/{submission_id}/history")
def history(submission_id: str):
    with db.connect() as conn:
        load(conn, submission_id)
        rows = conn.execute("SELECT actor, event, from_status, to_status, details, created_at FROM submission_events"
                            " WHERE submission_pk = ? ORDER BY pk", (db.parse_pk(submission_id),)).fetchall()
    return [dict(row) for row in rows]


# ── Measures ─────────────────────────────────────────────────────────────────

@router.get("/api/metrics")
def metrics():
    """The demo's success measures. Confirmed resolutions count; fewer escalations alone don't."""
    with db.connect() as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]
        column = lambda sql: [row[0] for row in conn.execute(sql)]
        submit_times = column("SELECT submission_seconds FROM submissions WHERE submission_seconds IS NOT NULL")
        review_times = column("SELECT review_seconds FROM submissions WHERE review_seconds IS NOT NULL")
        corrected = one("SELECT COUNT(DISTINCT submission_pk) FROM submission_events WHERE event = 'rerouted'")
        reviewed = one("SELECT COUNT(*) FROM submissions WHERE initial_route IS NOT NULL AND (review_outcome IS NOT NULL"
                       " OR pk IN (SELECT submission_pk FROM submission_events WHERE event = 'rerouted'))")
        wrong = one("SELECT COUNT(*) FROM submissions WHERE initial_route IS NOT NULL AND route != initial_route")
        ratings = column("SELECT satisfaction FROM intake_sessions WHERE satisfaction IS NOT NULL")
        outcomes = {row[0]: row[1] for row in conn.execute(
            "SELECT review_outcome, COUNT(*) FROM submissions WHERE review_outcome IS NOT NULL GROUP BY review_outcome")}
        compared = outcomes.get("agreed", 0) + outcomes.get("overrode", 0)
        return {
            "submission_time_seconds": statistics.median(submit_times) if submit_times else None,
            "routing_accuracy": round(1 - wrong / reviewed, 2) if reviewed else None,
            "routing_corrections": corrected,
            "reviewer_time_seconds": statistics.median(review_times) if review_times else None,
            "missed_opportunities": one(
                "SELECT COUNT(*) FROM submissions WHERE status = 'Accepted' AND initial_route IN"
                " ('it_support', 'hr', 'facilities_procurement', 'human_triage')"),
            "satisfaction": round(statistics.mean(ratings), 1) if ratings else None,
            "satisfaction_responses": len(ratings),
            "confirmed_resolutions": one("SELECT COUNT(*) FROM intake_sessions WHERE outcome = 'self_service'")
                                     + one("SELECT COUNT(*) FROM submissions WHERE resolution_confirmed = 1"),
            "agreement_rate": round(outcomes.get("agreed", 0) / compared, 2) if compared else None,
            "decisions": compared,
            "auto_declined": one("SELECT COUNT(*) FROM submission_events WHERE event = 'auto_declined'"),
            "auto_declines_overturned": outcomes.get("overturned_auto", 0),
            "research_started": one("SELECT COUNT(*) FROM submissions WHERE status = 'Research'"),
            "research_top_pick_rate": (lambda picks: round(sum(picks) / len(picks), 2) if picks else None)(
                [json.loads(row[0])["agreed_with_top_rank"] for row in conn.execute(
                    "SELECT research_json FROM submissions WHERE research_json IS NOT NULL")]),
            "pilots_running": one("SELECT COUNT(*) FROM submissions WHERE status = 'Pilot running'"),
            "pilots_scaled": one("SELECT COUNT(*) FROM submissions WHERE status = 'Scaling'"),
            "pilots_stopped": one("SELECT COUNT(*) FROM submissions WHERE status = 'Stopped'"),
            "employee_requested_open": one(
                "SELECT COUNT(*) FROM submissions WHERE innovation_track = 'employee_requested' AND status IN"
                " ('Submitted', 'Routed', 'Under review', 'Needs clarification')"),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def load(conn, submission_id: str) -> dict:
    record = db.get_submission(conn, submission_id)
    if record is None:
        raise HTTPException(404, "Submission not found")
    return record


def compare(record: dict, body: ReviewIn) -> str | None:
    """Did the reviewer agree with the screening? Asking a question is not a final decision."""
    if body.decision == "ask":
        return record["review_outcome"]
    if record["decided_by"] == "screening-policy" and record["appealed"]:
        return "overturned_auto" if body.decision == "accept" else "agreed"
    recommendation = record["recommendation"] or {}
    same = recommendation.get("decision") == body.decision and (
        body.decision != "decline" or recommendation.get("reason_code") == body.reason_code)
    return "agreed" if same else "overrode"
