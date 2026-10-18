"""One page per supplier company: details, official contacts, every email, reply and meeting, open actions
and the team's notes, from the first shortlist to the last step. Plus the Microsoft 365 actions behind it.

  shortlisted ──▶ contacted (email approved and sent) ──▶ meeting held ──▶ pilot partner ──▶ scaling ──▶ in operation
                                                                  └──▶ not chosen / stopped

Guardrails, in code:
  - an email goes out only after a person approves it (`confirm: true`), from their own mailbox
  - only to an official contact already on the company's page (no addresses made up by anyone)
  - replies and Teams transcripts come in as drafts for a person to read; nothing acts on them by itself
"""
import json
import os
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..m365.client import M365Error, get_client, mode
from ..meetings import calendar
from ..review.routes import DEMO_REVIEWER

router = APIRouter(tags=["companies"])

TAGS = ["General", "Requirement", "Pilot needed", "Pricing", "Security", "Risk", "Decision", "Next step"]
STAGES = ["Shortlisted", "Contacted", "Meeting held", "Pilot partner", "Scaling", "In operation"]
EMAIL_TYPES = ("sales_email", "partnership_email", "general_email")


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    tag: str = "General"
    submission_id: str | None = None


class DraftIn(BaseModel):
    to: str = Field(min_length=3, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    submission_id: str | None = None
    meeting_id: int | None = None


class SendIn(BaseModel):
    confirm: bool                                   # the person clicked "Approve & send"
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class BookIn(BaseModel):
    start_at: datetime
    duration_min: int = Field(default=45, ge=15, le=180)


# ── Companies ────────────────────────────────────────────────────────────────

@router.get("/api/companies")
def list_companies():
    with db.connect() as conn:
        sync(conn)
        return [summary(conn, row) for row in conn.execute("SELECT * FROM companies ORDER BY name")]


@router.get("/api/companies/{company_id}")
def read_company(company_id: str):
    with db.connect() as conn:
        sync(conn)
        return detail(conn, company_row(conn, company_id))


@router.post("/api/companies/{company_id}/notes", status_code=201)
def add_note(company_id: str, body: NoteIn):
    if body.tag not in TAGS:
        raise HTTPException(422, f"tag must be one of {', '.join(TAGS)}")
    with db.connect() as conn:
        company = company_row(conn, company_id)
        links = requests_for(conn, company["name"])
        if body.submission_id and body.submission_id not in {r["id"] for r in links}:
            raise HTTPException(422, "That request doesn't involve this company")
        link = next((r for r in links if r["id"] == body.submission_id), None) or (links[0] if links else None)
        conn.execute("INSERT INTO company_notes (company_pk, submission_pk, stage, tag, text, author, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (company["pk"], db.parse_pk(link["id"]) if link else None, link["stage"] if link else "Shortlisted",
                      body.tag, body.text.strip(), DEMO_REVIEWER, db.now()))
        return detail(conn, company)


# ── Email: draft → a person approves → sent from their Outlook ───────────────

@router.post("/api/companies/{company_id}/emails", status_code=201)
def draft_email(company_id: str, body: DraftIn):
    with db.connect() as conn:
        company = company_row(conn, company_id)
        to = official_address(conn, company, body.to)
        conn.execute("INSERT INTO emails (company_pk, submission_pk, meeting_pk, direction, status, address, subject, body, at)"
                     " VALUES (?, ?, ?, 'out', 'DRAFT', ?, ?, ?, ?)",
                     (company["pk"], db.parse_pk(body.submission_id) if body.submission_id else None, body.meeting_id,
                      to, body.subject.strip(), body.body.strip(), db.now()))
        return detail(conn, company)


