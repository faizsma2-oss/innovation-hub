"""Public demo mode: a private sandbox per visitor, and spending caps on Claude."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from backend import budget, llm, main
from backend.intake import brain as brain_module


@pytest.fixture
def public(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SANDBOXES", True)
    monkeypatch.setattr(main, "SANDBOX_DIR", tmp_path / "sandboxes")
    monkeypatch.setenv("HUB_DB_PATH", str(tmp_path / "shared.db"))
    monkeypatch.setenv("HUB_SPEND_DB", str(tmp_path / "spend.db"))
    return tmp_path


def visitor():
    return TestClient(main.app)


# ── Sandboxes ────────────────────────────────────────────────────────────────

def test_each_visitor_has_a_private_copy_of_the_demo(public):
    with visitor() as alice, visitor() as bob:
        created = alice.post("/api/submissions", json={"title": "Alice's idea",
                                                      "description": "Every week we retype logs by hand."}).json()
        alice_titles = [s["title"] for s in alice.get("/api/submissions").json()]
        bob_titles = [s["title"] for s in bob.get("/api/submissions").json()]
        assert "Alice's idea" in alice_titles and "Alice's idea" not in bob_titles
        assert len(bob_titles) == 12                                  # Bob starts from the clean demo (3 + 6 examples)
        assert bob.get(f"/api/submissions/{created['id']}").status_code == 404
        assert len(list((public / "sandboxes").glob("*.db"))) == 2


def test_sandbox_cookie_is_private_and_reused(public):
    with visitor() as alice:
        first = alice.get("/api/submissions")
        cookie = first.cookies.get("hub_sandbox")
        assert cookie and len(cookie) == 32
        assert "httponly" in first.headers["set-cookie"].lower()
        assert "hub_sandbox" not in alice.get("/api/submissions").headers.get("set-cookie", "")  # same visitor
        assert alice.get("/api/health").json()["public_demo"] is True


def test_a_tampered_cookie_gets_a_fresh_sandbox(public):
    with visitor() as mallory:
        mallory.cookies.set("hub_sandbox", "../../etc/passwd")
        response = mallory.get("/api/submissions")
        assert response.status_code == 200
        assert all(f.parent == public / "sandboxes" for f in (public / "sandboxes").glob("*"))


def test_old_sandboxes_are_deleted(public, monkeypatch):
    folder = public / "sandboxes"
    folder.mkdir(parents=True)
    old, recent = folder / ("a" * 32 + ".db"), folder / ("b" * 32 + ".db")
    old.write_text(""), recent.write_text("")
    two_days_ago = time.time() - 48 * 3600
    os.utime(old, (two_days_ago, two_days_ago))
    monkeypatch.setattr(main, "_last_cleanup", 0.0)
    main.clean_old_sandboxes()
    assert not old.exists() and recent.exists()


# ── Spending caps ────────────────────────────────────────────────────────────

@pytest.fixture
def capped(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SPEND_CAPS", "on")
    monkeypatch.setenv("HUB_SPEND_DB", str(tmp_path / "spend.db"))
    monkeypatch.setenv("HUB_BRAIN", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setenv("HUB_VISITOR_DAILY_USD", "0.10")
    monkeypatch.setenv("HUB_DAILY_USD", "0.25")
    monkeypatch.setenv("HUB_WEB_RUNS_PER_VISITOR", "1")


def as_visitor(name):
    return budget.current_visitor.set(name)


def test_visitor_cap_switches_that_visitor_to_the_scripted_brain(capped):
    token = as_visitor("alice")
    assert llm.claude_enabled() is True
    budget.record(0.12)
    assert llm.claude_enabled() is False
    assert brain_module.get_brain() is brain_module.MOCK
    assert "your AI allowance" in budget.status()["blocked"]
    budget.current_visitor.reset(token)
    token = as_visitor("bob")                       # other visitors are unaffected
    assert llm.claude_enabled() is True
    budget.current_visitor.reset(token)


def test_daily_total_cap_stops_everyone(capped):
    for name in ("a", "b", "c"):
        token = as_visitor(name)
        budget.record(0.09)
        budget.current_visitor.reset(token)
    token = as_visitor("newcomer")
    assert llm.claude_enabled() is False
    assert "budget for today is used up" in budget.status()["blocked"]
    budget.current_visitor.reset(token)


def test_one_live_supplier_search_per_visitor(capped):
    token = as_visitor("alice")
    assert llm.claude_enabled("web_search") is True
    budget.record(0, web_run=True)
    assert llm.claude_enabled("web_search") is False
    assert llm.claude_enabled() is True              # the cheaper AI features still work
    budget.current_visitor.reset(token)


def test_caps_are_off_locally(monkeypatch):
    monkeypatch.delenv("HUB_SPEND_CAPS", raising=False)
    assert budget.allows() and budget.allows("web_search")
    assert budget.status()["caps"] is False


def test_health_checks_and_static_files_do_not_create_sandboxes(public):
    with visitor() as pinger:
        for _ in range(5):
            assert pinger.get("/api/health").status_code == 200
        pinger.get("/js/app.js")
        assert not (public / "sandboxes").exists() or not list((public / "sandboxes").glob("*.db"))
        pinger.get("/")                                              # a real visit creates exactly one
        pinger.get("/api/submissions")
        assert len(list((public / "sandboxes").glob("*.db"))) == 1


def test_new_sandbox_never_calls_claude_even_with_a_key(public, monkeypatch):
    # Found on Render: preparing each new sandbox asked Claude to summarise the sample records,
    # so the page took too long to answer and the deploy timed out.
    from backend import llm
    monkeypatch.setenv("HUB_BRAIN", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    calls = []
    monkeypatch.setattr(llm, "call_json", lambda *args, **kwargs: calls.append(1) or (_ for _ in ()).throw(llm.LLMError("no")))
    with visitor() as newcomer:
        assert newcomer.get("/").status_code == 200
        assert not list((public / "sandboxes").glob("*.db"))          # the page alone creates nothing
        records = newcomer.get("/api/submissions").json()
        assert len(records) == 12 and all(r["brief"] for r in records)
    assert calls == []
