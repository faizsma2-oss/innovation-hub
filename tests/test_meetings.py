"""Meetings: contacts (official channels only), plan → sent → scheduled → debriefed, invites,
and reminders. Scripted assistant and a fake Claude: no network, no cost."""
import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from backend.meetings import assistant as assistant_module
from backend.meetings import calendar
from backend.meetings.assistant import MOCK_ASSISTANT, ClaudeMeetingAssistant, check_contacts
from backend.meetings import routes as meeting_routes
from test_evaluation import shortlisted


def plan(client, sid, supplier, **extra):
    response = client.post("/api/meetings", json={"submission_id": sid, "supplier": supplier} | extra)
    assert response.status_code == 201, response.text
    return response.json()


def at(monkeypatch, day: str, time: str = "09:00"):
    """Pretend today is `day` in Dubai."""
    monkeypatch.setattr(calendar, "today", lambda: date.fromisoformat(day))
    monkeypatch.setattr(calendar, "now_local", lambda: datetime.fromisoformat(f"{day}T{time}"))


# ── Contacts: official channels only, ranked in code ─────────────────────────

SUPPLIER = {"name": "Acme", "website": "https://www.acme.example"}
PAGE = "https://acme.example/contact"


def test_only_official_channels_with_a_retrieved_source_are_kept():
    raw = [
        {"type": "sales_email", "value": "sales@acme.example", "region": "global", "note": "", "source_url": PAGE},
        {"type": "sales_email", "value": "john.smith@acme.example", "region": "UAE", "note": "", "source_url": PAGE},
        {"type": "partnership_email", "value": "partners@acme.example", "region": "GCC", "note": "", "source_url": "https://not-retrieved.example"},
        {"type": "phone", "value": "call us", "region": "UAE", "note": "", "source_url": PAGE},
        {"type": "demo_booking_link", "value": "http://acme.example/demo", "region": "global", "note": "", "source_url": PAGE},
    ]
    kept = check_contacts(raw, SUPPLIER, {PAGE + "/"})
    assert [c["value"] for c in kept] == ["sales@acme.example"]   # personal, unsourced, malformed, non-https dropped


def test_best_route_prefers_uae_sales_and_flags_odd_domains():
    raw = [
        {"type": "general_email", "value": "info@acme.example", "region": "UAE", "note": "", "source_url": PAGE},
        {"type": "sales_email", "value": "sales.mena@acme.example", "region": "UAE", "note": "", "source_url": PAGE},
        {"type": "sales_email", "value": "sales@acme-reseller.example", "region": "global", "note": "", "source_url": PAGE},
    ]
    kept = check_contacts(raw, SUPPLIER, {PAGE})
    assert kept[0]["value"] == "sales.mena@acme.example" and kept[0]["best"]
    odd = next(c for c in kept if c["value"] == "sales@acme-reseller.example")
    assert odd["flags"] and odd["rank"] == 3


def test_find_and_add_contacts_for_a_shortlisted_supplier(client):
    sid, names = shortlisted(client)
    found = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": names[0]}).json()
    assert found["contacts"] and "fictional" in found["summary"].lower()
    added = client.post(f"/api/submissions/{sid}/contacts/add",
                        json={"supplier": names[0], "type": "sales_email", "value": "uae.sales@vendor.example",
                              "note": "From their reply"}).json()
    assert any(c["added_by"] == "demo-reviewer" for c in added["contacts"])
    again = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": names[0]}).json()
    assert any(c["value"] == "uae.sales@vendor.example" for c in again["contacts"])   # manual contacts survive a re-run
    assert client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": "Not listed"}).status_code == 422


# ── Meeting lifecycle ────────────────────────────────────────────────────────

