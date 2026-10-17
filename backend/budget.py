"""Spending caps for the public demo, so visitors can try real Claude without running up a bill.

Switched on with HUB_SPEND_CAPS=on (the hosted demo). Locally the caps are off.
  - per visitor per day:  HUB_VISITOR_DAILY_USD   (default $0.50)
  - all visitors per day: HUB_DAILY_USD           (default $5.00)
  - live supplier web searches per visitor per day: HUB_WEB_RUNS_PER_VISITOR (default 1)
When a cap is reached, each AI feature quietly uses its scripted version instead, and
/api/health says why, so the page can tell the visitor.

The ledger is its own small SQLite file, shared by every visitor's sandbox.
"""
import os
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

# Which visitor is making the current request (set by the sandbox middleware in main.py).
current_visitor: ContextVar[str] = ContextVar("current_visitor", default="local")


def caps_on() -> bool:
    return os.environ.get("HUB_SPEND_CAPS") == "on"


def limits() -> dict:
    return {"visitor_usd": float(os.environ.get("HUB_VISITOR_DAILY_USD", "0.50")),
            "daily_usd": float(os.environ.get("HUB_DAILY_USD", "5.00")),
            "web_runs": int(os.environ.get("HUB_WEB_RUNS_PER_VISITOR", "1"))}


def ledger_path() -> Path:
    return Path(os.environ.get("HUB_SPEND_DB", Path(__file__).resolve().parent.parent / "data" / "spend.db"))


def _connect():
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ledger_path())
    conn.execute("CREATE TABLE IF NOT EXISTS spend (day TEXT, visitor TEXT, cost REAL, web_run INTEGER DEFAULT 0)")
    return conn


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def status() -> dict:
    """What's been spent today, and whether a cap stops the AI for this visitor."""
    if not caps_on():
        return {"caps": False, "blocked": None, "web_blocked": None}
    cap = limits()
    conn = _connect()
    try:
        day, visitor = _today(), current_visitor.get()
        total = conn.execute("SELECT COALESCE(SUM(cost), 0) FROM spend WHERE day = ?", (day,)).fetchone()[0]
        mine, runs = conn.execute("SELECT COALESCE(SUM(cost), 0), COALESCE(SUM(web_run), 0) FROM spend"
                                  " WHERE day = ? AND visitor = ?", (day, visitor)).fetchone()
    finally:
        conn.close()
    blocked = ("The demo's AI budget for today is used up." if total >= cap["daily_usd"] else
               "You've used your AI allowance for today." if mine >= cap["visitor_usd"] else None)
    web_blocked = blocked or ("You've used today's live supplier web search." if runs >= cap["web_runs"] else None)
    return {"caps": True, "blocked": blocked, "web_blocked": web_blocked,
            "visitor_spent_usd": round(mine, 4), "visitor_cap_usd": cap["visitor_usd"]}


def allows(kind: str = "ai") -> bool:
    if not caps_on():
        return True
    state = status()
    return not (state["web_blocked"] if kind == "web_search" else state["blocked"])


def record(cost: float, web_run: bool = False):
    if not caps_on() or (cost <= 0 and not web_run):
        return
    conn = _connect()
    try:
        conn.execute("INSERT INTO spend (day, visitor, cost, web_run) VALUES (?, ?, ?, ?)",
                     (_today(), current_visitor.get(), cost, int(web_run)))
        conn.commit()
    finally:
        conn.close()
