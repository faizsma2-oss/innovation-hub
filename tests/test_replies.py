"""Reading the times a supplier's reply offers: found, checked in code, and offered as buttons."""
import json
from types import SimpleNamespace

from backend.meetings import replies
from test_companies import company_setup
from test_meetings import at

EMAIL = ("Hello,\n\nThanks for reaching out. Would Tuesday 10 November at 10:00 or Wednesday 11 November at 2pm "
         "work for you? Otherwise any morning the week after.\n\nBest regards")


def test_rules_reader_finds_written_times(monkeypatch):
    at(monkeypatch, "2026-11-04")
    offered = replies.offered_times(EMAIL, replies.date(2026, 11, 4))
    assert [(t["start"], t["ok"]) for t in offered["times"]] == [("2026-11-10T10:00", True), ("2026-11-11T14:00", True)]
    assert offered["times"][1]["quote"] == "Wednesday 11 November at 2pm"


def test_each_time_is_checked_in_code(monkeypatch):
    at(monkeypatch, "2026-11-04")
    text = "Options: Tuesday 11 November at 10:00, 2 November at 09:00, 9 February at 11:00, Saturday 7 November at 12:00."
    checked = {t["quote"]: t for t in replies.check([
        {"start": "2026-11-11T10:00", "timezone": None, "quote": "Tuesday 11 November at 10:00"},   # 11 Nov is a Wednesday
        {"start": "2026-11-02T09:00", "timezone": None, "quote": "2 November at 09:00"},           # in the past
        {"start": "2027-02-09T11:00", "timezone": None, "quote": "9 February at 11:00"},           # > 60 days away
        {"start": "2026-11-07T12:00", "timezone": None, "quote": "Saturday 7 November at 12:00"},  # UAE weekend
        {"start": "2026-11-12T10:00", "timezone": None, "quote": "Thursday 12 November at 10:00"},  # not in the email
    ], text)}
    assert "Wednesday, not a Tuesday" in checked["Tuesday 11 November at 10:00"]["problem"]
    assert checked["2 November at 09:00"]["problem"] == "Already in the past"
    assert "60 days" in checked["9 February at 11:00"]["problem"]
    weekend = checked["Saturday 7 November at 12:00"]
    assert weekend["ok"] and weekend["warning"] == "On the UAE weekend"
    assert checked["Thursday 12 November at 10:00"]["problem"] == "The quoted words aren't in the email"


def test_other_time_zones_are_converted_to_uae_time(monkeypatch):
    at(monkeypatch, "2026-11-04")
    london = replies.check([{"start": "2026-11-10T14:00", "timezone": "Europe/London",
                             "quote": "Tuesday 10 November, 2pm London time"}],
                           "Could we do Tuesday 10 November, 2pm London time?")[0]
    assert london["ok"] and london["start"] == "2026-11-10T18:00" and london["original"] == "2026-11-10T14:00"


class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.request = request
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=600, output_tokens=120,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def test_claude_reads_relative_dates_but_cannot_invent_times(monkeypatch):
    at(monkeypatch, "2026-11-04")
    fake = FakeClaude({"times": [
        {"start": "2026-11-10T10:00", "timezone": None, "quote": "next Tuesday at 10"},
        {"start": "2026-11-13T09:00", "timezone": None, "quote": "Friday at 9"}],          # made up
        "vague": ["any morning the week after"]})
    offered = replies.offered_times("Would next Tuesday at 10 suit you? If not, any morning the week after.",
                                    replies.date(2026, 11, 4), [], client=fake)
    assert offered["times"][0]["ok"] and offered["times"][0]["start"] == "2026-11-10T10:00"
    assert offered["times"][1]["problem"] == "The quoted words aren't in the email"
    assert offered["vague"] == ["any morning the week after"]
    assert json.loads(fake.request["messages"][0]["content"])["received_weekday"] == "wednesday"


def test_reply_on_a_meeting_offers_its_times_and_changes_the_reminder(client, monkeypatch):
    sid, names, page, email = company_setup(client)
    meeting = client.post("/api/meetings", json={"submission_id": sid, "supplier": names[0], "contact": email}).json()
    client.post(f"/api/meetings/{meeting['id']}/send-invite", json={"confirm": True, "subject": "Intro", "body": "Hello"})
    found = client.post(f"/api/meetings/{meeting['id']}/check-replies").json()
    assert found["new_replies"] == 1
    offered = found["replies"][0]["offered"]
    assert len([t for t in offered["times"] if t["ok"]]) == 2              # the demo reply offers two times
    items = client.get("/api/reminders").json()["items"]
    replied = next(i for i in items if i["kind"] == "replied" and i["meeting_id"] == meeting["id"])
    assert "2 possible times" in replied["text"]
    assert not any(i["kind"] == "follow_up" and i["meeting_id"] == meeting["id"] for i in items)
    company = client.get(f"/api/companies/{page['id']}").json()
    assert next(e for e in company["emails"] if e["direction"] == "in")["offered"]["times"]
    booked = client.post(f"/api/meetings/{meeting['id']}/book",
                         json={"start_at": offered["times"][0]["start"], "duration_min": 45}).json()
    assert booked["status"] == "scheduled" and booked["start_at"] == offered["times"][0]["start"]
