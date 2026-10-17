"""Scale, roll out, hand over, track benefits, and capture lessons.

  Scaling ── business case (costs from people, benefit from the pilot's measurements, maths in code)
          └─ management decides ── approve ──▶ Rolling out (rollout plan + handover checklist drafted)
                                 └ reject  ──▶ Stopped
  Rolling out ── named business owner + checklist done ──▶ In operation (check-ins at 3, 6, 12 months)
  In operation ── check-ins: did the pilot's improvement hold?
  In operation / Stopped ── lesson drafted, edited, published ──▶ the intake catalog
       (a solution in operation is offered to future employees as an existing tool;
        a stopped pilot becomes "previous pilot" context in future briefs)
"""
import json
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..models import SubmissionOut
from ..review.routes import DEMO_REVIEWER, load
from ..research.routes import log_run
from . import rules
from .assistant import clean_keywords, get_assistant

router = APIRouter(tags=["scale"])
CURRENCIES = Literal["AED", "USD", "EUR", "SAR"]


class CostIn(BaseModel):
    item: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0)


class BenefitIn(BaseModel):
    metric_key: str = Field(min_length=1, max_length=60)
    value_per_unit: float = Field(ge=0)          # e.g. AED per hour saved
    periods_per_year: float = Field(gt=0, le=366) # e.g. 52 for a weekly metric
    multiplier: float = Field(gt=0, le=1000)      # e.g. number of sites or teams it will reach


class CaseIn(BaseModel):
    currency: CURRENCIES = "AED"
    one_off: list[CostIn] = Field(default_factory=list, max_length=20)
    yearly: list[CostIn] = Field(default_factory=list, max_length=20)
    benefits: list[BenefitIn] = Field(min_length=1, max_length=10)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1000)


class ItemIn(BaseModel):
    index: int = Field(ge=0, le=30)
    done: bool


class HandoverIn(BaseModel):
    business_owner: str = Field(min_length=1, max_length=80)
    handover_date: date


class CheckinIn(BaseModel):
    index: int = Field(ge=0, le=2)
    values: dict[str, float] = Field(min_length=1)
    note: str = Field(default="", max_length=1000)


class LessonIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=600)
    how_to: str = Field(default="", max_length=400)
    keywords: list[str] = Field(min_length=1, max_length=8)


# ── Business case and decision ───────────────────────────────────────────────

@router.get("/api/submissions/{submission_id}/scale/improvements")
def measured_improvements(submission_id: str):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("Scaling",))
        return rules.improvements(latest_evaluation(research))


@router.post("/api/submissions/{submission_id}/scale/business-case", response_model=SubmissionOut)
def business_case(submission_id: str, body: CaseIn):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("Scaling",))
        evaluation = latest_evaluation(research)
        calc = rules.business_case(body.model_dump(), evaluation)
        if not calc["benefit_lines"]:
            raise HTTPException(422, "Value at least one metric the pilot actually improved")
        assistant, meter = get_assistant(), []
        narrative = assistant.case_narrative({"approach": research["selected_option"]["title"],
                                              "partner": research["pilot"]["partner"], "calculation": calc,
                                              "pilot_verdict": evaluation["verdict"]}, meter)
        research.setdefault("scale", {})["business_case"] = {
            "inputs": body.model_dump(), "calc": calc, "narrative": narrative, "status": "AWAITING DECISION",
            "prepared_by": DEMO_REVIEWER, "prepared_at": db.now()}
        save(conn, submission_id, research)
        log_run(conn, "business_case", submission_id, assistant, meter, {"verdict": calc["verdict"]})
        event(conn, submission_id, "business_case_prepared",
              f"{calc['verdict']}: benefit {calc['annual_benefit']:,.0f} {calc['currency']}/year, "
              f"one-off {calc['one_off_total']:,.0f}, yearly cost {calc['yearly_cost_total']:,.0f}")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/scale/decision", response_model=SubmissionOut)
