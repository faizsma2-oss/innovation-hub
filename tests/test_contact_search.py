"""Why a contact search isn't live, said plainly: fictional suppliers aren't searched, and a switched-off or
capped AI says so instead of pretending to be a search."""
import json

from backend import budget, db
from backend.meetings import routes as meeting_routes
from test_evaluation import shortlisted


def make_real(sid, name, website="https://acme-analytics.ae"):
    """Give the shortlisted example supplier a real-looking name and website."""
    with db.connect() as conn:
        research = json.loads(conn.execute("SELECT research_json FROM submissions WHERE pk = ?", (db.parse_pk(sid),)).fetchone()[0])
        supplier = next(s for s in research["suppliers"]["suppliers"] if s["name"] == name)
        supplier |= {"name": "Acme Analytics", "website": website}
        research["suppliers"]["shortlist"]["names"] = ["Acme Analytics" if n == name else n for n in research["suppliers"]["shortlist"]["names"]]
        conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), db.parse_pk(sid)))
    return "Acme Analytics"


def test_fictional_suppliers_are_not_searched_and_say_why(client, monkeypatch):
    sid, names = shortlisted(client)
    monkeypatch.setattr(meeting_routes, "get_assistant", lambda: (_ for _ in ()).throw(AssertionError("no search")))
    found = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": names[0], "fresh": True}).json()
    assert "fictional example supplier" in found["notice"] and found["contacts"]          # examples to try the flow


def test_without_the_ai_the_box_says_so(client):
    sid, names = shortlisted(client)
    name = make_real(sid, names[0])
    found = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": name, "fresh": True}).json()
    assert found["notice"].startswith("The AI assistant isn't switched on here.")
    assert "no AI key" not in found["summary"]


def test_a_used_up_allowance_is_named(client, monkeypatch):
    sid, names = shortlisted(client)
    name = make_real(sid, names[0])
    monkeypatch.setattr(budget, "status", lambda: {"caps": True, "blocked": "You've used your AI allowance for today.",
                                                    "web_blocked": "You've used your AI allowance for today."})
    found = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": name, "fresh": True}).json()
    assert found["notice"].startswith("You've used your AI allowance for today.")


def test_example_dot_com_websites_count_as_fictional():
    assert meeting_routes.no_live_search({"name": "Acme", "website": "https://example.com/supplier-1"})
    assert meeting_routes.no_live_search({"name": "Acme", "website": "https://gulf-integrator.example"})
    assert not meeting_routes.no_live_search({"name": "Zoho", "website": "https://www.zoho.com"})
    assert not meeting_routes.no_live_search({"name": "Example Systems LLC", "website": "https://examplesystems.ae"})
