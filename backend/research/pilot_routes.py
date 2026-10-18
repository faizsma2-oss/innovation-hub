"""Pilot API: agree the setup, measure a baseline, run, evaluate, decide.

  Pilot planning ── setup agreed (numeric targets, named owner) + baseline measured
                 └─ start ──▶ Pilot running ── pilot measurements + observations
                                └─ evaluate (verdict calculated in code) ── team decides:
                                     scale  ──▶ Scaling
                                     extend ──▶ Pilot running (new end date)
                                     revise ──▶ Pilot planning (history kept, next round)
                                     stop   ──▶ Stopped
"""
import json
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from .. import db
from ..models import SubmissionOut
from ..review.routes import DEMO_REVIEWER, load
from . import pilot as pilot_rules
from . import pilot_import
from .routes import log_run

router = APIRouter(tags=["pilot"])
NEW_STATUS = {"scale": "Scaling", "extend": "Pilot running", "revise": "Pilot planning", "stop": "Stopped"}


class CriterionIn(BaseModel):
    metric: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=30)
    direction: Literal["lower_better", "higher_better"]
    target: float
    min_points: int = Field(default=3, ge=2, le=20)


class SetupIn(BaseModel):
    criteria: list[CriterionIn] = Field(min_length=1, max_length=8)
    owner: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def check(self):
        if self.owner.strip().upper() == "UNASSIGNED":
            raise ValueError("Name the pilot owner")
        if self.end_date <= self.start_date:
            raise ValueError("The end date must be after the start date")
        if len({c.metric.strip().lower() for c in self.criteria}) != len(self.criteria):
            raise ValueError("Each success criterion needs a different metric")
        return self


class MeasurementIn(BaseModel):
    metric: str = Field(min_length=1, max_length=60)
    phase: Literal["baseline", "pilot"]
    value: float
    date: date
    note: str = Field(default="", max_length=500)


class ObservationIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class DecisionIn(BaseModel):
    decision: Literal["scale", "extend", "revise", "stop"]
    reason: str = Field(min_length=1, max_length=1000)
    new_end_date: date | None = None

    @model_validator(mode="after")
    def check(self):
        if self.decision == "extend" and self.new_end_date is None:
            raise ValueError("Extending needs a new end date")
        return self


def key_for(metric: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", metric.lower()).strip("_")[:50] or "metric"


@router.post("/api/submissions/{submission_id}/pilot/setup", response_model=SubmissionOut)
def agree_setup(submission_id: str, body: SetupIn):
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot planning",))
        pilot["setup"] = {"criteria": [c.model_dump() | {"key": key_for(c.metric)} for c in body.criteria],
                          "owner": body.owner.strip(), "start_date": body.start_date.isoformat(),
                          "end_date": body.end_date.isoformat(), "agreed_by": DEMO_REVIEWER, "agreed_at": db.now()}
        save(conn, submission_id, research)
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "pilot_setup_agreed", None, None,
                     f"Owner {body.owner.strip()}, {body.start_date} to {body.end_date}: "
                     + "; ".join(f"{c.metric} target {c.target:g} {c.unit}" for c in body.criteria))
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/pilot/measurements", response_model=SubmissionOut)
def log_measurement(submission_id: str, body: MeasurementIn):
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot planning", "Pilot running"))
        setup = pilot.get("setup")
        if not setup or body.metric not in {c["key"] for c in setup["criteria"]}:
            raise HTTPException(422, "Agree the setup first, then log against one of its metrics")
        if body.phase == "pilot" and record["status"] != "Pilot running":
            raise HTTPException(409, "Pilot measurements start once the pilot is running")
        pilot.setdefault("measurements", []).append(body.model_dump(mode="json") | {"round": pilot.get("round", 1),
                                                                                   "recorded_by": DEMO_REVIEWER})
        save(conn, submission_id, research)
        return db.get_submission(conn, submission_id)


class ImportRowIn(BaseModel):
    metric: str = Field(min_length=1, max_length=60)
    phase: Literal["baseline", "pilot"]
    value: float
    date: date


class ImportIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=200)
    rows: list[ImportRowIn] = Field(min_length=1, max_length=pilot_import.MAX_ROWS)


@router.post("/api/submissions/{submission_id}/pilot/import/preview")
async def preview_import(submission_id: str, file: UploadFile = File(...)):
    """Reads the file and shows what would be imported. Nothing is saved, and the file isn't kept."""
    data = await file.read(pilot_import.MAX_BYTES + 1)
    with db.connect() as conn:
        record, _, pilot = in_pilot(conn, submission_id, ("Pilot planning", "Pilot running"))
        setup = pilot.get("setup")
        if not setup:
            raise HTTPException(409, "Agree the pilot setup first, so the file's columns can be matched to its metrics")
        try:
            rows = pilot_import.read_table(file.filename, data)
            result = pilot_import.preview(rows, setup["criteria"], date.fromisoformat(setup["start_date"]),
                                          record["status"] == "Pilot running", current(pilot))
        except pilot_import.ImportProblem as problem:
            raise HTTPException(422, str(problem))
    return result | {"file_name": file.filename}


