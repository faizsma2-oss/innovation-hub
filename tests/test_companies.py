"""Company pages, approve-then-send email, replies, Outlook/Teams booking, transcripts and the Copilot API.
Uses the demo mailbox, and a fake Microsoft Graph for the real connector: no network."""
import json

import httpx
import pytest

from backend.m365.client import GraphM365, vtt_to_text
from test_evaluation import shortlisted


def company_setup(client):
    sid, names = shortlisted(client)
    client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": names[0]})
    companies = client.get("/api/companies").json()
    company = next(c for c in companies if c["name"] == names[0])
    page = client.get(f"/api/companies/{company['id']}").json()
    email = next(c["value"] for c in page["contacts"] if "@" in c["value"])
    return sid, names, page, email


def draft(client, company_id, to, sid, **extra):
    return client.post(f"/api/companies/{company_id}/emails",
                       json={"to": to, "subject": "Introductory call", "body": "Hello", "submission_id": sid} | extra)


def test_every_shortlisted_supplier_gets_a_company_page(client):
    sid, names, page, _ = company_setup(client)
    listed = {c["name"]: c for c in client.get("/api/companies").json()}
    assert set(names) <= set(listed)
    assert page["stage"] == "Shortlisted" and page["requests"][0]["id"] == sid
    assert page["contacts"] and page["facts"]["rank"] == 1


def test_email_only_to_an_official_contact_and_only_after_approval(client):
    sid, _, page, email = company_setup(client)
    assert draft(client, page["id"], "someone@gmail.com", sid).status_code == 422
    drafted = draft(client, page["id"], email, sid).json()["emails"][0]
    assert drafted["status"] == "DRAFT"
    send = lambda confirm: client.post(f"/api/emails/{drafted['id']}/send",
                                       json={"confirm": confirm, "subject": "Introductory call", "body": "Hello again"})
    assert send(False).status_code == 422
    sent = send(True).json()
    assert sent["emails"][0]["status"] == "SENT" and sent["emails"][0]["approved_by"]
    assert sent["emails"][0]["body"] == "Hello again"            # the approved text is what goes out
    assert sent["stage"] == "Contacted" and sent["waiting_for_reply"]
    assert send(True).status_code == 409                          # can't be sent twice


def test_replies_are_pulled_into_the_company_page_once(client):
    sid, _, page, email = company_setup(client)
    drafted = draft(client, page["id"], email, sid).json()["emails"][0]
    client.post(f"/api/emails/{drafted['id']}/send", json={"confirm": True, "subject": "Hi", "body": "Hello"})
    first = client.post(f"/api/companies/{page['id']}/check-replies").json()
    again = client.post(f"/api/companies/{page['id']}/check-replies").json()
    assert first["new_replies"] == 1 and again["new_replies"] == 0
    reply = next(e for e in again["emails"] if e["direction"] == "in")
    assert "DEMO" in reply["body"] and not again["waiting_for_reply"]


def test_meeting_invitation_sent_through_the_company_moves_the_meeting_on(client):
    sid, names, page, email = company_setup(client)
    meeting = client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0], "contact": email}).json()
    drafted = draft(client, page["id"], email, sid, meeting_id=meeting["id"]).json()["emails"][0]
    client.post(f"/api/emails/{drafted['id']}/send", json={"confirm": True, "subject": "Hi", "body": "Hello"})
    assert client.get(f"/api/meetings/{meeting['id']}").json()["status"] == "invite_sent"


def test_invitation_sent_from_the_meeting_needs_approval_and_an_official_contact(client):
    sid, names, page, email = company_setup(client)
    meeting = client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0], "contact": email}).json()
    send = lambda confirm: client.post(f"/api/meetings/{meeting['id']}/send-invite",
                                       json={"confirm": confirm, "subject": "Intro", "body": "Hello"})
    assert send(False).status_code == 422
    assert send(True).json()["status"] == "invite_sent"
    assert send(True).status_code == 409
    other = client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0], "contact": "me@gmail.com"}).json()
    assert client.post(f"/api/meetings/{other['id']}/send-invite",
                       json={"confirm": True, "subject": "Intro", "body": "Hello"}).status_code == 422


def test_booking_creates_a_teams_meeting_and_the_transcript_feeds_the_debrief(client):
    sid, names, page, email = company_setup(client)
    meeting = client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0], "contact": email}).json()
    assert client.post(f"/api/meetings/{meeting['id']}/transcript").status_code == 409
    booked = client.post(f"/api/meetings/{meeting['id']}/book", json={"start_at": "2026-11-03T10:00", "duration_min": 45}).json()
    assert booked["status"] == "scheduled" and booked["teams_link"].startswith("https://teams.microsoft.com/")
    transcript = client.post(f"/api/meetings/{meeting['id']}/transcript").json()
    assert "fictional" in transcript["source"].lower()
    held = client.post(f"/api/meetings/{meeting['id']}/debrief", json={"notes": transcript["text"]}).json()
    assert held["status"] == "held"
    assert client.get(f"/api/companies/{page['id']}").json()["stage"] == "Meeting held"


