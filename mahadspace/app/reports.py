"""Broker reports: read Vantage and PU Prime files, recognise what each sheet holds, and work out activity.

Two upload sections per broker, as on the original site:
  - "ib_account_report": account (balance/equity/last trade), funds (deposits/withdrawals) and opened-account sheets
  - "rebate":            the daily or monthly rebate report
A new file replaces that broker's dataset; the old one goes to recoverable trash, and every UID it contained is
remembered in the report history ("known from report history").

Activity (the rule stated on the original site): an account is ACTIVE when it has at least $50 equity OR a trade
within the last 30 days. A member is active when any linked account is active.
"""
import csv
import io
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import db

BROKERS = {"vantage": "Vantage", "puprime": "PU Prime"}
SECTIONS = {"ib_account_report": ("accounts", "funds", "opened_accounts"), "rebate": ("rebates",)}
DATASETS = ("accounts", "funds", "opened_accounts", "rebates")
ACTIVE_EQUITY = 50.0
ACTIVE_TRADE_DAYS = 30
MAX_BYTES = 10 * 1024 * 1024

# Header aliases, compared as lower-case letters and digits only ("Rebate(USD)" → "rebateusd").
ALIASES = {
    "uid": ["userid", "uid", "clientuid", "clientid", "customerid", "customeruid", "mt4uid", "useruid"],
    "account": ["account", "accountid", "accountnumber", "accountno", "login", "loginid", "mtaccount",
                "tradingaccount", "mt4account", "mt5account"],
    "name": ["name", "clientname", "fullname", "customername", "username"],
    "balance": ["balance", "totalbalance", "availablebalance", "accountbalance"],
    "equity": ["equity", "accountequity", "totalequity", "currentequity"],
    "last_trade": ["lasttradedate", "lasttradetime", "lasttrade", "lastactivity", "lasttradingdate"],
    "last_deposit": ["lastdepositdate", "lastdeposittime", "lastdeposit", "depositdate"],
    "deposits": ["deposits", "deposit", "totaldeposits", "totaldeposit"],
    "withdrawals": ["withdraw", "withdrawals", "withdrawal", "totalwithdrawal", "totalwithdrawals"],
    "net_deposits": ["netdeposits", "netdeposit", "net"],
    "open_date": ["opendate", "opentime", "registrationdate", "registertime", "registrationtime", "accountopendate",
                  "createdate", "createtime", "openeddate", "openedtime", "accountopeningdate"],
    "rebate": ["rebateusd", "rebate", "totalrebateusd", "totalrebate", "commission", "commissionusd"],
    "date": ["date", "day", "transactiondate", "tradedate", "closedate", "closetime", "settlementdate"],
    "lots": ["totalvolume", "totallots", "lots", "volume", "volumelots"],
    "notional": ["notionalvalueusd", "notionalvalue", "notional", "notionalusd"],
    "instrument": ["instrument", "symbol", "product"],
    "account_type": ["accounttype", "type"],
    "campaign": ["campaignsource", "campaign", "source"],
}
# The column name the page reads for each canonical field (it looks columns up by these names).
CANONICAL = {"uid": "User ID", "account": "Account", "name": "Name", "balance": "Balance", "equity": "Account Equity",
             "last_trade": "Last Trade Date", "last_deposit": "Last Deposit Date", "deposits": "Deposits",
             "withdrawals": "Withdrawals", "net_deposits": "Net Deposits", "open_date": "Open Date",
             "rebate": "Rebate(USD)", "date": "Date", "lots": "Total Volume", "notional": "Notional ValueUSD",
             "instrument": "Instrument", "account_type": "Account Type", "campaign": "Campaign source"}
NUMERIC = {"balance", "equity", "deposits", "withdrawals", "net_deposits", "rebate", "lots", "notional"}
DATES = {"last_trade", "last_deposit", "open_date", "date"}


