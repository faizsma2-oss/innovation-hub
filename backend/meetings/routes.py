"""Meetings API: supplier contacts, then each meeting from plan to debrief, plus reminders.

  find contacts (AI, official channels only) ── plan a meeting (AI agenda + email DRAFT)
     planned ──(a person sends the email from Outlook)──▶ invite_sent (follow up after 3 working days)
     invite_sent ──(they reply; time + Teams link entered)──▶ scheduled (download .ics invite)
     scheduled ──(notes or Teams recap pasted; AI debrief)──▶ held (actions, next steps, follow-up DRAFT)
     any open stage ──▶ cancelled (with a reason)

Reminders are calculated in plain code from these records; nothing is sent automatically.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from .. import db
from ..review.routes import DEMO_REVIEWER, load
from ..research import suppliers as supplier_rules
from ..research.routes import log_run
from . import calendar
from .assistant import CHANNEL_LABELS, CHANNEL_TYPES, get_assistant, rank_contacts

router = APIRouter(tags=["meetings"])
ACTIVE_STAGES = ("Research", "Pilot planning", "Pilot running")
OPEN_MEETING = ("planned", "invite_sent", "scheduled")


class SupplierIn(BaseModel):
    supplier: str = Field(min_length=1, max_length=120)


class ContactSearchIn(SupplierIn):
    fresh: bool = False          # True: search again even if contacts are on file


class ContactIn(SupplierIn):
    type: str
    value: str = Field(min_length=3, max_length=200)
    note: str = Field(default="", max_length=200)

    @field_validator("type")
    @classmethod
    def known_type(cls, value):
        if value not in CHANNEL_TYPES:
            raise ValueError(f"type must be one of {', '.join(CHANNEL_TYPES)}")
        return value


class MeetingIn(SupplierIn):
    submission_id: str
    contact: str | None = Field(default=None, max_length=200)
    proposed_slots: list[datetime] = Field(default_factory=list, max_length=4)
    booking_link: str | None = Field(default=None, max_length=300)
    internal_attendees: str = Field(default="", max_length=300)
    duration_min: int = Field(default=45, ge=15, le=180)

    @field_validator("booking_link")
    @classmethod
    def https_only(cls, value):
        if value and not value.startswith("https://"):
            raise ValueError("The booking link must start with https://")
        return value or None


class ScheduleIn(BaseModel):
    start_at: datetime
    duration_min: int = Field(default=45, ge=15, le=180)
    teams_link: str | None = Field(default=None, max_length=500)

    @field_validator("teams_link")
    @classmethod
    def https_only(cls, value):
        if value and not value.startswith("https://"):
            raise ValueError("The Teams link must start with https://")
        return value or None


class NotesIn(BaseModel):
    notes: str = Field(min_length=20, max_length=30000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ActionIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|done)$")
    owner: str | None = Field(default=None, max_length=80)
    due: date | None = None


# ── Contacts ─────────────────────────────────────────────────────────────────

@router.get("/api/meetings/contact-types")
def contact_types():
    return [{"type": t, "label": CHANNEL_LABELS[t]} for t in CHANNEL_TYPES]


@router.post("/api/submissions/{submission_id}/contacts/find")
def find_contacts(submission_id: str, body: ContactSearchIn):
    with db.connect() as conn:
        record, research, supplier = shortlisted_supplier(conn, submission_id, body.supplier)
        if not body.fresh and (on_file := contacts_on_file(conn, db.parse_pk(submission_id), body.supplier)):
            book = research.setdefault("contacts", {})
            manual = [c for c in book.get(body.supplier, {}).get("contacts", []) if c.get("added_by") != "research-ai"]
            book[body.supplier] = {"contacts": rank_contacts(on_file["contacts"] + manual),
                                   "summary": f"Reused {len(on_file['contacts'])} official contacts found for "
                                              f"{on_file['submission_id']} on {on_file['searched_at'][:10]}. No new search.",
                                   "searched_at": on_file["searched_at"], "reused_from": on_file["submission_id"],
                                   "cost_usd": 0, "searches": 0, "generated_by": "reuse"}
            save_research(conn, submission_id, research)
            db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "contacts_reused", None, None,
                         f"{body.supplier}: {len(on_file['contacts'])} contacts from {on_file['submission_id']}")
            return book[body.supplier]
        assistant, meter = get_assistant(), []
        found = assistant.find_contacts(record, supplier, meter)
        book = research.setdefault("contacts", {})
        manual = [c for c in book.get(body.supplier, {}).get("contacts", []) if c.get("added_by") != "research-ai"]
        book[body.supplier] = found | {"contacts": rank_contacts(found["contacts"] + manual), "searched_at": db.now(),
                                       "cost_usd": round(sum(m.get("cost_usd", 0) for m in meter), 4)}
        save_research(conn, submission_id, research)
        log_run(conn, "supplier_contacts", submission_id, assistant, meter, {"supplier": body.supplier})
        db.add_event(conn, db.parse_pk(submission_id), "research-ai", "contacts_found", None, None,
                     f"{body.supplier}: {len(found['contacts'])} official contact channels")
        return book[body.supplier]


@router.post("/api/submissions/{submission_id}/contacts/add")
def add_contact(submission_id: str, body: ContactIn):
    """A contact the team got another way (a business card, an email reply, a partner)."""
    with db.connect() as conn:
        _, research, _ = shortlisted_supplier(conn, submission_id, body.supplier)
        entry = research.setdefault("contacts", {}).setdefault(body.supplier, {"contacts": []})
        entry["contacts"] = rank_contacts(entry["contacts"] + [{
            "type": body.type, "label": CHANNEL_LABELS[body.type], "value": body.value.strip(), "region": "unknown",
            "note": body.note.strip(), "source_url": "", "flags": [], "added_by": DEMO_REVIEWER, "added_at": db.now()}])
        save_research(conn, submission_id, research)
        return entry


# ── Meetings ─────────────────────────────────────────────────────────────────

@router.post("/api/meetings", status_code=201)
def plan_meeting(body: MeetingIn):
    with db.connect() as conn:
        record, research, supplier = shortlisted_supplier(conn, body.submission_id, body.supplier)
        track = (research.get("evaluation") or {}).get(body.supplier, {})
        open_questions = [q["question"] for q in ((track.get("prep") or {}).get("questions") or [])] or \
            supplier.get("questions_for_supplier", [])
        slots = [slot.strftime("%A %d %B, %H:%M (UAE time)") for slot in body.proposed_slots]
        context = {"approach": research["selected_option"]["title"], "open_questions": open_questions[:8],
                   "proposed_slots": slots, "booking_link": body.booking_link, "duration_minutes": body.duration_min}
        assistant, meter = get_assistant(), []
        plan = assistant.plan(record, supplier, context, meter) | {"status": "DRAFT"}
        now = db.now()
        cursor = conn.execute(
            "INSERT INTO meetings (submission_pk, supplier, contact, title, status, proposed_slots, booking_link,"
            " internal_attendees, duration_min, plan_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?)",
            (db.parse_pk(body.submission_id), body.supplier, body.contact,
             f"{body.supplier} × Innovation team: {research['selected_option']['title']}"[:150],
             json.dumps([s.isoformat() for s in body.proposed_slots]), body.booking_link, body.internal_attendees,
             body.duration_min, json.dumps(plan), now, now))
        log_run(conn, "meeting_plan", body.submission_id, assistant, meter, {"supplier": body.supplier})
        db.add_event(conn, db.parse_pk(body.submission_id), DEMO_REVIEWER, "meeting_planned", None, None,
                     f"{body.supplier}: agenda and invitation drafted")
        return get_meeting(conn, cursor.lastrowid)


@router.get("/api/meetings")
def list_meetings():
    with db.connect() as conn:
        rows = conn.execute("SELECT pk FROM meetings ORDER BY COALESCE(start_at, created_at) DESC").fetchall()
        return [get_meeting(conn, row["pk"]) for row in rows]


@router.get("/api/meetings/{meeting_id}")
def read_meeting(meeting_id: int):
    with db.connect() as conn:
        return get_meeting(conn, meeting_id)


@router.post("/api/meetings/{meeting_id}/sent")
def mark_sent(meeting_id: int):
    """A person sent the invitation (from Outlook). Follow up if there's no reply in 3 working days."""
    with db.connect() as conn:
        meeting = in_status(conn, meeting_id, ("planned",))
        due = calendar.add_working_days(calendar.today(), 3)
        update(conn, meeting_id, status="invite_sent", sent_at=db.now(), reply_due=due.isoformat())
        event(conn, meeting, "meeting_invite_sent", f"Follow up by {due.isoformat()} if no reply")
        return get_meeting(conn, meeting_id)


