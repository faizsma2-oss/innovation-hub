"""The Telegram member directory and its links to broker UIDs.

A member's match status, from their linked UIDs:
  matched             at least one linked UID is in the latest uploaded reports
  historical_only     none are current, but at least one appeared in an earlier report
  uid_not_in_reports  UIDs are saved but have never appeared in any report
  no_uid              nothing linked yet
A member's activity: active if any linked account is active; inactive if they have current account data and none
is active; unknown otherwise.
"""
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException

from . import db, reports

BROKER_NAMES = {"vantage": "Vantage", "puprime": "PU Prime", "pu": "PU Prime", "pu prime": "PU Prime",
                "vantage markets": "Vantage", "pu_prime": "PU Prime"}


def broker_name(value: str | None) -> str:
    """'vantage', 'Vantage', 'puprime', 'PU Prime' → 'Vantage' / 'PU Prime'; anything else → ''."""
    compact = re.sub(r"[\s_-]+", " ", str(value or "").strip().lower())
    return BROKER_NAMES.get(compact) or BROKER_NAMES.get(compact.replace(" ", ""), "")


def clean_uid(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def candidate_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def name_tokens(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return [t for t in re.findall(r"[a-z]+", text) if len(t) > 1]


# ── Reading ──────────────────────────────────────────────────────────────────

def members(conn, user_id: int) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM members WHERE user_id = ?", (user_id,)).fetchall()
    return {row["telegram_id"]: {"telegram_id": row["telegram_id"], "display_name": row["display_name"] or "",
                                 "username": (row["username"] or "").lstrip("@"), "access_hash": row["access_hash"] or "",
                                 "groups": json.loads(row["groups_json"]), "source": row["source"]}
            for row in rows}


def links(conn, user_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT telegram_id, uid, broker, source, created_at FROM links"
                                              " WHERE user_id = ? ORDER BY created_at", (user_id,))]


def link_detail(link: dict, entry: dict | None) -> dict:
    entry = entry or {}
    current = bool(entry.get("current"))
    current_ids = sorted(entry.get("account_ids", set()), key=reports.natural) if current else []
    activity = ("active" if entry.get("active_accounts") else
                "inactive" if entry.get("in_accounts") else "unknown")
    sources = [label for flag, label in (("in_accounts", "IB account"), ("in_funds", "Funds"),
                                         ("in_opened", "Opened account"), ("in_rebates", "Rebate")) if entry.get(flag)]
    return {
        "uid": link["uid"], "broker": link["broker"], "brokers": [link["broker"]] if link["broker"] else [],
        "source": link.get("source"), "report_names": sorted(entry.get("names", set())),
        "account_count": entry.get("account_count", 0) if current else 0,
        "current_account_count": len(current_ids), "current_account_ids": current_ids,
        "account_ids": sorted(entry.get("account_ids", set()) | entry.get("historical_account_ids", set()),
                              key=reports.natural),
        "total_balance": round(entry.get("total_balance", 0.0), 2), "total_equity": round(entry.get("total_equity", 0.0), 2),
        "total_rebate": round(entry.get("total_rebate", 0.0), 2), "last_trade_date": entry.get("last_trade_date", ""),
        "active_account_count": entry.get("active_accounts", 0), "inactive_account_count": entry.get("inactive_accounts", 0),
        "activity_status": activity, "report_sources": sources,
        "present_in_reports": bool(entry), "present_in_current_reports": current,
        "present_in_account_reports": bool(entry.get("in_accounts")),
        "present_in_rebate_reports": bool(entry.get("in_rebates")),
        "known_from_history": bool(entry.get("historical")) and not current,
    }


def directory(conn, user_id: int, index: dict | None = None) -> dict:
    index = index if index is not None else reports.uid_index(conn, user_id)
    by_member = {}
    for link in links(conn, user_id):
        by_member.setdefault(link["telegram_id"], []).append(link_detail(link, index.get((link["broker"], link["uid"]))))
    rows, summary = [], {"members": 0, "active_members": 0, "inactive_members": 0, "unknown_activity_members": 0,
                         "linked_members": 0, "uid_links": 0, "matched_members": 0, "members_needing_current_match": 0,
                         "historical_only_members": 0, "uid_not_in_report_members": 0, "vantage_links": 0,
                         "puprime_links": 0}
    for member in sorted(members(conn, user_id).values(), key=lambda m: (m["display_name"] or m["username"]).lower()):
        member_links = by_member.get(member["telegram_id"], [])
        active = sum(l["active_account_count"] for l in member_links)
        inactive = sum(l["inactive_account_count"] for l in member_links)
        has_account_data = any(l["present_in_account_reports"] for l in member_links)
        activity = "active" if active else "inactive" if has_account_data else "unknown"
        match = ("no_uid" if not member_links else
                 "matched" if any(l["present_in_current_reports"] for l in member_links) else
                 "historical_only" if any(l["known_from_history"] for l in member_links) else "uid_not_in_reports")
        row = {k: v for k, v in member.items() if k != "access_hash"} | {
            "links": member_links, "activity_status": activity, "current_match_status": match,
            "account_count": sum(l["current_account_count"] for l in member_links),
            "active_account_count": active, "inactive_account_count": inactive,
            "total_equity": round(sum(l["total_equity"] for l in member_links), 2),
            "total_balance": round(sum(l["total_balance"] for l in member_links), 2),
            "last_trade_date": max((l["last_trade_date"] for l in member_links), default="")}
        rows.append(row)
        summary["members"] += 1
        summary[{"active": "active_members", "inactive": "inactive_members"}.get(activity, "unknown_activity_members")] += 1
        summary["linked_members"] += bool(member_links)
        summary["uid_links"] += len(member_links)
        summary["matched_members"] += match == "matched"
        summary["members_needing_current_match"] += match != "matched"
        summary["historical_only_members"] += match == "historical_only"
        summary["uid_not_in_report_members"] += match == "uid_not_in_reports"
        summary["vantage_links"] += sum(l["broker"] == "Vantage" for l in member_links)
        summary["puprime_links"] += sum(l["broker"] == "PU Prime" for l in member_links)
    return {"members": rows, "summary": summary}


# ── Repairs and resolving what a person typed ────────────────────────────────

def resolve_uid(index: dict, value: str, broker: str = "") -> list[tuple[str, str, str]]:
    """Which (broker, UID) a typed value means: a UID itself, or an account number that belongs to one.
    Returns [(broker, uid, how)] — empty if it isn't in any report."""
    value = clean_uid(value)
    found = [(b, u, "uid") for (b, u) in index if u == value and (not broker or b == broker)]
    if found:
        return found
    return [(b, u, "account") for (b, u), entry in index.items()
            if (not broker or b == broker) and value in (entry["account_ids"] | entry["historical_account_ids"])]


def repair_links(conn, user_id: int, index: dict) -> list[str]:
    """Saved values that the reports show are really an account number, or are at the other broker, are corrected."""
    repairs = []
    for link in links(conn, user_id):
        if (link["broker"], link["uid"]) in index:
            continue
        matches = resolve_uid(index, link["uid"])
        targets = {(b, u) for b, u, _ in matches}
        if len(targets) != 1:
            continue                       # nothing found, or ambiguous: leave it for a person
        broker, uid = targets.pop()
        conn.execute("DELETE FROM links WHERE user_id = ? AND telegram_id = ? AND uid = ? AND broker = ?",
                     (user_id, link["telegram_id"], link["uid"], link["broker"]))
        conn.execute("INSERT OR IGNORE INTO links (user_id, telegram_id, uid, broker, source, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)", (user_id, link["telegram_id"], uid, broker, link["source"], link["created_at"]))
        how = "account number" if uid != link["uid"] else "broker"
        repairs.append(f"{link['uid']} ({link['broker'] or 'no broker'}) → UID {uid} at {broker} (saved {how} corrected)")
    return repairs


def owner_of(conn, user_id: int, uid: str, broker: str) -> str | None:
    row = conn.execute("SELECT telegram_id FROM links WHERE user_id = ? AND uid = ? AND (broker = ? OR broker = '' OR ? = '')",
                       (user_id, uid, broker, broker)).fetchone()
    return row["telegram_id"] if row else None


def add_link(conn, user_id: int, telegram_id: str, value: str, broker: str = "", source: str = "manual") -> tuple[str, str]:
    """Link a member to a UID (or an account number, resolved to its UID). Returns the (broker, uid) saved."""
    value = clean_uid(value)
    if not re.fullmatch(r"[A-Za-z0-9]{3,40}", value):
        raise HTTPException(422, "Enter a UID of 3 to 40 letters or digits.")
    broker = broker_name(broker) if broker else ""
    if conn.execute("SELECT 1 FROM members WHERE user_id = ? AND telegram_id = ?", (user_id, telegram_id)).fetchone() is None:
        raise HTTPException(404, "That Telegram member isn't in the directory.")
    index = reports.uid_index(conn, user_id)
    targets = sorted({(b, u) for b, u, _ in resolve_uid(index, value, broker)})
    if len(targets) > 1:
        brokers = sorted({b for b, _ in targets})
        if len(brokers) > 1:
            raise HTTPException(409, f"{value} appears at both {' and '.join(brokers)}. Choose the broker and link it again.")
        raise HTTPException(409, f"Account {value} belongs to more than one UID: {', '.join(u for _, u in targets)}. "
                                 "Enter the UID itself.")
    broker, uid = targets[0] if targets else (broker, value)   # not in any report yet: saved as unverified
    owner = owner_of(conn, user_id, uid, broker)
    if owner and owner != telegram_id:
        name = conn.execute("SELECT display_name FROM members WHERE user_id = ? AND telegram_id = ?",
                            (user_id, owner)).fetchone()
        raise HTTPException(409, f"UID {uid} is already linked to {(name and name['display_name']) or owner}. "
                                 "Remove it there first.")
    conn.execute("INSERT OR IGNORE INTO links (user_id, telegram_id, uid, broker, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, telegram_id, uid, broker, source, db.now()))
    conn.execute("UPDATE link_candidates SET status = 'linked', decision = 'approved', updated_at = ?"
                 " WHERE user_id = ? AND telegram_id = ? AND uid = ? AND broker = ?",
                 (db.now(), user_id, telegram_id, uid, broker))
    return broker, uid


def remove_link(conn, user_id: int, telegram_id: str, uid: str, broker: str = "") -> int:
    broker = broker_name(broker) if broker else ""
    sql = "DELETE FROM links WHERE user_id = ? AND telegram_id = ? AND uid = ?"
    params = [user_id, str(telegram_id), clean_uid(uid)]
    if broker:
        sql += " AND broker = ?"
        params.append(broker)
    removed = conn.execute(sql, params).rowcount
    conn.execute("UPDATE link_candidates SET status = 'needs_review', decision = 'pending', updated_at = ?"
                 " WHERE user_id = ? AND telegram_id = ? AND uid = ? AND status = 'linked'",
                 (db.now(), user_id, str(telegram_id), clean_uid(uid)))
    return removed


# ── Suggestions from a group scan ────────────────────────────────────────────

def suggest(conn, user_id: int, index: dict):
    """Name matches between Telegram members and report names. Never linked without a person approving."""
    linked_uids = {(row["broker"], row["uid"]) for row in links(conn, user_id)}
    linked_members = {row["telegram_id"] for row in links(conn, user_id)}
    by_name = {}
    for (broker, uid), entry in index.items():
        if not entry["current"] or (broker, uid) in linked_uids:
            continue
        for name in entry["names"]:
            tokens = name_tokens(name)
            if tokens:
                by_name.setdefault(" ".join(tokens), set()).add((broker, uid, name))
    for member in members(conn, user_id).values():
        if member["telegram_id"] in linked_members:
            continue
        tokens = name_tokens(member["display_name"])
        if len(tokens) < 2:
            continue                                   # a single first name is too weak to suggest anything
        exact = by_name.get(" ".join(tokens), set())
        partial = set()
        if not exact:
            for name, targets in by_name.items():
                if set(tokens) <= set(name.split()):
                    partial |= targets
        if exact:
            status, confidence = ("suggested", 0.96) if len(exact) == 1 else ("conflict", 0.6)
            reason = ("Telegram name matches the broker report name exactly" if len(exact) == 1 else
                      f"Telegram name matches {len(exact)} different report accounts")
            targets = exact
        elif partial:
            status, confidence = "needs_review", 0.75 if len(partial) == 1 else 0.5
            reason = "Every word of the Telegram name appears in the report name"
            targets = partial
        else:
            continue
        for broker, uid, report_name in sorted(targets):
            cid = candidate_id(member["telegram_id"], broker, uid)
            existing = conn.execute("SELECT decision FROM link_candidates WHERE user_id = ? AND id = ?",
                                    (user_id, cid)).fetchone()
            if existing and existing["decision"] != "pending":
                continue                              # a person already decided: keep it
            conn.execute("INSERT INTO link_candidates (id, user_id, telegram_id, uid, broker, status, decision, confidence,"
                         " source, reason, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'identity_match', ?, ?)"
                         " ON CONFLICT(user_id, id) DO UPDATE SET status = excluded.status, confidence = excluded.confidence,"
                         " reason = excluded.reason, updated_at = excluded.updated_at",
                         (cid, user_id, member["telegram_id"], uid, broker, status, confidence,
                          f"{reason} ({report_name})", db.now()))


def review(conn, user_id: int, candidate_ids: list[str], decision: str) -> int:
    changed = 0
    for cid in candidate_ids:
        row = conn.execute("SELECT * FROM link_candidates WHERE user_id = ? AND id = ?", (user_id, cid)).fetchone()
        if row is None:
            continue
        if decision == "approved":
            add_link(conn, user_id, row["telegram_id"], row["uid"], row["broker"], source="identity_match")
        else:
            conn.execute("UPDATE link_candidates SET decision = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                         (decision, db.now(), user_id, cid))
        changed += 1
    return changed


# ── The payload the page reads ───────────────────────────────────────────────

def payload(conn, user_id: int, extra: dict | None = None) -> dict:
    index = reports.uid_index(conn, user_id)
    repairs = repair_links(conn, user_id, index)
    member_map = members(conn, user_id)
    directory_data = directory(conn, user_id, index)
    detail_by_member = {m["telegram_id"]: m for m in directory_data["members"]}

    def candidate_row(base: dict) -> dict:
        member = member_map.get(base["telegram_id"], {})
        entry = index.get((base["broker"], base["uid"])) or {}
        return base | {"telegram_display_name": member.get("display_name", ""), "telegram_username": member.get("username", ""),
                       "groups": member.get("groups", []), "brokers": [base["broker"]] if base["broker"] else [],
                       "report_names": sorted(entry.get("names", set())), "account_count": entry.get("account_count", 0),
                       "total_balance": round(entry.get("total_balance", 0.0), 2)}

    candidates = []
    approved = set()
    for link in links(conn, user_id):
        approved.add((link["telegram_id"], link["broker"], link["uid"]))
        candidates.append(candidate_row({
            "id": candidate_id(link["telegram_id"], link["broker"], link["uid"]), "telegram_id": link["telegram_id"],
            "uid": link["uid"], "broker": link["broker"], "status": "linked", "decision": "approved", "confidence": 1.0,
            "source": "approved_link" if link["source"] != "manual" else "manual",
            "reason": f"Linked ({link['source'].replace('_', ' ')})"}))
    for row in conn.execute("SELECT * FROM link_candidates WHERE user_id = ?", (user_id,)):
        if (row["telegram_id"], row["broker"], row["uid"]) in approved or row["telegram_id"] not in member_map:
            continue
        candidates.append(candidate_row({k: row[k] for k in ("id", "telegram_id", "uid", "broker", "status", "decision",
                                                              "confidence", "source", "reason")}))
    pending = [c for c in candidates if c["decision"] == "pending"]
    with_options = {c["telegram_id"] for c in candidates if c["decision"] != "rejected"}
    linked_members = len({c["telegram_id"] for c in candidates if c["status"] == "linked"})
    summary = {"discovered": len(member_map), "linked_members": linked_members,
               "remaining": max(len(member_map) - linked_members, 0),
               "suggested": sum(c["status"] == "suggested" for c in pending),
               "needs_review": sum(c["status"] == "needs_review" for c in pending),
               "conflict": sum(c["status"] == "conflict" for c in pending),
               "unmatched": sum(1 for tid in member_map if tid not in with_options),
               "linked": sum(c["status"] == "linked" for c in candidates)}
    groups_state = db.get_state(conn, user_id, "groups", {})
    result = {
        "member_directory": directory_data,
        "members": [{k: v for k, v in m.items() if k != "access_hash"} | {
            "activity_status": detail_by_member[m["telegram_id"]]["activity_status"]} for m in member_map.values()],
        "candidates": candidates,
        "approved_links": [c for c in candidates if c["status"] == "linked"],
        "summary": summary,
        "groups": [{"group": g, "member_count": groups_state.get(g, {}).get("member_count", 0),
                    "title": groups_state.get(g, {}).get("title")} for g in ("discussion", "vip") if g in groups_state],
        "needs_scan": not member_map and not db.get_state(conn, user_id, "last_scanned_at"),
        "last_scanned_at": db.get_state(conn, user_id, "last_scanned_at"),
        "automatic_repairs": repairs, "warnings": [], "membership_changes": {"added": 0, "removed": 0},
    }
    return result | (extra or {})


def accounts_search(conn, user_id: int, query: str, broker: str, limit: int) -> dict:
    index = reports.uid_index(conn, user_id)
    wanted = broker_name(broker) if broker and broker != "all" else ""
    query = query.strip().lower()
    rows = []
    for (b, uid), entry in index.items():
        if not entry["current"] or (wanted and b != wanted):
            continue
        names = sorted(entry["names"])
        haystack = " ".join([uid, b, *names, *entry["account_ids"]]).lower()
        if query and query not in haystack:
            continue
        rows.append({"uid": uid, "brokers": [b], "report_name": ", ".join(names), "account_count": entry["account_count"],
                     "total_balance": round(entry["total_balance"], 2)})
    rows.sort(key=lambda r: (r["report_name"].lower(), reports.natural(r["uid"])))
    return {"row_count": len(rows), "rows": rows[:limit]}


def upsert_member(conn, user_id: int, member: dict, source: str, groups: list[str] | None = None):
    existing = conn.execute("SELECT * FROM members WHERE user_id = ? AND telegram_id = ?",
                            (user_id, member["telegram_id"])).fetchone()
    stamp = db.now()
    if existing:
        new_groups = groups if groups is not None else json.loads(existing["groups_json"])
        conn.execute("UPDATE members SET display_name = COALESCE(NULLIF(?, ''), display_name),"
                     " username = COALESCE(NULLIF(?, ''), username), access_hash = COALESCE(NULLIF(?, ''), access_hash),"
                     " groups_json = ?, source = ?, last_seen = ? WHERE user_id = ? AND telegram_id = ?",
                     (member.get("display_name", ""), member.get("username", ""), member.get("access_hash", ""),
                      json.dumps(sorted(set(new_groups))), source if source == "telegram_scan" else existing["source"],
                      stamp, user_id, member["telegram_id"]))
    else:
        conn.execute("INSERT INTO members (user_id, telegram_id, display_name, username, access_hash, groups_json, source,"
                     " first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (user_id, member["telegram_id"], member.get("display_name", ""), member.get("username", ""),
                      member.get("access_hash", ""), json.dumps(sorted(set(groups or []))), source, stamp, stamp))