def test_plan_drafts_agenda_and_invitation_but_sends_nothing(client):
    sid, names = shortlisted(client)
    meeting = plan(client, sid, names[0], proposed_slots=["2026-11-03T10:00", "2026-11-04T14:00"],
                   booking_link="https://outlook.office.com/bookwithme/example")
    assert meeting["status"] == "planned" and meeting["sent_at"] is None
    assert meeting["plan"]["agenda"] and meeting["plan"]["status"] == "DRAFT"
    assert "Tuesday 03 November, 10:00" in meeting["plan"]["email_body"]
    assert client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0],
                                              "booking_link": "http://insecure.example"}).status_code == 422


def test_sent_sets_follow_up_three_uae_working_days_later(client, monkeypatch):
    sid, names = shortlisted(client)
    at(monkeypatch, "2026-10-29")                          # a Thursday
    meeting = client.post(f"/api/meetings/{plan(client, sid, names[0])['id']}/sent").json()
    assert meeting["status"] == "invite_sent"
    assert meeting["reply_due"] == "2026-11-03"            # Fri, (skip Sat, Sun), Mon, Tue


def test_schedule_and_download_an_outlook_invite(client):
    sid, names = shortlisted(client)
    meeting_id = plan(client, sid, names[0])["id"]
    assert client.get(f"/api/meetings/{meeting_id}/invite.ics").status_code == 409
    client.post(f"/api/meetings/{meeting_id}/schedule", json={
        "start_at": "2026-11-03T10:00", "duration_min": 60, "teams_link": "https://teams.microsoft.com/l/meetup-join/abc"})
    response = client.get(f"/api/meetings/{meeting_id}/invite.ics")
    ics = response.text
    assert response.headers["content-type"].startswith("text/calendar")
    assert "DTSTART;TZID=Asia/Dubai:20261103T100000" in ics and "DTEND;TZID=Asia/Dubai:20261103T110000" in ics
    assert "TZOFFSETTO:+0400" in ics and "teams.microsoft.com" in ics.replace("\r\n ", "")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))   # valid line lengths for Outlook


def test_debrief_saves_actions_without_inventing_owners_or_dates(client):
    sid, names = shortlisted(client)
    meeting_id = plan(client, sid, names[0])["id"]
    client.post(f"/api/meetings/{meeting_id}/schedule", json={"start_at": "2026-11-03T10:00"})
    meeting = client.post(f"/api/meetings/{meeting_id}/debrief",
                          json={"notes": "Good call. They will send the SOC 2 report. We agreed a demo next week."}).json()
    assert meeting["status"] == "held" and meeting["debrief"]["next_steps"]
    assert meeting["debrief"]["follow_up_body"] and meeting["debrief"]["status"] == "DRAFT"


