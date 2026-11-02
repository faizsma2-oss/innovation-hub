"""Telegram: connection, member directory, links, outreach and UID replies — against the fake Telegram."""
from datetime import datetime, timezone

from app.telegram_client import FAKE
from conftest import connect_telegram, upload, vantage_accounts, xlsx


def scan(client):
    response = client.post("/api/telegram/account-links/scan")
    assert response.status_code == 200, response.text
    return response.json()


def member(payload, telegram_id):
    return next(m for m in payload["member_directory"]["members"] if m["telegram_id"] == telegram_id)


# ── Connection ───────────────────────────────────────────────────────────────

def test_connect_with_a_code(client):
    assert client.get("/api/connections/telegram/health").json()["status"] == "not_connected"
    bad = client.post("/api/connections/telegram/start", json={"phone_number": "0501234567"})
    assert bad.status_code == 422 and "country code" in bad.json()["detail"]
    assert client.post("/api/connections/telegram/verify-code", json={"code": "12345"}).status_code == 409
    client.post("/api/connections/telegram/start", json={"phone_number": "+971 50 000 0001"})
    assert client.post("/api/connections/telegram/verify-code", json={"code": "99999"}).status_code == 409
    assert client.post("/api/connections/telegram/verify-code", json={"code": "12345"}).json()["requires_password"] is False
    health = client.get("/api/connections/telegram/health").json()
    assert health["status"] == "connected" and health["authorized"] is True
    assert client.get("/api/connections").json()["telegram"]["status"] == "connected"


def test_two_step_password_and_disconnect(client):
    assert connect_telegram(client, "+971500000002").json()["requires_password"] is True
    assert client.post("/api/connections/telegram/verify-password", json={"password": "nope"}).status_code == 409
    assert client.post("/api/connections/telegram/verify-password", json={"password": "hunter2"}).status_code == 200
    assert client.get("/api/connections/telegram/health").json()["authorized"] is True
    assert client.delete("/api/connections/telegram").json()["status"] == "disconnected"
    assert client.post("/api/telegram/account-links/scan").status_code == 409


# ── Directory and links ──────────────────────────────────────────────────────