@router.post("/api/meetings/{meeting_id}/schedule")
def schedule(meeting_id: int, body: ScheduleIn):
    with db.connect() as conn:
        meeting = in_status(conn, meeting_id, ("planned", "invite_sent", "scheduled"))
        update(conn, meeting_id, status="scheduled", start_at=body.start_at.strftime("%Y-%m-%dT%H:%M"),
               duration_min=body.duration_min, teams_link=body.teams_link)
        event(conn, meeting, "meeting_scheduled", f"{body.start_at.strftime('%d %b %Y %H:%M')} UAE time")
        return get_meeting(conn, meeting_id)


@router.get("/api/meetings/{meeting_id}/invite.ics")
def invite(meeting_id: int):
    with db.connect() as conn:
        meeting = get_meeting(conn, meeting_id)
    if not meeting["start_at"]:
        raise HTTPException(409, "Schedule the meeting first")
    filename = re.sub(r"[^A-Za-z0-9]+", "-", meeting["supplier"]).strip("-")[:40] or "meeting"
    return Response(calendar.invite_ics(meeting), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{filename}-meeting.ics"'})


@router.post("/api/meetings/{meeting_id}/debrief")
def debrief(meeting_id: int, body: NotesIn):
    with db.connect() as conn:
        meeting = in_status(conn, meeting_id, ("scheduled", "invite_sent", "held"))
        submission_id = f"SUB-{meeting['submission_pk']:04d}"
        record = load(conn, submission_id)
        research = record["research"]
        found = (research.get("suppliers") or {}).get("suppliers", [])
        supplier = next((s for s in found if s["name"] == meeting["supplier"]), None)
        assistant, meter = get_assistant(), []
        result = assistant.debrief(record, supplier, meeting, body.notes, meter)

        # Findings from the meeting update the supplier comparison, labelled as verbal claims.
        if supplier and result["factor_updates"] and record["status"] == "Research":
            label = f"Meeting {meeting['start_at'] or db.now()[:10]}"
            for item in result["factor_updates"]:
                supplier["findings"][item["factor_key"]] = {
                    "rating": item["rating"], "finding": item["finding"], "evidence": "supplier (meeting, verbal)",
                    "sources": [label], "must_have_met": item["must_have_met"]}
            supplier_rules.rank(found, research["suppliers"]["setup"])
            track = research.setdefault("evaluation", {}).get(meeting["supplier"])
            if track is not None and track.get("outreach") in ("not_contacted", "contacted", "meeting_booked"):
                track["outreach"] = "meeting_held"
            save_research(conn, submission_id, research)

        conn.execute("DELETE FROM meeting_actions WHERE meeting_pk = ? AND status = 'open'", (meeting_id,))
        reference = date.fromisoformat((meeting["start_at"] or db.now())[:10])
        for action in result["actions"]:
            due = calendar.parse_due(action["deadline"] if action["deadline"] != "NO DATE AGREED" else "", reference)
            conn.execute("INSERT INTO meeting_actions (meeting_pk, submission_pk, action, owner, due, due_text,"
                         " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (meeting_id, meeting["submission_pk"], action["action"], action["owner"],
                          due.isoformat() if due else None, action["deadline"], db.now()))
        update(conn, meeting_id, status="held", notes=body.notes, debrief_json=json.dumps(result | {"status": "DRAFT"}))
        log_run(conn, "meeting_debrief", submission_id, assistant, meter, {"meeting": meeting_id})
        event(conn, meeting, "meeting_debriefed",
              f"{len(result['actions'])} actions, {len(result['next_steps'])} suggested next steps")
        return get_meeting(conn, meeting_id)