@router.post("/api/emails/{email_id}/send")
def approve_and_send(email_id: int, body: SendIn):
    if not body.confirm:
        raise HTTPException(422, "A person has to approve the email before it is sent")
    with db.connect() as conn:
        email = conn.execute("SELECT * FROM emails WHERE pk = ?", (email_id,)).fetchone()
        if email is None or email["status"] != "DRAFT":
            raise HTTPException(409, "Only a draft can be approved and sent")
        company = conn.execute("SELECT * FROM companies WHERE pk = ?", (email["company_pk"],)).fetchone()
        to = official_address(conn, company, email["address"])
        try:
            sent = get_client(conn).send_mail(to, body.subject.strip(), body.body.strip())
        except M365Error as error:
            raise HTTPException(502, str(error))
        conn.execute("UPDATE emails SET status = 'SENT', subject = ?, body = ?, m365_id = ?, conversation_id = ?,"
                     " approved_by = ?, at = ? WHERE pk = ?",
                     (body.subject.strip(), body.body.strip(), sent["message_id"], sent["conversation_id"],
                      DEMO_REVIEWER, sent["sent_at"], email_id))
        if email["submission_pk"]:
            db.add_event(conn, email["submission_pk"], DEMO_REVIEWER, "email_sent", None, None,
                         f"{company['name']}: “{body.subject.strip()}” approved and sent to {to}")
        if email["meeting_pk"]:
            meeting = conn.execute("SELECT * FROM meetings WHERE pk = ?", (email["meeting_pk"],)).fetchone()
            if meeting and meeting["status"] == "planned":
                due = calendar.add_working_days(calendar.today(), 3)
                conn.execute("UPDATE meetings SET status = 'invite_sent', sent_at = ?, reply_due = ?, updated_at = ? WHERE pk = ?",
                             (db.now(), due.isoformat(), db.now(), email["meeting_pk"]))
        return detail(conn, company)


@router.post("/api/meetings/{meeting_id}/send-invite")
def send_invitation(meeting_id: int, body: SendIn):
    """The meeting invitation, approved by a person and sent to the meeting's official contact."""
    with db.connect() as conn:
        meeting = conn.execute("SELECT * FROM meetings WHERE pk = ?", (meeting_id,)).fetchone()
        if meeting is None:
            raise HTTPException(404, "Meeting not found")
        if meeting["status"] != "planned":
            raise HTTPException(409, "The invitation has already gone out")
        company = ensure_company(conn, meeting["supplier"])
        to = official_address(conn, company, meeting["contact"])
        cursor = conn.execute("INSERT INTO emails (company_pk, submission_pk, meeting_pk, direction, status, address,"
                              " subject, body, at) VALUES (?, ?, ?, 'out', 'DRAFT', ?, ?, ?, ?)",
                              (company["pk"], meeting["submission_pk"], meeting_id, to, body.subject, body.body, db.now()))
        email_id = cursor.lastrowid
    approve_and_send(email_id, body)
    from ..meetings.routes import read_meeting
    return read_meeting(meeting_id)


@router.post("/api/companies/{company_id}/check-replies")
def check_replies(company_id: str):
    """Pull replies to the emails we sent. They're shown to the team; nothing acts on them automatically."""
    with db.connect() as conn:
        company = company_row(conn, company_id)
        client, new = get_client(conn), 0
        for sent in conn.execute("SELECT * FROM emails WHERE company_pk = ? AND status = 'SENT' AND conversation_id IS NOT NULL",
                                 (company["pk"],)).fetchall():
            try:
                replies = client.replies(sent["conversation_id"], sent["address"])
            except M365Error as error:
                raise HTTPException(502, str(error))
            for reply in replies:
                if conn.execute("SELECT 1 FROM emails WHERE m365_id = ? AND direction = 'in'", (reply["message_id"],)).fetchone():
                    continue
                conn.execute("INSERT INTO emails (company_pk, submission_pk, meeting_pk, direction, status, address, subject,"
                             " body, m365_id, conversation_id, at) VALUES (?, ?, ?, 'in', 'RECEIVED', ?, ?, ?, ?, ?, ?)",
                             (company["pk"], sent["submission_pk"], sent["meeting_pk"], reply["from"], reply["subject"][:200],
                              reply["body"][:10000], reply["message_id"], sent["conversation_id"], reply["received_at"]))
                new += 1
        return detail(conn, company) | {"new_replies": new}


# ── Meetings booked through Outlook with a Teams link, and the Teams transcript ──

