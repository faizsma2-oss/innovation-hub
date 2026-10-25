"""Test a rule on the session grids. The bots never compute their own numbers: every figure
they quote comes from here.

Fills are deliberately conservative:
  - breakouts fill at the trigger level, or at the bar's open if price gapped past it, plus slippage
  - every other setup enters at the close of the signal bar
  - a bar that touches both the stop and the target counts as a stop
  - a stop or target that price gaps through fills at that bar's open
  - on a breakout's entry bar only the stop can be hit (the bar's path after the fill is unknown)
  - every trade pays the spread; stop exits also pay slippage
Results are in R: profit or loss divided by the amount risked (entry to stop). A +2R trade made
twice what it risked; a stopped trade loses a little over 1R once costs are paid.
"""
from dataclasses import dataclass

import numpy as np

from .market import Market, Panel, day_label
from .rules import Rule

FOLDS = 4  # the period is cut into this many equal stretches to see whether results are steady


@dataclass(frozen=True)
class Costs:
    spread: float = 0.30    # USD per ounce, paid once per trade
    slippage: float = 0.10  # USD per ounce, added to breakout entries and stop exits


# ── Entries ──────────────────────────────────────────────────────────────────

def signals(rule: Rule, market: Market, panel: Panel):
    """Where each session-day could go long or short, at what price, and whether the fill is
    intrabar (a stop order) or at the bar's close."""
    p = dict(rule.params)
    bar = market.bar_minutes
    O, H, L, C = panel.open, panel.high, panel.low, panel.close
    cols = np.arange(panel.width)
    datr = panel.datr[:, None]
    end = p.get("entry_window_minutes", 0) // bar
    long_price = short_price = C
    intrabar = False

    if rule.setup in ("opening_range_breakout", "pre_session_breakout"):
        if rule.setup == "opening_range_breakout":
            k = max(1, p["range_minutes"] // bar)
            top, bottom = np.fmax.reduce(H[:, :k], axis=1), np.fmin.reduce(L[:, :k], axis=1)
        else:
            k = 0
            top, bottom = panel.pre_high, panel.pre_low
        up = top[:, None] + p["buffer_atr"] * datr
        down = bottom[:, None] - p["buffer_atr"] * datr
        window = (cols >= k) & (cols < end)
        long_ok, short_ok = window & (H >= up), window & (L <= down)
        long_price, short_price = np.maximum(up, O), np.minimum(down, O)
        intrabar = True
    elif rule.setup == "pre_session_sweep":
        window = cols < end
        highest, lowest = np.fmax.accumulate(H, axis=1), np.fmin.accumulate(L, axis=1)
        top, bottom = panel.pre_high[:, None], panel.pre_low[:, None]
        short_ok = window & (highest >= top + p["sweep_atr"] * datr) & (C < top)
        long_ok = window & (lowest <= bottom - p["sweep_atr"] * datr) & (C > bottom)
    elif rule.setup == "trend_pullback":
        window = cols < end
        fast = market.indicator(panel, "ema", p["ema_fast"])
        slow = market.indicator(panel, "ema", p["ema_slow"])
        long_ok = window & (fast > slow) & (L <= fast) & (C > fast) & (C > O)
        short_ok = window & (fast < slow) & (H >= fast) & (C < fast) & (C < O)
    elif rule.setup == "session_momentum":
        at = min(max(p["delay_minutes"] // bar - 1, 0), panel.width - 1)
        move = (C[:, at] - panel.pre_open)[:, None]
        when = cols == at
        long_ok = when & (move >= p["momentum_atr"] * datr)
        short_ok = when & (move <= -p["momentum_atr"] * datr)
    elif rule.setup == "band_reversion":
        window = cols < end
        mid = market.indicator(panel, "band_mid", p["band_period"])
        sd = market.indicator(panel, "band_sd", p["band_period"])
        rsi = market.indicator(panel, "rsi", 14)
        long_ok = window & (C < mid - p["band_k"] * sd) & (rsi < p["rsi_level"])
        short_ok = window & (C > mid + p["band_k"] * sd) & (rsi > 100 - p["rsi_level"])
    elif rule.setup == "session_open_long":  # the referee's naive baseline, not offered to bots
        long_ok = np.broadcast_to(cols == 0, C.shape) & ~np.isnan(O)
        short_ok = np.zeros_like(long_ok)
        long_price = O
        intrabar = True
    else:
        raise ValueError(f"unknown setup {rule.setup}")

    if rule.trend_ema:
        # A stop order is placed before its bar closes, so it is filtered on the previous close.
        if intrabar:
            close, ema = market.indicator(panel, "close_prev"), market.indicator(panel, "ema_prev", rule.trend_ema)
        else:
            close, ema = C, market.indicator(panel, "ema", rule.trend_ema)
        long_ok, short_ok = long_ok & (close > ema), short_ok & (close < ema)
    if rule.vol_filter:
        lively = (panel.datr_rel >= rule.vol_filter)[:, None]
        long_ok, short_ok = long_ok & lively, short_ok & lively
    if rule.direction == "short":
        long_ok = np.zeros_like(long_ok)
    if rule.direction == "long":
        short_ok = np.zeros_like(short_ok)
    before_close = cols < panel.last_col[:, None]  # never open a trade on the session's last bar
    return (long_ok & before_close, short_ok & before_close,
            np.broadcast_to(long_price, C.shape), np.broadcast_to(short_price, C.shape), intrabar)


def first_true(mask: np.ndarray) -> np.ndarray:
    """Column of the first True in each row, or the row width if there is none."""
    return np.where(mask.any(axis=1), mask.argmax(axis=1), mask.shape[1])


# ── Exits ────────────────────────────────────────────────────────────────────

def exits(O, H, L, C, last_col, entry_col, direction, entry, risk, target_r, intrabar: bool, costs: Costs):
    """Simulate each trade to its stop, its target or the session close. All arguments are per
    trade: O/H/L/C are (T, W) rows of the trade's session, the rest (T,). Returns (exit, reason, r)."""
    T, W = H.shape
    rows = np.arange(T)
    cols = np.arange(W)
    up = direction[:, None] > 0
    stop = entry - direction * risk
    target = entry + direction * target_r * risk
    after = cols > entry_col[:, None]
    from_entry = (cols >= entry_col[:, None]) if intrabar else after
    hit_stop = from_entry & np.where(up, L <= stop[:, None], H >= stop[:, None])
    hit_target = after & np.where(up, H >= target[:, None], L <= target[:, None])
    stop_col, target_col = first_true(hit_stop), first_true(hit_target)

    stopped = (stop_col < W) & (stop_col <= target_col)
    reached = ~stopped & (target_col < W)
    stop_open = O[rows, np.minimum(stop_col, W - 1)]
    target_open = O[rows, np.minimum(target_col, W - 1)]
    gapped = stop_col > entry_col
    stop_fill = np.where(gapped, np.where(direction > 0, np.minimum(stop, stop_open), np.maximum(stop, stop_open)), stop)
    target_fill = np.where(direction > 0, np.maximum(target, target_open), np.minimum(target, target_open))
    close_fill = C[rows, last_col]

    exit_ = np.where(stopped, stop_fill - direction * costs.slippage, np.where(reached, target_fill, close_fill))
    reason = np.where(stopped, "stop", np.where(reached, "target", "close"))
    r = (direction * (exit_ - entry) - costs.spread) / risk
    return exit_, reason, r


# ── A whole backtest ─────────────────────────────────────────────────────────

def trades(rule: Rule, market: Market, period: tuple[int, int], costs: Costs) -> dict:
    """Every trade the rule takes in the period (inclusive day numbers), oldest first."""
    parts = []
    for order, name in enumerate(rule.sessions):
        panel = market.panels[name]
        long_ok, short_ok, long_price, short_price, intrabar = signals(rule, market, panel)
        in_period = (panel.days >= period[0]) & (panel.days <= period[1])
        first_long, first_short = first_true(long_ok), first_true(short_ok)
        take = in_period & (first_long != first_short)  # equal means no signal, or both in one bar: skip
        rows = np.flatnonzero(take)
        if not len(rows):
            continue
        is_long = first_long[rows] < first_short[rows]
        col = np.where(is_long, first_long[rows], first_short[rows])
        direction = np.where(is_long, 1.0, -1.0)
        price = np.where(is_long, long_price[rows, col], short_price[rows, col])
        entry = price + direction * (costs.slippage if intrabar else 0.0)
        risk = rule.stop_atr * panel.datr[rows]
        exit_, reason, r = exits(panel.open[rows], panel.high[rows], panel.low[rows], panel.close[rows],
                                 panel.last_col[rows], col, direction, entry, risk, rule.target_r, intrabar, costs)
        parts.append({"day": panel.days[rows], "order": np.full(len(rows), order), "session": np.full(len(rows), name),
                      "direction": direction, "entry": entry, "exit": exit_, "risk": risk, "reason": reason, "r": r})
    if not parts:
        return {key: np.array([]) for key in ("day", "order", "session", "direction", "entry", "exit", "risk", "reason", "r")}
    merged = {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
    order = np.lexsort((merged["order"], merged["day"]))
    return {key: values[order] for key, values in merged.items()}


def metrics(result: dict, period: tuple[int, int], trading_days: int) -> dict:
    """The numbers the council argues about. Rounded, so they read the same everywhere."""
    r = result["r"].astype(float)
    n = len(r)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0, "profit_factor": 0.0,
                "max_drawdown_r": 0.0, "t_stat": 0.0, "sharpe": 0.0, "worst_streak": 0, "folds_positive": 0.0,
                "fold_r": [0.0] * FOLDS, "sessions": {}, "years": {}, "from": day_label(period[0]), "to": day_label(period[1])}
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    sd = r.std(ddof=1) if n > 1 else 0.0
    # Daily R for a Sharpe ratio, with zero on trading days without a trade.
    days, day_r = np.unique(result["day"], return_inverse=True)
    per_day = np.bincount(day_r, weights=r)
    daily = np.concatenate([per_day, np.zeros(max(trading_days - len(days), 0))])
    edges = np.linspace(period[0], period[1] + 1, FOLDS + 1)
    fold = np.clip(np.searchsorted(edges, result["day"], side="right") - 1, 0, FOLDS - 1)
    fold_r = np.bincount(fold, weights=r, minlength=FOLDS)
    streak = worst = 0
    for value in r:
        streak = streak + 1 if value < 0 else 0
        worst = max(worst, streak)
    years = {}
    for year, value in zip(np.array([day_label(d)[:4] for d in result["day"]]), r):
        entry = years.setdefault(year, {"trades": 0, "total_r": 0.0})
        entry["trades"] += 1
        entry["total_r"] += value
    sessions = {}
    for name in dict.fromkeys(str(s) for s in result["session"]):
        mine = r[result["session"] == name]
        win, loss = mine[mine > 0].sum(), -mine[mine < 0].sum()
        sessions[name] = {"trades": int(len(mine)), "win_rate": round(float((mine > 0).mean()), 3),
                          "avg_r": round(float(mine.mean()), 3), "total_r": round(float(mine.sum()), 2),
                          "profit_factor": round(float(min(win / loss, 99.0)) if loss else 99.0, 3)}
    return {
        "trades": n,
        "win_rate": round(float((r > 0).mean()), 3),
        "avg_r": round(float(r.mean()), 3),
        "total_r": round(float(r.sum()), 2),
        "profit_factor": round(float(min(wins / losses, 99.0)) if losses else 99.0, 3),
        "max_drawdown_r": round(float((peak - equity).max()), 2),
        "t_stat": round(float(r.mean() / (sd / np.sqrt(n))) if sd > 0 else 0.0, 2),
        "sharpe": round(float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0, 2),
        "worst_streak": int(worst),
        "folds_positive": round(float((fold_r > 0).mean()), 2),
        "fold_r": [round(float(value), 1) for value in fold_r],
        "sessions": sessions,
        "years": {year: {"trades": v["trades"], "total_r": round(v["total_r"], 1)} for year, v in sorted(years.items())},
        "from": day_label(period[0]),
        "to": day_label(period[1]),
    }


class Lab:
    """One stretch of history and a cache of every rule tested on it. The bots are only ever given
    the training Lab; the holdout Lab stays with the referee until the vote is over."""

    def __init__(self, market: Market, period: tuple[int, int], costs: Costs = Costs()):
        self.market = market
        self.period = period
        self.costs = costs
        self.trading_days = int(((market.days >= period[0]) & (market.days <= period[1])).sum())
        self._results: dict = {}

    @property
    def tested(self) -> int:
        """How many different rules were tried here: the more, the likelier a lucky winner."""
        return sum(1 for rule in self._results if rule.setup != "session_open_long")

    def test(self, rule: Rule) -> dict:
        if rule not in self._results:
            self._results[rule] = metrics(trades(rule, self.market, self.period, self.costs), self.period, self.trading_days)
        return self._results[rule]

    def baseline(self, rule: Rule) -> dict:
        """Buy every session open with the same stop, target and sessions: what the trend alone gives."""
        naive = Rule(setup="session_open_long", params=(), sessions=rule.sessions,
                     stop_atr=rule.stop_atr, target_r=rule.target_r)
        return self.test(naive)

    def trades(self, rule: Rule) -> dict:
        return trades(rule, self.market, self.period, self.costs)