def test_cancel_needs_a_reason(client):
    sid, names = shortlisted(client)
    meeting_id = plan(client, sid, names[0])["id"]
    assert client.post(f"/api/meetings/{meeting_id}/cancel", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/meetings/{meeting_id}/cancel", json={"reason": "Supplier withdrew"}).json()["status"] == "cancelled"
    assert client.post(f"/api/meetings/{meeting_id}/sent").status_code == 409


# ── Reminders (plain code) ───────────────────────────────────────────────────

def kinds(client):
    return [item["kind"] for item in client.get("/api/reminders").json()["items"]]


def test_reminders_follow_the_meeting_through_its_life(client, monkeypatch):
    sid, names = shortlisted(client)
    at(monkeypatch, "2026-10-29")
    meeting_id = plan(client, sid, names[0])["id"]
    client.post(f"/api/meetings/{meeting_id}/sent")
    assert "follow_up" not in kinds(client)
    at(monkeypatch, "2026-11-03")
    assert "follow_up" in kinds(client)                    # no reply by the follow-up date
    client.post(f"/api/meetings/{meeting_id}/schedule", json={"start_at": "2026-11-04T10:00"})
    assert "upcoming" in kinds(client) and "follow_up" not in kinds(client)
    at(monkeypatch, "2026-11-04", "15:00")
    assert "needs_notes" in kinds(client)                  # it happened; no notes yet


def test_action_reminders_and_marking_done(client, monkeypatch):
    sid, names = shortlisted(client)
    meeting_id = plan(client, sid, names[0])["id"]
    client.post(f"/api/meetings/{meeting_id}/schedule", json={"start_at": "2026-11-03T10:00"})
    client.post(f"/api/meetings/{meeting_id}/debrief", json={"notes": "Short call about the pilot scope and next steps."})
    with meeting_routes.db.connect() as conn:                       # add two actions as the AI would
        conn.execute("INSERT INTO meeting_actions (meeting_pk, submission_pk, action, owner, due, due_text, created_at)"
                     " VALUES (?, 1, 'Send sample files', 'Sara', '2026-11-05', '5 November', 'x')", (meeting_id,))
        conn.execute("INSERT INTO meeting_actions (meeting_pk, submission_pk, action, owner, due, due_text, created_at)"
                     " VALUES (?, 1, 'Check SOC 2 report', 'UNASSIGNED', NULL, 'NO DATE AGREED', 'x')", (meeting_id,))
    at(monkeypatch, "2026-11-07")
    assert {"overdue", "no_owner"} <= set(kinds(client))
    actions = client.get(f"/api/meetings/{meeting_id}").json()["actions"]
    for action in actions:
        client.post(f"/api/actions/{action['pk']}", json={"status": "done"})
    assert not {"overdue", "no_owner"} & set(kinds(client))


def test_written_deadlines_become_dates_only_when_clear():
    ref = date(2026, 11, 3)
    assert calendar.parse_due("28 October", ref) == date(2026, 10, 28)
    assert calendar.parse_due("by Nov 12", ref) == date(2026, 11, 12)
    assert calendar.parse_due("2026-12-01", ref) == date(2026, 12, 1)
    assert calendar.parse_due("5 January", date(2026, 12, 20)) == date(2027, 1, 5)
    assert calendar.parse_due("next week", ref) is None and calendar.parse_due("NO DATE AGREED", ref) is None


# ── Claude debrief: checked like every AI answer ─────────────────────────────

class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=900,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def test_claude_debrief_updates_comparison_and_keeps_owners_honest(client, monkeypatch):
    sid, names = shortlisted(client)
    meeting_id = plan(client, sid, names[0])["id"]
    client.post(f"/api/meetings/{meeting_id}/schedule", json={"start_at": "2026-11-03T10:00"})
    notes = "Layla confirmed data stays in their Dubai region. Sara will send sample files by 10 November. Someone should review the SOC 2 report."
    monkeypatch.setattr(meeting_routes, "get_assistant", lambda: ClaudeMeetingAssistant(MOCK_ASSISTANT, client=FakeClaude({
        "summary": "Data residency confirmed verbally.", "decisions": ["Share sample files"],
        "answers": [], "risks": ["SOC 2 not yet reviewed"],
        "factor_updates": [{"factor_key": "data_residency", "finding": "Data stays in their Dubai region.", "rating": 5, "must_have_met": "yes"}],
        "actions": [{"action": "Send sample files", "owner": "Sara", "deadline": "10 November"},
                    {"action": "Review SOC 2 report", "owner": "Omar", "deadline": "Friday"}],
        "next_steps": [{"step": "Get written data-residency confirmation", "why": "Verbal only so far"}],
        "follow_up_subject": "Thanks", "follow_up_body": "Thank you. We will purchase the platform."})))
    meeting = client.post(f"/api/meetings/{meeting_id}/debrief", json={"notes": notes}).json()
    actions = {a["action"]: a for a in meeting["actions"]}
    assert actions["Send sample files"]["owner"] == "Sara" and actions["Send sample files"]["due"] == "2026-11-10"
    assert actions["Review SOC 2 report"]["owner"] == "UNASSIGNED" and actions["Review SOC 2 report"]["due"] is None
    assert meeting["debrief"]["flags"]                      # "we will purchase" is flagged in the draft
    record = client.get(f"/api/submissions/{sid}").json()
    supplier = next(s for s in record["research"]["suppliers"]["suppliers"] if s["name"] == names[0])
    assert supplier["findings"]["data_residency"]["evidence"] == "supplier (meeting, verbal)"
