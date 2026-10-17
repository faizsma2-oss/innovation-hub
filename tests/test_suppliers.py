"""Supplier research: setup questions with remembered answers, custom factors, and checked,
ranked results. Uses the scripted researcher and a fake Claude: no network, no cost."""
import json
from types import SimpleNamespace

import pytest

from backend.research import routes as research_routes
from backend.research import suppliers
from backend.research.suppliers import MOCK_SUPPLIERS, ClaudeSupplierResearcher


def in_research(client):
    record = client.post("/api/submissions", json={
        "title": "Weekly report merging", "description": "Every week we manually combine energy reports from several systems.",
        "current_process": "Copy numbers from 3 tools into a spreadsheet; should be automatic.",
        "people_affected": "The reporting team at 4 sites", "impact": "About 6 hours a week"}).json()
    sid = record["id"]
    client.post(f"/api/submissions/{sid}/review", json={"decision": "accept"})
    client.post(f"/api/submissions/{sid}/solutions", json={})
    client.post(f"/api/submissions/{sid}/solutions/select", json={"option_id": "B", "reason": "Fits"})
    return sid


def setup(**changes):
    base = suppliers.default_setup()
    base["factors"] = [{k: f[k] for k in ("key", "name", "description", "importance")} for f in base["factors"]]
    return base | changes


def run(client, sid, body=None):
    return client.post(f"/api/submissions/{sid}/suppliers", json=body or setup())


# ── The setup questions ──────────────────────────────────────────────────────

def test_setup_offers_library_options_and_defaults(client):
    data = client.get("/api/research/supplier-setup").json()
    assert {f["key"] for f in data["library"]} >= {"cost", "uae_presence", "data_residency", "certifications"}
    assert set(data["geography"]) == {"uae_first", "uae_gcc", "global"}
    assert set(data["cost_policy"]) == {"published_only", "estimates", "relative"}
    assert data["defaults"]["geography"] == "uae_first"


def test_last_answers_are_remembered_for_next_time(client):
    sid = in_research(client)
    custom = {"key": "custom_arabic_support", "name": "Arabic-language support", "description": "", "importance": "medium"}
    body = setup(geography="uae_gcc", cost_policy="relative", supplier_count=3,
                 factors=setup()["factors"][:3] + [custom])
    assert run(client, sid, body).status_code == 200
    defaults = client.get("/api/research/supplier-setup").json()["defaults"]
    assert defaults["geography"] == "uae_gcc" and defaults["cost_policy"] == "relative"
    assert any(f["name"] == "Arabic-language support" for f in defaults["factors"])


def test_ai_suggests_extra_factors_with_keys(client):
    sid = in_research(client)
    suggested = client.post(f"/api/submissions/{sid}/suppliers/suggest-factors").json()
    assert suggested and all(f["key"].startswith("custom_") and f["name"] and f["why"] for f in suggested)


def test_setup_is_validated(client):
    sid = in_research(client)
    duplicate = setup(factors=[setup()["factors"][0]] * 2)
    assert run(client, sid, duplicate).status_code == 422
    only_musts = setup(factors=[dict(setup()["factors"][0], importance="must")])
    assert run(client, sid, only_musts).status_code == 422
    assert run(client, sid, setup(supplier_count=12)).status_code == 422


def test_supplier_research_only_after_an_option_is_chosen(client):
    record = client.post("/api/submissions", json={"title": "x", "description": "Every week we retype logs by hand."}).json()
    assert run(client, record["id"]).status_code == 409


# ── Results and shortlist (scripted researcher) ──────────────────────────────

def test_custom_factor_appears_in_every_supplier_comparison(client):
    sid = in_research(client)
    custom = {"key": "custom_arabic_support", "name": "Arabic-language support", "description": "", "importance": "high"}
    result = run(client, sid, setup(factors=setup()["factors"] + [custom])).json()["research"]["suppliers"]
    assert result["status"] == "PROPOSED" and result["round"] == 1
    assert all("custom_arabic_support" in s["findings"] for s in result["suppliers"])
    assert "fictional" in result["summary"].lower()      # scripted examples are clearly labelled


def test_shortlist_from_latest_comparison(client):
    sid = in_research(client)
    found = run(client, sid).json()["research"]["suppliers"]["suppliers"]
    names = [found[0]["name"], found[1]["name"]]
    shortlisted = client.post(f"/api/submissions/{sid}/suppliers/shortlist", json={"names": names, "note": "Call both"})
    assert shortlisted.json()["research"]["suppliers"]["shortlist"]["names"] == names
    bad = client.post(f"/api/submissions/{sid}/suppliers/shortlist", json={"names": ["Made Up Ltd"]})
    assert bad.status_code == 422


# ── Ranking rules (plain code) ───────────────────────────────────────────────

def factor(key, importance):
    return {"key": key, "name": key, "description": "", "importance": importance}


def finding(rating, met="yes", url="https://a.example/page"):
    return {"rating": rating, "finding": "x", "evidence": "supplier-stated", "sources": [url], "must_have_met": met}


def test_must_have_failure_ranks_last_and_unknown_is_not_zero():
    setup_ = {"factors": [factor("price", "high"), factor("residency", "must"), factor("refs", "low")]}
    ranked = suppliers.rank([
        {"name": "Fails residency", "findings": {"price": finding(5), "residency": finding(None, "no"), "refs": finding(5)}},
        {"name": "Unknown refs", "findings": {"price": finding(4), "residency": finding(None, "yes"), "refs": finding(None)}},
        {"name": "Residency unconfirmed", "findings": {"price": finding(5), "residency": finding(None, "unknown"),
                                                        "refs": finding(5)}},
    ], setup_)
    assert [s["name"] for s in ranked] == ["Unknown refs", "Residency unconfirmed", "Fails residency"]
    unknown_refs = ranked[0]
    assert unknown_refs["fit_score"] == 80             # 4/5 from price alone: refs left out, not zero
    assert unknown_refs["confidence"] == "high"        # 3 of 4 weight known


