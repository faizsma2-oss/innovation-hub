"""The forward journal: what the frozen rule would have done on days after its holdout.

The holdout has already been used to check the rule, so new days are the test that hasn't been spent.
Run `fetch` to bring the data up to date, then `journal`. A session is logged only once its 17:00 close
is in the data, so a row never depends on bars that weren't there yet. Columns you fill in yourself
(signal_score, simulated_size, rule_followed, actual_entry, actual_exit, notes) are kept when the journal
updates.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Costs, Lab
from .data import load_csv, resample
from .market import SESSIONS, Market, day_label
from .rules import Rule

COLUMNS = ["date", "session", "entry_time_local", "market", "setup", "signal_score", "direction", "entry", "stop",
           "target", "exit", "exit_reason", "result_R", "costs_usd", "simulated_size", "rule_followed",
           "actual_entry", "actual_exit", "notes", "source"]


def session_closed(day: int, session: str, last_bar: pd.Timestamp, bar_minutes: int = 5) -> bool:
    """True once the bar that ends at the session's close is in the data."""
    spec = SESSIONS[session]
    close = pd.Timestamp(f"{day_label(day)} {spec.close_minute // 60:02d}:{spec.close_minute % 60:02d}", tz=spec.tz)
    return last_bar + pd.Timedelta(minutes=bar_minutes) >= close.tz_convert("UTC")


def update(rule_path, data_path, out_path, since=None, spread=0.30, slippage=0.10, bar_minutes=5):
    """Adds every newly closed session since `since` to the journal. Returns (added, total, R added)."""
    record = json.loads(Path(rule_path).read_text(encoding="utf-8"))
    rule = Rule.from_dict(record["rule"])
    if since is None:
        since = (pd.Timestamp(record["data"]["holdout"][1]) + pd.Timedelta(days=1)).date().isoformat()
    bars = resample(load_csv(data_path), bar_minutes)
    market = Market(bars, bar_minutes)
    start = int(np.datetime64(since, "D").astype(np.int64))
    if start > int(market.days[-1]):
        raise ValueError(f"the data ends {day_label(int(market.days[-1]))}, so there are no days after {since} yet. "
                         f"Run fetch first.")
    trades = Lab(market, (start, int(market.days[-1])), Costs(spread, slippage)).trades(rule)
    last_bar = bars.index.max()
    delay = dict(rule.params).get("delay_minutes", 0)
    rows = []
    for session, day, direction, entry, risk, exit_price, reason, r in zip(
            trades["session"], trades["day"], trades["direction"], trades["entry"], trades["risk"],
            trades["exit"], trades["reason"], trades["r"]):
        session, day = str(session), int(day)
        if not session_closed(day, session, last_bar, bar_minutes):
            continue
        sign = 1 if direction > 0 else -1
        clock = SESSIONS[session].open_minute + delay
        rows.append({
            "date": day_label(day), "session": session, "entry_time_local": f"{clock // 60:02d}:{clock % 60:02d}",
            "market": "XAUUSD", "setup": rule.short(), "signal_score": "", "direction": "buy" if sign > 0 else "sell",
            "entry": round(float(entry), 2), "stop": round(float(entry - sign * risk), 2),
            "target": round(float(entry + sign * rule.target_r * risk), 2), "exit": round(float(exit_price), 2),
            "exit_reason": str(reason), "result_R": round(float(r), 3),
            "costs_usd": round(spread + (slippage if reason == "stop" else 0.0), 2), "simulated_size": "",
            "rule_followed": "", "actual_entry": "", "actual_exit": "", "notes": "",
            "source": f"{Path(rule_path).name}; data to {last_bar:%Y-%m-%d %H:%M} UTC",
        })
    new = pd.DataFrame(rows, columns=COLUMNS).astype(str)
    out = Path(out_path)
    if out.exists():
        old = pd.read_csv(out, dtype=str, keep_default_na=False).reindex(columns=COLUMNS, fill_value="")
        known = set(zip(old["date"], old["session"]))
        fresh = new[np.array([key not in known for key in zip(new["date"], new["session"])], dtype=bool)]
        combined = pd.concat([old, fresh], ignore_index=True)
    else:
        fresh, combined = new, new
    combined = combined.sort_values(["date", "session"]).reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    added_r = float(pd.to_numeric(fresh["result_R"]).sum()) if len(fresh) else 0.0
    return len(fresh), len(combined), added_r