@router.post("/api/submissions/{submission_id}/pilot/import", response_model=SubmissionOut)
def confirm_import(submission_id: str, body: ImportIn):
    """The rows the person confirmed in the preview. Every row is checked again; all are saved, or none."""
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot planning", "Pilot running"))
        setup = pilot.get("setup")
        if not setup:
            raise HTTPException(409, "Agree the pilot setup first")
        known = {c["key"] for c in setup["criteria"]}
        readings = [{"row": i + 1, "metric": r.metric if r.metric in known else None, "metric_name": r.metric,
                     "date": r.date, "value": r.value, "phase": r.phase, "problem": None}
                    for i, r in enumerate(body.rows)]
        for r in readings:
            if r["metric"] is None:
                r["problem"] = f"“{r['metric_name']}” isn't one of the pilot's metrics"
        pilot_import.mark(readings, record["status"] == "Pilot running", current(pilot))
        problems = [f"Row {r['row']}: {r['problem']}" for r in readings if r["problem"]]
        if problems:
            raise HTTPException(422, "Nothing imported. " + "; ".join(problems[:5]))
        note = f"Imported from {body.file_name.strip()}"
        pilot.setdefault("measurements", []).extend(
            {"metric": r["metric"], "phase": r["phase"], "value": r["value"], "date": r["date"].isoformat(),
             "note": note, "round": pilot.get("round", 1), "recorded_by": DEMO_REVIEWER} for r in readings)
        save(conn, submission_id, research)
        db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "pilot_measurements_imported", None, None,
                     f"{len(readings)} readings from {body.file_name.strip()}")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/pilot/observations", response_model=SubmissionOut)
def add_observation(submission_id: str, body: ObservationIn):
    with db.connect() as conn:
        _, research, pilot = in_pilot(conn, submission_id, ("Pilot planning", "Pilot running"))
        pilot.setdefault("observations", []).append({"text": body.text.strip(), "at": db.now(), "by": DEMO_REVIEWER})
        save(conn, submission_id, research)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/pilot/start", response_model=SubmissionOut)
def start_pilot(submission_id: str):
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot planning",))
        setup = pilot.get("setup")
        if not setup:
            raise HTTPException(409, "Agree the pilot setup first: numeric targets and a named owner")
        measured = {m["metric"] for m in current(pilot) if m["phase"] == "baseline"}
        missing = [c["metric"] for c in setup["criteria"] if c["key"] not in measured]
        if missing:
            raise HTTPException(409, f"Measure the baseline first for: {', '.join(missing)}")
        pilot["started_at"] = db.now()
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET status = 'Pilot running', research_json = ? WHERE pk = ?",
                     (json.dumps(research), pk))
        db.add_event(conn, pk, DEMO_REVIEWER, "pilot_started", "Pilot planning", "Pilot running",
                     f"Round {pilot.get('round', 1)}, owner {setup['owner']}")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/pilot/evaluate", response_model=SubmissionOut)
def evaluate_pilot(submission_id: str):
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot running",))
        computed = pilot_rules.evaluate(pilot["setup"], current(pilot))
        writer, meter = pilot_rules.get_writer(), []
        context = {"problem": record["description"], "approach": research["selected_option"]["title"],
                   "partner": pilot["partner"], "observations": [o["text"] for o in pilot.get("observations", [])]}
        narrative = writer.narrative(context, computed, meter)
        pilot.setdefault("evaluations", []).append(computed | {"narrative": narrative, "round": pilot.get("round", 1),
                                                              "evaluated_at": db.now(), "status": "PROPOSED"})
        save(conn, submission_id, research)
        log_run(conn, "pilot_evaluation", submission_id, writer, meter, {"verdict": computed["verdict"]})
        db.add_event(conn, db.parse_pk(submission_id), "pilot-evaluation", "pilot_evaluated", None, None,
                     f"{computed['verdict']} → recommends {computed['recommendation']}: {computed['reason']}")
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/pilot/decide", response_model=SubmissionOut)
def decide(submission_id: str, body: DecisionIn):
    with db.connect() as conn:
        record, research, pilot = in_pilot(conn, submission_id, ("Pilot running",))
        evaluations = [e for e in pilot.get("evaluations", []) if e["round"] == pilot.get("round", 1)]
        if not evaluations:
            raise HTTPException(409, "Evaluate the pilot before deciding")
        latest = evaluations[-1]
        if body.decision == "extend" and body.new_end_date.isoformat() <= pilot["setup"]["end_date"]:
            raise HTTPException(422, "The new end date must be after the current one")
        decision = {"decision": body.decision, "reason": body.reason.strip(), "by": DEMO_REVIEWER, "at": db.now(),
                    "round": pilot.get("round", 1), "recommended": latest["recommendation"],
                    "agreed_with_recommendation": body.decision == latest["recommendation"]}
        pilot.setdefault("decisions", []).append(decision)
        if body.decision == "extend":
            pilot["setup"]["end_date"] = body.new_end_date.isoformat()
        if body.decision == "revise":
            pilot["round"] = pilot.get("round", 1) + 1   # measurements so far stay in the history
            pilot.pop("setup", None)
        new_status = NEW_STATUS[body.decision]
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET status = ?, research_json = ? WHERE pk = ?",
                     (new_status, json.dumps(research), pk))
        db.add_event(conn, pk, DEMO_REVIEWER, f"pilot_{body.decision}", record["status"], new_status,
                     f"{body.reason.strip()} (recommended: {latest['recommendation']})")
        return db.get_submission(conn, submission_id)


def current(pilot: dict) -> list[dict]:
    """Measurements from the current round only; earlier rounds stay as history."""
    return [m for m in pilot.get("measurements", []) if m.get("round", 1) == pilot.get("round", 1)]


def in_pilot(conn, submission_id: str, statuses: tuple):
    record = load(conn, submission_id)
    if record["status"] not in statuses:
        raise HTTPException(409, f"Not possible while the request is {record['status']}")
    research = record["research"]
    return record, research, research["pilot"]


def save(conn, submission_id: str, research: dict):
    conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?",
                 (json.dumps(research), db.parse_pk(submission_id)))