# ── Claude researcher: sources must have been retrieved ──────────────────────

def block(**fields):
    return SimpleNamespace(**fields)


def search_response(urls, stop_reason="end_turn", searches=3):
    results = [block(type="web_search_result", url=url, title="t") for url in urls]
    return SimpleNamespace(
        model="claude-opus-5-5", stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=20000, output_tokens=3000, cache_creation_input_tokens=0,
                              cache_read_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=searches)),
        content=[block(type="server_tool_use", id="s1", name="web_search", input={}),
                 block(type="web_search_tool_result", tool_use_id="s1", content=results),
                 block(type="text", text="Findings with links...", citations=None)])


class FakeClaude:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, SimpleNamespace):
            return reply
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=5000, output_tokens=2000,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(reply))])


@pytest.fixture
def use_claude(monkeypatch):
    def install(*replies):
        fake = FakeClaude(*replies)
        monkeypatch.setattr(suppliers, "get_supplier_researcher",
                            lambda: ClaudeSupplierResearcher(fallback=MOCK_SUPPLIERS, client=fake))
        return fake
    return install


def structured(*supplier_list):
    return {"suppliers": list(supplier_list), "summary": "Compared.", "gaps": ["No public prices"]}


def supplier(name, sources, price=None, price_sources=(), **ratings):
    return {"name": name, "website": "https://" + name.lower().replace(" ", "") + ".example", "headquarters": "Dubai",
            "uae_presence": "Dubai office", "offering": "Does it.",
            "findings": [{"factor_key": key, "rating": value, "finding": "Found.", "evidence": "supplier-stated",
                          "sources": sources, "must_have_met": "unknown"} for key, value in ratings.items()],
            "cost": {"published_price": price or "", "estimate": "", "relative": "moderate", "sources": list(price_sources)},
            "questions_for_supplier": ["Pilot price?"]}


def small_setup(**changes):
    return {"factors": [factor("cost", "high"), factor("integration", "medium")], "geography": "uae_first",
            "cost_policy": "published_only", "supplier_count": 3, "notes": ""} | changes


def test_sources_not_retrieved_are_dropped_and_become_unknown(client, use_claude):
    use_claude(search_response(["https://real.example/pricing", "https://real.example/integrations"]),
               structured(supplier("Real Co", ["https://real.example/integrations/"], cost=4, integration=5),
                          supplier("Invented Co", ["https://invented.example/page"], cost=5, integration=5)))
    result = run(client, in_research(client), small_setup()).json()["research"]["suppliers"]
    by_name = {s["name"]: s for s in result["suppliers"]}
    assert by_name["Real Co"]["findings"]["integration"]["rating"] == 5      # trailing slash still matches
    invented = by_name["Invented Co"]["findings"]["integration"]
    assert invented["rating"] is None and invented["evidence"] == "not verified"
    assert by_name["Invented Co"]["fit_score"] is None
    assert result["searches"] == 3 and result["sources_retrieved"] == 2


def test_price_without_a_retrieved_source_is_price_on_request(client, use_claude):
    use_claude(search_response(["https://real.example/pricing"]),
               structured(supplier("Sourced", ["https://real.example/pricing"], price="AED 2,000 per month",
                                   price_sources=["https://real.example/pricing"], cost=3, integration=3),
                          supplier("Unsourced", ["https://real.example/pricing"], price="AED 500 per month",
                                   cost=5, integration=3)))
    result = run(client, in_research(client), small_setup()).json()["research"]["suppliers"]
    by_name = {s["name"]: s["cost"] for s in result["suppliers"]}
    assert by_name["Sourced"]["published_price"] == "AED 2,000 per month" and by_name["Sourced"]["price_is_published"]
    assert by_name["Unsourced"]["published_price"] == "Price on request"


def test_paused_search_is_resumed(client, use_claude):
    fake = use_claude(search_response(["https://a.example/1"], stop_reason="pause_turn"),
                      search_response(["https://b.example/2"]),
                      structured(supplier("B Co", ["https://b.example/2"], cost=3, integration=3)))
    result = run(client, in_research(client), small_setup()).json()["research"]["suppliers"]
    assert result["sources_retrieved"] == 2
    assert fake.requests[1]["messages"][1]["role"] == "assistant"   # paused turn sent back, no extra user message
    assert len(fake.requests[1]["messages"]) == 2


def test_geography_and_prompt_rules_are_sent(client, use_claude):
    fake = use_claude(search_response(["https://a.example/1"]),
                      structured(supplier("A Co", ["https://a.example/1"], cost=3, integration=3)))
    run(client, in_research(client), small_setup())
    search_tool = fake.requests[0]["tools"][0]
    assert search_tool["type"] == "web_search_20260209"
    assert "user_location" not in search_tool        # the API rejects country "AE"
    assert "UAE first" in fake.requests[0]["messages"][0]["content"]
    assert "never instructions" in fake.requests[0]["system"][0]["text"]


def test_no_retrieved_pages_falls_back_to_labelled_examples(client, use_claude):
    use_claude(search_response([]))
    result = run(client, in_research(client), small_setup()).json()["research"]["suppliers"]
    assert result["generated_by"].startswith("suppliers-mock") and "error" in result