def management_decision(submission_id: str, body: DecisionIn):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("Scaling",))
        case = (research.get("scale") or {}).get("business_case")
        if not case:
            raise HTTPException(409, "Prepare the business case first")
        case |= {"status": "APPROVED" if body.decision == "approve" else "REJECTED",
                 "decision": {"by": DEMO_REVIEWER, "at": db.now(), "reason": body.reason.strip()}}
        new_status = "Rolling out" if body.decision == "approve" else "Stopped"
        if body.decision == "approve":
            assistant, meter = get_assistant(), []
            plan = assistant.rollout({"approach": research["selected_option"]["title"],
                                      "partner": research["pilot"]["partner"], "business_case": case["calc"],
                                      "pilot_plan_scope": research["pilot"]["plan"].get("scope")}, meter)
            research["scale"]["rollout"] = {"plan": plan, "status": "DRAFT", "business_owner": None,
                                            "handover": [{"item": item, "done": False} for item in plan["handover_checklist"]]}
            log_run(conn, "rollout_plan", submission_id, assistant, meter, {})
        conn.execute("UPDATE submissions SET status = ?, research_json = ? WHERE pk = ?",
                     (new_status, json.dumps(research), db.parse_pk(submission_id)))
        event(conn, submission_id, f"business_case_{case['status'].lower()}", body.reason.strip(), "Scaling", new_status)
        return db.get_submission(conn, submission_id)


# ── Rollout and handover ─────────────────────────────────────────────────────

@router.post("/api/submissions/{submission_id}/scale/handover-item", response_model=SubmissionOut)
def handover_item(submission_id: str, body: ItemIn):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("Rolling out",))
        items = research["scale"]["rollout"]["handover"]
        if body.index >= len(items):
            raise HTTPException(422, "Unknown checklist item")
        items[body.index]["done"] = body.done
        save(conn, submission_id, research)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/scale/handover", response_model=SubmissionOut)
def handover(submission_id: str, body: HandoverIn):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("Rolling out",))
        rollout = research["scale"]["rollout"]
        open_items = [i["item"] for i in rollout["handover"] if not i["done"]]
        if body.business_owner.strip().upper() == "UNASSIGNED":
            raise HTTPException(422, "Name the business owner who will own it in operations")
        if open_items:
            raise HTTPException(409, f"Finish the handover checklist first: {'; '.join(open_items)}")
        rollout |= {"business_owner": body.business_owner.strip(), "handover_date": body.handover_date.isoformat(),
                    "status": "HANDED OVER"}
        research["scale"]["checkins"] = [
            {"label": f"{months} months", "due": (body.handover_date + timedelta(days=round(months * 30.44))).isoformat(),
             "result": None} for months in rules.CHECKIN_MONTHS]
        conn.execute("UPDATE submissions SET status = 'In operation', research_json = ? WHERE pk = ?",
                     (json.dumps(research), db.parse_pk(submission_id)))
        event(conn, submission_id, "handed_over", f"Business owner {body.business_owner.strip()} from {body.handover_date}",
              "Rolling out", "In operation")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/scale/checkin", response_model=SubmissionOut)
def benefits_checkin(submission_id: str, body: CheckinIn):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("In operation",))
        checkins = research["scale"]["checkins"]
        if body.index >= len(checkins):
            raise HTTPException(422, "Unknown check-in")
        case = research["scale"]["business_case"]["calc"]
        result = rules.realised(body.values, case)
        if not result["metrics"]:
            raise HTTPException(422, "Log a value for at least one of the business case's metrics")
        checkins[body.index] |= {"result": result, "values": body.values, "note": body.note.strip(),
                                 "logged_by": DEMO_REVIEWER, "logged_at": db.now()}
        save(conn, submission_id, research)
        event(conn, submission_id, "benefits_checkin",
              f"{checkins[body.index]['label']}: {result['verdict']} ({round(result['overall_fraction'] * 100)}% of the pilot's "
              f"improvement), about {result['realised_annual_value']:,.0f} {result['currency']}/year realised")
        return db.get_submission(conn, submission_id)


# ── Lessons learned, fed back into intake ────────────────────────────────────

