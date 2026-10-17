"""Shared test setup: every test gets its own empty database file, and the scripted brain.
Tests never call Claude, so they're free and repeatable."""
import os

os.environ["HUB_BRAIN"] = "mock"  # before the app is imported

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:  # `with` runs the startup step
        yield test_client


class Chat:
    """Plays the employee: starts a conversation and sends messages or button clicks."""

    def __init__(self, client):
        self.client = client
        self.reply = client.post("/api/intake/sessions").json()

    def say(self, text, **edits):
        return self._send({"text": text, "edits": edits})

    def click(self, action, **edits):
        return self._send({"action": action, "edits": edits})

    def _send(self, body):
        response = self.client.post(f"/api/intake/sessions/{self.reply['session_id']}/messages", json=body)
        assert response.status_code == 200, response.text
        self.reply = response.json()
        return self.reply

    def dont_know_until_done(self):
        for _ in range(10):  # a cap, so a bug fails the test instead of hanging it
            if self.reply["stage"] != "clarifying":
                return self.reply
            self.click("dont_know")
        pytest.fail("Still asking questions after 10 answers")

    def submission(self):
        return self.client.get(f"/api/submissions/{self.reply['submission_id']}").json()


@pytest.fixture
def chat(client):
    return lambda: Chat(client)