@router.post("/api/meetings/{meeting_id}/book")
def book_meeting(meeting_id: int, body: BookIn):
    with db.connect() as conn:
        meeting = conn.execute("SELECT * FROM meetings WHERE pk = ?", (meeting_id,)).fetchone()
        if meeting is None:
            raise HTTPException(404, "Meeting not found")
        if meeting["status"] not in ("planned", "invite_sent", "scheduled"):
            raise HTTPException(409, f"Not possible while the meeting is {meeting['status']}")
        company = ensure_company(conn, meeting["supplier"])
        attendees = [official_address(conn, company, meeting["contact"])] if is_email(meeting["contact"]) else []
        plan = json.loads(meeting["plan_json"] or "{}")
        agenda = "\n".join(f"- {a['item']} ({a['minutes']} min)" for a in plan.get("agenda", []))
        try:
            booked = get_client(conn).create_meeting(meeting["title"], body.start_at, body.duration_min, attendees,
                                                     f"Agenda\n{agenda}" if agenda else meeting["title"])
        except M365Error as error:
            raise HTTPException(502, str(error))
        conn.execute("UPDATE meetings SET status = 'scheduled', start_at = ?, duration_min = ?, teams_link = ?,"
                     " m365_event_id = ?, updated_at = ? WHERE pk = ?",
                     (body.start_at.strftime("%Y-%m-%dT%H:%M"), body.duration_min, booked["teams_link"],
                      booked["event_id"], db.now(), meeting_id))
        db.add_event(conn, meeting["submission_pk"], DEMO_REVIEWER, "meeting_booked", None, None,
                     f"{meeting['supplier']}: Teams meeting booked in Outlook for {body.start_at:%d %b %Y %H:%M} UAE time"
                     f"{' with ' + attendees[0] if attendees else ''}")
    from ..meetings.routes import read_meeting
    return read_meeting(meeting_id)


@router.post("/api/meetings/{meeting_id}/transcript")
def fetch_transcript(meeting_id: int):
    """Returns the Teams transcript as text for a person to check, then debrief. It is not saved by itself."""
    with db.connect() as conn:
        meeting = conn.execute("SELECT * FROM meetings WHERE pk = ?", (meeting_id,)).fetchone()
        if meeting is None or not meeting["teams_link"]:
            raise HTTPException(409, "Book the meeting with a Teams link first")
        try:
            text = get_client(conn).transcript(meeting["teams_link"], meeting["supplier"])
        except M365Error as error:
            raise HTTPException(502, str(error))
        if not text:
            raise HTTPException(404, "No transcript yet. Transcription has to be turned on in the meeting")
        return {"text": text[:30000], "source": "Teams transcript" if mode() == "graph" else "Demo transcript (fictional)"}


@router.get("/api/m365/status")
def m365_status():
    return {"mode": mode(), "label": "Microsoft 365 (Outlook and Teams)" if mode() == "graph" else "Demo mailbox (fictional)",
            "copilot_key_required": bool(os.environ.get("HUB_COPILOT_KEY"))}


# ── For the Copilot agent: short, factual answers about each company ─────────

def copilot_key(authorization: str | None, x_api_key: str | None):
    expected = os.environ.get("HUB_COPILOT_KEY")
    given = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    if expected and given != expected:
        raise HTTPException(401, "API key required")


@router.get("/api/copilot/companies", operation_id="listCompanies",
            summary="List supplier companies the innovation team is working with, with stage and next step")
def copilot_companies(search: str = "", authorization: str | None = Header(default=None),
                      x_api_key: str | None = Header(default=None)):
    copilot_key(authorization, x_api_key)
    with db.connect() as conn:
        sync(conn)
        rows = conn.execute("SELECT * FROM companies WHERE name LIKE ? ORDER BY name", (f"%{search.strip()}%",)).fetchall()
        return {"companies": [summary(conn, row) for row in rows[:20]]}


@router.get("/api/copilot/companies/{company_id}", operation_id="getCompanyStatus",
            summary="Where the team stands with one supplier: stage, contacts, emails, meetings, actions and notes")
