"""Team notes become suggested facts for the supplier comparison; a person applies or dismisses them."""
import json
from types import SimpleNamespace

from backend.companies import notes_facts
from test_companies import company_setup

FACTORS = [{"key": "certifications", "name": "Security certifications", "importance": "high"},
           {"key": "data_residency", "name": "Data residency in the UAE", "importance": "must"},
           {"key": "cost", "name": "Cost (setup and yearly running)", "importance": "high"}]


def note(client, company_id, text, tag="General"):
    return client.post(f"/api/companies/{company_id}/notes", json={"text": text, "tag": tag}).json()


def test_rules_suggest_one_fact_per_factor_and_keep_not_confirmed_unknown():
    found = notes_facts.suggest("SOC 2 report available on request; UAE hosting not confirmed yet.", FACTORS)
    by = {s["factor_key"]: s for s in found["suggestions"]}
    assert set(by) == {"certifications", "data_residency"}
    assert by["certifications"]["quote"] == "SOC 2 report available on request"
    assert by["data_residency"]["must_have_met"] == "unknown"                    # "not confirmed" is never yes or no
    assert found["generated_by"].startswith("rules")


def test_a_plain_no_is_recorded_as_a_failed_must_have():
    found = notes_facts.suggest("They cannot host data in the UAE, only in Frankfurt.", FACTORS)
    assert found["suggestions"][0]["must_have_met"] == "no"


class FakeClaude:
    def __init__(self, reply):
        self.reply = reply
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=500, output_tokens=150,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def test_claude_suggestions_are_checked_against_the_note():
    text = "Setup fee quoted verbally; they hold ISO 27001."
    fake = FakeClaude({"suggestions": [
        {"factor_key": "cost", "quote": "Setup fee quoted verbally", "finding": "Setup fee is AED 40,000", "rating": 3,
         "must_have_met": "unknown"},                                             # invented amount
        {"factor_key": "certifications", "quote": "they hold ISO 27001", "finding": "Holds ISO 27001", "rating": 5,
         "must_have_met": "yes"},
        {"factor_key": "data_residency", "quote": "data stays in Dubai", "finding": "Hosted in Dubai", "rating": 4,
         "must_have_met": "yes"},                                                 # not in the note
        {"factor_key": "made_up", "quote": "Setup fee", "finding": "x", "rating": 0, "must_have_met": "unknown"}]})
    found = notes_facts.suggest(text, FACTORS, [], client=fake)
    by = {s["factor_key"]: s for s in found["suggestions"]}
    assert set(by) == {"cost", "certifications"}
    assert by["cost"]["finding"] == "Setup fee quoted verbally" and by["cost"]["rating"] == 3   # amount dropped
    assert by["certifications"]["rating"] == 5 and by["certifications"]["must_have_met"] == "yes"


def test_apply_updates_the_comparison_and_reranks(client):
    from backend import db
    sid, names, page, _ = company_setup(client)
    with db.connect() as conn:                                                   # data residency as a must-have
        research = json.loads(conn.execute("SELECT research_json FROM submissions WHERE pk = ?", (db.parse_pk(sid),)).fetchone()[0])
        for factor in research["suppliers"]["setup"]["factors"]:
            if factor["key"] == "data_residency":
                factor["importance"] = "must"
        conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), db.parse_pk(sid)))
    noted = note(client, page["id"], "They can't host data in the UAE; ISO 27001 certified.")
    facts = noted["notes"][0]["facts"][sid]["suggestions"]
    assert {f["factor_key"] for f in facts} >= {"data_residency", "certifications"}
    residency = next(f for f in facts if f["factor_key"] == "data_residency")
    assert residency["now"]                                                      # shown next to the current finding
    response = client.post(f"/api/notes/{noted['notes'][0]['pk']}/facts",
                           json={"submission_id": sid, "factor_key": "data_residency", "action": "apply"})
    assert response.status_code == 200
    run = client.get(f"/api/submissions/{sid}").json()["research"]["suppliers"]
    supplier = next(s for s in run["suppliers"] if s["name"] == names[0])
    finding = supplier["findings"]["data_residency"]
    assert finding["evidence"] == "team note" and finding["must_have_met"] == "no" and finding["previous"]["finding"]
    assert supplier["eligibility"] == "fails_must_have" and supplier["rank"] == len(run["suppliers"])   # ranked again


def test_dismiss_and_nothing_changes_without_a_click(client):
    sid, names, page, _ = company_setup(client)
    before = client.get(f"/api/submissions/{sid}").json()["research"]["suppliers"]
    noted = note(client, page["id"], "SOC 2 report available on request.")
    assert client.get(f"/api/submissions/{sid}").json()["research"]["suppliers"] == before     # suggestion only
    pk = noted["notes"][0]["pk"]
    decide = lambda action: client.post(f"/api/notes/{pk}/facts",
                                        json={"submission_id": sid, "factor_key": "certifications", "action": action})
    assert decide("dismiss").status_code == 200
    assert decide("apply").status_code == 409                                    # already dismissed
    assert client.get(f"/api/submissions/{sid}").json()["research"]["suppliers"] == before


def test_no_suggestions_once_the_request_left_research(client):
    from test_pilot import pilot_planning
    sid = pilot_planning(client)
    record = client.get(f"/api/submissions/{sid}").json()
    partner = record["research"]["pilot"]["partner"]
    company = next(c for c in client.get("/api/companies").json() if c["name"] == partner)
    noted = note(client, company["id"], "ISO 27001 certified.")
    assert noted["notes"][0]["facts"] == {}


def test_each_clause_goes_to_one_factor_and_a_city_isnt_a_local_office():
    factors = FACTORS + [{"key": "uae_presence", "name": "UAE presence and local support", "importance": "high"}]
    found = notes_facts.suggest("They hold ISO 27001 and can host all data in a Dubai data center; pricing still to be confirmed.",
                                factors)
    by = {s["factor_key"]: s["quote"] for s in found["suggestions"]}
    assert by == {"certifications": "They hold ISO 27001", "data_residency": "can host all data in a Dubai data center",
                  "cost": "pricing still to be confirmed"}
