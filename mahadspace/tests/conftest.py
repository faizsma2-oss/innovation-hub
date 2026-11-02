"""Every test gets its own empty database, the fake Telegram and a signed-in owner account."""
import io
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ["MAHADSPACE_TELEGRAM"] = "fake"
os.environ["MAHADSPACE_DISCUSSION_GROUP"] = "demo-discussion"
os.environ["MAHADSPACE_VIP_GROUP"] = "demo-vip"
os.environ["MAHADSPACE_SEND_DELAY"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.telegram_client import FAKE  # noqa: E402

TODAY = date.today()


def dmy(days_ago: int) -> str:
    """A date written day-first, the way many broker exports do."""
    return (TODAY - timedelta(days=days_ago)).strftime("%d/%m/%Y")


@pytest.fixture
def anon(tmp_path, monkeypatch):
    monkeypatch.setenv("MAHADSPACE_DB", str(tmp_path / "test.db"))
    FAKE.reset()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(anon):
    anon.post("/api/auth/register", json={"display_name": "Owner", "email": "owner@example.com", "password": "correct horse"})
    assert anon.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse"}).status_code == 200
    return anon


def xlsx(*sheets) -> bytes:
    """sheets: (title, rows). Returns the bytes of an Excel file."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def vantage_accounts() -> bytes:
    return xlsx(("Accounts", [
        ["Vantage IB Account Report"], ["Generated for IB 555"], [],
        ["User ID", "Account", "Name", "Balance", "Equity", "Last Trade Time"],
        [11111111, 800001, "Ali Hassan", 1200, 1150.5, dmy(2)],        # big equity: active
        [22222222, 800002, "Sara Khan", 20, 10, dmy(5)],               # small equity, recent trade: active
        [33333333, 800003, "Bilal Ahmed", 30, 12, dmy(60)],            # small equity, old trade: inactive
        [33333333, 800004, "Bilal Ahmed", 0, 0, ""],                   # second account, nothing: inactive
        [None, None, "Totals", 1250, 1172.5, None],                   # no UID: skipped
    ]))


def upload(client, broker, section, filename, data):
    return client.post(f"/api/reports/{broker}?section={section}&filename={filename}", content=data)


def connect_telegram(client, phone="+971500000001"):
    client.post("/api/connections/telegram/start", json={"phone_number": phone})
    return client.post("/api/connections/telegram/verify-code", json={"code": "12345"})
