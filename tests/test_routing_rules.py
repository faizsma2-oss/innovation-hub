"""Routing rules learned from the team's corrections: suggested with evidence, replayed, approved by a person."""
from conftest import Chat

CARD = ["My access card stopped working at the turnstile this morning",
        "The turnstile rejects my access card since yesterday",
        "New starter's access card does not open the turnstile on level 2"]


def submit(client, text, title=None):
    return client.post("/api/submissions", json={"title": title or text[:60], "description": text}).json()


def corrected(client, text, to="facilities_procurement", reason="Security desk handles access cards"):
    record = submit(client, text)
    assert record["route"] == "human_triage"                       # the built-in rules don't know this one
    client.post(f"/api/submissions/{record['id']}/reroute", json={"route": to, "reason": reason})
    return record["id"]


def suggestions(client):
    return client.get("/api/routing/suggestions").json()


def test_one_correction_is_not_enough(client):
    corrected(client, CARD[0])
    assert suggestions(client)["suggestions"] == []


def test_repeated_corrections_suggest_a_rule_with_evidence_and_replay(client):
    ids = [corrected(client, text) for text in CARD]
    found = suggestions(client)["suggestions"]
    assert found and all(s["route"] == "facilities_procurement" and s["breaks"] == 0 for s in found)
    best = found[0]
    assert best["fixes"] == 3 and {r["id"] for r in best["requests"]} == set(ids)
    assert best["word"] in ("turnstile", "access", "card") and "Security desk" in best["requests"][0]["reason"]


def test_a_rule_that_would_misroute_a_past_request_is_not_suggested(client):
    for text in CARD:
        corrected(client, text)
    other = submit(client, "Turnstile badge photo for my HR file is wrong, payroll needs the new one")
    assert other["route"] == "hr"                                  # routed right first time, never corrected
    words = {s["term"] for s in suggestions(client)["suggestions"]}
    assert "turnstil" not in words                                 # "turnstile" also appears in an HR request
    assert words                                                    # "access card" still qualifies


def test_approved_rule_routes_new_requests_but_never_before_the_incident_check(client):
    for text in CARD:
        corrected(client, text)
    key = suggestions(client)["suggestions"][0]["key"]
    data = client.post("/api/routing/rules", json={"key": key}).json()
    rule = data["rules"][0]
    assert rule["approved_by"] and rule["fixes"] == 3 and not any(s["key"] == key for s in data["suggestions"])
    new = submit(client, f"Visitor's {rule['word']} problem at reception, it fails every time")
    assert new["route"] == "facilities_procurement" and "Learned rule" in new["route_reason"]
    chat = Chat(client)
    chat.say(f"There is smoke near the {rule['word']} reader by the loading bay")
    assert chat.reply["stage"] in ("safety_check", "incident") or "emergency" in chat.reply["message"].lower()
    assert client.delete(f"/api/routing/rules/{rule['term']}").json()["rules"] == []
    assert submit(client, f"Another {rule['word']} problem at reception today")["route"] == "human_triage"


def test_dismissed_suggestions_stay_dismissed_and_stale_ones_cant_be_approved(client):
    for text in CARD:
        corrected(client, text)
    key = suggestions(client)["suggestions"][0]["key"]
    after = client.post("/api/routing/suggestions/dismiss", json={"key": key}).json()
    assert key not in {s["key"] for s in after["suggestions"]}
    assert client.post("/api/routing/rules", json={"key": key}).status_code == 409