def copilot_company(company_id: str, authorization: str | None = Header(default=None),
                    x_api_key: str | None = Header(default=None)):
    copilot_key(authorization, x_api_key)
    with db.connect() as conn:
        sync(conn)
        company = detail(conn, company_row(conn, company_id))
    return {key: company[key] for key in ("id", "name", "website", "country", "stage", "requests", "next_meeting",
                                          "last_contact", "actions", "facts")} | {
        "contacts": [{"label": c["label"], "value": c["value"]} for c in company["contacts"][:5]],
        "recent_emails": [{k: e[k] for k in ("direction", "status", "subject", "at")} for e in company["emails"][:5]],
        "meetings": [{k: m[k] for k in ("title", "status", "start_at", "summary")} for m in company["meetings"][:5]],
        "notes": [{k: n[k] for k in ("stage", "tag", "text", "created_at")} for n in company["notes"][:10]],
        "source": "Innovation Hub records (fictional demo data)"}


@router.get("/api/copilot/overdue", operation_id="listOverdue",
            summary="What is overdue or slipping: actions, unanswered supplier emails, missing meeting notes, pilots and check-ins")
def copilot_overdue(owner: str = "", authorization: str | None = Header(default=None),
                    x_api_key: str | None = Header(default=None)):
    """The same rules as the Today panel, without the 'coming up' items. Optionally for one owner."""
    copilot_key(authorization, x_api_key)
    from ..meetings.routes import reminders
    with db.connect() as conn:
        actions = {row["pk"]: dict(row) for row in conn.execute("SELECT pk, action, owner, due FROM meeting_actions")}
        titles = {f"SUB-{row['pk']:04d}": row["title"] for row in conn.execute("SELECT pk, title FROM submissions")}
    today = calendar.today()
    items = []
    for item in reminders()["items"]:
        if item["kind"] in ("upcoming", "due_soon", "decision"):
            continue                                  # not overdue; decisions have their own question
        action = actions.get(item.get("action_id")) or {}
        due = item.get("due")
        late = (today - datetime.fromisoformat(due[:10]).date()).days if due else None
        items.append({"what": item["text"], "kind": item["kind"], "owner": action.get("owner") or "Innovation team",
                      "due": due, "days_late": late if late and late > 0 else 0,
                      "request": item.get("submission_id"), "request_title": titles.get(item.get("submission_id"))})
    if owner.strip():
        items = [i for i in items if owner.strip().lower() in i["owner"].lower()]
    return {"today": today.isoformat(), "count": len(items), "items": items,
            "source": "Innovation Hub records, same rules as the Today panel (fictional demo data)"}


@router.get("/api/copilot/decisions", operation_id="listDecisionsNeeded",
            summary="Decisions waiting on people: business cases, pilot decisions and employee-requested reviews")
