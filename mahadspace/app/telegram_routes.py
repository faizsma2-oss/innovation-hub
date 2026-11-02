"""Telegram: connection, group scans, member links, reviewed outreach and UID replies.

Safety rules kept from the original site and enforced here, not just on the page:
  - nothing is sent unless a person selected the recipients, ticked the review box and typed SEND
  - only members who are eligible for the chosen group and audience right now can be sent to
  - removing someone from a group needs REMOVE typed
  - a reply's UID becomes a link only when it is an exact match or a person approves it
"""
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import db, members as directory, reports
from .auth import current_user
from .telegram_client import GROUPS, TelegramError, get_gateway, group_ref

router = APIRouter()
MAX_RECIPIENTS_PER_SEND = 100
GROUP_LABELS = {"discussion": "Discussion", "vip": "VIP"}
TEMPLATES = {
    "welcome": ("Welcome to the group! 👋\n\nTo link your trading account to your membership, please reply with "
                "your broker (Vantage or PU Prime) and your UID.\n\nExample: Vantage 12345678"),
    "record_request": ("Hello! We're updating our member records. Please reply with your broker (Vantage or PU Prime) "
                       "and the UID of your trading account, so we can keep your benefits up to date. Thank you!"),
}


def fail(error: TelegramError):
    raise HTTPException(409, str(error))


# ── Session storage ──────────────────────────────────────────────────────────

def session_row(conn, user_id: int):
    return conn.execute("SELECT * FROM telegram_sessions WHERE user_id = ?", (user_id,)).fetchone()


def save_session(conn, user_id: int, **values):
    current = session_row(conn, user_id)
    merged = {"phone": None, "session": None, "status": "not_connected", "phone_code_hash": None}
    if current:
        merged |= {k: current[k] for k in merged}
    merged |= values
    conn.execute("INSERT INTO telegram_sessions (user_id, phone, session, status, phone_code_hash, updated_at)"
                 " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET phone = excluded.phone,"
                 " session = excluded.session, status = excluded.status, phone_code_hash = excluded.phone_code_hash,"
                 " updated_at = excluded.updated_at",
                 (user_id, merged["phone"], merged["session"], merged["status"], merged["phone_code_hash"], db.now()))


def authorized_session(user_id: int) -> str:
    with db.connect() as conn:
        row = session_row(conn, user_id)
    if row is None or row["status"] != "connected" or not row["session"]:
        raise HTTPException(409, "Connect an authorized Telegram session first. Reconnect Telegram to continue.")
    return row["session"]


# ── Connection ───────────────────────────────────────────────────────────────

