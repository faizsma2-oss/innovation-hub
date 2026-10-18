"""Reusing supplier research and contacts from earlier requests instead of searching again."""
import json
from datetime import datetime, timedelta, timezone

from backend import db
from backend.research import suppliers as supplier_module
from test_suppliers import in_research, run, setup


def researched(client, option="B"):
    sid = in_research(client) if option == "B" else other_approach(client)
    run(client, sid)
    return sid


def other_approach(client):
    record = client.post("/api/submissions", json={
        "title": "Visitor badges", "description": "Visitors wait at reception because badges are printed by hand.",
        "current_process": "Reception types each visitor into the badge printer.", "people_affected": "Reception"}).json()
    sid = record["id"]
    client.post(f"/api/submissions/{sid}/review", json={"decision": "accept"})
    client.post(f"/api/submissions/{sid}/solutions", json={})
    client.post(f"/api/submissions/{sid}/solutions/select", json={"option_id": "C", "reason": "Needs a real product"})
    return sid


def earlier(client, sid):
    return client.get(f"/api/submissions/{sid}/suppliers/earlier").json()


def test_similar_earlier_research_is_offered_and_unrelated_isnt(client):
    first = researched(client)
    unrelated = researched(client, option="C")
    new = in_research(client)
    offered = earlier(client, new)
    assert [r["submission_id"] for r in offered] == [first]
    assert offered[0]["suppliers"] and offered[0]["age_days"] == 0
    assert unrelated not in [r["submission_id"] for r in offered]


def test_reuse_without_a_web_search_costs_nothing(client, monkeypatch):
    first = researched(client)
    new = in_research(client)
    calls = []
    monkeypatch.setattr(supplier_module.MockSupplierResearcher, "research",
                        lambda *args, **kwargs: calls.append(1) or {"suppliers": []})
    record = run(client, new, setup() | {"reuse": [first], "web_search": False}).json()
    found = record["research"]["suppliers"]
    assert calls == [] and found["cost_usd"] == 0
    assert all(s["reused_from"]["submission_id"] == first for s in found["suppliers"])
    assert [s["rank"] for s in found["suppliers"]] == list(range(1, len(found["suppliers"]) + 1))


def test_factors_the_earlier_search_didnt_cover_are_unknown(client):
    first = researched(client)
    new = in_research(client)
    extra = {"key": "arabic_support", "name": "Arabic interface", "description": "", "importance": "must"}
    body = setup() | {"reuse": [first], "web_search": False}
    body["factors"] = body["factors"] + [extra]
    supplier = run(client, new, body).json()["research"]["suppliers"]["suppliers"][0]
    assert supplier["findings"]["arabic_support"]["rating"] is None
    assert supplier["findings"]["arabic_support"]["finding"] == "Not covered by the earlier research."
    assert "Arabic interface" in supplier["must_haves"]["unconfirmed"]            # rechecked with this request's must-haves
    assert supplier["eligibility"] == "must_have_unconfirmed"


def test_reuse_with_a_web_search_merges_without_duplicates(client):
    first = researched(client)
    new = in_research(client)
    found = run(client, new, setup() | {"reuse": [first]}).json()["research"]["suppliers"]["suppliers"]
    names = [s["name"].lower() for s in found]
    assert len(names) == len(set(names))
    assert any("reused_from" not in s for s in found)                             # fresh results win for the same name


def test_old_research_is_flagged_and_only_offered_runs_can_be_reused(client):
    first = researched(client)
    with db.connect() as conn:
        row = conn.execute("SELECT research_json FROM submissions WHERE pk = ?", (int(first[4:]),)).fetchone()
        research = json.loads(row["research_json"])
        research["suppliers"]["run_at"] = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
        conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), int(first[4:])))
    new = in_research(client)
    supplier = run(client, new, setup() | {"reuse": [first], "web_search": False}).json()["research"]["suppliers"]["suppliers"][0]
    assert supplier["reused_from"]["stale"] and supplier["reused_from"]["age_days"] == 120
    unrelated = researched(client, option="C")
    assert run(client, new, setup() | {"reuse": [unrelated], "web_search": False}).status_code == 422
    assert run(client, new, setup() | {"reuse": [], "web_search": False}).status_code == 422


def test_contacts_on_file_are_reused_unless_searching_again(client, monkeypatch):
    first = researched(client)
    name = client.get(f"/api/submissions/{first}").json()["research"]["suppliers"]["suppliers"][0]["name"]
    client.post(f"/api/submissions/{first}/suppliers/shortlist", json={"names": [name]})
    client.post(f"/api/submissions/{first}/contacts/find", json={"supplier": name})
    new = in_research(client)
    run(client, new, setup() | {"reuse": [first], "web_search": False})
    client.post(f"/api/submissions/{new}/suppliers/shortlist", json={"names": [name]})
    from backend.meetings import assistant as meeting_assistant
    searches = []
    original = meeting_assistant.MockMeetingAssistant.find_contacts
    monkeypatch.setattr(meeting_assistant.MockMeetingAssistant, "find_contacts",
                        lambda self, *a, **k: searches.append(1) or original(self, *a, **k))
    reused = client.post(f"/api/submissions/{new}/contacts/find", json={"supplier": name}).json()
    assert searches == [] and reused["reused_from"] == first and reused["contacts"] and reused["cost_usd"] == 0
    fresh = client.post(f"/api/submissions/{new}/contacts/find", json={"supplier": name, "fresh": True}).json()
    assert searches == [1] and "reused_from" not in fresh