def copilot_decisions(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    """The same rules as the weekly report. Says who decides; the Hub doesn't yet know who is asking."""
    copilot_key(authorization, x_api_key)
    from ..reports.routes import decisions_needed, innovation_records
    with db.connect() as conn:
        records = {r["id"]: r for r in innovation_records(conn)}
    decisions = decisions_needed(records)
    today = calendar.today()
    for d in decisions:
        since = d.get("waiting_since")
        d["days_waiting"] = (today - datetime.fromisoformat(since).date()).days if since else None
    return {"today": today.isoformat(), "count": len(decisions), "decisions": decisions,
            "note": "Decisions are made in the Innovation Hub, not in Copilot.",
            "source": "Innovation Hub records, same rules as the weekly report (fictional demo data)"}


# ── Building the pages ───────────────────────────────────────────────────────

def sync(conn):
    """Every shortlisted supplier, meeting partner or pilot partner gets a company page."""
    for row in conn.execute("SELECT research_json FROM submissions WHERE research_json IS NOT NULL").fetchall():
        research = json.loads(row["research_json"])
        found = research.get("suppliers") or {}
        names = set((found.get("shortlist") or {}).get("names") or []) | set(research.get("contacts") or {})
        if (research.get("pilot") or {}).get("partner"):
            names.add(research["pilot"]["partner"])
        for name in names:
            supplier = next((s for s in found.get("suppliers", []) if s["name"] == name), {})
            ensure_company(conn, name, supplier.get("website"), supplier.get("headquarters"))
    for row in conn.execute("SELECT DISTINCT supplier FROM meetings").fetchall():
        ensure_company(conn, row["supplier"])


def ensure_company(conn, name: str, website: str | None = None, country: str | None = None):
    conn.execute("INSERT OR IGNORE INTO companies (name, website, country, created_at) VALUES (?, ?, ?, ?)",
                 (name, website, country, db.now()))
    if website or country:
        conn.execute("UPDATE companies SET website = COALESCE(website, ?), country = COALESCE(country, ?) WHERE name = ?",
                     (website, country, name))
    return conn.execute("SELECT * FROM companies WHERE name = ?", (name,)).fetchone()


def company_row(conn, company_id: str):
    try:
        pk = int(company_id.removeprefix("CO-"))
    except ValueError:
        raise HTTPException(404, "Company not found")
    row = conn.execute("SELECT * FROM companies WHERE pk = ?", (pk,)).fetchone()
    if row is None:
        raise HTTPException(404, "Company not found")
    return row


def requests_for(conn, name: str) -> list[dict]:
    """Each request this company is part of, and how far the relationship got in it."""
    links = []
    for row in conn.execute("SELECT * FROM submissions WHERE research_json IS NOT NULL ORDER BY pk").fetchall():
        record = db.to_public(row)
        research = record["research"] or {}
        shortlist = set(((research.get("suppliers") or {}).get("shortlist") or {}).get("names") or [])
        partner = (research.get("pilot") or {}).get("partner")
        if name not in shortlist and name != partner and name not in (research.get("contacts") or {}):
            continue
        meetings = conn.execute("SELECT status FROM meetings WHERE submission_pk = ? AND supplier = ? COLLATE NOCASE",
                                (row["pk"], name)).fetchall()
        sent = conn.execute("SELECT 1 FROM emails e JOIN companies c ON c.pk = e.company_pk WHERE e.submission_pk = ?"
                            " AND c.name = ? AND e.status IN ('SENT', 'RECEIVED')", (row["pk"], name)).fetchone()
        if name == partner:
            stage = {"Pilot planning": "Pilot partner", "Pilot running": "Pilot partner", "Scaling": "Scaling",
                     "Rolling out": "Scaling", "In operation": "In operation", "Stopped": "Stopped"}.get(record["status"], "Pilot partner")
        elif partner or record["status"] in ("Stopped", "In operation", "Rolling out", "Scaling"):
            stage = "Not chosen"
        elif any(m["status"] == "held" for m in meetings):
            stage = "Meeting held"
        elif sent or any(m["status"] in ("invite_sent", "scheduled") for m in meetings):
            stage = "Contacted"
        else:
            stage = "Shortlisted"
        links.append({"id": record["id"], "title": record["title"], "status": record["status"], "stage": stage})
    return links


def best_stage(links: list[dict]) -> str:
    stages = [l["stage"] for l in links]
    ranked = [s for s in STAGES if s in stages]
    return ranked[-1] if ranked else (stages[0] if stages else "Shortlisted")


def contacts_for(conn, name: str) -> list[dict]:
    seen, contacts = set(), []
    for row in conn.execute("SELECT research_json FROM submissions WHERE research_json IS NOT NULL").fetchall():
        book = (json.loads(row["research_json"]).get("contacts") or {}).get(name) or {}
        for contact in book.get("contacts", []):
            if contact["value"].lower() not in seen:
                seen.add(contact["value"].lower())
                contacts.append(contact)
    return sorted(contacts, key=lambda c: c.get("rank", 99))


def official_address(conn, company, address: str | None) -> str:
    """Only an email address already on the company's page as an official channel, never one typed in freely."""
    address = (address or "").strip()
    allowed = {c["value"].lower() for c in contacts_for(conn, company["name"]) if is_email(c["value"])}
    if address.lower() not in allowed:
        raise HTTPException(422, "Email only an official contact on this company's page. Add the contact first")
    return address


def is_email(value: str | None) -> bool:
    return bool(value) and "@" in value and " " not in value.strip()


def meetings_for(conn, name: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM meetings WHERE supplier = ? COLLATE NOCASE ORDER BY COALESCE(start_at, created_at) DESC",
                        (name,)).fetchall()
    result = []
    for m in rows:
        debrief = json.loads(m["debrief_json"]) if m["debrief_json"] else None
        result.append({"id": m["pk"], "submission_id": f"SUB-{m['submission_pk']:04d}", "title": m["title"],
                       "status": m["status"], "start_at": m["start_at"], "teams_link": m["teams_link"],
                       "booked_in_outlook": bool(m["m365_event_id"]),
                       "summary": (debrief or {}).get("summary")})
    return result


def summary(conn, company) -> dict:
    links = requests_for(conn, company["name"])
    meetings = meetings_for(conn, company["name"])
    upcoming = sorted((m for m in meetings if m["status"] == "scheduled" and m["start_at"]), key=lambda m: m["start_at"])
    last = conn.execute("SELECT MAX(at) FROM emails WHERE company_pk = ? AND status != 'DRAFT'", (company["pk"],)).fetchone()[0]
    actions = open_actions(conn, company["name"])
    return {"id": f"CO-{company['pk']:04d}", "name": company["name"], "website": company["website"],
            "country": company["country"], "stage": best_stage(links), "requests": links,
            "last_contact": last, "next_meeting": upcoming[0]["start_at"] if upcoming else None,
            "open_actions": len(actions),
            "drafts": conn.execute("SELECT COUNT(*) FROM emails WHERE company_pk = ? AND status = 'DRAFT'",
                                   (company["pk"],)).fetchone()[0],
            "waiting_for_reply": bool(conn.execute(
                "SELECT 1 FROM emails o WHERE o.company_pk = ? AND o.status = 'SENT' AND NOT EXISTS (SELECT 1 FROM emails i"
                " WHERE i.conversation_id = o.conversation_id AND i.direction = 'in')", (company["pk"],)).fetchone())}


def open_actions(conn, name: str) -> list[dict]:
    return [dict(a) for a in conn.execute(
        "SELECT a.pk, a.action, a.owner, a.due FROM meeting_actions a JOIN meetings m ON m.pk = a.meeting_pk"
        " WHERE m.supplier = ? COLLATE NOCASE AND a.status = 'open' ORDER BY a.due IS NULL, a.due", (name,))]


def facts_for(conn, name: str) -> dict | None:
    """What the supplier research found, from the most recent request that compared this company."""
    for row in conn.execute("SELECT research_json FROM submissions WHERE research_json IS NOT NULL ORDER BY pk DESC").fetchall():
        supplier = next((s for s in ((json.loads(row["research_json"]).get("suppliers") or {}).get("suppliers") or [])
                         if s["name"] == name), None)
        if supplier:
            return {"offering": supplier.get("offering"), "cost": supplier.get("cost"), "rank": supplier.get("rank"),
                    "fit_score": supplier.get("fit_score"), "eligibility": supplier.get("eligibility"),
                    "uae_presence": supplier.get("uae_presence"), "must_haves": supplier.get("must_haves")}
    return None


def detail(conn, company) -> dict:
    base = summary(conn, company)
    emails = [dict(e) for e in conn.execute("SELECT * FROM emails WHERE company_pk = ? ORDER BY at DESC, pk DESC", (company["pk"],))]
    for e in emails:
        e["id"] = e.pop("pk")
        e["submission_id"] = f"SUB-{e['submission_pk']:04d}" if e["submission_pk"] else None
    notes = [dict(n) | {"submission_id": f"SUB-{n['submission_pk']:04d}" if n["submission_pk"] else None}
             for n in conn.execute("SELECT * FROM company_notes WHERE company_pk = ? ORDER BY pk DESC", (company["pk"],))]
    meetings = meetings_for(conn, company["name"])
    timeline = ([{"at": n["created_at"], "kind": "note", "text": f"{n['tag']}: {n['text']}", "stage": n["stage"]} for n in notes]
                + [{"at": e["at"], "kind": "email_" + e["direction"],
                    "text": f"{'Draft' if e['status'] == 'DRAFT' else 'Sent' if e['direction'] == 'out' else 'Reply'}: {e['subject']}"}
                   for e in emails]
                + [{"at": m["start_at"] or "", "kind": "meeting", "text": f"Meeting {m['status']}: {m['title']}"} for m in meetings])
    timeline.sort(key=lambda item: item["at"] or "", reverse=True)
    return base | {"contacts": contacts_for(conn, company["name"]), "emails": emails, "meetings": meetings,
                   "notes": notes, "actions": open_actions(conn, company["name"]), "open_actions": len(open_actions(conn, company["name"])),
                   "facts": facts_for(conn, company["name"]), "timeline": timeline, "tags": TAGS,
                   "m365": {"mode": mode()}}
