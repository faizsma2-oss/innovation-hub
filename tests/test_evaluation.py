"""Supplier evaluation: prepare → outreach → meeting → due diligence → pilot partner.
Scripted evaluator and a fake Claude: no network, no cost."""
import json
from types import SimpleNamespace

import pytest

from backend.research import evaluation
from backend.research.evaluation import MOCK_EVALUATOR, ClaudeEvaluator
from test_suppliers import in_research, run


def shortlisted(client):
    sid = in_research(client)
    found = run(client, sid).json()["research"]["suppliers"]["suppliers"]
    names = [found[0]["name"], found[1]["name"]]
    client.post(f"/api/submissions/{sid}/suppliers/shortlist", json={"names": names})
    return sid, names


def post(client, sid, path, **body):
    return client.post(f"/api/submissions/{sid}/evaluation/{path}", json=body)


def pass_required(client, sid, supplier):
    for item in evaluation.CHECKLIST:
        if item["required"]:
            assert post(client, sid, "checklist", supplier=supplier, item=item["key"], status="passed",
                        owner="Sara").status_code == 200


# ── Workflow (scripted evaluator) ────────────────────────────────────────────

def test_prepare_drafts_questions_and_an_unsent_email(client):
    sid, names = shortlisted(client)
    track = post(client, sid, "prepare", supplier=names[0]).json()["research"]["evaluation"][names[0]]
    prep = track["prep"]
    assert prep["status"] == "DRAFT" and prep["questions"] and prep["email_body"]
    assert track["outreach"] == "not_contacted"   # preparing never contacts anyone


def test_only_shortlisted_suppliers_can_be_evaluated(client):
    sid, _ = shortlisted(client)
    assert post(client, sid, "prepare", supplier="Not On The List").status_code == 422


def test_outreach_is_recorded_by_a_person(client):
    sid, names = shortlisted(client)
    track = post(client, sid, "outreach", supplier=names[0], status="contacted").json()["research"]["evaluation"][names[0]]
    assert track["outreach"] == "contacted"
    events = [e["event"] for e in client.get(f"/api/submissions/{sid}/history").json()]
    assert "supplier_outreach" in events


def test_meeting_notes_are_logged_and_mark_meeting_held(client):
    sid, names = shortlisted(client)
    post(client, sid, "prepare", supplier=names[0])
    track = post(client, sid, "meeting", supplier=names[0], date="2026-10-20",
                 notes="Good call with their solutions lead. They can demo next week.").json()["research"]["evaluation"][names[0]]
    assert track["outreach"] == "meeting_held"
    assert track["meetings"][0]["date"] == "2026-10-20"
    assert post(client, sid, "meeting", supplier=names[0], date="2026-10-20", notes="too short").status_code == 422


def test_pilot_partner_needs_every_required_check(client):
    sid, names = shortlisted(client)
    blocked = post(client, sid, "pilot-partner", supplier=names[0], reason="Best fit")
    assert blocked.status_code == 409 and "still open" in blocked.json()["detail"]
    pass_required(client, sid, names[0])
    post(client, sid, "checklist", supplier=names[0], item="references", status="failed", note="Bad reference")
    assert "failed" in post(client, sid, "pilot-partner", supplier=names[0], reason="Best fit").json()["detail"]
    post(client, sid, "checklist", supplier=names[0], item="references", status="passed")
    record = post(client, sid, "pilot-partner", supplier=names[0], reason="Best fit").json()
    assert record["status"] == "Pilot planning"
    pilot = record["research"]["pilot"]
    assert pilot["partner"] == names[0] and pilot["plan"]["status"] == "DRAFT"
    assert pilot["plan"]["baseline_metrics"] and pilot["plan"]["exit_criteria"]


def test_required_check_marked_not_applicable_needs_a_reason(client):
    sid, names = shortlisted(client)
    assert post(client, sid, "checklist", supplier=names[0], item="demo", status="not_applicable").status_code == 422
    assert post(client, sid, "checklist", supplier=names[0], item="demo", status="not_applicable",
                note="Product already in use at another site").status_code == 200


