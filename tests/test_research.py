"""Research AI: options after acceptance, ranking in code, selection starts research.
Uses the scripted researcher and a fake Claude: no network, no cost."""
import json
from types import SimpleNamespace

import pytest

from backend.research import routes as research_routes
from backend.research.researcher import CRITERIA, MOCK_RESEARCHER, ClaudeResearcher, usefulness


def accepted(client):
    record = client.post("/api/submissions", json={
        "title": "Weekly report merging", "department": "Operations",
        "description": "Every week we manually combine energy reports from several systems.",
        "current_process": "Copy numbers from 3 tools into a spreadsheet; should be automatic.",
        "people_affected": "The reporting team at 4 sites", "impact": "About 6 hours a week"}).json()
    response = client.post(f"/api/submissions/{record['id']}/review", json={"decision": "accept"})
    assert response.json()["status"] == "Accepted"
    return record["id"]


def propose(client, sid, **body):
    return client.post(f"/api/submissions/{sid}/solutions", json=body)


def select(client, sid, option_id, reason="Fastest to try"):
    return client.post(f"/api/submissions/{sid}/solutions/select", json={"option_id": option_id, "reason": reason})


# ── Options and ranking ──────────────────────────────────────────────────────

def test_options_are_ranked_by_usefulness_calculated_in_code(client):
    sid = accepted(client)
    solutions = propose(client, sid).json()["solutions"]
    options = solutions["options"]
    assert solutions["status"] == "PROPOSED" and solutions["round"] == 1
    assert 3 <= len(options) <= 5
    assert [o["rank"] for o in options] == list(range(1, len(options) + 1))
    assert [o["usefulness"] for o in options] == sorted((o["usefulness"] for o in options), reverse=True)
    for option in options:
        assert set(option["scores"]) == set(CRITERIA)
        assert option["usefulness"] == usefulness(option["scores"])
        assert option["pros"] and option["cons"]
    assert any(o["title"] == "Improve the current process" for o in options)  # baseline always present


def test_weights_add_up_and_are_shown(client):
    assert sum(weight for _, weight in CRITERIA.values()) == pytest.approx(1.0)
    listed = client.get("/api/research/criteria").json()
    assert [c["key"] for c in listed] == list(CRITERIA)


def test_options_only_after_acceptance(client):
    record = client.post("/api/submissions", json={"title": "x", "description": "Every week we retype logs by hand."}).json()
    assert propose(client, record["id"]).status_code == 409


def test_asking_again_with_feedback_starts_a_new_round(client):
    sid = accepted(client)
    propose(client, sid)
    again = propose(client, sid, feedback="We can't buy new software this year").json()["solutions"]
    assert again["round"] == 2 and again["feedback"] == "We can't buy new software this year"


# ── Selection starts research ────────────────────────────────────────────────

def test_selecting_an_option_starts_research_with_a_plan(client):
    sid = accepted(client)
    options = propose(client, sid).json()["solutions"]["options"]
    second = options[1]
    record = select(client, sid, second["id"], "Uses systems we already have").json()
    assert record["status"] == "Research"
    research = record["research"]
    assert research["selected_option"]["id"] == second["id"]
    assert research["agreed_with_top_rank"] is False
    assert research["reason"] == "Uses systems we already have"
    assert research["plan"]["research_questions"] and research["plan"]["next_steps"]
    metrics = client.get("/api/metrics").json()
    assert metrics["research_started"] == 1 and metrics["research_top_pick_rate"] == 0.0
    events = [e["event"] for e in client.get(f"/api/submissions/{sid}/history").json()]
    assert events[-2:] == ["options_proposed", "option_selected"]


def test_selection_needs_a_valid_option_and_a_reason(client):
    sid = accepted(client)
    propose(client, sid)
    assert select(client, sid, "Z").status_code == 422
    assert select(client, sid, "A", reason="").status_code == 422
    assert select(client, sid, "A").status_code == 200
    assert select(client, sid, "B").status_code == 409   # research already started
    assert propose(client, sid).status_code == 409


def test_cannot_select_before_options_exist(client):
    sid = accepted(client)
    assert select(client, sid, "A").status_code == 422


# ── Claude researcher: checked like every AI answer ──────────────────────────

def claude_option(option_id, title, values, summary="An approach."):
    return {"id": option_id, "title": title, "summary": summary, "how_it_helps": "It helps.",
            "scores": {key: {"value": value, "reason": "Because."} for key, value in zip(CRITERIA, values)},
            "pros": ["A pro"], "cons": ["A con"], "assumptions": ["An assumption"], "open_questions": ["A question?"]}


class FakeClaude:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        payload = self.replies.pop(0)
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=1500,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])


@pytest.fixture
def use_claude(monkeypatch):
    def install(*replies):
        fake = FakeClaude(*replies)
        monkeypatch.setattr(research_routes, "get_researcher",
                            lambda: ClaudeResearcher(fallback=MOCK_RESEARCHER, client=fake))
        return fake
    return install


def test_claude_order_is_ignored_and_ranking_is_recalculated(client, use_claude):
    use_claude({"comparison": "Trade-offs.", "options": [
        claude_option("A", "Weak option listed first", [1, 1, 1, 1, 1, 1]),
        claude_option("B", "Strong option", [5, 4, 4, 4, 4, 3]),
        claude_option("C", "Middle option", [3, 3, 3, 3, 3, 3])]})
    options = propose(client, accepted(client)).json()["solutions"]["options"]
    assert [o["title"] for o in options] == ["Strong option", "Middle option", "Weak option listed first"]
    assert options[0]["usefulness"] == usefulness(options[0]["scores"])


def test_figures_not_in_the_request_are_flagged(client, use_claude):
    use_claude({"comparison": "x", "options": [
        claude_option("A", "Baseline", [2, 5, 5, 5, 5, 3]),
        claude_option("B", "Automate", [4, 4, 4, 3, 4, 3], summary="Saves 40% of the 6 hours."),
        claude_option("C", "Tool", [5, 2, 2, 3, 3, 4])]})
    options = propose(client, accepted(client)).json()["solutions"]["options"]
    flagged = next(o for o in options if o["title"] == "Automate")
    assert flagged["unverified_figures"] == ["40%"]   # "6" was in the request, "40%" wasn't


@pytest.mark.parametrize("bad_reply", [
    {"comparison": "x", "options": [claude_option("A", "Only one", [3, 3, 3, 3, 3, 3])]},     # too few
    {"comparison": "x", "options": [claude_option("A", "Same id", [3] * 6)] * 3},              # duplicate ids
    {"comparison": "x", "options": [dict(claude_option(i, i, [3] * 6), cons=[]) for i in "ABC"]},  # no cons
])
def test_unusable_replies_fall_back_to_the_scripted_researcher(client, use_claude, bad_reply):
    use_claude(bad_reply)
    solutions = propose(client, accepted(client)).json()["solutions"]
    assert solutions["generated_by"].startswith("research-mock")


def test_research_prompt_forbids_vendor_names_and_invented_numbers(client, use_claude):
    fake = use_claude({"comparison": "x", "options": [claude_option(i, t, [3] * 6) for i, t in zip("ABC", "XYZ")]})
    propose(client, accepted(client))
    system = fake.requests[0]["system"][0]["text"]
    assert "not vendors, products or brand names" in system
    assert "Never invent numbers" in system
