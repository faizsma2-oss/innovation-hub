"""The database layer: one SQLite file on disk that remembers everything."""
import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

# The database is a single file. Tests point HUB_DB_PATH at a temporary file instead.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "hub.db"

# The submissions table follows the Submission record in coordinator/memory/schema.md.
# `pk` is an internal counter; the public ID (SUB-0001) is built from it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    pk                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL,
    department         TEXT NOT NULL,
    current_process    TEXT,
    people_affected    TEXT,
    frequency          TEXT,
    impact             TEXT,
    desired_outcome    TEXT,
    suggested_solution TEXT,
    submitted_by       TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'Submitted',
    review_question    TEXT
);

-- One row per intake conversation. `state_json` holds the draft and what has been asked.
CREATE TABLE IF NOT EXISTS intake_sessions (
    id         TEXT PRIMARY KEY,
    stage      TEXT NOT NULL,
    outcome    TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Every chat line, from the employee or the assistant.
CREATE TABLE IF NOT EXISTS intake_messages (
    pk         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES intake_sessions(id),
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per assistant turn: what it was given and what it decided. Used for evals later.
CREATE TABLE IF NOT EXISTS agent_runs (
    pk             INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow       TEXT NOT NULL,
    session_id     TEXT,
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    input_text     TEXT,
    output_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

-- The history of every submission: who did what, and when. Never edited, only added to.
CREATE TABLE IF NOT EXISTS submission_events (
    pk            INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_pk INTEGER NOT NULL REFERENCES submissions(pk),
    actor         TEXT NOT NULL,
    event         TEXT NOT NULL,
    from_status   TEXT,
    to_status     TEXT,
    details       TEXT,
    created_at    TEXT NOT NULL
);

-- Meetings with suppliers, across all requests (see backend/meetings/).
CREATE TABLE IF NOT EXISTS meetings (
    pk                 INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_pk      INTEGER NOT NULL REFERENCES submissions(pk),
    supplier           TEXT NOT NULL,
    contact            TEXT,
    title              TEXT NOT NULL,
    status             TEXT NOT NULL,          -- planned, invite_sent, scheduled, held, cancelled
    proposed_slots     TEXT,                   -- JSON list of the times offered
    booking_link       TEXT,                   -- e.g. a Microsoft Bookings page
    internal_attendees TEXT,
    start_at           TEXT,                   -- local Dubai time, e.g. 2026-11-03T10:00
    duration_min       INTEGER,
    teams_link         TEXT,
    plan_json          TEXT,                   -- agenda and invitation draft
    sent_at            TEXT,
    reply_due          TEXT,                   -- follow up if no reply by this date
    notes              TEXT,
    debrief_json       TEXT,
    cancelled_reason   TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- Actions agreed in meetings. Owner and due date stay UNASSIGNED / empty unless the notes said so.
CREATE TABLE IF NOT EXISTS meeting_actions (
    pk            INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_pk    INTEGER NOT NULL REFERENCES meetings(pk),
    submission_pk INTEGER NOT NULL,
    action        TEXT NOT NULL,
    owner         TEXT NOT NULL,
    due           TEXT,                        -- ISO date, or NULL when no date was agreed
    due_text      TEXT,                        -- the deadline as written in the notes
    status        TEXT NOT NULL DEFAULT 'open',
    created_at    TEXT NOT NULL,
    done_at       TEXT
);

-- Weekly management reports (the collected facts and the summary, as JSON).
CREATE TABLE IF NOT EXISTS reports (
    pk           INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    report_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Small app settings, such as the supplier research answers last used (to pre-fill the next run).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Known solutions the assistant can offer before involving the innovation team.
CREATE TABLE IF NOT EXISTS solutions (
    id       TEXT PRIMARY KEY,
    kind     TEXT NOT NULL DEFAULT 'tool',  -- tool, guidance, active_project or previous_pilot
    title    TEXT NOT NULL,
    summary  TEXT NOT NULL,
    how_to   TEXT NOT NULL,
    source   TEXT NOT NULL,
    keywords TEXT NOT NULL
);
"""

# Columns added after the first version of each table. A "migration" upgrades an existing
# database file without losing its data.
NEW_SUBMISSION_COLUMNS = {
    "brief_json": "TEXT",
    "score": "REAL",
    "supporters": "INTEGER NOT NULL DEFAULT 0",
    "intake_session_id": "TEXT",
    # Milestone 4: screening and review
    "recommendation_json": "TEXT",   # the screening's PROPOSED decision
    "decision_reason": "TEXT",       # criterion code when declined
    "decision_message": "TEXT",      # what the employee was told
    "decided_by": "TEXT",            # 'reviewer' or 'screening-policy'
    "review_outcome": "TEXT",        # agreed / overrode / overturned_auto
    "appealed": "INTEGER NOT NULL DEFAULT 0",
    # Milestone 5: routing, linked opportunities and measures
    "tried_already": "TEXT",
    "route": "TEXT",                 # where the request goes first (see models.ROUTES)
    "route_reason": "TEXT",
    "initial_route": "TEXT",         # the agent's first route, kept to measure routing accuracy
    "innovation_track": "TEXT NOT NULL DEFAULT 'none'",
    "linked_to": "TEXT",             # SUB-xxxx or PRJ-xxx this request was linked to
    "feasibility": "TEXT",
    "resolution_confirmed": "INTEGER NOT NULL DEFAULT 0",
    "submission_seconds": "INTEGER", # how long the employee took to submit
    "review_seconds": "INTEGER",     # how long the reviewer took to decide
    # Milestone 7: solution options and research
    "solutions_json": "TEXT",        # the Research AI's PROPOSED, ranked options
    "research_json": "TEXT",         # the selected option and research plan
}
MIGRATIONS = {
    "submissions": NEW_SUBMISSION_COLUMNS,
    "intake_sessions": {"satisfaction": "INTEGER"},
    # Milestone 6: what each assistant turn cost, and whether the scripted brain stepped in.
    "agent_runs": {"input_tokens": "INTEGER", "output_tokens": "INTEGER", "cost_usd": "REAL",
                   "fallback_used": "INTEGER NOT NULL DEFAULT 0"},
    "solutions": {"kind": "TEXT NOT NULL DEFAULT 'tool'"},
}

# Fictional starting records, so the inbox is not empty on first run.
SEED = [
    {
        "title": "Inspection reports take too long to prepare",
        "description": "After inspections, our team copies handwritten notes into a shared report.",
        "department": "Operations",
        "submitted_by": "demo-employee",
        "status": "Needs clarification",
        "review_question": "How many reports are produced each week, and how long does each one take?",
    },
    {
        "title": "It is difficult to find the latest process document",
        "description": "Different versions are stored in different folders, so we spend time asking which version to use.",
        "department": "IT",
        "submitted_by": "demo-employee",
        "status": "Submitted",
        "review_question": "Which documents are hardest to find, and where are they currently stored?",
    },
    {
        "title": "Purchase requests often arrive incomplete",
        "description": "The team must follow up for missing information before reviewing requests.",
        "department": "Finance",
        "submitted_by": "another-employee",
        "status": "Under review",
        "review_question": "Which fields are most often missing, and could the request form collect them earlier?",
    },
]

# Fictional solutions catalog. In a real deployment this would come from the IT service
# catalog, approved procedures and past project results.
SOLUTIONS = [
    # (id, kind, title, summary, how to use it, source, keywords)
    ("SOL-001", "tool", "Digital shift handover checklist",
     "A shared checklist in the operations app replaces paper handover notes between shifts.",
     "Operations app → Handover → New checklist.", "Fictional: past project PRJ-002 (scaled 2025)",
     "handover,shift change,between shifts,handover notes"),
    ("SOL-002", "tool", "Visitor pre-registration portal",
     "Hosts register visitors the day before, so badges are printed before arrival.",
     "Intranet → Security → Pre-register a visitor.", "Fictional: Security service catalog",
     "visitor,badge,waiting at the gate,gate queue,access card"),
    ("SOL-003", "tool", "Spare parts lookup in the ERP",
     "Live stock levels and bin locations for spare parts, searchable by part number.",
     "ERP → Inventory → Parts lookup. Ask your supervisor for read access.", "Fictional: IT service catalog",
     "spare parts,spare part,parts availability,stock level,inventory"),
    ("SOL-004", "tool", "Expense claims mobile app",
     "Photograph receipts and submit claims from your phone; approvals happen in the app.",
     "Install 'Expenses' from the company app store.", "Fictional: Finance service catalog",
     "expense,receipt,reimbursement,claim form"),
    ("SOL-005", "tool", "Training records in the learning system",
     "Certificates and expiry dates for every employee, with automatic renewal reminders.",
     "Learning system → My records. Managers: Team view.", "Fictional: HR service catalog",
     "training record,certificate,certification,expiry reminder"),
    ("SOL-006", "tool", "Thermal camera loan kit",
     "Handheld thermal cameras that any site team can borrow for hotspot checks.",
     "Book through the engineering tool store, up to 5 days.", "Fictional: past project PRJ-004",
     "thermal camera,hotspot,infrared"),
    ("SOL-007", "guidance", "Meeting room booking in the calendar",
     "All meeting rooms can be booked directly from a calendar invite, with live availability.",
     "Calendar → New meeting → Add room.", "Fictional: IT service catalog",
     "meeting room,room booking,book a room"),
    ("PRJ-011", "active_project", "Digital permit-to-work (active project)",
     "Replacing paper permit-to-work forms with a tablet workflow at two sites.",
     "Owner: operations excellence team.", "Fictional: innovation project records",
     "permit to work,permit-to-work,paper permits,permit forms"),
    ("PRJ-005", "previous_pilot", "Vibration sensors on chillers (pilot, 2025)",
     "A 3-month pilot on two chillers tested vibration sensors for earlier fault warnings. Result: "
     "inconclusive. The sensors worked, but alarm thresholds were never tuned.",
     "Pilot report in the innovation records.", "Fictional: innovation project records",
     "faults late,earlier detection,early warning,predictive,vibration"),
]


# On the public demo every visitor has their own database file (see the sandbox middleware in
# main.py). Locally this stays empty and the single file below is used.
current_file: ContextVar[Path | None] = ContextVar("current_file", default=None)


def db_path() -> Path:
    return current_file.get() or Path(os.environ.get("HUB_DB_PATH", DEFAULT_DB_PATH))


@contextmanager
def connect():
    """Open a connection, commit if everything worked, and always close it."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row  # rows behave like dictionaries
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create missing tables, upgrade old files, and add starting data once."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        if conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0:
            for record in SEED:
                conn.execute(
                    "INSERT INTO submissions (title, description, department, submitted_by,"
                    " created_at, status, review_question)"
                    " VALUES (?, ?, ?, ?, '2026-10-01T09:00:00+00:00', ?, ?)",
                    (record["title"], record["description"], record["department"],
                     record["submitted_by"], record["status"], record["review_question"]),
                )
        # INSERT OR IGNORE adds catalog entries that older databases don't have yet.
        conn.executemany("INSERT OR IGNORE INTO solutions (id, kind, title, summary, how_to, source, keywords)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?)", SOLUTIONS)


def migrate(conn):
    """Add any column a table doesn't have yet."""
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, column_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")


def insert_submission(conn, values: dict, submitted_by: str, *, brief: dict | None = None,
                      status: str = "Submitted", route: str | None = None, route_reason: str | None = None,
                      innovation_track: str = "none", linked_to: str | None = None,
                      intake_session_id: str | None = None, submission_seconds: int | None = None) -> str:
    """Save a validated submission and return its public ID."""
    # The ? placeholders keep user text as data. Never paste user text into SQL.
    cursor = conn.execute(
        "INSERT INTO submissions (title, description, department, current_process, people_affected,"
        " frequency, impact, tried_already, desired_outcome, suggested_solution, submitted_by, created_at,"
        " status, brief_json, route, route_reason, initial_route, innovation_track, linked_to,"
        " intake_session_id, submission_seconds)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (values["title"], values["description"], values["department"], values["current_process"],
         values["people_affected"], values["frequency"], values["impact"], values["tried_already"],
         values["desired_outcome"], values["suggested_solution"], submitted_by, now(), status,
         json.dumps(brief) if brief else None, route, route_reason, route, innovation_track, linked_to,
         intake_session_id, submission_seconds),
    )
    add_event(conn, cursor.lastrowid, submitted_by, "submitted", None, status,
              "via intake assistant" if intake_session_id else "via form")
    return f"SUB-{cursor.lastrowid:04d}"


def add_event(conn, pk: int, actor: str, event: str, from_status: str | None, to_status: str | None,
              details: str | None = None):
    conn.execute("INSERT INTO submission_events (submission_pk, actor, event, from_status, to_status, details,"
                 " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (pk, actor, event, from_status, to_status, details, now()))


def parse_pk(submission_id: str) -> int | None:
    """'SUB-0007' → 7. Anything else → None."""
    try:
        return int(submission_id.removeprefix("SUB-"))
    except ValueError:
        return None


def get_submission(conn, submission_id: str) -> dict | None:
    pk = parse_pk(submission_id)
    row = conn.execute("SELECT * FROM submissions WHERE pk = ?", (pk,)).fetchone() if pk else None
    return to_public(row) if row else None


def to_public(row: sqlite3.Row) -> dict:
    """Turn a database row into what the API sends: pk 1 becomes id 'SUB-0001'."""
    record = dict(row)
    record["id"] = f"SUB-{record.pop('pk'):04d}"
    brief_json = record.pop("brief_json", None)
    record["brief"] = json.loads(brief_json) if brief_json else None
    recommendation_json = record.pop("recommendation_json", None)
    record["recommendation"] = json.loads(recommendation_json) if recommendation_json else None
    record["appealed"] = bool(record.get("appealed"))
    record["resolution_confirmed"] = bool(record.get("resolution_confirmed"))
    for field in ("solutions", "research"):
        raw = record.pop(f"{field}_json", None)
        record[field] = json.loads(raw) if raw else None
    return record


def get_setting(conn, key: str):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def set_setting(conn, key: str, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