def test_scan_builds_the_directory_and_suggests_name_matches(client):
    connect_telegram(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    data = scan(client)
    assert data["member_directory"]["summary"]["members"] == 5
    assert member(data, "1001")["groups"] == ["discussion", "vip"]
    suggestions = {(c["telegram_id"], c["uid"]): c for c in data["candidates"] if c["decision"] == "pending"}
    assert suggestions[("1001", "11111111")]["status"] == "suggested"       # "Ali Hassan" = "Ali Hassan"
    assert ("1003", "33333333") not in suggestions                          # names differ: no guess
    # Nothing is linked until a person approves.
    assert data["member_directory"]["summary"]["linked_members"] == 0
    reviewed = client.post("/api/telegram/account-links/review",
                           json={"candidate_ids": [suggestions[("1001", "11111111")]["id"]], "decision": "approved"}).json()
    ali = member(reviewed, "1001")
    assert ali["current_match_status"] == "matched" and ali["activity_status"] == "active"
    assert ali["links"][0]["broker"] == "Vantage" and ali["links"][0]["account_count"] == 1


def test_a_failed_group_read_never_empties_the_directory(client, monkeypatch):
    connect_telegram(client)
    scan(client)
    monkeypatch.setenv("MAHADSPACE_VIP_GROUP", "missing-group")
    data = scan(client)
    assert data["member_directory"]["summary"]["members"] == 5                # Bilal (VIP only) is kept
    assert any("VIP" in w for w in data["warnings"])


def test_members_who_left_both_groups_are_removed(client):
    connect_telegram(client)
    scan(client)
    title, people = FAKE.groups["vip"]
    FAKE.groups["vip"] = (title, [p for p in people if p["telegram_id"] != "1005"])
    data = scan(client)
    assert data["membership_changes"]["removed"] == 1
    assert "1005" not in {m["telegram_id"] for m in data["member_directory"]["members"]}
    assert member(data, "1001")["groups"] == ["discussion", "vip"]


def test_linking_by_account_number_resolves_to_the_uid(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    data = client.post("/api/telegram/account-links/manual", json={"telegram_id": "1003", "uid": "800003"}).json()
    omar = member(data, "1003")
    assert [(l["uid"], l["broker"]) for l in omar["links"]] == [("33333333", "Vantage")]
    assert omar["activity_status"] == "inactive" and omar["account_count"] == 2


def test_a_uid_at_both_brokers_needs_the_broker_and_a_uid_has_one_owner(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    upload(client, "puprime", "ib_account_report", "p.xlsx",
           xlsx(("Accounts", [["User ID", "Account", "Equity"], ["11111111", "900001", 5]])))
    ambiguous = client.post("/api/telegram/account-links/manual", json={"telegram_id": "1002", "uid": "11111111"})
    assert ambiguous.status_code == 409 and "both" in ambiguous.json()["detail"]
    linked = client.post("/api/telegram/account-links/manual",
                         json={"telegram_id": "1002", "uid": "11111111", "broker": "PU Prime"}).json()
    assert member(linked, "1002")["links"][0]["broker"] == "PU Prime"
    taken = client.post("/api/telegram/account-links/manual",
                        json={"telegram_id": "1003", "uid": "11111111", "broker": "PU Prime"})
    assert taken.status_code == 409 and "already linked" in taken.json()["detail"]


def test_a_uid_from_an_older_report_is_historical_and_an_unknown_one_is_unverified(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v1.xlsx", vantage_accounts())
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1002", "uid": "22222222"})
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1004", "uid": "77777777"})
    upload(client, "vantage", "ib_account_report", "v2.xlsx",
           xlsx(("Accounts", [["User ID", "Account", "Equity"], ["11111111", "800001", 900]])))
    data = client.get("/api/telegram/account-links").json()
    assert member(data, "1002")["current_match_status"] == "historical_only"
    assert member(data, "1002")["links"][0]["known_from_history"] is True
    assert member(data, "1004")["current_match_status"] == "uid_not_in_reports"
    summary = data["member_directory"]["summary"]
    assert summary["historical_only_members"] == 1 and summary["uid_not_in_report_members"] == 1


def test_a_saved_value_on_the_wrong_broker_is_corrected_from_the_reports(client):
    connect_telegram(client)
    scan(client)
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1002", "uid": "22222222", "broker": "PU Prime"})
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    data = client.get("/api/telegram/account-links").json()
    assert member(data, "1002")["links"][0]["broker"] == "Vantage"


def test_unlink_and_accounts_search(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    found = client.get("/api/telegram/account-links/accounts?query=bilal&broker=vantage&limit=50").json()
    assert found["row_count"] == 1 and found["rows"][0]["uid"] == "33333333" and found["rows"][0]["account_count"] == 2
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1005", "uid": "33333333"})
    data = client.post("/api/telegram/account-links/unlink", json={"telegram_id": "1005", "uid": "33333333"}).json()
    assert member(data, "1005")["links"] == []
    assert client.post("/api/telegram/account-links/unlink", json={"telegram_id": "1005", "uid": "33333333"}).status_code == 404


def test_removing_a_member_from_groups_needs_REMOVE(client):
    connect_telegram(client)
    scan(client)
    body = {"telegram_id": "1001", "groups": ["vip"], "confirmation_text": "remove"}
    assert client.post("/api/telegram/account-links/remove-member", json=body).status_code == 422
    data = client.post("/api/telegram/account-links/remove-member", json=body | {"confirmation_text": "REMOVE"}).json()
    assert data["member_removal"]["removed_groups"] == ["vip"] and member(data, "1001")["groups"] == ["discussion"]
    assert FAKE.removed == [("vip", "1001")]


def test_member_csv_import_and_removal(client):
    csv_text = "telegram_id,name,username,group\n2001,Zara Q,@zara,VIP\n2001,dup,,\nabc,bad,,\n2002,Yusuf R,,discussion\n"
    result = client.post("/api/telegram/members/import?filename=members.csv", content=csv_text.encode()).json()
    assert result["member_count"] == 2 and result["skipped_count"] == 2
    status = client.get("/api/telegram/members/import").json()
    assert status["present"] and status["filename"] == "members.csv"
    data = client.get("/api/telegram/account-links").json()
    assert member(data, "2001")["groups"] == ["vip"] and member(data, "2001")["username"] == "zara"
    client.delete("/api/telegram/members/import")
    assert client.get("/api/telegram/account-links").json()["member_directory"]["summary"]["members"] == 0


# ── Outreach ─────────────────────────────────────────────────────────────────

def send(client, ids, **extra):
    body = {"group": "discussion", "audience": "existing", "recipient_ids": ids, "message": "Hello",
            "confirm_send": True, "confirmation_text": "SEND"} | extra
    return client.post("/api/telegram/outreach/send", json=body)


def test_sending_needs_SEND_and_only_reaches_eligible_people(client):
    connect_telegram(client)
    preview = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "existing"}).json()
    assert {r["telegram_id"] for r in preview["recipients"]} == {"1001", "1002", "1003", "1004"}
    assert send(client, ["1001"], confirmation_text="send").status_code == 422
    assert send(client, ["1005"]).status_code == 409                      # Bilal is only in VIP
    result = send(client, ["1001", "1004"]).json()
    assert result["sent_count"] == 1 and result["failed"][0]["telegram_id"] == "1004"
    assert FAKE.sent == [{"telegram_id": "1001", "text": "Hello"}]
    history = client.get("/api/telegram/outreach/history").json()["history"]
    assert [(h["telegram_id"], h["group"]) for h in history] == [("1001", "discussion")]
    workspace = client.get("/api/telegram/workspace").json()
    assert workspace["outreach"]["sent_total"] == 1 and workspace["outreach"]["unique_recipients"] == 1


def test_new_members_are_counted_from_the_baseline_and_welcomed_once(client):
    connect_telegram(client)
    no_baseline = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "new"})
    assert no_baseline.status_code == 409
    client.post("/api/telegram/outreach/initialize", json={"group": "discussion"})
    title, people = FAKE.groups["discussion"]
    FAKE.groups["discussion"] = (title, people + [{"telegram_id": "1009", "display_name": "New Person", "username": "",
                                                   "access_hash": "9"}])
    preview = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "new"}).json()
    assert [r["telegram_id"] for r in preview["recipients"]] == ["1009"]
    assert send(client, ["1009"], audience="new").json()["sent_count"] == 1
    again = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "new"}).json()
    assert again["recipients"] == []


