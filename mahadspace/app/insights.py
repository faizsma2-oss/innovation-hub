"""Rebate Insights: totals, trend, concentration and breakdowns from the imported rebate reports."""
import re
from collections import defaultdict

from . import db, reports

CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SGD", "HKD", "CNH", "ZAR", "TRY", "MXN",
              "NOK", "SEK", "DKK", "PLN", "HUF", "CZK", "AED", "SAR", "INR", "THB"}
CLASS_PATTERNS = [
    ("Metals", r"XAU|XAG|XPT|XPD|GOLD|SILVER"),
    ("Crypto", r"BTC|ETH|LTC|XRP|SOL|DOGE|ADA|BNB|CRYPTO"),
    ("Energy", r"OIL|WTI|BRENT|XTI|XBR|USO|UKO|NGAS|NATGAS|\bNG\b"),
    ("Indices", r"US30|US100|US500|NAS|SPX|SP500|USTEC|DJ30|DAX|GER|UK100|FTSE|JPN|JP225|NIKKEI|HK50|AUS200|FRA40|EU50|STOXX|CHINA50|VIX"),
]


def asset_class(row: dict) -> str:
    for key in ("Asset Class", "Product Type", "Category"):
        if row.get(key):
            return str(row[key]).strip()
    symbol = re.sub(r"[^A-Z0-9]", "", str(row.get("Instrument") or "").upper())
    if not symbol:
        return "Unknown"
    for name, pattern in CLASS_PATTERNS:
        if re.search(pattern, symbol):
            return name
    if len(symbol) >= 6 and symbol[:3] in CURRENCIES and symbol[3:6] in CURRENCIES:
        return "Forex"
    return "Other"


def is_summary_row(row: dict) -> bool:
    """A totals line inside the report: no UID and no account, and a label like "Total"."""
    if row.get("User ID") or row.get("Account"):
        return False
    label = " ".join(str(value) for key, value in row.items() if isinstance(value, str) and key not in ("Broker",))
    return bool(re.search(r"\b(sub)?total\b", label, re.IGNORECASE))


def breakdown(rows: list[dict], key, label: str, total: float) -> list[dict]:
    groups = defaultdict(lambda: {"rebate": 0.0, "lots": 0.0, "notional": 0.0, "members": set()})
    for row in rows:
        name = key(row) or "Unknown"
        group = groups[name]
        group["rebate"] += row.get("Rebate(USD)") or 0
        group["lots"] += row.get("Total Volume") or 0
        group["notional"] += row.get("Notional ValueUSD") or 0
        if row.get("User ID"):
            group["members"].add((row["Broker"], row["User ID"]))
    out = [{label: name, "Total Rebate": round(g["rebate"], 2),
            "Share %": round(g["rebate"] / total * 100, 2) if total else 0.0,
            "Total Lots": round(g["lots"], 2), "Notional Value": round(g["notional"], 2), "Members": len(g["members"])}
           for name, g in groups.items()]
    return sorted(out, key=lambda r: r["Total Rebate"], reverse=True)


def view(rows: list[dict]) -> dict:
    summary_rows = [row for row in rows if is_summary_row(row)]
    detail = [row for row in rows if not is_summary_row(row)]
    total = sum(row.get("Rebate(USD)") or 0 for row in detail)
    notional = sum(row.get("Notional ValueUSD") or 0 for row in detail)
    lots = sum(row.get("Total Volume") or 0 for row in detail)

    daily = defaultdict(lambda: {"Total Rebate": 0.0, "Total Lots": 0.0, "Notional Value": 0.0})
    for row in detail:
        if row.get("Date"):
            day = daily[row["Date"]]
            day["Total Rebate"] += row.get("Rebate(USD)") or 0
            day["Total Lots"] += row.get("Total Volume") or 0
            day["Notional Value"] += row.get("Notional ValueUSD") or 0
    daily_rows = [{"Date": day, **{k: round(v, 2) for k, v in values.items()}} for day, values in sorted(daily.items())]

    members = defaultdict(lambda: {"Name": "", "rebate": 0.0, "lots": 0.0, "notional": 0.0, "accounts": set(), "rows": 0})
    for row in detail:
        if not row.get("User ID"):
            continue
        member = members[(row["Broker"], row["User ID"])]
        member["Name"] = member["Name"] or row.get("Name") or ""
        member["rebate"] += row.get("Rebate(USD)") or 0
        member["lots"] += row.get("Total Volume") or 0
        member["notional"] += row.get("Notional ValueUSD") or 0
        member["rows"] += 1
        if row.get("Account"):
            member["accounts"].add(row["Account"])
    member_rows = sorted(({
        "Name": m["Name"], "User ID": uid, "Broker": broker, "Total Rebate": round(m["rebate"], 2),
        "Share %": round(m["rebate"] / total * 100, 2) if total else 0.0, "Total Lots": round(m["lots"], 2),
        "Notional Value": round(m["notional"], 2), "Accounts": len(m["accounts"]), "Transactions": m["rows"]}
        for (broker, uid), m in members.items()), key=lambda r: r["Total Rebate"], reverse=True)
    accounts = {(row["Broker"], row["Account"]) for row in detail if row.get("Account")}
    top_five = sum(r["Total Rebate"] for r in member_rows[:5])
    dates = [row["Date"] for row in daily_rows]
    peak = max(daily_rows, key=lambda r: r["Total Rebate"]) if daily_rows else None
    summary_total = sum(row.get("Rebate(USD)") or 0 for row in summary_rows)
    with_campaign = sum(row.get("Rebate(USD)") or 0 for row in detail if row.get("Campaign source"))

    return {
        "summary": {
            "total_rebate": round(total, 2), "notional_value": round(notional, 2), "total_lots": round(lots, 2),
            "rebate_per_million": round(total / notional * 1_000_000, 2) if notional else 0.0,
            "trading_days": len(dates), "member_count": len(member_rows), "account_count": len(accounts),
            "average_rebate_per_member": round(total / len(member_rows), 2) if member_rows else 0.0,
            "transaction_rows": len(detail),
            "top_five_share": round(top_five / total * 100, 2) if total else 0.0,
            "peak_day": peak, "date_start": dates[0] if dates else None, "date_end": dates[-1] if dates else None,
        },
        "daily": daily_rows,
        "members": member_rows,
        "asset_classes": breakdown(detail, asset_class, "Asset Class", total),
        "instruments": breakdown(detail, lambda r: r.get("Instrument"), "Instrument", total),
        "account_types": breakdown(detail, lambda r: r.get("Account Type"), "Account Type", total),
        "campaigns": breakdown(detail, lambda r: r.get("Campaign source"), "Campaign", total),
        "data_quality": {
            # Only meaningful when the report has its own totals line: does it agree with the rows?
            "summary_difference": round(summary_total - total, 2) if summary_rows else 0.0,
            "campaign_attribution_pct": round(with_campaign / total * 100, 2) if total else 0.0,
            "missing_uid_rows": sum(1 for row in detail if not row.get("User ID")),
            "missing_instrument_rows": sum(1 for row in detail if not row.get("Instrument")),
        },
    }


def rebate_insights(user_id: int) -> dict:
    with db.connect() as conn:
        stored = reports.load(conn, user_id)
    brokers, all_rows = {}, []
    for key in reports.BROKERS:
        dataset = stored[key].get("rebates") or {}
        rows = dataset.get("rows", [])
        all_rows += rows
        brokers[key] = view(rows) | {"source": {"filename": dataset.get("filename"),
                                                "imported_at": dataset.get("imported_at")} if dataset else None}
    return {"combined": view(all_rows), "brokers": brokers}
