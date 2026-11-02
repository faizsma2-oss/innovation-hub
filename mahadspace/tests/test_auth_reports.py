"""Accounts, report imports, activity and rebate insights."""
from conftest import TODAY, dmy, upload, vantage_accounts, xlsx


# ── Accounts ─────────────────────────────────────────────────────────────────

def test_first_account_is_the_owner_and_later_ones_need_verification(anon):
    first = anon.post("/api/auth/register", json={"display_name": "Owner", "email": "Owner@Example.com",
                                                  "password": "correct horse"}).json()
    assert first["verified"] is True
    anon.post("/api/auth/register", json={"display_name": "Guest", "email": "guest@example.com", "password": "guest pass"})
    blocked = anon.post("/api/auth/login", json={"email": "guest@example.com", "password": "guest pass"})
    assert blocked.status_code == 403 and "verified" in blocked.json()["detail"]
    assert anon.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong"}).status_code == 401
    assert anon.post("/api/auth/register", json={"display_name": "X", "email": "owner@example.com",
                                                 "password": "another pass"}).status_code == 409


def test_session_cookie_signs_in_and_out(client):
    assert client.get("/api/auth/me").json()["email"] == "owner@example.com"
    client.post("/api/auth/logout", json={})
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/reports/data").status_code == 401


# ── IB account reports ───────────────────────────────────────────────────────

def test_account_report_with_a_title_block_and_day_first_dates(client):
    result = upload(client, "vantage", "ib_account_report", "vantage.xlsx", vantage_accounts()).json()
    assert result["datasets"] == {"accounts": 4} and result["skipped_count"] == 1
    status = client.get("/api/reports/status").json()["vantage"]
    assert status["ib_account_report_status"] == "manual_report"
    assert status["datasets"]["accounts"]["status"] == "manual_report"

    data = client.get("/api/reports/data").json()
    accounts = {row["Account"]: row for row in data["vantage"]["account_rows"]}
    assert accounts["800001"]["Last Trade Date"] == (TODAY.fromordinal(TODAY.toordinal() - 2)).isoformat()
    assert accounts["800001"]["Calculated Status"] == "Active"        # $1,150 equity
    assert accounts["800002"]["Calculated Status"] == "Active"        # traded 5 days ago
    assert accounts["800003"]["Calculated Status"] == "Inactive"      # $12 equity, 60 days since a trade
    members = {row["User ID"]: row for row in data["combined"]["member_rows"]}
    assert members["33333333"]["Account Count"] == 2 and members["33333333"]["Calculated Status"] == "Inactive"
    assert members["11111111"]["Broker"] == "Vantage"


def test_exactly_50_equity_is_active_and_a_trade_31_days_ago_is_not(client):
    report = xlsx(("Accounts", [["UID", "Login", "Equity", "Last Trade Date"],
                                ["1", "10", 50, dmy(100)], ["2", "20", 49.99, dmy(30)], ["3", "30", 49.99, dmy(31)]]))
    upload(client, "puprime", "ib_account_report", "pu.xlsx", report)
    status = {r["User ID"]: r["Calculated Status"] for r in client.get("/api/reports/data").json()["puprime"]["account_rows"]}
    assert status == {"1": "Active", "2": "Active", "3": "Inactive"}


def test_a_report_in_the_wrong_section_is_refused_with_a_clear_message(client):
    rebate = "User ID,Rebate(USD),Date\n1,2.5,2026-08-01\n".encode()
    response = upload(client, "vantage", "ib_account_report", "rebate.csv", rebate)
    assert response.status_code == 422 and "rebate section" in response.json()["detail"]
    response = upload(client, "vantage", "rebate", "accounts.xlsx", vantage_accounts())
    assert response.status_code == 422 and "IB account section" in response.json()["detail"]


def test_unrecognised_and_unsupported_files_are_refused(client):
    assert upload(client, "vantage", "ib_account_report", "notes.csv", b"hello,world\n1,2\n").status_code == 422
    assert upload(client, "vantage", "rebate", "rebates.json", b"[]").status_code == 422      # rebate takes xlsx/csv only
    assert upload(client, "vantage", "ib_account_report", "empty.csv", b"").status_code == 422


