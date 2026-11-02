"""SQLite storage. One file, created on first start. Every table is scoped to the signed-in user."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);

-- The latest imported file per broker and dataset (accounts, funds, opened_accounts, rebates).
CREATE TABLE IF NOT EXISTS report_datasets (
    user_id INTEGER NOT NULL, broker TEXT NOT NULL, dataset TEXT NOT NULL, filename TEXT NOT NULL,
    imported_at TEXT NOT NULL, rows_json TEXT NOT NULL, skipped INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, broker, dataset));
-- Removed or replaced datasets, so a removal can be recovered.
CREATE TABLE IF NOT EXISTS report_trash (
    pk INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, broker TEXT NOT NULL, dataset TEXT NOT NULL,
    filename TEXT NOT NULL, imported_at TEXT NOT NULL, removed_at TEXT NOT NULL, rows_json TEXT NOT NULL);
-- Every UID (and its account numbers and names) ever seen in a report: "known from report history".
CREATE TABLE IF NOT EXISTS report_history (
    user_id INTEGER NOT NULL, broker TEXT NOT NULL, uid TEXT NOT NULL, account_ids_json TEXT NOT NULL,
    names_json TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    PRIMARY KEY (user_id, broker, uid));

CREATE TABLE IF NOT EXISTS telegram_sessions (
    user_id INTEGER PRIMARY KEY, phone TEXT, session TEXT, status TEXT NOT NULL,
    phone_code_hash TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER NOT NULL, telegram_id TEXT NOT NULL, display_name TEXT, username TEXT,
    access_hash TEXT, groups_json TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY (user_id, telegram_id));
CREATE TABLE IF NOT EXISTS member_import (
    user_id INTEGER PRIMARY KEY, filename TEXT NOT NULL, imported_at TEXT NOT NULL, member_count INTEGER NOT NULL,
    ids_json TEXT NOT NULL);
-- Approved Telegram member ↔ broker UID links.
CREATE TABLE IF NOT EXISTS links (
    user_id INTEGER NOT NULL, telegram_id TEXT NOT NULL, uid TEXT NOT NULL, broker TEXT NOT NULL,
    source TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, telegram_id, uid, broker));
-- Suggested links from a group scan, waiting for a person.
CREATE TABLE IF NOT EXISTS link_candidates (
    id TEXT NOT NULL, user_id INTEGER NOT NULL, telegram_id TEXT NOT NULL, uid TEXT NOT NULL, broker TEXT NOT NULL,
    status TEXT NOT NULL, decision TEXT NOT NULL, confidence REAL NOT NULL, source TEXT NOT NULL,
    reason TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, id));
CREATE TABLE IF NOT EXISTS group_baselines (
    user_id INTEGER NOT NULL, grp TEXT NOT NULL, member_ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, grp));
CREATE TABLE IF NOT EXISTS outreach_log (
    pk INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, telegram_id TEXT NOT NULL, display_name TEXT,
    grp TEXT NOT NULL, audience TEXT NOT NULL, sent_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reply_candidates (
    id TEXT NOT NULL, user_id INTEGER NOT NULL, telegram_id TEXT NOT NULL, display_name TEXT, username TEXT,
    chat_name TEXT, reply_text TEXT NOT NULL, uid TEXT, broker TEXT, source TEXT NOT NULL,
    match_status TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT, report_client_name TEXT,
    account_count INTEGER NOT NULL DEFAULT 0, message_date TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, id));
CREATE TABLE IF NOT EXISTS app_state (
    user_id INTEGER NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, PRIMARY KEY (user_id, key));
"""


def db_path() -> Path:
    return Path(os.environ.get("MAHADSPACE_DB", Path(__file__).resolve().parent.parent / "data" / "mahadspace.db"))


def init():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_state(conn, user_id: int, key: str, default=None):
    row = conn.execute("SELECT value_json FROM app_state WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return json.loads(row["value_json"]) if row else default


def set_state(conn, user_id: int, key: str, value):
    conn.execute("INSERT INTO app_state (user_id, key, value_json) VALUES (?, ?, ?)"
                 " ON CONFLICT(user_id, key) DO UPDATE SET value_json = excluded.value_json",
                 (user_id, key, json.dumps(value)))