class PhoneIn(BaseModel):
    phone_number: str = Field(min_length=6, max_length=20)


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=10)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.get("/api/connections")
def connections(user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = session_row(conn, user["id"])
    return {"telegram": {"status": row["status"] if row else "not_connected"}}


@router.get("/api/connections/telegram/health")
async def telegram_health(user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = session_row(conn, user["id"])
    if row is None or row["status"] in ("not_connected", "disconnected"):
        return {"status": "not_connected", "authorized": False, "message": "Telegram is not connected."}
    if row["status"] != "connected":
        return {"status": row["status"], "authorized": False, "message": "Finish connecting Telegram."}
    try:
        me = await get_gateway().whoami(row["session"])
    except TelegramError as error:
        return {"status": "error", "authorized": False, "message": str(error)}
    if me is None:
        with db.connect() as conn:
            save_session(conn, user["id"], status="expired")
        return {"status": "expired", "authorized": False,
                "message": "The Telegram session has expired. Reconnect Telegram."}
    return {"status": "connected", "authorized": True, "message": f"Connected as {me['name']}."}


@router.post("/api/connections/telegram/start")
async def telegram_start(body: PhoneIn, user: dict = Depends(current_user)):
    phone = re.sub(r"[\s()-]", "", body.phone_number)
    if not re.fullmatch(r"\+\d{7,15}", phone):
        raise HTTPException(422, "Include the country code, for example +971501234567.")
    try:
        session, code_hash = await get_gateway().send_code(phone)
    except TelegramError as error:
        fail(error)
    with db.connect() as conn:
        save_session(conn, user["id"], phone=phone, session=session, status="pending", phone_code_hash=code_hash)
    return {"status": "pending", "message": f"Telegram sent a login code to {phone}. Enter it below."}


@router.post("/api/connections/telegram/verify-code")
async def telegram_verify_code(body: CodeIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = session_row(conn, user["id"])
    if row is None or row["status"] != "pending":
        raise HTTPException(409, "Request a Telegram code first.")
    try:
        session, needs_password = await get_gateway().sign_in_code(row["session"], row["phone"], body.code.strip(),
                                                                   row["phone_code_hash"])
    except TelegramError as error:
        fail(error)
    with db.connect() as conn:
        save_session(conn, user["id"], session=session, status="pending_password" if needs_password else "connected",
                     phone_code_hash=None)
    if needs_password:
        return {"requires_password": True, "message": "This account has two-step verification. Enter its password."}
    return {"requires_password": False, "message": "Telegram connected successfully."}


@router.post("/api/connections/telegram/verify-password")
async def telegram_verify_password(body: PasswordIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = session_row(conn, user["id"])
    if row is None or row["status"] != "pending_password":
        raise HTTPException(409, "Enter the Telegram code first.")
    try:
        session = await get_gateway().sign_in_password(row["session"], body.password)
    except TelegramError as error:
        fail(error)
    with db.connect() as conn:
        save_session(conn, user["id"], session=session, status="connected")
    return {"message": "Telegram connected successfully."}


@router.delete("/api/connections/telegram")
async def telegram_disconnect(user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = session_row(conn, user["id"])
    if row and row["session"]:
        try:
            await get_gateway().log_out(row["session"])
        except TelegramError:
            pass                                  # the local session is removed either way
    with db.connect() as conn:
        save_session(conn, user["id"], session=None, status="disconnected", phone_code_hash=None)
    return {"status": "disconnected", "message": "Telegram disconnected. No messages were sent."}


# ── Members: scan, CSV import, links ─────────────────────────────────────────

class ManualLinkIn(BaseModel):
    telegram_id: str = Field(min_length=1, max_length=40)
    uid: str = Field(min_length=1, max_length=40)
    broker: str | None = Field(default=None, max_length=20)


class UnlinkIn(BaseModel):
    telegram_id: str = Field(min_length=1, max_length=40)
    uid: str = Field(min_length=1, max_length=40)
    broker: str | None = Field(default=None, max_length=20)


class ReviewLinksIn(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=500)
    decision: Literal["approved", "rejected", "pending"]


class RemoveMemberIn(BaseModel):
    telegram_id: str = Field(min_length=1, max_length=40)
    groups: list[Literal["discussion", "vip"]] = Field(min_length=1)
    confirmation_text: str


def links_payload(user_id: int, extra: dict | None = None) -> dict:
    with db.connect() as conn:
        return directory.payload(conn, user_id, extra)


@router.get("/api/telegram/account-links")
def account_links(user: dict = Depends(current_user)):
    return links_payload(user["id"])


async def scan_groups(user_id: int) -> dict:
    """Read the configured groups and bring the directory up to date. Members who left both groups are removed."""
    session = authorized_session(user_id)
    gateway, found, warnings, groups_state = get_gateway(), {}, [], {}
    scanned_groups = []
    for group in GROUPS:
        ref = group_ref(group)
        if not ref:
            warnings.append(f"The {GROUP_LABELS[group]} group isn't configured on the server.")
            continue
        try:
            title, people = await gateway.group_members(session, ref)
        except TelegramError as error:
            warnings.append(f"{GROUP_LABELS[group]}: {error}")
            continue
        scanned_groups.append(group)
        groups_state[group] = {"title": title, "member_count": len(people), "scanned_at": db.now()}
        for person in people:
            found.setdefault(person["telegram_id"], {"person": person, "groups": set()})["groups"].add(group)
    added = removed = 0
    with db.connect() as conn:
        existing = directory.members(conn, user_id)
        for telegram_id, item in found.items():
            added += telegram_id not in existing
            directory.upsert_member(conn, user_id, item["person"], "telegram_scan", sorted(item["groups"]))
        if scanned_groups:
            for telegram_id, member in existing.items():
                if telegram_id in found:
                    continue
                remaining = [g for g in member["groups"] if g not in scanned_groups]
                if remaining or member["source"] != "telegram_scan":
                    conn.execute("UPDATE members SET groups_json = ? WHERE user_id = ? AND telegram_id = ?",
                                 (json.dumps(remaining), user_id, telegram_id))
                elif len(scanned_groups) == len(GROUPS):
                    # Only when BOTH groups were read: a failed read must never empty the directory.
                    conn.execute("DELETE FROM members WHERE user_id = ? AND telegram_id = ?", (user_id, telegram_id))
                    removed += 1
            previous = db.get_state(conn, user_id, "groups", {})
            db.set_state(conn, user_id, "groups", previous | groups_state)
            db.set_state(conn, user_id, "last_scanned_at", db.now())
        directory.suggest(conn, user_id, reports.uid_index(conn, user_id))
        return directory.payload(conn, user_id, {"warnings": warnings,
                                                 "membership_changes": {"added": added, "removed": removed}})


@router.post("/api/telegram/account-links/scan")
async def scan_account_links(user: dict = Depends(current_user)):
    return await scan_groups(user["id"])


@router.post("/api/telegram/account-links/manual")
def manual_link(body: ManualLinkIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        directory.add_link(conn, user["id"], body.telegram_id.strip(), body.uid, body.broker or "")
    return links_payload(user["id"])


@router.post("/api/telegram/account-links/unlink")
def unlink(body: UnlinkIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        if not directory.remove_link(conn, user["id"], body.telegram_id.strip(), body.uid, body.broker or ""):
            raise HTTPException(404, f"UID {body.uid} isn't linked to that member.")
    return links_payload(user["id"])


@router.post("/api/telegram/account-links/review")
def review_links(body: ReviewLinksIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        directory.review(conn, user["id"], body.candidate_ids, body.decision)
    return links_payload(user["id"])


@router.get("/api/telegram/account-links/accounts")
def account_options(query: str = "", broker: str = "all", limit: int = Query(50, ge=1, le=200),
                    user: dict = Depends(current_user)):
    with db.connect() as conn:
        return directory.accounts_search(conn, user["id"], query, broker, limit)


@router.post("/api/telegram/account-links/remove-member")
async def remove_member(body: RemoveMemberIn, user: dict = Depends(current_user)):
    if body.confirmation_text != "REMOVE":
        raise HTTPException(422, "Type REMOVE to confirm.")
    session = authorized_session(user["id"])
    with db.connect() as conn:
        member = directory.members(conn, user["id"]).get(body.telegram_id)
    if member is None:
        raise HTTPException(404, "That Telegram member isn't in the directory.")
    removed, failed = [], []
    for group in body.groups:
        if group not in member["groups"]:
            continue
        ref = group_ref(group)
        if not ref:
            failed.append({"group": group, "error": "group not configured"})
            continue
        try:
            await get_gateway().remove_from_group(session, ref, member)
            removed.append(group)
        except TelegramError as error:
            failed.append({"group": group, "error": str(error)})
    with db.connect() as conn:
        remaining = [g for g in member["groups"] if g not in removed]
        if not remaining and member["source"] == "telegram_scan":
            conn.execute("DELETE FROM members WHERE user_id = ? AND telegram_id = ?", (user["id"], body.telegram_id))
        else:
            conn.execute("UPDATE members SET groups_json = ? WHERE user_id = ? AND telegram_id = ?",
                         (json.dumps(remaining), user["id"], body.telegram_id))
        return directory.payload(conn, user["id"], {"member_removal": {"removed_groups": removed, "failed_groups": failed}})


MEMBER_COLUMNS = {
    "telegram_id": ["telegramid", "userid", "id", "tgid", "memberid"],
    "display_name": ["name", "displayname", "fullname", "telegramname", "member"],
    "first_name": ["firstname"], "last_name": ["lastname"],
    "username": ["username", "telegramusername", "handle"],
    "groups": ["group", "groups", "chat", "telegramgroup"],
}


def csv_groups(value: str) -> list[str]:
    text = str(value or "").lower()
    found = [g for g in GROUPS if g in text or (g == "discussion" and "discuss" in text)]
    return found


@router.post("/api/telegram/members/import")
async def import_members(request: Request, filename: str = "members.csv", user: dict = Depends(current_user)):
    data = await request.body()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(422, "Choose a .csv file.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "The member CSV must be 5 MB or smaller.")
    text = reports.decode(data)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise HTTPException(422, "The CSV is empty.")
    columns = {}
    for index, header in enumerate(rows[0]):
        for field, aliases in MEMBER_COLUMNS.items():
            if reports.token(header) in aliases and field not in columns:
                columns[field] = index
    if "telegram_id" not in columns:
        raise HTTPException(422, "The CSV needs a Telegram ID column (for example telegram_id or user_id).")
    get = lambda row, field: row[columns[field]].strip() if field in columns and columns[field] < len(row) else ""
    seen, imported, skipped = set(), [], 0
    for row in rows[1:]:
        telegram_id = re.sub(r"\.0$", "", get(row, "telegram_id"))
        if not re.fullmatch(r"\d{3,20}", telegram_id) or telegram_id in seen:
            skipped += 1
            continue
        seen.add(telegram_id)
        name = get(row, "display_name") or " ".join(filter(None, [get(row, "first_name"), get(row, "last_name")]))
        imported.append(({"telegram_id": telegram_id, "display_name": name, "username": get(row, "username").lstrip("@")},
                         csv_groups(get(row, "groups"))))
    if not imported:
        raise HTTPException(422, "No valid members found. Each row needs a numeric Telegram ID.")
    with db.connect() as conn:
        for member, groups in imported:
            directory.upsert_member(conn, user["id"], member, "csv", groups or None)
        conn.execute("INSERT INTO member_import (user_id, filename, imported_at, member_count, ids_json) VALUES (?, ?, ?, ?, ?)"
                     " ON CONFLICT(user_id) DO UPDATE SET filename = excluded.filename, imported_at = excluded.imported_at,"
                     " member_count = excluded.member_count, ids_json = excluded.ids_json",
                     (user["id"], filename, db.now(), len(imported), json.dumps(sorted(seen))))
    return {"message": f"Imported {len(imported)} members from {filename}.", "member_count": len(imported),
            "skipped_count": skipped}


@router.get("/api/telegram/members/import")
def member_import_status(user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM member_import WHERE user_id = ?", (user["id"],)).fetchone()
    if row is None:
        return {"present": False, "member_count": 0, "filename": None}
    return {"present": True, "member_count": row["member_count"], "filename": row["filename"],
            "imported_at": row["imported_at"]}


@router.delete("/api/telegram/members/import")
def remove_member_import(user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM member_import WHERE user_id = ?", (user["id"],)).fetchone()
        if row is None:
            raise HTTPException(404, "No member CSV is imported.")
        ids = json.loads(row["ids_json"])
        # Only members that came from the CSV and were never seen in a group scan.
        removed = 0
        for telegram_id in ids:
            removed += conn.execute("DELETE FROM members WHERE user_id = ? AND telegram_id = ? AND source = 'csv'",
                                    (user["id"], telegram_id)).rowcount
        conn.execute("DELETE FROM member_import WHERE user_id = ?", (user["id"],))
    return {"message": f"Removed the imported member CSV ({removed} member(s) that weren't found in a group scan)."}


# ── Outreach ─────────────────────────────────────────────────────────────────

class GroupIn(BaseModel):
    group: Literal["discussion", "vip"]


class PreviewIn(BaseModel):
    group: Literal["discussion", "vip"]
    audience: Literal["new", "existing", "unmatched", "active", "inactive"]


class SendIn(PreviewIn):
    recipient_ids: list[str] = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4096)
    confirm_send: bool
    confirmation_text: str


@router.get("/api/telegram/outreach/templates")
def templates(user: dict = Depends(current_user)):
    return TEMPLATES


async def live_group(user_id: int, group: str) -> tuple[str, list[dict]]:
    ref = group_ref(group)
    if not ref:
        raise HTTPException(409, f"The {GROUP_LABELS[group]} group isn't configured on the server.")
    try:
        title, people = await get_gateway().group_members(authorized_session(user_id), ref)
    except TelegramError as error:
        fail(error)
    with db.connect() as conn:
        for person in people:
            current = directory.members(conn, user_id).get(person["telegram_id"])
            groups = sorted(set((current or {}).get("groups", [])) | {group})
            directory.upsert_member(conn, user_id, person, "telegram_scan", groups)
    return title, people


@router.post("/api/telegram/outreach/initialize")
async def initialize(body: GroupIn, user: dict = Depends(current_user)):
    title, people = await live_group(user["id"], body.group)
    with db.connect() as conn:
        conn.execute("INSERT INTO group_baselines (user_id, grp, member_ids_json, created_at) VALUES (?, ?, ?, ?)"
                     " ON CONFLICT(user_id, grp) DO UPDATE SET member_ids_json = excluded.member_ids_json,"
                     " created_at = excluded.created_at",
                     (user["id"], body.group, json.dumps([p["telegram_id"] for p in people]), db.now()))
    return {"message": f"Tracking started for {title}: {len(people)} current members are the baseline. "
                       "People who join from now on count as new members. No messages were sent."}


@router.get("/api/telegram/outreach/diagnostics")
async def diagnostics(user: dict = Depends(current_user)):
    session = authorized_session(user["id"])
    groups = []
    for group in GROUPS:
        ref = group_ref(group)
        if not ref:
            groups.append({"group": group, "status": "error", "error": "Not configured on the server."})
            continue
        try:
            title, people = await get_gateway().group_members(session, ref)
            groups.append({"group": group, "status": "ok", "resolved_group_name": title,
                           "discoverable_recipients": len(people)})
        except TelegramError as error:
            groups.append({"group": group, "status": "error", "error": str(error)})
    return {"groups": groups}


async def eligible(user_id: int, group: str, audience: str) -> list[dict]:
    _, people = await live_group(user_id, group)
    with db.connect() as conn:
        detail = {m["telegram_id"]: m for m in directory.directory(conn, user_id)["members"]}
        baseline = conn.execute("SELECT member_ids_json FROM group_baselines WHERE user_id = ? AND grp = ?",
                                (user_id, group)).fetchone()
        welcomed = {row["telegram_id"] for row in conn.execute(
            "SELECT telegram_id FROM outreach_log WHERE user_id = ? AND grp = ? AND audience = 'new'", (user_id, group))}
    if audience == "new":
        if baseline is None:
            raise HTTPException(409, f"Start tracking the {GROUP_LABELS[group]} group before using the New members audience.")
        known = set(json.loads(baseline["member_ids_json"]))
        # New since the baseline, and not already sent a new-member message (so nobody is welcomed twice).
        people = [p for p in people if p["telegram_id"] not in known and p["telegram_id"] not in welcomed]
    elif audience == "unmatched":
        people = [p for p in people if not (detail.get(p["telegram_id"]) or {}).get("links")]
    elif audience in ("active", "inactive"):
        people = [p for p in people if (detail.get(p["telegram_id"]) or {}).get("activity_status") == audience]
    return [{"telegram_id": p["telegram_id"], "display_name": p["display_name"], "username": p["username"],
             "access_hash": p.get("access_hash", ""), "group": group} for p in people]


@router.post("/api/telegram/outreach/preview")
async def preview(body: PreviewIn, user: dict = Depends(current_user)):
    recipients = await eligible(user["id"], body.group, body.audience)
    message = (f"{len(recipients)} eligible recipient(s) in {GROUP_LABELS[body.group]}. Select who to message; "
               "nothing is sent until you confirm." if recipients else "No eligible recipients for this audience.")
    return {"recipients": [{k: v for k, v in r.items() if k != "access_hash"} for r in recipients], "message": message}


@router.post("/api/telegram/outreach/send")
async def send(body: SendIn, user: dict = Depends(current_user)):
    if not body.confirm_send or body.confirmation_text != "SEND":
        raise HTTPException(422, "Tick the review box and type SEND to confirm.")
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Write a message first.")
    wanted = list(dict.fromkeys(str(i) for i in body.recipient_ids))
    if len(wanted) > MAX_RECIPIENTS_PER_SEND:
        raise HTTPException(422, f"Send to at most {MAX_RECIPIENTS_PER_SEND} people at a time.")
    allowed = {r["telegram_id"]: r for r in await eligible(user["id"], body.group, body.audience)}
    not_allowed = [i for i in wanted if i not in allowed]
    if not_allowed:
        raise HTTPException(409, f"{len(not_allowed)} selected recipient(s) are no longer eligible for this group and "
                                 "audience. Preview the recipients again.")
    try:
        results = await get_gateway().send_messages(authorized_session(user["id"]), [allowed[i] for i in wanted], message)
    except TelegramError as error:
        fail(error)
    sent = [r for r in results if not r["error"]]
    failed = [{"telegram_id": r["telegram_id"], "display_name": r["display_name"], "error": r["error"]}
              for r in results if r["error"]]
    with db.connect() as conn:
        for r in sent:
            conn.execute("INSERT INTO outreach_log (user_id, telegram_id, display_name, grp, audience, sent_at)"
                         " VALUES (?, ?, ?, ?, ?, ?)",
                         (user["id"], r["telegram_id"], r["display_name"], body.group, body.audience, db.now()))
    return {"sent_count": len(sent), "failed_count": len(failed), "failed": failed}


@router.get("/api/telegram/outreach/history")
def history(user: dict = Depends(current_user)):
    with db.connect() as conn:
        rows = conn.execute("SELECT telegram_id, display_name, grp AS 'group', audience, sent_at FROM outreach_log"
                            " WHERE user_id = ? ORDER BY pk DESC LIMIT 2000", (user["id"],)).fetchall()
    return {"history": [dict(row) for row in rows]}


# ── Replies with UIDs ────────────────────────────────────────────────────────

class ScanRepliesIn(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    scan_mode: Literal["prompted", "all_chats"] = "prompted"


class ReplyReviewIn(BaseModel):
    candidate_id: str
    decision: Literal["approved", "rejected"]


class ReplyEditIn(BaseModel):
    candidate_id: str
    telegram_name: str = Field(default="", max_length=120)
    uid: str = Field(default="", max_length=40)
    broker: str = Field(default="", max_length=20)


class ReplyIdIn(BaseModel):
    candidate_id: str


# 5–10 digits, not part of a longer number, an international phone number (+…) or a date.
UID_PATTERN = re.compile(r"(?<![\d+/.-])\d{5,10}(?![\d/.-])")


def reply_uids(text: str) -> list[str]:
    """Numbers in a reply that could be a UID or account number. Local phone numbers (0 then 8+ digits) aren't."""
    return list(dict.fromkeys(n for n in UID_PATTERN.findall(text) if not (n.startswith("0") and len(n) >= 9)))


def mentioned_broker(text: str) -> str:
    lower = text.lower()
    vantage = "vantage" in lower
    pu = bool(re.search(r"\bpu\s*-?\s*prime\b|\bpuprime\b|\bpu\b", lower))
    return "Vantage" if vantage and not pu else "PU Prime" if pu and not vantage else ""


def judge(index: dict, uids: list[str], broker: str, owner) -> dict:
    """Match the UIDs in a reply against the reports. owner(uid, broker) → who it's already linked to, if anyone."""
    resolved = {}
    for value in uids:
        for b, uid, _ in directory.resolve_uid(index, value, broker):
            resolved[(b, uid)] = index[(b, uid)]
    if not resolved:
        first = uids[0] if uids else ""
        return {"match_status": "uid_not_found", "uid": first, "broker": broker,
                "reason": "None of the numbers in this reply is a UID or account number in the uploaded reports.",
                "report_client_name": "", "account_count": 0}
    if len(resolved) > 1:
        brokers = sorted({b for b, _ in resolved})
        b, uid = sorted(resolved)[0]
        why = (f"The UID appears at both {' and '.join(brokers)}; the reply doesn't say which."
               if len({u for _, u in resolved}) == 1 else "The reply contains more than one UID.")
        return {"match_status": "needs_review", "uid": uid, "broker": b if len(brokers) == 1 else "",
                "reason": why, "report_client_name": "", "account_count": 0}
    (b, uid), entry = next(iter(resolved.items()))
    base = {"uid": uid, "broker": b, "report_client_name": ", ".join(sorted(entry["names"])),
            "account_count": entry["account_count"]}
    if owner(uid, b):
        return base | {"match_status": "needs_review", "reason": "This UID is already linked to another member."}
    return base | {"match_status": "exact_match", "reason": "The UID is in the uploaded reports."}


@router.post("/api/telegram/reply-matches/scan")
async def scan_replies(body: ScanRepliesIn, user: dict = Depends(current_user)):
    session = authorized_session(user["id"])
    with db.connect() as conn:
        member_map = directory.members(conn, user["id"])
        prompted_ids = [row["telegram_id"] for row in conn.execute(
            "SELECT DISTINCT telegram_id FROM outreach_log WHERE user_id = ?", (user["id"],))]
    peers = [member_map.get(tid, {"telegram_id": tid}) | {"telegram_id": tid} for tid in prompted_ids]
    if body.scan_mode == "prompted" and not peers:
        return {"checked_messages": 0, "prompted_recipients": 0, "checked_chats": 0, "new_or_updated_matches": 0}
    try:
        messages, chats = await get_gateway().incoming(session, body.days, None if body.scan_mode == "all_chats" else peers)
    except TelegramError as error:
        fail(error)
    prompted = set(prompted_ids)
    changed = 0
    with db.connect() as conn:
        index = reports.uid_index(conn, user["id"])
        for message in messages:
            uids = reply_uids(message["text"])
            if not uids:
                continue
            cid = directory.candidate_id(message["telegram_id"], message["message_id"])
            existing = conn.execute("SELECT decision FROM reply_candidates WHERE user_id = ? AND id = ?",
                                    (user["id"], cid)).fetchone()
            if existing and existing["decision"] != "pending":
                continue                                   # already decided by a person
            sender = message["telegram_id"]
            owner = lambda uid, b: (lambda o: o if o and o != sender else None)(directory.owner_of(conn, user["id"], uid, b))
            verdict = judge(index, uids, mentioned_broker(message["text"]), owner)
            conn.execute(
                "INSERT INTO reply_candidates (id, user_id, telegram_id, display_name, username, chat_name, reply_text, uid,"
                " broker, source, match_status, decision, reason, report_client_name, account_count, message_date,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id, id) DO UPDATE SET reply_text = excluded.reply_text, uid = excluded.uid,"
                " broker = excluded.broker, match_status = excluded.match_status, reason = excluded.reason,"
                " report_client_name = excluded.report_client_name, account_count = excluded.account_count,"
                " updated_at = excluded.updated_at",
                (cid, user["id"], sender, message["display_name"], message["username"], message["chat_name"],
                 message["text"][:2000], verdict["uid"], verdict["broker"],
                 "prompted" if sender in prompted else "open_scan", verdict["match_status"], verdict["reason"],
                 verdict["report_client_name"], verdict["account_count"], message["date"], db.now()))
            changed += 1
    return {"checked_messages": len(messages), "prompted_recipients": len(prompted_ids), "checked_chats": chats,
            "new_or_updated_matches": changed}


def reply_rows(conn, user_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM reply_candidates WHERE user_id = ? ORDER BY message_date DESC",
                                              (user_id,))]


@router.get("/api/telegram/reply-matches")
def reply_matches(user: dict = Depends(current_user)):
    with db.connect() as conn:
        rows = reply_rows(conn, user["id"])
    return {"candidates": [{"id": r["id"], "telegram_id": r["telegram_id"], "telegram_display_name": r["display_name"],
                            "telegram_username": r["username"], "reply_text": r["reply_text"], "chat_name": r["chat_name"],
                            "uid": r["uid"], "broker": r["broker"], "broker_name": r["broker"], "source": r["source"],
                            "match_status": r["match_status"], "reason": r["reason"], "decision": r["decision"]}
                           for r in rows]}


def reply_link_source(cid: str) -> str:
    return f"reply:{cid}"


@router.post("/api/telegram/reply-matches/review")
def review_reply(body: ReplyReviewIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM reply_candidates WHERE user_id = ? AND id = ?",
                           (user["id"], body.candidate_id)).fetchone()
        if row is None:
            raise HTTPException(404, "That reply record no longer exists.")
        if body.decision == "approved":
            if row["match_status"] == "uid_not_found":
                raise HTTPException(409, "This UID isn't in any uploaded report yet. Upload the report first, or edit the UID.")
            if not row["broker"]:
                raise HTTPException(409, "Choose the broker for this UID (Edit), then approve it.")
            # Someone who replied from a private chat may not be in a scanned group yet: add them on approval only.
            directory.upsert_member(conn, user["id"], {"telegram_id": row["telegram_id"], "display_name": row["display_name"] or "",
                                                       "username": row["username"] or ""}, "reply")
            broker, uid = directory.add_link(conn, user["id"], row["telegram_id"], row["uid"], row["broker"],
                                             source=reply_link_source(row["id"]))
            message = f"UID {uid} ({broker}) linked to {row['display_name'] or row['telegram_id']}."
        else:
            message = "Reply rejected. Its UID will not be used."
        conn.execute("UPDATE reply_candidates SET decision = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                     (body.decision, db.now(), user["id"], body.candidate_id))
    return {"message": message}


@router.get("/api/telegram/reply-directory")
def reply_directory(user: dict = Depends(current_user)):
    with db.connect() as conn:
        rows = reply_rows(conn, user["id"])
        linked = {(r["telegram_id"], r["uid"]) for r in conn.execute("SELECT telegram_id, uid FROM links WHERE user_id = ?",
                                                                     (user["id"],))}
    out = [{"candidate_id": r["id"], "telegram_name": r["display_name"], "uid": r["uid"], "broker": r["broker"],
            "original_reply": r["reply_text"], "source": r["source"], "match_status": r["match_status"],
            "decision": r["decision"], "linked": (r["telegram_id"], r["uid"]) in linked and r["decision"] != "rejected",
            "report_client_name": r["report_client_name"], "account_count": r["account_count"], "reason": r["reason"]}
           for r in rows]
    return {"rows": out, "row_count": len(out)}


@router.post("/api/telegram/reply-directory/edit")
def edit_reply(body: ReplyEditIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM reply_candidates WHERE user_id = ? AND id = ?",
                           (user["id"], body.candidate_id)).fetchone()
        if row is None:
            raise HTTPException(404, "That reply record no longer exists.")
        # An edit is a new claim: undo any link this reply created and send it back for review.
        conn.execute("DELETE FROM links WHERE user_id = ? AND source = ?", (user["id"], reply_link_source(row["id"])))
        uid = directory.clean_uid(body.uid) or row["uid"]
        broker = directory.broker_name(body.broker) or row["broker"] or ""
        index = reports.uid_index(conn, user["id"])
        owner = lambda u, b: (lambda o: o if o and o != row["telegram_id"] else None)(directory.owner_of(conn, user["id"], u, b))
        verdict = judge(index, [uid], broker, owner)
        conn.execute("UPDATE reply_candidates SET display_name = ?, uid = ?, broker = ?, match_status = ?, reason = ?,"
                     " report_client_name = ?, account_count = ?, decision = 'pending', updated_at = ?"
                     " WHERE user_id = ? AND id = ?",
                     (body.telegram_name.strip() or row["display_name"], verdict["uid"], verdict["broker"] or broker,
                      verdict["match_status"], f"Edited by a person. {verdict['reason']}", verdict["report_client_name"],
                      verdict["account_count"], db.now(), user["id"], row["id"]))
    return {"message": "Reply updated and sent back for review."}


@router.post("/api/telegram/reply-directory/delete")
def delete_reply(body: ReplyIdIn, user: dict = Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM links WHERE user_id = ? AND source = ?", (user["id"], reply_link_source(body.candidate_id)))
        if not conn.execute("DELETE FROM reply_candidates WHERE user_id = ? AND id = ?",
                            (user["id"], body.candidate_id)).rowcount:
            raise HTTPException(404, "That reply record no longer exists.")
    return {"message": "Reply deleted."}


@router.delete("/api/telegram/reply-directory")
def erase_replies(user: dict = Depends(current_user)):
    with db.connect() as conn:
        replies = conn.execute("DELETE FROM reply_candidates WHERE user_id = ?", (user["id"],)).rowcount
        links = conn.execute("DELETE FROM links WHERE user_id = ? AND source LIKE 'reply:%'", (user["id"],)).rowcount
    return {"message": f"Erased {replies} reply record(s) and {links} UID link(s) created from replies. "
                       "Imported members and broker reports were kept."}


# ── Workspace summary ────────────────────────────────────────────────────────

@router.get("/api/telegram/workspace")
def workspace(user: dict = Depends(current_user)):
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    with db.connect() as conn:
        uid = user["id"]
        one = lambda sql, *args: conn.execute(sql, (uid, *args)).fetchone()[0]
        groups = {}
        for group in GROUPS:
            row = conn.execute("SELECT member_ids_json FROM group_baselines WHERE user_id = ? AND grp = ?",
                               (uid, group)).fetchone()
            groups[group] = {"initialized": row is not None,
                             "baseline_count": len(json.loads(row["member_ids_json"])) if row else 0}
        replies = reply_rows(conn, uid)
        linked = {(r["telegram_id"], r["uid"]) for r in conn.execute("SELECT telegram_id, uid FROM links WHERE user_id = ?", (uid,))}
        links_summary = directory.payload(conn, uid)["summary"]
        return {
            "outreach": {"sent_total": one("SELECT COUNT(*) FROM outreach_log WHERE user_id = ?"),
                         "sent_last_7_days": one("SELECT COUNT(*) FROM outreach_log WHERE user_id = ? AND sent_at >= ?", week_ago),
                         "unique_recipients": one("SELECT COUNT(DISTINCT telegram_id) FROM outreach_log WHERE user_id = ?"),
                         "last_sent_at": one("SELECT MAX(sent_at) FROM outreach_log WHERE user_id = ?"),
                         "groups": groups},
            "replies": {"total": len(replies), "pending": sum(r["decision"] == "pending" for r in replies),
                        "linked": sum((r["telegram_id"], r["uid"]) in linked for r in replies)},
            "account_links": {"summary": links_summary},
        }