def test_active_and_unmatched_audiences_follow_the_directory(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1001", "uid": "11111111"})
    active = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "active"}).json()
    unmatched = client.post("/api/telegram/outreach/preview", json={"group": "discussion", "audience": "unmatched"}).json()
    assert [r["telegram_id"] for r in active["recipients"]] == ["1001"]
    assert "1001" not in {r["telegram_id"] for r in unmatched["recipients"]}


# ── Replies ──────────────────────────────────────────────────────────────────

def reply(telegram_id, text, message_id="1", name="Ali Hassan"):
    FAKE.inbox.append({"telegram_id": telegram_id, "message_id": message_id, "display_name": name, "username": "",
                       "access_hash": "", "chat_name": name, "text": text,
                       "date": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def prepared(client):
    connect_telegram(client)
    scan(client)
    upload(client, "vantage", "ib_account_report", "v.xlsx", vantage_accounts())
    send(client, ["1001", "1002", "1003"])


def test_a_reply_with_a_known_uid_is_an_exact_match_and_approving_links_it(client):
    prepared(client)
    reply("1003", "Hi! My Vantage UID is 33333333, phone +971501234567")
    scanned = client.post("/api/telegram/reply-matches/scan", json={"days": 30}).json()
    assert scanned["new_or_updated_matches"] == 1 and scanned["prompted_recipients"] == 3
    match = client.get("/api/telegram/reply-matches").json()["candidates"][0]
    assert match["match_status"] == "exact_match" and match["uid"] == "33333333" and match["broker"] == "Vantage"
    assert client.post("/api/telegram/reply-matches/review",
                       json={"candidate_id": match["id"], "decision": "approved"}).status_code == 200
    data = client.get("/api/telegram/account-links").json()
    assert member(data, "1003")["links"][0]["uid"] == "33333333"
    row = client.get("/api/telegram/reply-directory").json()["rows"][0]
    assert row["linked"] is True and row["report_client_name"] == "Bilal Ahmed"


def test_unknown_uids_and_phone_numbers_are_not_linked(client):
    prepared(client)
    reply("1001", "Call me on 0501234567 or +971501234567", message_id="1")
    reply("1002", "UID 55555555", message_id="2", name="Sara Khan")
    client.post("/api/telegram/reply-matches/scan", json={"days": 30})
    candidates = client.get("/api/telegram/reply-matches").json()["candidates"]
    assert [c["telegram_id"] for c in candidates] == ["1002"]          # the phone-number reply isn't a UID reply
    assert candidates[0]["match_status"] == "uid_not_found"
    refused = client.post("/api/telegram/reply-matches/review", json={"candidate_id": candidates[0]["id"], "decision": "approved"})
    assert refused.status_code == 409


def test_editing_a_reply_undoes_its_link_and_sends_it_back_for_review(client):
    prepared(client)
    reply("1002", "my uid 22222222")
    client.post("/api/telegram/reply-matches/scan", json={"days": 30})
    match = client.get("/api/telegram/reply-matches").json()["candidates"][0]
    client.post("/api/telegram/reply-matches/review", json={"candidate_id": match["id"], "decision": "approved"})
    client.post("/api/telegram/reply-directory/edit",
                json={"candidate_id": match["id"], "telegram_name": "Sara K", "uid": "11111111", "broker": "Vantage"})
    row = client.get("/api/telegram/reply-directory").json()["rows"][0]
    assert row["decision"] == "pending" and row["uid"] == "11111111" and row["linked"] is False
    assert member(client.get("/api/telegram/account-links").json(), "1002")["links"] == []


def test_only_prompted_chats_unless_all_chats_is_chosen(client):
    prepared(client)
    reply("1005", "Vantage 33333333", name="Bilal Ahmed")             # never messaged
    prompted = client.post("/api/telegram/reply-matches/scan", json={"days": 30}).json()
    assert prompted["new_or_updated_matches"] == 0
    everything = client.post("/api/telegram/reply-matches/scan", json={"days": 30, "scan_mode": "all_chats"}).json()
    assert everything["new_or_updated_matches"] == 1
    match = client.get("/api/telegram/reply-matches").json()["candidates"][0]
    assert match["source"] == "open_scan"


def test_erasing_replies_removes_only_reply_links(client):
    prepared(client)
    client.post("/api/telegram/account-links/manual", json={"telegram_id": "1001", "uid": "11111111"})
    reply("1003", "33333333")
    client.post("/api/telegram/reply-matches/scan", json={"days": 30})
    match = client.get("/api/telegram/reply-matches").json()["candidates"][0]
    client.post("/api/telegram/reply-matches/review", json={"candidate_id": match["id"], "decision": "approved"})
    message = client.delete("/api/telegram/reply-directory").json()["message"]
    assert "1 reply record" in message and "1 UID link" in message
    data = client.get("/api/telegram/account-links").json()
    assert member(data, "1001")["links"] and not member(data, "1003")["links"]
