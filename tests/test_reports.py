"""The weekly report prepares itself every Monday from 08:00 UAE time, once per week, as a DRAFT
that a person checks and marks as sent."""
import asyncio

from backend.reports import routes as reports
from test_meetings import at


def due(client):
    return client.post("/api/reports/due").json()


def test_not_due_before_monday_8am_then_prepared_once(client, monkeypatch):
    at(monkeypatch, "2026-11-04", "10:00")                   # Wednesday: a report on request (up to 4 Nov)
    client.post("/api/reports/weekly")
    at(monkeypatch, "2026-11-09", "07:59")                   # Monday, before 08:00: the week due is still covered
    assert due(client) == {"prepared": False, "next_due": "2026-11-09T08:00"}
    at(monkeypatch, "2026-11-09", "08:01")
    assert due(client)["prepared"] is True
    assert due(client)["prepared"] is False                  # never twice for the same week
    latest = client.get("/api/reports").json()[0]
    assert latest["trigger"] == "automatic" and latest["status"] == "DRAFT"
    assert latest["period"] == "2026-11-02 to 2026-11-08"    # last week, Monday to Sunday
    at(monkeypatch, "2026-11-12", "10:00")                   # later that week: nothing new
    assert due(client) == {"prepared": False, "next_due": "2026-11-16T08:00"}


def test_a_report_already_covering_last_week_is_not_repeated(client, monkeypatch):
    at(monkeypatch, "2026-11-08", "18:00")                   # Sunday evening, prepared by hand
    client.post("/api/reports/weekly")
    at(monkeypatch, "2026-11-09", "09:00")
    assert due(client)["prepared"] is False


def test_today_reminder_until_marked_sent(client, monkeypatch):
    at(monkeypatch, "2026-11-09", "09:00")
    due(client)
    reminders = client.get("/api/reminders").json()["items"]
    item = next(i for i in reminders if i["kind"] == "report")
    assert "ready" in item["text"] and "2026-11-02 to 2026-11-08" in item["text"]
    # Nothing in this test happened in that week, so nothing may be counted in it.
    report = client.get("/api/reports").json()[0]
    assert report["moved"] == [] and report["results"] == [] and report["ai_spend_usd"] == 0
    sent = client.post(f"/api/reports/{item['report_id']}/sent").json()
    assert sent["status"] == "SENT" and sent["sent_at"]
    assert not any(i["kind"] == "report" for i in client.get("/api/reminders").json()["items"])
    assert client.post("/api/reports/999/sent").status_code == 404


def test_a_report_on_request_doesnt_raise_the_reminder(client):
    client.post("/api/reports/weekly")
    assert not any(i["kind"] == "report" for i in client.get("/api/reminders").json()["items"])


def test_week_due_is_the_latest_monday_8am():
    from datetime import datetime
    assert reports.week_due(datetime(2026, 11, 11, 15, 0)) == datetime(2026, 11, 9, 8, 0)   # Wednesday
    assert reports.week_due(datetime(2026, 11, 9, 7, 0)) == datetime(2026, 11, 2, 8, 0)     # Monday, too early
    assert reports.week_due(datetime(2026, 11, 9, 8, 0)) == datetime(2026, 11, 9, 8, 0)


def test_scheduler_keeps_going_after_a_failure(monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database busy")

    monkeypatch.setattr(reports, "ensure_weekly_report", flaky)

    async def run():
        task = asyncio.create_task(reports.scheduler(interval_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    assert len(calls) >= 2


def test_scheduler_only_on_an_always_on_server():
    import inspect
    from backend import main
    source = inspect.getsource(main.lifespan)
    assert 'os.environ.get("HUB_SCHEDULER") == "on" and not SANDBOXES' in source


def test_report_counts_only_what_happened_inside_its_week(client, monkeypatch):
    """Found in the browser check: a catch-up report for an earlier week counted this week's moves."""
    from test_scale import scaling
    sid = scaling(client)                                    # moves happen now (real clock)
    from backend.meetings import calendar
    real = calendar.today()
    from datetime import timedelta
    old_monday = real - timedelta(days=real.weekday() + 14)
    report = reports.build_report(old_monday, old_monday + timedelta(days=6), "automatic")
    assert report["moved"] == [] and report["results"] == []
    current = client.post("/api/reports/weekly").json()
    assert any(m["id"] == sid for m in current["moved"])