def test_notes_are_tagged_with_stage_and_topic(client):
    sid, _, page, _ = company_setup(client)
    bad = client.post(f"/api/companies/{page['id']}/notes", json={"text": "x", "tag": "Gossip"})
    assert bad.status_code == 422
    noted = client.post(f"/api/companies/{page['id']}/notes",
                        json={"text": "They need a 2-week pilot with our own data first", "tag": "Pilot needed",
                              "submission_id": sid}).json()
    assert noted["notes"][0] | {} and noted["notes"][0]["stage"] == "Shortlisted" and noted["notes"][0]["tag"] == "Pilot needed"
    assert noted["timeline"][0]["kind"] == "note"


def test_copilot_api_answers_from_the_records_and_can_require_a_key(client, monkeypatch):
    sid, names, page, _ = company_setup(client)
    client.post(f"/api/companies/{page['id']}/notes", json={"text": "Quote expected next week", "tag": "Pricing"})
    found = client.get("/api/copilot/companies", params={"search": names[0][:4]}).json()["companies"]
    assert any(c["id"] == page["id"] for c in found)
    status = client.get(f"/api/copilot/companies/{page['id']}").json()
    assert status["stage"] == "Shortlisted" and status["notes"][0]["text"] == "Quote expected next week"
    monkeypatch.setenv("HUB_COPILOT_KEY", "test-key")
    assert client.get(f"/api/copilot/companies/{page['id']}").status_code == 401
    assert client.get(f"/api/copilot/companies/{page['id']}", headers={"Authorization": "Bearer test-key"}).status_code == 200


def test_openapi_has_the_operations_the_copilot_plugin_calls(client):
    spec = client.get("/openapi.json").json()
    operations = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert {"listCompanies", "getCompanyStatus"} <= operations
    plugin = json.load(open("copilot/appPackage/hub-plugin.json"))
    assert {f["name"] for f in plugin["functions"]} == {"listCompanies", "getCompanyStatus"}
    agent = json.load(open("copilot/appPackage/declarativeAgent.json"))
    assert agent["actions"][0]["file"] == "hub-plugin.json"


# ── The real Microsoft Graph connector, against a fake Graph ─────────────────

def fake_graph():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        path = request.url.path
        if request.method == "POST" and path.endswith("/me/messages"):
            return httpx.Response(201, json={"id": "msg-1", "conversationId": "conv-1"})
        if path.endswith("/send"):
            return httpx.Response(202)
        if request.method == "GET" and path.endswith("/me/messages"):
            return httpx.Response(200, json={"value": [
                {"id": "r1", "from": {"emailAddress": {"address": "sales@acme.example"}}, "subject": "RE: Hi",
                 "bodyPreview": "Tuesday works", "receivedDateTime": "2026-11-01T08:00:00Z"},
                {"id": "r2", "from": {"emailAddress": {"address": "me@khazna.example"}}, "subject": "Hi",
                 "bodyPreview": "our own", "receivedDateTime": "2026-11-01T07:00:00Z"}]})
        if path.endswith("/me/events"):
            return httpx.Response(201, json={"id": "evt-1", "webLink": "https://outlook.office.com/x",
                                             "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/abc"}})
        return httpx.Response(404)
    return GraphM365(token="t", transport=httpx.MockTransport(handler)), calls


def test_graph_sends_from_the_users_mailbox_and_keeps_the_thread():
    graph, calls = fake_graph()
    sent = graph.send_mail("sales@acme.example", "Hi", "Hello")
    assert sent["conversation_id"] == "conv-1"
    assert [c[:2] for c in calls] == [("POST", "/v1.0/me/messages"), ("POST", "/v1.0/me/messages/msg-1/send")]
    assert calls[0][2]["toRecipients"][0]["emailAddress"]["address"] == "sales@acme.example"
    replies = graph.replies("conv-1", "sales@acme.example")
    assert [r["message_id"] for r in replies] == ["r1"]          # our own messages in the thread aren't replies


def test_graph_books_a_teams_meeting_in_uae_time():
    from datetime import datetime
    graph, calls = fake_graph()
    booked = graph.create_meeting("Intro", datetime(2026, 11, 3, 10, 0), 45, ["sales@acme.example"], "Agenda")
    body = calls[0][2]
    assert body["isOnlineMeeting"] and body["onlineMeetingProvider"] == "teamsForBusiness"
    assert body["start"] == {"dateTime": "2026-11-03T10:00:00", "timeZone": "Arabian Standard Time"}
    assert body["end"]["dateTime"] == "2026-11-03T10:45:00"
    assert booked["teams_link"] == "https://teams.microsoft.com/l/meetup-join/abc"


def test_transcript_is_turned_into_plain_text():
    vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\n<v Sara>Can you host in the UAE?</v>\n\n00:00:05.000 --> 00:00:07.000\n<v Supplier>Yes, in Dubai.</v>"
    assert vtt_to_text(vtt) == "Sara: Can you host in the UAE?\nSupplier: Yes, in Dubai."
