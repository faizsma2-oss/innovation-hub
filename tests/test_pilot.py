"""Pilot run and evaluation: setup, baseline first, measurements, a verdict calculated in code,
and the team's decision. Scripted writer and a fake Claude: no network, no cost."""
import json
from types import SimpleNamespace

import pytest

from backend.research import pilot as pilot_rules
from backend.research.pilot import MOCK_WRITER, ClaudePilotWriter, evaluate
from test_evaluation import pass_required, post as evaluation_post, shortlisted

HOURS = {"metric": "Hours per week", "unit": "hours", "direction": "lower_better", "target": 2, "min_points": 3}
ERRORS = {"metric": "Errors per week", "unit": "errors", "direction": "lower_better", "target": 1, "min_points": 3}


def pilot_planning(client):
    sid, names = shortlisted(client)
    pass_required(client, sid, names[0])
    evaluation_post(client, sid, "pilot-partner", supplier=names[0], reason="Best fit")
    return sid


def call(client, sid, path, **body):
    return client.post(f"/api/submissions/{sid}/pilot/{path}", json=body)


def setup(client, sid, criteria=(HOURS, ERRORS)):
    return call(client, sid, "setup", criteria=list(criteria), owner="Sara", start_date="2026-11-01", end_date="2026-12-01")


def log(client, sid, metric, phase, *values):
    for day, value in enumerate(values, start=1):
        response = call(client, sid, "measurements", metric=metric, phase=phase, value=value, date=f"2026-11-{day:02d}")
        assert response.status_code == 200, response.text


def running(client, baseline_hours=(6, 6.5, 5.5), baseline_errors=(4, 3, 5)):
    sid = pilot_planning(client)
    setup(client, sid)
    log(client, sid, "hours_per_week", "baseline", *baseline_hours)
    log(client, sid, "errors_per_week", "baseline", *baseline_errors)
    assert call(client, sid, "start").json()["status"] == "Pilot running"
    return sid


def evaluated(client, sid):
    return call(client, sid, "evaluate").json()["research"]["pilot"]["evaluations"][-1]


# ── Setup and gates ──────────────────────────────────────────────────────────

def test_setup_needs_numeric_targets_and_a_named_owner(client):
    sid = pilot_planning(client)
    assert call(client, sid, "setup", criteria=[HOURS | {"target": "less"}], owner="Sara",
                start_date="2026-11-01", end_date="2026-12-01").status_code == 422
    assert call(client, sid, "setup", criteria=[HOURS], owner="UNASSIGNED",
                start_date="2026-11-01", end_date="2026-12-01").status_code == 422
    assert call(client, sid, "setup", criteria=[HOURS], owner="Sara",
                start_date="2026-12-01", end_date="2026-11-01").status_code == 422
    assert setup(client, sid).status_code == 200


def test_baseline_must_be_measured_before_the_pilot_starts(client):
    sid = pilot_planning(client)
    assert call(client, sid, "start").status_code == 409            # no setup yet
    setup(client, sid)
    blocked = call(client, sid, "start")
    assert blocked.status_code == 409 and "baseline" in blocked.json()["detail"]
    assert call(client, sid, "measurements", metric="hours_per_week", phase="pilot", value=1,
                date="2026-11-01").status_code == 409             # not running yet
    log(client, sid, "hours_per_week", "baseline", 6)
    log(client, sid, "errors_per_week", "baseline", 4)
    assert call(client, sid, "start").json()["status"] == "Pilot running"


def test_measurements_must_match_an_agreed_metric(client):
    sid = pilot_planning(client)
    setup(client, sid)
    assert call(client, sid, "measurements", metric="made_up", phase="baseline", value=1,
                date="2026-11-01").status_code == 422


# ── The verdict, calculated in code ──────────────────────────────────────────

def test_too_few_measurements_is_inconclusive(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8)              # only 2 of the 3 needed
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    result = evaluated(client, sid)
    assert result["verdict"] == "inconclusive" and result["recommendation"] == "extend"
    assert "Hours per week" in result["reason"] and result["evidence_strength"] == "low"