@router.post("/api/meetings/{meeting_id}/cancel")
def cancel(meeting_id: int, body: ReasonIn):
    with db.connect() as conn:
        meeting = in_status(conn, meeting_id, OPEN_MEETING)
        update(conn, meeting_id, status="cancelled", cancelled_reason=body.reason.strip())
        event(conn, meeting, "meeting_cancelled", body.reason.strip())
        return get_meeting(conn, meeting_id)


@router.post("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionIn):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM meeting_actions WHERE pk = ?", (action_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Action not found")
        changes = {}
        if body.status:
            changes |= {"status": body.status, "done_at": db.now() if body.status == "done" else None}
        if body.owner is not None:
            changes["owner"] = body.owner.strip() or "UNASSIGNED"
        if body.due is not None:
            changes["due"] = body.due.isoformat()
        if changes:
            conn.execute(f"UPDATE meeting_actions SET {', '.join(f'{k} = ?' for k in changes)} WHERE pk = ?",
                         (*changes.values(), action_id))
        return dict(conn.execute("SELECT * FROM meeting_actions WHERE pk = ?", (action_id,)).fetchone())


# ── Reminders (plain code, nothing sent) ─────────────────────────────────────

@router.get("/api/reminders")
def reminders():
    today, now = calendar.today(), calendar.now_local()
    items = []
    with db.connect() as conn:
        for row in conn.execute("SELECT * FROM meetings WHERE status IN ('invite_sent', 'scheduled')"):
            ref = {"meeting_id": row["pk"], "submission_id": f"SUB-{row['submission_pk']:04d}"}
            reply = conn.execute("SELECT offered_json FROM emails WHERE meeting_pk = ? AND direction = 'in'"
                                 " ORDER BY pk DESC LIMIT 1", (row["pk"],)).fetchone() if row["status"] == "invite_sent" else None
            if reply:
                usable = [t for t in (json.loads(reply["offered_json"] or "null") or {}).get("times", []) if t["ok"]]
                items.append(ref | {"kind": "replied", "severity": "high",
                                    "text": f"{row['supplier']} replied" + (f" with {len(usable)} possible "
                                            f"{'time' if len(usable) == 1 else 'times'}: book one." if usable else
                                            ": read it and agree a time."), "due": today.isoformat()})
            elif row["status"] == "invite_sent" and row["reply_due"] and date.fromisoformat(row["reply_due"]) <= today:
                items.append(ref | {"kind": "follow_up", "severity": "high",
                                    "text": f"No reply from {row['supplier']} since {row['sent_at'][:10]}. Send a polite follow-up.",
                                    "due": row["reply_due"]})
            if row["status"] == "scheduled" and row["start_at"]:
                start = datetime.fromisoformat(row["start_at"])
                if start < now - timedelta(hours=1):
                    items.append(ref | {"kind": "needs_notes", "severity": "high",
                                        "text": f"Meeting with {row['supplier']} has happened. Paste the notes or Teams recap.",
                                        "due": row["start_at"][:10]})
                elif start <= now + timedelta(days=2):
                    items.append(ref | {"kind": "upcoming", "severity": "medium",
                                        "text": f"Meeting with {row['supplier']} on {start.strftime('%a %d %b, %H:%M')}. Review the agenda and brief.",
                                        "due": row["start_at"][:10]})
        for row in conn.execute("SELECT a.*, m.supplier FROM meeting_actions a JOIN meetings m ON m.pk = a.meeting_pk"
                                " WHERE a.status = 'open'"):
            ref = {"meeting_id": row["meeting_pk"], "submission_id": f"SUB-{row['submission_pk']:04d}",
                   "action_id": row["pk"]}
            if row["owner"] == "UNASSIGNED":
                items.append(ref | {"kind": "no_owner", "severity": "medium",
                                    "text": f"Action from the {row['supplier']} meeting has no owner: {row['action']}",
                                    "due": row["due"]})
            if row["due"] and date.fromisoformat(row["due"]) < today:
                items.append(ref | {"kind": "overdue", "severity": "high",
                                    "text": f"Overdue since {row['due']}: {row['action']} ({row['owner']})", "due": row["due"]})
            elif row["due"] and date.fromisoformat(row["due"]) <= today + timedelta(days=1):
                items.append(ref | {"kind": "due_soon", "severity": "medium",
                                    "text": f"Due {row['due']}: {row['action']} ({row['owner']})", "due": row["due"]})
        for row in conn.execute("SELECT pk, research_json FROM submissions WHERE status = 'Pilot running'"):
            pilot = json.loads(row["research_json"]).get("pilot", {})
            end = (pilot.get("setup") or {}).get("end_date")
            if end and date.fromisoformat(end) < today:
                items.append({"kind": "pilot_ended", "severity": "high", "submission_id": f"SUB-{row['pk']:04d}",
                              "text": f"The pilot with {pilot.get('partner')} passed its end date ({end}). Evaluate it.",
                              "due": end})
        for row in conn.execute("SELECT pk, status, research_json FROM submissions WHERE status IN ('Scaling', 'In operation')"):
            scale = json.loads(row["research_json"]).get("scale") or {}
            sid = f"SUB-{row['pk']:04d}"
            case = scale.get("business_case")
            if row["status"] == "Scaling" and case and case["status"] == "AWAITING DECISION":
                items.append({"kind": "decision", "severity": "high", "submission_id": sid,
                              "text": f"Business case ready for a decision ({case['calc']['verdict'].lower()}).",
                              "due": case["prepared_at"][:10]})
            for checkin in scale.get("checkins", []):
                if not checkin.get("result") and date.fromisoformat(checkin["due"]) <= today:
                    items.append({"kind": "checkin", "severity": "high", "submission_id": sid,
                                  "text": f"{checkin['label']} benefits check-in is due: did the improvement hold?",
                                  "due": checkin["due"]})
        latest = conn.execute("SELECT pk, report_json FROM reports ORDER BY pk DESC LIMIT 1").fetchone()
        if latest:
            report = json.loads(latest["report_json"])
            if report.get("trigger") == "automatic" and report["status"] == "DRAFT":
                items.append({"kind": "report", "severity": "medium", "report_id": latest["pk"],
                              "text": f"The weekly report for {report['period']} is ready: check it and send it to management.",
                              "due": report["generated_at"][:10]})
    order = {"high": 0, "medium": 1}
    items.sort(key=lambda item: (order[item["severity"]], item.get("due") or "9999"))
    return {"today": today.isoformat(), "items": items}


# ── Helpers ──────────────────────────────────────────────────────────────────

CONTACTS_FRESH_DAYS = 90


def contacts_on_file(conn, submission_pk: int, supplier: str) -> dict | None:
    """The most recent official contacts found for this supplier in another request, if under 90 days old."""
    best = None
    for row in conn.execute("SELECT pk, research_json FROM submissions WHERE pk != ? AND research_json IS NOT NULL",
                            (submission_pk,)):
        book = (json.loads(row["research_json"]).get("contacts") or {}).get(supplier) or {}
        found = book.get("contacts", [])                  # found by the Research AI or added by the team
        stamp = book.get("searched_at") or max((c.get("added_at") or "" for c in found), default="") or None
        if not found or not stamp or book.get("reused_from"):
            continue
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).days
        if age <= CONTACTS_FRESH_DAYS and (best is None or stamp > best["searched_at"]):
            best = {"submission_id": f"SUB-{row['pk']:04d}", "searched_at": stamp, "contacts": found}
    return best


def shortlisted_supplier(conn, submission_id: str, name: str):
    record = load(conn, submission_id)
    if record["status"] not in ACTIVE_STAGES:
        raise HTTPException(409, "Supplier meetings happen during research and piloting")
    research = record["research"]
    found = research.get("suppliers") or {}
    if name not in ((found.get("shortlist") or {}).get("names") or []):
        raise HTTPException(422, "Contact and meet only suppliers on the saved shortlist")
    return record, research, next(s for s in found["suppliers"] if s["name"] == name)


def get_meeting(conn, meeting_id: int) -> dict:
    row = conn.execute("SELECT * FROM meetings WHERE pk = ?", (meeting_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Meeting not found")
    meeting = dict(row)
    meeting["id"] = meeting.pop("pk")
    meeting["submission_id"] = f"SUB-{meeting['submission_pk']:04d}"
    for field in ("plan", "debrief"):
        raw = meeting.pop(f"{field}_json")
        meeting[field] = json.loads(raw) if raw else None
    meeting["proposed_slots"] = json.loads(meeting["proposed_slots"] or "[]")
    meeting["actions"] = [dict(a) for a in conn.execute(
        "SELECT * FROM meeting_actions WHERE meeting_pk = ? ORDER BY pk", (meeting_id,))]
    meeting["replies"] = [{"id": r["pk"], "from": r["address"], "subject": r["subject"], "body": r["body"], "at": r["at"],
                           "offered": json.loads(r["offered_json"] or "null")}
                          for r in conn.execute("SELECT * FROM emails WHERE meeting_pk = ? AND direction = 'in' ORDER BY pk",
                                                (meeting_id,))]
    return meeting


def in_status(conn, meeting_id: int, allowed: tuple) -> dict:
    meeting = get_meeting(conn, meeting_id)
    if meeting["status"] not in allowed:
        raise HTTPException(409, f"Not possible while the meeting is {meeting['status']}")
    return meeting


def update(conn, meeting_id: int, **fields):
    fields["updated_at"] = db.now()
    conn.execute(f"UPDATE meetings SET {', '.join(f'{k} = ?' for k in fields)} WHERE pk = ?",
                 (*fields.values(), meeting_id))


def event(conn, meeting: dict, name: str, details: str):
    db.add_event(conn, meeting["submission_pk"], DEMO_REVIEWER, name, None, None, f"{meeting['supplier']}: {details}")


def save_research(conn, submission_id: str, research: dict):
    conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?",
                 (json.dumps(research), db.parse_pk(submission_id)))