def token(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


TOKEN_FIELD = {alias: field for field, aliases in ALIASES.items() for alias in aliases}


# ── Reading files ────────────────────────────────────────────────────────────

def read_tables(filename: str, data: bytes) -> list[tuple[str, list[list]]]:
    """Every sheet of the file as (sheet name, rows of cells)."""
    if not data:
        raise HTTPException(422, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than the 10 MB upload limit.")
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension in ("xlsx", "xlsm"):
        import openpyxl
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as error:  # noqa: BLE001 - any unreadable workbook
            raise HTTPException(422, f"Could not read the Excel file ({type(error).__name__}).")
        return [(sheet.title, [list(row) for row in sheet.iter_rows(values_only=True)]) for sheet in book.worksheets]
    if extension == "csv":
        text = decode(data)
        # The delimiter used most in the first lines (a title line above the table breaks csv.Sniffer).
        sample = text[:8192]
        delimiter = max((",", ";", "\t"), key=sample.count)
        return [("CSV", [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)])]
    if extension == "json":
        try:
            parsed = json.loads(decode(data))
        except json.JSONDecodeError:
            raise HTTPException(422, "The JSON file isn't valid JSON.")
        rows = parsed.get("rows", parsed.get("data", [])) if isinstance(parsed, dict) else parsed
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise HTTPException(422, "The JSON file must be a list of rows (objects).")
        headers = list(dict.fromkeys(k for r in rows for k in r))
        return [("JSON", [headers] + [[r.get(h) for h in headers] for r in rows])]
    raise HTTPException(422, "Unsupported file type. Choose .xlsx, .csv or .json.")


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def header_row(rows: list[list]) -> int | None:
    """Reports often start with a title block: the header is the first row naming two known fields."""
    for index, row in enumerate(rows[:25]):
        fields = {TOKEN_FIELD.get(token(cell)) for cell in row} - {None}
        if len(fields) >= 2:
            return index
    return None


def classify(fields: set[str]) -> str | None:
    if "rebate" in fields:
        return "rebates"
    if fields & {"deposits", "withdrawals", "net_deposits"} and fields & {"uid", "account"}:
        return "funds"
    # Opened-account lists often show an available balance too; an opening date without equity or trading
    # activity makes it an opened-accounts sheet, not the account (activity) report.
    if "open_date" in fields and fields & {"uid", "account"} and not fields & {"equity", "last_trade"}:
        return "opened_accounts"
    if fields & {"equity", "balance"} and fields & {"uid", "account"}:
        return "accounts"
    return None


# ── Cleaning values ──────────────────────────────────────────────────────────

def clean_uid(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = re.sub(r"\s+", "", str(value))
    return re.sub(r"\.0+$", "", text)


def number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "").replace("USD", "").replace("usd", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    try:
        result = float(text.strip("()"))
    except ValueError:
        return None
    return -result if negative else result


DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y")


def iso_date(value) -> str:
    """Any date the reports use, as YYYY-MM-DD (so dates sort and compare correctly). Unreadable → ""."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and 20000 < float(value) < 80000:   # an Excel serial date
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    text = str(value).strip()
    head = re.split(r"[ T]", text, maxsplit=1)[0] if re.match(r"^\d", text) else text
    for fmt in DATE_FORMATS:
        for candidate in (text, head):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    match = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", head)
    if match:
        first, second, year = (int(part) for part in match.groups())
        year += 2000 if year < 100 else 0
        # Day first (as UAE and most broker portals write it) unless that's impossible.
        day, month = (second, first) if first <= 12 < second else (first, second)
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return ""
    return ""


def table_rows(rows: list[list], start: int) -> tuple[list[dict], dict[str, str]]:
    """Rows as dicts keyed by the file's own headers, plus which header holds each canonical field."""
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[start]]
    mapping = {}
    for header in headers:
        field = TOKEN_FIELD.get(token(header))
        if field and field not in mapping:
            mapping[field] = header
    out = []
    for raw in rows[start + 1:]:
        if raw is None or all(cell in (None, "") for cell in raw):
            continue
        out.append({header: raw[i] if i < len(raw) else None for i, header in enumerate(headers) if header})
    return out, mapping


def canonical_row(row: dict, mapping: dict, broker: str) -> dict:
    """The file's own columns, with the known fields cleaned and written under the names the page reads."""
    result = {}
    replaced = {mapping[field] for field in mapping}
    for key, value in row.items():
        if key in replaced:
            continue
        result[key] = value.isoformat() if isinstance(value, (date, datetime)) else value
    result["Broker"] = broker
    for field, header in mapping.items():
        value = row.get(header)
        if field in ("uid", "account"):
            result[CANONICAL[field]] = clean_uid(value)
        elif field in NUMERIC:
            parsed = number(value)
            result[CANONICAL[field]] = round(parsed, 2) if parsed is not None else None
        elif field in DATES:
            result[CANONICAL[field]] = iso_date(value)
        else:
            result[CANONICAL[field]] = str(value).strip() if value is not None else ""
    return result


def account_status(row: dict, today: date) -> str:
    equity = row.get("Account Equity")
    if equity is None:
        equity = row.get("Balance")     # some account sheets have only a balance column
    trade = row.get("Last Trade Date") or ""
    if equity is None and not trade:
        return "Unknown"
    if equity is not None and equity >= ACTIVE_EQUITY:
        return "Active"
    if trade:
        age = (today - date.fromisoformat(trade)).days
        if 0 <= age <= ACTIVE_TRADE_DAYS:
            return "Active"
    return "Inactive"


def parse_report(filename: str, data: bytes, broker_key: str, section: str) -> tuple[dict, int]:
    """{dataset: rows} for the sheets this section accepts, and how many rows were skipped."""
    broker = BROKERS[broker_key]
    found, skipped, wrong_section = {}, 0, set()
    for _, rows in read_tables(filename, data):
        start = header_row(rows)
        if start is None:
            continue
        records, mapping = table_rows(rows, start)
        dataset = classify(set(mapping))
        if dataset is None:
            continue
        if dataset not in SECTIONS[section]:
            wrong_section.add(dataset)
            continue
        for record in records:
            row = canonical_row(record, mapping, broker)
            has_id = row.get("User ID") or row.get("Account")
            if dataset != "rebates" and not has_id:
                skipped += 1               # an account, fund or opened-account row must say whose it is
                continue
            if dataset == "rebates" and row.get("Rebate(USD)") is None and not has_id:
                skipped += 1               # blank or note rows inside the rebate report
                continue
            found.setdefault(dataset, []).append(row)
    if not found:
        if wrong_section:
            other = "rebate" if "rebates" in wrong_section else "IB account"
            raise HTTPException(422, f"This looks like a {other} report. Upload it in the {other} section instead.")
        raise HTTPException(422, "No report table was recognised. The file needs a header row with columns such as "
                                 "User ID, Account, Equity, Balance, Deposits or Rebate.")
    return found, skipped


# ── Storing ──────────────────────────────────────────────────────────────────

def import_report(user_id: int, broker_key: str, section: str, filename: str, data: bytes) -> dict:
    datasets, skipped = parse_report(filename, data, broker_key, section)
    with db.connect() as conn:
        for dataset, rows in datasets.items():
            trash(conn, user_id, broker_key, dataset)
            conn.execute("INSERT INTO report_datasets (user_id, broker, dataset, filename, imported_at, rows_json, skipped)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (user_id, broker_key, dataset, filename, db.now(), json.dumps(rows), skipped))
            remember_history(conn, user_id, broker_key, rows)
    return {"filename": filename, "datasets": {name: len(rows) for name, rows in datasets.items()},
            "skipped_count": skipped}


def trash(conn, user_id: int, broker_key: str, dataset: str) -> bool:
    row = conn.execute("SELECT * FROM report_datasets WHERE user_id = ? AND broker = ? AND dataset = ?",
                       (user_id, broker_key, dataset)).fetchone()
    if row is None:
        return False
    conn.execute("INSERT INTO report_trash (user_id, broker, dataset, filename, imported_at, removed_at, rows_json)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (user_id, broker_key, dataset, row["filename"], row["imported_at"], db.now(), row["rows_json"]))
    conn.execute("DELETE FROM report_datasets WHERE user_id = ? AND broker = ? AND dataset = ?",
                 (user_id, broker_key, dataset))
    return True


def remove_section(user_id: int, broker_key: str, section: str) -> dict:
    with db.connect() as conn:
        removed = [dataset for dataset in SECTIONS[section] if trash(conn, user_id, broker_key, dataset)]
    label = "IB account report" if section == "ib_account_report" else "rebate report"
    if not removed:
        raise HTTPException(404, f"No {BROKERS[broker_key]} {label} data is imported.")
    return {"message": f"Removed the {BROKERS[broker_key]} {label} data.", "removed": removed}


def remember_history(conn, user_id: int, broker_key: str, rows: list[dict]):
    seen = {}
    for row in rows:
        uid = row.get("User ID") or ""
        if not uid:
            continue
        entry = seen.setdefault(uid, (set(), set()))
        if row.get("Account"):
            entry[0].add(row["Account"])
        if row.get("Name"):
            entry[1].add(row["Name"])
    stamp = db.now()
    for uid, (accounts, names) in seen.items():
        old = conn.execute("SELECT account_ids_json, names_json FROM report_history WHERE user_id = ? AND broker = ? AND uid = ?",
                           (user_id, broker_key, uid)).fetchone()
        if old:
            accounts |= set(json.loads(old["account_ids_json"]))
            names |= set(json.loads(old["names_json"]))
        conn.execute("INSERT INTO report_history (user_id, broker, uid, account_ids_json, names_json, first_seen, last_seen)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, broker, uid) DO UPDATE SET"
                     " account_ids_json = excluded.account_ids_json, names_json = excluded.names_json,"
                     " last_seen = excluded.last_seen",
                     (user_id, broker_key, uid, json.dumps(sorted(accounts)), json.dumps(sorted(names)), stamp, stamp))


# ── Reading back ─────────────────────────────────────────────────────────────

def load(conn, user_id: int) -> dict:
    """{broker_key: {dataset: {"rows", "filename", "imported_at", "skipped"}}}"""
    stored = {key: {} for key in BROKERS}
    for row in conn.execute("SELECT * FROM report_datasets WHERE user_id = ?", (user_id,)):
        stored[row["broker"]][row["dataset"]] = {"rows": json.loads(row["rows_json"]), "filename": row["filename"],
                                                 "imported_at": row["imported_at"], "skipped": row["skipped"]}
    return stored


def with_status(rows: list[dict], today: date) -> list[dict]:
    return [row | {"Calculated Status": account_status(row, today)} for row in rows]


def member_rows(accounts: list[dict], funds: list[dict], opened: list[dict], rebates: list[dict]) -> list[dict]:
    """One row per broker UID: its accounts, money and activity together."""
    members = {}

    def entry(row):
        uid = row.get("User ID") or ""
        if not uid:
            return None
        return members.setdefault((row["Broker"], uid), {
            "Broker": row["Broker"], "User ID": uid, "Name": "", "account_ids": set(), "Total Balance": 0.0,
            "Total Equity": 0.0, "Last Trade Date": "", "Last Deposit Date": "", "statuses": [],
            "Fund Rows": 0, "Opened Account Rows": 0, "Rebate Rows": 0, "Total Rebate": 0.0})

    for row in accounts:
        item = entry(row)
        if item is None:
            continue
        item["Name"] = item["Name"] or row.get("Name") or ""
        if row.get("Account"):
            item["account_ids"].add(row["Account"])
        item["Total Balance"] += row.get("Balance") or 0
        item["Total Equity"] += row.get("Account Equity") or 0
        item["Last Trade Date"] = max(item["Last Trade Date"], row.get("Last Trade Date") or "")
        item["Last Deposit Date"] = max(item["Last Deposit Date"], row.get("Last Deposit Date") or "")
        item["statuses"].append(row["Calculated Status"])
    for rows, counter in ((funds, "Fund Rows"), (opened, "Opened Account Rows"), (rebates, "Rebate Rows")):
        for row in rows:
            item = entry(row)
            if item is None:
                continue
            item[counter] += 1
            item["Name"] = item["Name"] or row.get("Name") or ""
            if counter == "Opened Account Rows" and row.get("Account"):
                item["account_ids"].add(row["Account"])
            if counter == "Rebate Rows":
                item["Total Rebate"] += row.get("Rebate(USD)") or 0
    out = []
    for item in members.values():
        statuses = item.pop("statuses")
        ids = sorted(item.pop("account_ids"), key=natural)
        status = "Active" if "Active" in statuses else "Inactive" if "Inactive" in statuses else "Unknown"
        out.append(item | {"Account Count": len(ids), "Account IDs": ", ".join(ids), "Calculated Status": status,
                           "Total Balance": round(item["Total Balance"], 2), "Total Equity": round(item["Total Equity"], 2),
                           "Total Rebate": round(item["Total Rebate"], 2)})
    return out


def natural(value: str):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(value))]


def broker_view(stored: dict, broker_key: str, today: date) -> dict:
    datasets = stored[broker_key]
    rows = {name: (datasets.get(name) or {}).get("rows", []) for name in DATASETS}
    accounts = with_status(rows["accounts"], today)
    return {"member_rows": member_rows(accounts, rows["funds"], rows["opened_accounts"], rows["rebates"]),
            "account_rows": accounts, "accounts": accounts, "funds": rows["funds"],
            "opened_accounts": rows["opened_accounts"], "rebates": rows["rebates"]}


def data(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    with db.connect() as conn:
        stored = load(conn, user_id)
    views = {key: broker_view(stored, key, today) for key in BROKERS}
    combined = {name: views["vantage"][name] + views["puprime"][name] for name in views["vantage"]}
    return {"combined": combined, **views}


def status(user_id: int) -> dict:
    with db.connect() as conn:
        stored = load(conn, user_id)
    out = {}
    for key in BROKERS:
        datasets = {}
        for name in DATASETS:
            item = stored[key].get(name)
            datasets[name] = ({"status": "manual_report", "filename": item["filename"], "imported_at": item["imported_at"],
                               "row_count": len(item["rows"]), "skipped_count": item["skipped"]}
                              if item else {"status": "not_imported"})
        account_loaded = any(datasets[name]["status"] == "manual_report" for name in SECTIONS["ib_account_report"])
        out[key] = {"ib_account_report_status": "manual_report" if account_loaded else "not_imported", "datasets": datasets}
    return out


def uid_index(conn, user_id: int, today: date | None = None) -> dict:
    """Everything the reports say about each (broker, UID), current and historical. Used for linking."""
    today = today or date.today()
    stored = load(conn, user_id)
    index = {}

    def item(broker_key, uid):
        return index.setdefault((BROKERS[broker_key], uid), {
            "broker": BROKERS[broker_key], "uid": uid, "names": set(), "account_ids": set(), "account_count": 0,
            "total_balance": 0.0, "total_equity": 0.0, "total_rebate": 0.0, "last_trade_date": "",
            "active_accounts": 0, "inactive_accounts": 0, "in_accounts": False, "in_rebates": False,
            "in_funds": False, "in_opened": False, "historical": False, "historical_account_ids": set()})

    for key in BROKERS:
        datasets = stored[key]
        for row in with_status((datasets.get("accounts") or {}).get("rows", []), today):
            if not row.get("User ID"):
                continue
            entry = item(key, row["User ID"])
            entry["in_accounts"] = True
            if row.get("Account"):
                entry["account_ids"].add(row["Account"])
            entry["names"].add(row.get("Name") or "")
            entry["account_count"] += 1
            entry["total_balance"] += row.get("Balance") or 0
            entry["total_equity"] += row.get("Account Equity") or 0
            entry["last_trade_date"] = max(entry["last_trade_date"], row.get("Last Trade Date") or "")
            if row["Calculated Status"] == "Active":
                entry["active_accounts"] += 1
            elif row["Calculated Status"] == "Inactive":
                entry["inactive_accounts"] += 1
        for dataset, flag in (("funds", "in_funds"), ("opened_accounts", "in_opened"), ("rebates", "in_rebates")):
            for row in (datasets.get(dataset) or {}).get("rows", []):
                if not row.get("User ID"):
                    continue
                entry = item(key, row["User ID"])
                entry[flag] = True
                entry["names"].add(row.get("Name") or "")
                if row.get("Account") and dataset == "opened_accounts":
                    entry["account_ids"].add(row["Account"])
                if dataset == "rebates":
                    entry["total_rebate"] += row.get("Rebate(USD)") or 0
    for row in conn.execute("SELECT * FROM report_history WHERE user_id = ?", (user_id,)):
        entry = item(row["broker"], row["uid"])
        entry["historical"] = True
        entry["historical_account_ids"] |= set(json.loads(row["account_ids_json"]))
        entry["names"] |= set(json.loads(row["names_json"]))
    for entry in index.values():
        entry["names"].discard("")
        entry["current"] = entry["in_accounts"] or entry["in_rebates"] or entry["in_funds"] or entry["in_opened"]
    return index