def test_all_targets_met_recommends_scale(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    result = evaluated(client, sid)
    assert result["verdict"] == "success" and result["recommendation"] == "scale"
    hours = next(m for m in result["metrics"] if m["key"] == "hours_per_week")
    assert hours["baseline_mean"] == 6 and hours["pilot_mean"] == 1.63 and hours["change_percent"] == -72.8


def test_partial_improvement_recommends_revise(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 3, 3.5, 3.2)          # better, but target is 2
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    result = evaluated(client, sid)
    assert result["verdict"] == "partial" and result["recommendation"] == "revise"
    statuses = {m["key"]: m["status"] for m in result["metrics"]}
    assert statuses == {"hours_per_week": "improved, target not met", "errors_per_week": "target met"}


def test_change_within_normal_variation_is_not_an_improvement(client):
    sid = running(client, baseline_hours=(4, 8, 6), baseline_errors=(4, 3, 5))
    log(client, sid, "hours_per_week", "pilot", 5.5, 5, 6)             # mean 5.5 vs 6, but baseline varies by 2
    log(client, sid, "errors_per_week", "pilot", 4.2, 3.8, 4)
    result = evaluated(client, sid)
    assert {m["status"] for m in result["metrics"]} == {"no clear change"}
    assert result["verdict"] == "no improvement" and result["recommendation"] == "stop"


def test_higher_is_better_metrics_work_too():
    setup_ = {"criteria": [{"key": "uptime", "metric": "Uptime", "unit": "%", "direction": "higher_better",
                            "target": 99.5, "min_points": 2}]}
    data = [{"metric": "uptime", "phase": "baseline", "value": v} for v in (98.0, 98.2)] + \
           [{"metric": "uptime", "phase": "pilot", "value": v} for v in (99.6, 99.7)]
    assert evaluate(setup_, data)["verdict"] == "success"


# ── The team decides ─────────────────────────────────────────────────────────

def decide(client, sid, decision, **extra):
    return call(client, sid, "decide", decision=decision, reason="Team review", **extra)


def test_decision_needs_an_evaluation_and_a_reason(client):
    sid = running(client)
    assert decide(client, sid, "scale").status_code == 409
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    evaluated(client, sid)
    assert call(client, sid, "decide", decision="scale", reason="").status_code == 422


@pytest.mark.parametrize("decision, status", [("scale", "Scaling"), ("stop", "Stopped")])
def test_scale_and_stop_close_the_pilot(client, decision, status):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    evaluated(client, sid)
    record = decide(client, sid, decision).json()
    assert record["status"] == status
    recorded = record["research"]["pilot"]["decisions"][-1]
    assert recorded["agreed_with_recommendation"] is (decision == "scale")
    metrics = client.get("/api/metrics").json()
    assert metrics["pilots_scaled" if decision == "scale" else "pilots_stopped"] == 1


def test_extend_needs_a_later_end_date_and_keeps_running(client):
    sid = running(client)
    evaluated(client, sid)
    assert call(client, sid, "decide", decision="extend", reason="More data").status_code == 422
    assert decide(client, sid, "extend", new_end_date="2026-11-15").status_code == 422   # earlier than 1 Dec
    record = decide(client, sid, "extend", new_end_date="2026-12-31").json()
    assert record["status"] == "Pilot running"
    assert record["research"]["pilot"]["setup"]["end_date"] == "2026-12-31"


def test_revise_starts_a_new_round_and_keeps_history(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 3, 3.5, 3.2)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    evaluated(client, sid)
    record = decide(client, sid, "revise").json()
    pilot = record["research"]["pilot"]
    assert record["status"] == "Pilot planning" and pilot["round"] == 2 and "setup" not in pilot
    assert len(pilot["measurements"]) == 12                          # round 1 kept as history
    setup(client, sid)
    blocked = call(client, sid, "start")
    assert blocked.status_code == 409                                # round 2 needs its own baseline


# ── Claude narrative: can't change the verdict or add numbers ────────────────

class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=600,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def test_narrative_with_invented_figures_is_replaced(client, monkeypatch):
    monkeypatch.setattr(pilot_rules, "get_writer", lambda: ClaudePilotWriter(MOCK_WRITER, client=FakeClaude({
        "summary": "A clear success that will save 300 hours a year.",
        "lessons": ["Hours dropped from 6 to 1.63.", "Saves AED 50,000."],
        "risks_if_scaled": ["Other sites use different tools."], "next_steps": ["Plan rollout."]})))
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5, 1.8, 1.6)
    log(client, sid, "errors_per_week", "pilot", 0, 1, 0)
    result = evaluated(client, sid)
    assert result["verdict"] == "success"                            # computed, untouched
    assert "300" not in result["narrative"]["summary"]               # invented figure: summary replaced
    assert result["narrative"]["lessons"] == ["Hours dropped from 6 to 1.63."]   # "50,000" dropped
