"""Supplier evaluation API: from a shortlist to a pilot partner.

  Research (shortlist saved)
     per supplier: prepare (AI draft) → outreach marked by a person → meeting notes (AI extracts)
                   → due diligence checklist (people update each item)
     choose pilot partner (only if its required checks passed) ──▶ Pilot planning (pilot plan drafted)

Nothing is sent to a supplier by the app: drafts are copied and sent by a person.
"""
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..models import SubmissionOut
from ..review.routes import DEMO_REVIEWER, load
from . import evaluation, suppliers
from .routes import log_run

router = APIRouter(tags=["evaluation"])


class SupplierIn(BaseModel):
    supplier: str = Field(min_length=1, max_length=120)


class OutreachIn(SupplierIn):
    status: Literal["not_contacted", "contacted", "meeting_booked", "meeting_held", "declined_by_supplier"]


class MeetingIn(SupplierIn):
    date: date
    notes: str = Field(min_length=20, max_length=20000)


class ChecklistIn(SupplierIn):
    item: str = Field(min_length=1, max_length=40)
    status: Literal["not_started", "in_progress", "passed", "failed", "not_applicable"]
    owner: str = Field(default=evaluation.UNASSIGNED, max_length=80)
    note: str = Field(default="", max_length=1000)


class PartnerIn(SupplierIn):
    reason: str = Field(min_length=1, max_length=1000)


@router.get("/api/evaluation/checklist")
def checklist_template():
    return {"items": evaluation.CHECKLIST, "statuses": evaluation.CHECK_STATUSES}


@router.post("/api/submissions/{submission_id}/evaluation/prepare", response_model=SubmissionOut)
def prepare(submission_id: str, body: SupplierIn):
    with db.connect() as conn:
        record, research, supplier, track = shortlisted(conn, submission_id, body.supplier)
        evaluator, meter = evaluation.get_evaluator(), []
        track["prep"] = evaluator.prepare(record, supplier, meter) | {"status": "DRAFT", "prepared_at": db.now()}
        save(conn, submission_id, research)
        log_run(conn, "supplier_prep", submission_id, evaluator, meter, {"supplier": body.supplier})
        db.add_event(conn, db.parse_pk(submission_id), "research-ai", "meeting_prepared", None, None,
                     f"{body.supplier}: {len(track['prep']['questions'])} questions and a draft email")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/evaluation/outreach", response_model=SubmissionOut)
def outreach(submission_id: str, body: OutreachIn):
    """A person records what they did. The app never contacts suppliers itself."""
    with db.connect() as conn:
        _, research, _, track = shortlisted(conn, submission_id, body.supplier)
        previous, track["outreach"] = track["outreach"], body.status
        save(conn, submission_id, research)
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "supplier_outreach", None, None,
                     f"{body.supplier}: {previous} → {body.status}")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/evaluation/meeting", response_model=SubmissionOut)
def meeting(submission_id: str, body: MeetingIn):
    with db.connect() as conn:
        record, research, supplier, track = shortlisted(conn, submission_id, body.supplier)
        questions = (track["prep"] or {}).get("questions", [])
        evaluator, meter = evaluation.get_evaluator(), []
        extracted = evaluator.meeting(record, supplier, questions, body.notes, meter)
        label = f"Meeting notes {body.date.isoformat()}"
        # What the supplier said in a meeting updates the comparison, labelled as a verbal claim.
        for update in extracted["factor_updates"]:
            supplier["findings"][update["factor_key"]] = {
                "rating": update["rating"], "finding": update["finding"], "evidence": "supplier (meeting, verbal)",
                "sources": [label], "must_have_met": update["must_have_met"]}
        suppliers.rank(research["suppliers"]["suppliers"], research["suppliers"]["setup"])
        track["meetings"].append({"date": body.date.isoformat(), "notes": body.notes, "extracted": extracted,
                                  "logged_by": DEMO_REVIEWER, "logged_at": db.now()})
        if track["outreach"] in ("not_contacted", "contacted", "meeting_booked"):
            track["outreach"] = "meeting_held"
        save(conn, submission_id, research)
        log_run(conn, "supplier_meeting", submission_id, evaluator, meter, {"supplier": body.supplier})
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "supplier_meeting", None, None,
                     f"{body.supplier} on {body.date.isoformat()}: {len(extracted['actions'])} actions, "
                     f"{len(extracted['factor_updates'])} findings updated")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/evaluation/checklist", response_model=SubmissionOut)
def update_checklist(submission_id: str, body: ChecklistIn):
    with db.connect() as conn:
        _, research, _, track = shortlisted(conn, submission_id, body.supplier)
        item = next((i for i in track["checklist"] if i["key"] == body.item), None)
        if item is None:
            raise HTTPException(422, "Unknown checklist item")
        if item["required"] and body.status == "not_applicable" and not body.note.strip():
            raise HTTPException(422, "Explain why a required check doesn't apply")
        before = item["status"]
        item.update(status=body.status, owner=body.owner.strip() or evaluation.UNASSIGNED, note=body.note.strip())
        save(conn, submission_id, research)
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "due_diligence", None, None,
                     f"{body.supplier} · {item['name']}: {before} → {body.status}"
                     + (f" ({body.note.strip()})" if body.note.strip() else ""))
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/evaluation/pilot-partner", response_model=SubmissionOut)
def choose_pilot_partner(submission_id: str, body: PartnerIn):
    with db.connect() as conn:
        record, research, supplier, track = shortlisted(conn, submission_id, body.supplier)
        status = evaluation.gate(track)
        if not status["ready"]:
            problems = ([f"failed: {', '.join(status['failed'])}"] if status["failed"] else []) + \
                       ([f"still open: {', '.join(status['waiting'])}"] if status["waiting"] else [])
            raise HTTPException(409, f"{body.supplier} can't start a pilot yet ({'; '.join(problems)})")
        evaluator, meter = evaluation.get_evaluator(), []
        plan = evaluator.pilot_plan(record, supplier, track, meter)
        research["pilot"] = {"partner": body.supplier, "reason": body.reason.strip(), "chosen_by": DEMO_REVIEWER,
                             "chosen_at": db.now(), "plan": plan | {"status": "DRAFT"}}
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET status = 'Pilot planning', research_json = ? WHERE pk = ?",
                     (json.dumps(research), pk))
        log_run(conn, "pilot_plan", submission_id, evaluator, meter, {"supplier": body.supplier})
        db.add_event(conn, pk, DEMO_REVIEWER, "pilot_partner_chosen", "Research", "Pilot planning",
                     f"{body.supplier}: {body.reason.strip()}")
        return db.get_submission(conn, submission_id)


def shortlisted(conn, submission_id: str, name: str):
    record = load(conn, submission_id)
    if record["status"] != "Research":
        raise HTTPException(409, "Supplier evaluation happens during research, after a shortlist")
    research = record["research"]
    found = research.get("suppliers") or {}
    shortlist = (found.get("shortlist") or {}).get("names", [])
    if name not in shortlist:
        raise HTTPException(422, "Evaluate only suppliers on the saved shortlist")
    supplier = next(s for s in found["suppliers"] if s["name"] == name)
    tracks = research.setdefault("evaluation", {})
    track = tracks.setdefault(name, evaluation.new_track())
    return record, research, supplier, track


def save(conn, submission_id: str, research: dict):
    conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?",
                 (json.dumps(research), db.parse_pk(submission_id)))