def test_a_new_report_replaces_the_old_one_but_history_is_kept(client):
    upload(client, "vantage", "ib_account_report", "v1.xlsx", vantage_accounts())
    newer = xlsx(("Accounts", [["User ID", "Account", "Name", "Equity"], ["11111111", "800001", "Ali Hassan", 900]]))
    upload(client, "vantage", "ib_account_report", "v2.xlsx", newer)
    uids = {r["User ID"] for r in client.get("/api/reports/data").json()["vantage"]["member_rows"]}
    assert uids == {"11111111"}
    removed = client.delete("/api/reports/vantage?section=ib_account_report").json()
    assert "Removed" in removed["message"]
    assert client.get("/api/reports/data").json()["vantage"]["member_rows"] == []
    assert client.delete("/api/reports/vantage?section=ib_account_report").status_code == 404


def test_funds_and_opened_accounts_sheets_in_one_workbook(client):
    report = xlsx(("Funds", [["User ID", "Account", "Deposits", "Withdraw", "Net Deposits"], ["11111111", "800001", "1,000", "(200)", 800]]),
                  ("Opened", [["User ID", "Account", "Open Date", "Available Balance"], ["44444444", "800009", "2026-08-02", 5]]))
    result = upload(client, "vantage", "ib_account_report", "mixed.xlsx", report).json()
    assert result["datasets"] == {"funds": 1, "opened_accounts": 1}
    funds = client.get("/api/reports/data").json()["vantage"]["funds"][0]
    assert funds["Deposits"] == 1000 and funds["Withdrawals"] == -200


# ── Rebates ──────────────────────────────────────────────────────────────────

REBATES = (
    "Vantage Rebate Report\n"
    "\n"
    "Date,User ID,Account,Name,Instrument,Total Volume,Notional ValueUSD,Rebate(USD),Account Type,Campaign source\n"
    "01/08/2026,11111111,800001,Ali Hassan,XAUUSD,2,400000,10,Standard,Spring\n"
    "01/08/2026,22222222,800002,Sara Khan,EURUSD,1,100000,4,Raw,\n"
    "02/08/2026,11111111,800001,Ali Hassan,US30,1,90000,6,Standard,Spring\n"
    ",,,Total,,4,590000,21,,\n"
)


def test_rebate_insights_totals_trend_and_quality(client):
    result = upload(client, "vantage", "rebate", "rebates.csv", REBATES.encode()).json()
    assert result["datasets"] == {"rebates": 4}
    data = client.get("/api/reports/rebate-insights").json()
    summary = data["brokers"]["vantage"]["summary"]
    assert summary["total_rebate"] == 20 and summary["transaction_rows"] == 3       # the totals line isn't a transaction
    assert summary["trading_days"] == 2 and summary["date_start"] == "2026-08-01"
    assert summary["peak_day"] == {"Date": "2026-08-01", "Total Rebate": 14.0, "Total Lots": 3.0, "Notional Value": 500000.0}
    assert summary["rebate_per_million"] == round(20 / 590000 * 1e6, 2)
    assert summary["member_count"] == 2 and summary["top_five_share"] == 100.0
    quality = data["brokers"]["vantage"]["data_quality"]
    assert quality["summary_difference"] == 1.0          # the report's own total says 21, the rows add up to 20
    assert quality["campaign_attribution_pct"] == 80.0
    classes = {row["Asset Class"]: row["Total Rebate"] for row in data["combined"]["asset_classes"]}
    assert classes == {"Metals": 10, "Forex": 4, "Indices": 6}
    assert data["brokers"]["puprime"]["summary"]["total_rebate"] == 0 and data["brokers"]["puprime"]["source"] is None


def test_report_template_downloads(anon):
    response = anon.get("/api/reports/template.csv")
    assert response.status_code == 200 and response.text.startswith("User ID,Account")
