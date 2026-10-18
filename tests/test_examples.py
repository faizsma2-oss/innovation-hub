"""Example records: a new public-demo sandbox shows the whole lifecycle, built with the scripted
assistants only, fast, and without disturbing the demo journey."""
import time

from fastapi.testclient import TestClient

from backend import examples, llm, main
from conftest import Chat
from test_public_demo import public  # noqa: F401  (fixture)

STAGES = ["Screening", "Choose a solution", "Research", "Pilot", "Scaling", "In operation", "Closed"]


def test_new_sandbox_has_an_example_in_every_stage(public, monkeypatch):
    monkeypatch.setenv("HUB_BRAIN", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")      # would use Claude if seeding let it
    calls = []
    monkeypatch.setattr(llm, "call_json", lambda *args, **kwargs: calls.append(1) or (_ for _ in ()).throw(llm.LLMError("no")))
    with TestClient(main.app) as visitor:
        started = time.perf_counter()
        records = visitor.get("/api/submissions").json()
        assert time.perf_counter() - started < 5                          # Render's port scan timed out before
        stages = {s["name"]: s["cards"] for s in visitor.get("/api/portfolio").json()["stages"]}
        assert all(stages[name] for name in STAGES)
        by_status = {r["status"]: r for r in records if r["submitted_by"] == examples.EXAMPLE_USER and r["status"] != "Routed"}
        assert set(by_status) == {"Accepted", "Research", "Pilot running", "Scaling", "In operation", "Stopped"}
        assert all(r["title"].startswith("Example:") for r in by_status.values())

        assert len(by_status["Accepted"]["solutions"]["options"]) >= 3
        assert by_status["Research"]["research"]["suppliers"]["shortlist"]
        assert by_status["Pilot running"]["research"]["pilot"]["measurements"]
        assert by_status["Scaling"]["research"]["scale"]["business_case"]["status"] == "AWAITING DECISION"
        live = by_status["In operation"]["research"]
        assert live["scale"]["checkins"][0]["result"] and live["lesson"]["id"].startswith("LES-")
        assert by_status["Stopped"]["research"]["lesson"]["kind"] == "previous_pilot"

        # The supplier pages aren't empty: contacts, an approved email and its reply, a held meeting with
        # actions (owners and dates from the notes), a draft waiting for approval, and tagged notes.
        pages = {c["name"]: visitor.get(f"/api/companies/{c['id']}").json() for c in visitor.get("/api/companies").json()}
        met = next(p for p in pages.values() if any(m["status"] == "held" for m in p["meetings"]))
        assert {(e["direction"], e["status"]) for e in met["emails"]} == {("out", "SENT"), ("in", "RECEIVED")}
        assert met["actions"] and any(a["owner"] == "Example Reviewer" and a["due"] for a in met["actions"])
        assert {n["tag"] for n in met["notes"]} >= {"Requirement", "Pricing", "Pilot needed"}
        assert any(e["status"] == "DRAFT" for p in pages.values() for e in p["emails"])
        assert all(p["contacts"] for p in pages.values())
        assert any(i["kind"] == "overdue" for i in visitor.get("/api/reminders").json()["items"])

        rule = visitor.get("/api/routing/suggestions").json()["suggestions"][0]
        assert rule["route"] == "facilities_procurement" and rule["fixes"] == 3 and rule["breaks"] == 0

        report = visitor.get("/api/reports").json()[0]
        assert report["decisions_needed"] and report["moved"] and report["summary"]
        assert "Example:" in visitor.get("/api/submissions").text
    assert calls == []


def test_examples_do_not_take_over_the_demo_chat(client):
    examples.seed()
    examples.seed()                                                        # a second call adds nothing
    assert sum(r["submitted_by"] == examples.EXAMPLE_USER for r in client.get("/api/submissions").json()) == 9
    linked = Chat(client)
    linked.say("Several sites repeat the same inspection paperwork: handwritten inspection notes are copied "
               "into shared reports by hand.")
    assert linked.dont_know_until_done()["stage"] == "link_offer" and "SUB-0001" in linked.reply["message"]
    reporting = Chat(client)
    reporting.say("Every week, we manually combine reports from several systems.")
    assert reporting.dont_know_until_done()["stage"] not in ("link_offer", "solution_offer")
