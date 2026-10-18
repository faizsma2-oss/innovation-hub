"""Scale → roll out → hand over → benefits → lessons, plus the portfolio and weekly report.
Scripted assistant and a fake Claude: no network, no cost."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from backend.meetings import calendar
from backend.scale import routes as scale_routes
from backend.scale.assistant import MOCK, ClaudeScaleAssistant
from conftest import Chat
from test_pilot import call, evaluated, log, running

CASE = {"currency": "AED",
        "one_off": [{"item": "Setup and integration", "amount": 50000}],
        "yearly": [{"item": "Licences", "amount": 12000}],
        "benefits": [{"metric_key": "hours_per_week", "value_per_unit": 150, "periods_per_year": 52, "multiplier": 3},
                     {"metric_key": "errors_per_week", "value_per_unit": 200, "periods_per_year": 52, "multiplier": 3}]}


def scaling(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    evaluated(client, sid)
    assert call(client, sid, "decide", decision="scale", reason="Targets met").json()["status"] == "Scaling"
    return sid


def post(client, sid, path, **body):
    return client.post(f"/api/submissions/{sid}/{path}", json=body)


def approved(client):
    sid = scaling(client)
    post(client, sid, "scale/business-case", **CASE)
    assert post(client, sid, "scale/decision", decision="approve", reason="Strong payback").json()["status"] == "Rolling out"
    return sid


def in_operation(client):
    sid = approved(client)
    items = client.get(f"/api/submissions/{sid}").json()["research"]["scale"]["rollout"]["handover"]
    for index in range(len(items)):
        post(client, sid, "scale/handover-item", index=index, done=True)
    assert post(client, sid, "scale/handover", business_owner="Huda (Operations)",
                handover_date="2026-12-01").json()["status"] == "In operation"
    return sid


# ── Business case: maths in code ─────────────────────────────────────────────

def test_improvements_come_from_the_pilot_measurements(client):
    sid = scaling(client)
    lines = {l["metric_key"]: l for l in client.get(f"/api/submissions/{sid}/scale/improvements").json()}
    assert lines["hours_per_week"]["gain_per_period"] == 4.37          # 6 → 1.63 hours a week
    assert lines["errors_per_week"]["gain_per_period"] == 3.67


def test_business_case_is_calculated_not_estimated(client):
    sid = scaling(client)
    case = post(client, sid, "scale/business-case", **CASE).json()["research"]["scale"]["business_case"]
    calc = case["calc"]
    hours = 4.37 * 52 * 3 * 150                                         # 102,258
    errors = 3.67 * 52 * 3 * 200                                        # 114,504
    assert calc["annual_benefit"] == pytest.approx(hours + errors)
    assert calc["net_annual"] == pytest.approx(hours + errors - 12000)
    assert calc["payback_months"] == pytest.approx(round(50000 / (hours + errors - 12000) * 12, 1))
    assert calc["three_year_net"] == pytest.approx(3 * (hours + errors - 12000) - 50000)
    assert case["status"] == "AWAITING DECISION" and calc["verdict"].startswith("Pays back in")


def test_only_improved_metrics_can_carry_a_benefit(client):
    sid = scaling(client)
    bad = CASE | {"benefits": [{"metric_key": "made_up", "value_per_unit": 1, "periods_per_year": 52, "multiplier": 1}]}
    assert post(client, sid, "scale/business-case", **bad).status_code == 422


def test_costs_higher_than_benefit_do_not_pay_back(client):
    sid = scaling(client)
    costly = CASE | {"yearly": [{"item": "Licences", "amount": 900000}]}
    calc = post(client, sid, "scale/business-case", **costly).json()["research"]["scale"]["business_case"]["calc"]
    assert calc["payback_months"] is None and calc["verdict"].startswith("Does not pay back")


# ── Decision, rollout and handover ───────────────────────────────────────────

def test_management_decision_needs_a_business_case(client):
    sid = scaling(client)
    assert post(client, sid, "scale/decision", decision="approve", reason="Go").status_code == 409


def test_rejected_business_case_stops_the_work(client):
    sid = scaling(client)
    post(client, sid, "scale/business-case", **CASE)
    record = post(client, sid, "scale/decision", decision="reject", reason="Budget frozen this year").json()
    assert record["status"] == "Stopped"
    assert record["research"]["scale"]["business_case"]["status"] == "REJECTED"


def test_handover_needs_a_named_owner_and_a_finished_checklist(client):
    sid = approved(client)
    rollout = client.get(f"/api/submissions/{sid}").json()["research"]["scale"]["rollout"]
    assert rollout["plan"]["phases"] and rollout["handover"]
    blocked = post(client, sid, "scale/handover", business_owner="Huda", handover_date="2026-12-01")
    assert blocked.status_code == 409 and "checklist" in blocked.json()["detail"]
    for index in range(len(rollout["handover"])):
        post(client, sid, "scale/handover-item", index=index, done=True)
    assert post(client, sid, "scale/handover", business_owner="UNASSIGNED", handover_date="2026-12-01").status_code == 422


def test_check_ins_are_scheduled_at_3_6_and_12_months(client):
    sid = in_operation(client)
    checkins = client.get(f"/api/submissions/{sid}").json()["research"]["scale"]["checkins"]
    assert [c["label"] for c in checkins] == ["3 months", "6 months", "12 months"]
    assert checkins[0]["due"] == "2027-03-02" and checkins[2]["due"] == "2027-12-01"


# ── Benefits tracking ────────────────────────────────────────────────────────

@pytest.mark.parametrize("hours, errors, verdict", [(1.8, 0.5, "held"), (4.0, 2.5, "partly held"), (5.9, 3.9, "eroded")])
def test_benefits_held_partly_held_or_eroded(client, hours, errors, verdict):
    sid = in_operation(client)
    record = post(client, sid, "scale/checkin", index=0,
                  values={"hours_per_week": hours, "errors_per_week": errors}).json()
    result = record["research"]["scale"]["checkins"][0]["result"]
    assert result["verdict"] == verdict
    metrics = client.get("/api/metrics").json()
    assert metrics["in_operation"] == 1 and metrics["benefits_realised"]["AED"] == result["realised_annual_value"]


def test_reminders_for_decisions_and_due_check_ins(client, monkeypatch):
    sid = scaling(client)
    post(client, sid, "scale/business-case", **CASE)
    assert "decision" in [i["kind"] for i in client.get("/api/reminders").json()["items"]]
    sid2 = in_operation(client)
    monkeypatch.setattr(calendar, "today", lambda: date(2027, 3, 5))
    items = client.get("/api/reminders").json()["items"]
    assert any(i["kind"] == "checkin" and i["submission_id"] == sid2 for i in items)


# ── Lessons feed back into intake ────────────────────────────────────────────

def test_solution_in_operation_is_offered_to_the_next_employee(client):
    sid = in_operation(client)
    draft = post(client, sid, "lessons/draft").json()["research"]["lesson_draft"]
    assert draft["kind"] == "tool" and "Huda" in draft["how_to"]
    assert post(client, sid, "lessons/publish", title="Automated weekly energy report", summary="x",
                keywords=["data", "report"]).status_code == 422                     # too generic to publish
    post(client, sid, "lessons/publish", title="Automated weekly energy report",
         summary="Energy reports now refresh automatically from the source tools.",
         keywords=["combine energy reports", "energy report"])
    chat = Chat(client)
    chat.say("Each week someone has to combine energy reports from three tools by hand.")
    chat.dont_know_until_done()
    assert chat.reply["stage"] == "solution_offer"
    assert "Automated weekly energy report" in chat.reply["message"] and "Huda" in chat.reply["message"]


def test_stopped_pilot_becomes_context_for_future_requests(client):
    sid = scaling(client)
    post(client, sid, "scale/business-case", **CASE)
    post(client, sid, "scale/decision", decision="reject", reason="Budget frozen this year")
    post(client, sid, "lessons/draft")
    post(client, sid, "lessons/publish", title="Energy report automation (stopped)", summary="Worked, but budget was frozen.",
         keywords=["combine energy reports"])
    chat = Chat(client)
    chat.say("We still combine energy reports by hand every week.")
    chat.dont_know_until_done()
    assert "previous pilot looked at something similar" in chat.reply["message"]
    assert "SUB-" not in chat.reply["message"]                    # the stopped request isn't offered as "being reviewed"
    if chat.reply["stage"] != "closed":
        chat.click("submit")
    assert any("LES-" in attempt for attempt in chat.submission()["brief"]["previous_attempts"])


# ── Portfolio and weekly report ──────────────────────────────────────────────

def test_portfolio_shows_each_opportunity_in_its_stage(client):
    sid = in_operation(client)
    stages = {s["name"]: s["cards"] for s in client.get("/api/portfolio").json()["stages"]}
    card = next(c for c in stages["In operation"] if c["id"] == sid)
    assert card["owner"] == "Huda (Operations)" and card["partner"]
    assert all(c["status"] not in ("Routed", "Linked") for cards in stages.values() for c in cards)


def test_weekly_report_collects_decisions_moves_and_sources(client):
    sid = scaling(client)
    post(client, sid, "scale/business-case", **CASE)
    report = client.post("/api/reports/weekly").json()
    assert any(d["id"] == sid and "business case" in d["decision"] for d in report["decisions_needed"])
    assert any(m["id"] == sid and m["to"] == "Scaling" for m in report["moved"])
    assert report["summary"] and report["status"] == "DRAFT"
    assert {p["stage"] for p in report["pipeline"]} >= {"Pilot", "Scaling", "In operation"}
    assert client.get("/api/reports").json()[0]["id"] == report["id"]


# ── Claude narrative can't add money ─────────────────────────────────────────

class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=500,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def test_business_case_narrative_cannot_add_figures(client, monkeypatch):
    monkeypatch.setattr(scale_routes, "get_assistant", lambda: ClaudeScaleAssistant(MOCK, client=FakeClaude({
        "summary": "This will save AED 2,000,000 over five years.",
        "assumptions": ["Benefit holds at 3 sites", "Saves 40% more next year"], "risks": ["Adoption"]})))
    sid = scaling(client)
    narrative = post(client, sid, "scale/business-case", **CASE).json()["research"]["scale"]["business_case"]["narrative"]
    assert "2,000,000" not in narrative["summary"]
    assert narrative["assumptions"] == ["Benefit holds at 3 sites"]


# ── Scenarios: low / expected / high, and break-even ─────────────────────────

def test_three_scenarios_and_break_even_are_calculated(client):
    sid = scaling(client)
    calc = post(client, sid, "scale/business-case", **CASE).json()["research"]["scale"]["business_case"]["calc"]
    benefit, low, expected, high = calc["annual_benefit"], *(calc["scenarios"][k] for k in ("low", "expected", "high"))
    assert expected["annual_benefit"] == benefit and expected["payback_months"] == calc["payback_months"]   # unchanged
    assert low["annual_benefit"] == pytest.approx(benefit * 0.5)
    assert low["one_off_total"] == pytest.approx(50000 * 1.2) and low["yearly_cost_total"] == pytest.approx(12000 * 1.2)
    assert high["annual_benefit"] == pytest.approx(benefit * 1.2)
    assert low["payback_months"] > expected["payback_months"] > high["payback_months"]
    assert calc["break_even_share"] == pytest.approx(round((12000 + 50000 / 3) / benefit, 2))
    # At exactly the break-even share, three years of net benefit cover the one-off cost.
    share = (12000 + 50000 / 3) / benefit
    assert 3 * (share * benefit - 12000) - 50000 == pytest.approx(0, abs=1e-6)


def test_team_can_set_its_own_scenarios_within_limits(client):
    sid = scaling(client)
    mine = {"low": {"benefit": 0.3, "cost": 1.5}, "expected": {"benefit": 0.8, "cost": 1.1}, "high": {"benefit": 1, "cost": 1}}
    calc = post(client, sid, "scale/business-case", **CASE, scenarios=mine).json()["research"]["scale"]["business_case"]["calc"]
    assert calc["scenarios"]["low"]["benefit_factor"] == 0.3 and calc["scenarios"]["expected"]["cost_factor"] == 1.1
    assert post(client, sid, "scale/business-case", **CASE,
                scenarios=mine | {"low": {"benefit": 0.05, "cost": 1}}).status_code == 422          # below 10%
    assert post(client, sid, "scale/business-case", **CASE,
                scenarios=mine | {"low": {"benefit": 0.9, "cost": 1}}).status_code == 422           # out of order


def test_a_low_scenario_that_never_pays_back(client):
    sid = scaling(client)
    pricey = CASE | {"yearly": [{"item": "Licences", "amount": 150000}]}
    calc = post(client, sid, "scale/business-case", **pricey).json()["research"]["scale"]["business_case"]["calc"]
    assert calc["scenarios"]["low"]["payback_months"] is None and not calc["scenarios"]["low"]["pays_back_in_3_years"]
    assert calc["scenarios"]["expected"]["pays_back_in_3_years"]
