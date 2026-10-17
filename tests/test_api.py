"""Automated checks for the API. Run with:  python -m pytest"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Each test gets its own empty database file, so tests never touch data/hub.db.
    monkeypatch.setenv("HUB_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:  # `with` runs the startup step
        yield test_client


def new_submission(**changes):
    body = {"title": "Badge access is slow", "description": "Visitors wait at the gate.",
            "department": "Operations"}
    return body | changes


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_starts_with_three_sample_submissions(client):
    records = client.get("/api/submissions").json()
    assert len(records) == 3
    assert {record["id"] for record in records} == {"SUB-0001", "SUB-0002", "SUB-0003"}


def test_filter_by_status(client):
    records = client.get("/api/submissions", params={"status": "Needs clarification"}).json()
    assert [record["id"] for record in records] == ["SUB-0001"]


def test_create_saves_and_returns_the_new_record(client):
    response = client.post("/api/submissions", json=new_submission())
    assert response.status_code == 201
    created = response.json()
    assert created["id"] == "SUB-0004"
    assert created["status"] == "Submitted"
    assert created["submitted_by"] == "demo-employee"
    assert client.get("/api/submissions/SUB-0004").json()["title"] == "Badge access is slow"


def test_saved_submission_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DB_PATH", str(tmp_path / "restart.db"))
    with TestClient(app) as first_run:
        first_run.post("/api/submissions", json=new_submission())
    with TestClient(app) as second_run:
        assert len(second_run.get("/api/submissions").json()) == 4


def test_blank_title_is_rejected(client):
    response = client.post("/api/submissions", json=new_submission(title="   "))
    assert response.status_code == 422


def test_unknown_department_is_rejected(client):
    response = client.post("/api/submissions", json=new_submission(department="Marketing"))
    assert response.status_code == 422


def test_blank_optional_answers_are_stored_as_unknown(client):
    created = client.post("/api/submissions", json=new_submission(impact="  ")).json()
    assert created["impact"] is None


def test_client_cannot_choose_who_submitted_or_the_status(client):
    created = client.post("/api/submissions",
                          json=new_submission(submitted_by="someone-else", status="Accepted")).json()
    assert created["submitted_by"] == "demo-employee"
    assert created["status"] == "Submitted"


def test_text_that_looks_like_sql_is_stored_as_plain_text(client):
    sneaky = "x'); DROP TABLE submissions; --"
    created = client.post("/api/submissions", json=new_submission(title=sneaky)).json()
    assert created["title"] == sneaky
    assert len(client.get("/api/submissions").json()) == 4


def test_missing_submission_returns_404(client):
    assert client.get("/api/submissions/SUB-9999").status_code == 404
    assert client.get("/api/submissions/nonsense").status_code == 404