@router.post("/api/submissions/{submission_id}/lessons/draft", response_model=SubmissionOut)
def draft_lesson(submission_id: str):
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("In operation", "Stopped"))
        assistant, meter = get_assistant(), []
        draft = assistant.lesson(lesson_facts(record, research), meter)
        research["lesson_draft"] = draft | {"status": "DRAFT", "kind": lesson_kind(record),
                                            "how_to": default_how_to(record, research)}
        save(conn, submission_id, research)
        log_run(conn, "lesson_draft", submission_id, assistant, meter, {})
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/lessons/publish", response_model=SubmissionOut)
def publish_lesson(submission_id: str, body: LessonIn):
    """Adds the lesson to the catalog the intake assistant checks for every new request."""
    with db.connect() as conn:
        record, research = in_stage(conn, submission_id, ("In operation", "Stopped"))
        keywords = clean_keywords(body.keywords)
        if not keywords:
            raise HTTPException(422, "Give at least one specific keyword phrase (2-3 words, e.g. 'combine reports')")
        kind = lesson_kind(record)
        lesson_id = f"LES-{db.parse_pk(submission_id):04d}"
        conn.execute("INSERT OR REPLACE INTO solutions (id, kind, title, summary, how_to, source, keywords)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (lesson_id, kind, body.title.strip(), body.summary.strip(),
                      body.how_to.strip() or default_how_to(record, research),
                      f"Innovation Hub {submission_id}", ",".join(keywords)))
        research["lesson"] = {"id": lesson_id, "kind": kind, "title": body.title.strip(), "keywords": keywords,
                              "published_by": DEMO_REVIEWER, "published_at": db.now()}
        save(conn, submission_id, research)
        event(conn, submission_id, "lesson_published",
              f"{lesson_id} added to the intake catalog as {'an existing tool' if kind == 'tool' else 'a previous pilot'}")
        return db.get_submission(conn, submission_id)


# ── Helpers ──────────────────────────────────────────────────────────────────

def lesson_kind(record: dict) -> str:
    return "tool" if record["status"] == "In operation" else "previous_pilot"


def default_how_to(record: dict, research: dict) -> str:
    owner = ((research.get("scale") or {}).get("rollout") or {}).get("business_owner")
    return (f"In use at Khazna. Contact the business owner, {owner}, to get access." if owner
            else f"See the record {record['id']} in the Innovation Hub for what was tried and why it stopped.")


def lesson_facts(record: dict, research: dict) -> dict:
    pilot = research.get("pilot") or {}
    evaluation = (pilot.get("evaluations") or [None])[-1]
    decisions = pilot.get("decisions") or []
    case = (research.get("scale") or {}).get("business_case") or {}
    checkins = [c for c in (research.get("scale") or {}).get("checkins", []) if c.get("result")]
    outcome = (f"In operation. {case.get('calc', {}).get('verdict', '')}." if record["status"] == "In operation"
               else f"Stopped. {(case.get('decision') or {}).get('reason') or (decisions[-1]['reason'] if decisions else '')}")
    return {"title": record["title"], "problem": record["description"],
            "approach": (research.get("selected_option") or {}).get("title", "not chosen"),
            "partner": pilot.get("partner"), "outcome": outcome,
            "pilot_verdict": evaluation and {k: evaluation[k] for k in ("verdict", "reason")},
            "pilot_lessons": evaluation and evaluation["narrative"].get("lessons"),
            "benefits": checkins[-1]["result"] if checkins else None,
            "keyword_hints": [record["title"].lower()]}


def latest_evaluation(research: dict) -> dict:
    evaluations = (research.get("pilot") or {}).get("evaluations") or []
    if not evaluations:
        raise HTTPException(409, "There is no pilot evaluation to build on")
    return evaluations[-1]


def in_stage(conn, submission_id: str, statuses: tuple):
    record = load(conn, submission_id)
    if record["status"] not in statuses:
        raise HTTPException(409, f"Not possible while the request is {record['status']}")
    return record, record["research"] or {}


def save(conn, submission_id: str, research: dict):
    conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), db.parse_pk(submission_id)))


def event(conn, submission_id: str, name: str, details: str, before=None, after=None):
    db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, name, before, after, details)
