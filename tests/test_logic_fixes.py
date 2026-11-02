"""Logic errors found in an audit, one scenario each. Each test failed before its fix."""
from datetime import date, timedelta

from backend.intake import language, rules
from backend.meetings import replies
from backend.research import pilot
from backend.reports import routes as reports

from conftest import Chat


# ── Intake ───────────────────────────────────────────────────────────────────

ARABIC = "كل أسبوع نجمع تقارير الطاقة يدويًا من ثلاثة أنظمة مختلفة، ويستغرق ذلك ست ساعات."


def test_untranslated_arabic_is_read_by_a_person_not_auto_declined(client, monkeypatch):
    """Without the translator the employee is told "a person will read your original words".
    The 'not a request' rule only counted Latin letters, so the Arabic request was closed automatically."""
    monkeypatch.setattr(language, "available", lambda: False)
    chat = Chat(client)
    chat.say(ARABIC)
    reply = chat.click("submit")
    assert reply["outcome"] != "auto_declined"
    record = chat.submission()
    assert record["status"] != "Declined"


def test_not_a_request_still_catches_short_or_test_text():
    assert rules.is_not_a_request("test")
    assert rules.is_not_a_request("asdf")
    assert rules.is_not_a_request("hello there")
    assert not rules.is_not_a_request(ARABIC)
    assert rules.is_meaningful_need(ARABIC)


def test_dollar_amounts_count_as_quantified():
    assert rules.is_quantified("It costs us $500 a month")
    assert rules.is_quantified("about AED 2000")


# ── Pilot evaluation ─────────────────────────────────────────────────────────

def setup(direction="lower_better", target=10.0):
    return {"criteria": [{"key": "m", "metric": "Minutes", "unit": "min", "direction": direction,
                          "target": target, "min_points": 3}]}


def readings(baseline, pilot_values):
    return ([{"metric": "m", "phase": "baseline", "value": v} for v in baseline]
            + [{"metric": "m", "phase": "pilot", "value": v} for v in pilot_values])


def test_a_metric_that_got_worse_is_not_a_success_just_because_it_is_under_target():
    """Baseline already beat the target; the pilot made it clearly worse. That's not 'target met'."""
    result = pilot.evaluate(setup(target=10.0), readings([5, 5.1, 4.9], [8, 8.1, 7.9]))
    assert result["metrics"][0]["status"] == "worse"
    assert result["verdict"] != "success"


def test_an_improvement_that_meets_the_target_is_still_a_success():
    result = pilot.evaluate(setup(target=10.0), readings([20, 21, 19], [8, 8.2, 7.8]))
    assert result["metrics"][0]["status"] == "target met" and result["verdict"] == "success"


def test_higher_better_worse_but_above_target_is_worse():
    result = pilot.evaluate(setup("higher_better", target=50), readings([90, 91, 89], [70, 71, 69]))
    assert result["metrics"][0]["status"] == "worse"


# ── Supplier replies ─────────────────────────────────────────────────────────

def test_month_in_a_quote_is_not_read_as_monday():
    start = (date.today() + timedelta(days=10))
    while start.weekday() != 2:            # a Wednesday
        start += timedelta(days=1)
    quote = f"later this month, {start.day} {start.strftime('%B')} at 10am"
    checked = replies.check([{"start": f"{start.isoformat()}T10:00", "timezone": None, "quote": quote}], quote)
    assert checked[0]["problem"] is None, checked[0]["problem"]


def test_a_wrong_weekday_is_still_caught():
    start = (date.today() + timedelta(days=10))
    while start.weekday() != 2:            # a Wednesday, quoted as Tuesday
        start += timedelta(days=1)
    quote = f"Tues {start.day} {start.strftime('%B')} at 10am"
    checked = replies.check([{"start": f"{start.isoformat()}T10:00", "timezone": None, "quote": quote}], quote)
    assert "not a Tuesday" in (checked[0]["problem"] or "")


# ── Reports ──────────────────────────────────────────────────────────────────

def test_a_report_on_request_covers_seven_days_not_eight(client, monkeypatch):
    monkeypatch.setattr(reports.calendar, "today", lambda: date(2026, 11, 4))
    report = client.post("/api/reports/weekly").json()
    assert report["period"] == "2026-10-29 to 2026-11-04"


def test_an_employee_requested_review_on_a_routed_request_is_a_decision_needed(client):
    chat = Chat(client)
    chat.say("My laptop won't start")
    chat.click("route_send")
    sid = chat.reply["submission_id"]
    assert client.get(f"/api/submissions/{sid}").json()["status"] == "Routed"
    client.post(f"/api/submissions/{sid}/request-review", json={"text": "It happens to the whole team"})
    decisions = client.get("/api/copilot/decisions").json()
    ids = [d["id"] for d in (decisions.get("decisions") if isinstance(decisions, dict) else decisions)]
    assert sid in ids
    board = client.get("/api/portfolio").json()
    assert sid in [card["id"] for stage in board["stages"] for card in stage["cards"]]


# ── Measures ─────────────────────────────────────────────────────────────────

def test_a_caught_opportunity_stays_counted_after_it_moves_on_to_research(client):
    record = client.post("/api/submissions", json={"title": "Reporting access", "department": "Operations",
                                                   "description": "I cannot access the reporting system."}).json()
    assert record["status"] == "Routed"
    client.post(f"/api/submissions/{record['id']}/request-review", json={})
    client.post(f"/api/submissions/{record['id']}/review", json={"decision": "accept"})
    assert client.get("/api/metrics").json()["missed_opportunities"] == 1
    options = client.post(f"/api/submissions/{record['id']}/solutions", json={}).json()["solutions"]["options"]
    selected = client.post(f"/api/submissions/{record['id']}/solutions/select",
                           json={"option_id": options[0]["id"], "reason": "Quickest"}).json()
    assert selected["status"] == "Research"
    assert client.get("/api/metrics").json()["missed_opportunities"] == 1


# ── Pilot decisions ──────────────────────────────────────────────────────────

def test_after_extending_the_pilot_is_evaluated_again_before_the_next_decision(client):
    from test_pilot import call, log, running
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5)          # too few points: inconclusive
    assert call(client, sid, "evaluate").json()["research"]["pilot"]["evaluations"][-1]["verdict"] == "inconclusive"
    extended = call(client, sid, "decide", decision="extend", reason="Need more data", new_end_date="2026-12-20")
    assert extended.status_code == 200
    # The inconclusive evaluation has been decided on; scaling on it now would skip the new data.
    blocked = call(client, sid, "decide", decision="scale", reason="Looks good")
    assert blocked.status_code == 409 and "again" in blocked.json()["detail"]
    decisions = client.get("/api/copilot/decisions").json()
    decisions = decisions.get("decisions") if isinstance(decisions, dict) else decisions
    assert sid not in [d["id"] for d in decisions if d["decision"].startswith("Decide the pilot")]
    log(client, sid, "hours_per_week", "pilot", 1.4, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0.5, 0.8, 0.7)
    call(client, sid, "evaluate")
    assert call(client, sid, "decide", decision="scale", reason="Targets met").json()["status"] == "Scaling"


def test_a_weekly_report_lists_only_benefit_checkins_logged_that_week(client):
    from backend import examples
    examples.seed()                                       # includes a solution in operation with a check-in today
    this_week = client.post("/api/reports/weekly").json()
    assert len(this_week["benefits_realised"]) == 1
    long_ago = reports.build_report(date(2020, 1, 6), date(2020, 1, 12), "manual")
    assert long_ago["benefits_realised"] == []