def test_evaluation_only_during_research(client):
    record = client.post("/api/submissions", json={"title": "x", "description": "Every week we retype logs by hand."}).json()
    assert post(client, record["id"], "prepare", supplier="Anyone").status_code == 409


# ── Claude evaluator: checked like every AI answer ───────────────────────────

class FakeClaude:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=1000,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.replies.pop(0)))])


@pytest.fixture
def use_claude(monkeypatch):
    def install(*replies):
        fake = FakeClaude(*replies)
        monkeypatch.setattr(evaluation, "get_evaluator", lambda: ClaudeEvaluator(fallback=MOCK_EVALUATOR, client=fake))
        return fake
    return install


def test_email_that_sounds_like_a_commitment_is_flagged(client, use_claude):
    sid, names = shortlisted(client)
    use_claude({"meeting_goal": "Goal", "questions": [{"question": "Q?", "why": "W", "priority": "must"}],
                "demo_requests": ["Demo"], "email_subject": "Hi",
                "email_body": "Hello, we will purchase your platform and look forward to the contract."})
    prep = post(client, sid, "prepare", supplier=names[0]).json()["research"]["evaluation"][names[0]]["prep"]
    assert prep["flags"] and prep["status"] == "DRAFT"


def test_meeting_never_invents_owners_dates_or_figures(client, use_claude):
    sid, names = shortlisted(client)
    notes = ("Met Layla from the supplier on Monday. Data stays in their Dubai region. Sara will send our sample "
             "files by 28 October. Someone needs to check their SOC 2 report.")
    use_claude({"summary": "Useful call.", "answers": [],
                "factor_updates": [
                    {"factor_key": "data_residency", "finding": "Data stays in their Dubai region.", "rating": 5,
                     "must_have_met": "yes"},
                    {"factor_key": "cost", "finding": "Costs AED 900 per month.", "rating": 4, "must_have_met": "unknown"}],
                "risks": ["SOC 2 report not yet seen"],
                "actions": [{"action": "Send sample files", "owner": "Sara", "deadline": "28 October"},
                            {"action": "Check SOC 2 report", "owner": "Omar", "deadline": "Friday"}]})
    record = post(client, sid, "meeting", supplier=names[0], date="2026-10-20", notes=notes).json()
    meeting = record["research"]["evaluation"][names[0]]["meetings"][0]["extracted"]
    assert meeting["actions"][0] == {"action": "Send sample files", "owner": "Sara", "deadline": "28 October"}
    assert meeting["actions"][1]["owner"] == "UNASSIGNED" and meeting["actions"][1]["deadline"] == "NO DATE AGREED"
    assert [u["factor_key"] for u in meeting["factor_updates"]] == ["data_residency"]  # "AED 900" isn't in the notes
    supplier = next(s for s in record["research"]["suppliers"]["suppliers"] if s["name"] == names[0])
    residency = supplier["findings"]["data_residency"]
    assert residency["evidence"] == "supplier (meeting, verbal)" and residency["sources"] == ["Meeting notes 2026-10-20"]


def test_pilot_targets_not_in_the_facts_are_left_to_agree(client, use_claude):
    sid, names = shortlisted(client)
    pass_required(client, sid, names[0])
    use_claude({"objective": "O", "scope": "S", "duration": "6 weeks", "baseline_metrics": [{"metric": "Hours", "how_measured": "Log"}],
                "success_criteria": [{"metric": "Hours per week", "target": "Cut from 6 to 1 hours"},
                                     {"metric": "Errors", "target": "Reduce errors by 80%"}],
                "costs_to_confirm": [], "risks": [], "exit_criteria": ["Stop if data leaves the UAE"],
                "roles": [{"role": "Pilot owner", "responsibility": "UNASSIGNED"}]})
    plan = post(client, sid, "pilot-partner", supplier=names[0], reason="Best fit").json()["research"]["pilot"]["plan"]
    targets = {c["metric"]: c["target"] for c in plan["success_criteria"]}
    assert targets["Hours per week"] == "To be agreed before the pilot starts"   # "1" isn't in the facts
    assert targets["Errors"] == "To be agreed before the pilot starts"           # "80" isn't in the facts
