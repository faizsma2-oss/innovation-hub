"""Checking each solution option's evidence on the web: only sources the search opened count, scores change
only with verified evidence, and the ranking is recalculated in code. Fake Claude: no network, no cost."""
import json
from types import SimpleNamespace

import pytest

from backend import llm
from backend.research import evidence
from backend.research.researcher import usefulness
from test_research import accepted, propose

OPENED = ["https://www.uptimeinstitute.com/resources/case-study-automation", "https://example-utility.org/report"]


def usage(searches=0):
    return SimpleNamespace(input_tokens=4000, output_tokens=800, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                           server_tool_use=SimpleNamespace(web_search_requests=searches))


class FakeWeb:
    """Phase 1 returns search results for OPENED; phase 2 returns the structured reply given."""
    def __init__(self, structured):
        self.structured, self.calls = structured, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.calls.append(request)
        if "tools" in request:
            results = SimpleNamespace(type="web_search_tool_result", content=[
                SimpleNamespace(type="web_search_result", url=url) for url in OPENED])
            return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn", usage=usage(searches=3),
                                   content=[results, SimpleNamespace(type="text", text="Notes about each option…", citations=None)])
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn", usage=usage(),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.structured))])


@pytest.fixture
def web(monkeypatch):
    def install(structured):
        fake = FakeWeb(structured)
        monkeypatch.setattr(evidence, "_client", fake)
        monkeypatch.setattr(llm, "claude_enabled", lambda kind="ai": True)
        return fake
    return install


def options_of(client, sid):
    return {o["id"]: o for o in client.get(f"/api/submissions/{sid}").json()["solutions"]["options"]}


def test_verified_sources_update_the_score_and_the_ranking(client, web):
    sid = accepted(client)
    propose(client, sid)
    before = options_of(client, sid)
    web({"summary": "Automation is well documented; process changes less so.", "options": [
        {"id": "B", "score": 5, "reason": "Several operators report it.", "findings": [
            {"claim": "An operator cut report preparation time by automating exports.", "url": OPENED[0]},
            {"claim": "A made-up source.", "url": "https://never-opened.example/page"}]},
        {"id": "A", "score": 4, "reason": "Sounds plausible.", "findings": []},
        {"id": "C", "score": 2, "reason": "Mixed results.", "findings": [
            {"claim": "A utility found dedicated tools slow to integrate.", "url": OPENED[1] + "/"}]}]})
    reply = client.post(f"/api/submissions/{sid}/solutions/evidence")
    assert reply.status_code == 200
    after = options_of(client, sid)
    b = after["B"]["evidence_check"]
    assert [f["url"] for f in b["findings"]] == [OPENED[0]]                      # the unopened source is dropped
    assert b["before"] == before["B"]["scores"]["evidence"]["value"] and b["after"] == 5
    assert after["B"]["scores"]["evidence"]["reason"].startswith("Web check:")
    assert after["A"]["evidence_check"]["after"] == before["A"]["scores"]["evidence"]["value"]   # no source, no change
    assert after["C"]["evidence_check"]["findings"][0]["url"] == OPENED[1]           # trailing slash still matches
    assert all(o["usefulness"] == usefulness(o["scores"]) for o in after.values())  # ranking recalculated in code
    solutions = reply.json()["solutions"]
    assert solutions["evidence_check"]["sources_retrieved"] == 2 and solutions["evidence_check"]["cost_usd"] > 0


def test_without_the_ai_nothing_changes_and_the_reason_is_given(client):
    sid = accepted(client)
    propose(client, sid)
    before = options_of(client, sid)
    reply = client.post(f"/api/submissions/{sid}/solutions/evidence")
    assert reply.status_code == 409 and "nothing changed" in reply.json()["detail"]
    assert options_of(client, sid) == before


def test_only_while_choosing_an_option(client, web):
    sid = accepted(client)
    assert client.post(f"/api/submissions/{sid}/solutions/evidence").status_code == 409     # no options yet


def test_a_failed_search_changes_nothing(client, monkeypatch):
    sid = accepted(client)
    propose(client, sid)
    before = options_of(client, sid)
    monkeypatch.setattr(llm, "claude_enabled", lambda kind="ai": True)
    monkeypatch.setattr(evidence, "check_evidence", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("timeout")))
    reply = client.post(f"/api/submissions/{sid}/solutions/evidence")
    assert reply.status_code == 502 and "nothing changed" in reply.json()["detail"]
    assert options_of(client, sid) == before
