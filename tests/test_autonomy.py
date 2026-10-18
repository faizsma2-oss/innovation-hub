"""Earned autonomy: agreement per decision area and a fixed readiness rule. Nothing switches on."""
import json

from backend import db
from backend.review import autonomy


def area(client, key):
    return next(a for a in client.get("/api/autonomy").json()["areas"] if a["key"] == key)


def test_summary_statuses_follow_the_rule():
    ok, override = (True, None), (False, "SUB-0001: reason")
    assert autonomy.summarise("routing", [ok] * 7)["status"] == "too_few"
    assert autonomy.summarise("routing", [ok] * 7)["why"] == "7 of 20 decisions needed before judging."
    ready = autonomy.summarise("routing", [ok] * 25)
    assert ready["status"] == "ready" and ready["agreement"] == 1.0 and "nothing changes automatically" in ready["why"]
    low = autonomy.summarise("screening", [ok] * 16 + [override] * 4 + [ok] * 10)
    assert low["status"] == "keep" and low["agreement"] == 0.87
    recent = autonomy.summarise("screening", [ok] * 40 + [override] + [ok] * 5)
    assert recent["status"] == "keep" and "last 10" in recent["why"] and recent["recent_agreement"] == 0.9
    assert recent["overrides"] == ["SUB-0001: reason"]
    assert autonomy.summarise("pilots", [ok] * 50)["status"] == "always_human"    # never "ready", whatever the numbers
    assert autonomy.summarise("policy_declines", [ok] * 3 + [(False, "x")] * 2)["status"] == "keep"


def test_screening_agreement_and_override_reasons_come_from_the_decisions(client):
    records = client.get("/api/submissions").json()
    with db.connect() as conn:
        for record, outcome in zip(records[:3], ("agreed", "agreed", "overrode")):
            conn.execute("UPDATE submissions SET review_outcome = ?, status = 'Declined', decision_message = ?,"
                         " recommendation_json = ? WHERE pk = ?",
                         (outcome, "Not a priority this quarter", json.dumps({"decision": "accept"}), db.parse_pk(record["id"])))
    screening = area(client, "screening")
    assert screening["decisions"] == 3 and screening["agreement"] == 0.67 and screening["status"] == "too_few"
    assert "recommended accept, the reviewer chose decline" in screening["overrides"][0]
    assert "Not a priority this quarter" in screening["overrides"][0]


def test_option_supplier_and_pilot_choices_are_counted(client):
    from test_pilot import call, evaluated, log, running
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    evaluated(client, sid)
    call(client, sid, "decide", decision="stop", reason="Budget moved to another project")
    assert area(client, "options")["decisions"] == 1
    assert area(client, "suppliers")["decisions"] == 1
    pilots = area(client, "pilots")
    assert pilots["decisions"] == 1 and pilots["agreement"] == 0.0 and pilots["status"] == "always_human"
    assert "recommended scale, decided stop" in pilots["overrides"][0]


def test_the_dashboard_only_reads(client):
    before = client.get("/api/submissions").json()
    client.get("/api/autonomy")
    assert client.get("/api/submissions").json() == before
    assert client.post("/api/autonomy").status_code == 405
