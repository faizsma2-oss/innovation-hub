"""The small rule language the bots share, so every idea is tested the same way.

A rule is one entry setup, applied to the London and New York sessions, with a stop and a target
measured in daily ATR, and two optional filters. Every rule is intraday: at most one trade per
session per day, and any open trade is closed at the session's close.

Rules are plain data. Bots (scripted or Claude) can only describe a rule in this language, and the
backtester is the only thing that turns a rule into numbers.
"""
from dataclasses import dataclass

from .market import SESSIONS


class RuleError(ValueError):
    """A rule that can't be tested as written."""


# name: (lowest, highest, default). Minutes are rounded down to whole bars when testing.
SETUPS = {
    "opening_range_breakout": {
        "label": "Opening-range breakout",
        "summary": "Mark the high and low of the session's first minutes, then trade a break of either side.",
        "params": {"range_minutes": (5, 240, 30), "buffer_atr": (0.0, 0.5, 0.05), "entry_window_minutes": (30, 480, 240)},
    },
    "pre_session_breakout": {
        "label": "Pre-session range breakout",
        "summary": "Trade a break of the range built before the session opened "
                   "(Asia before London, the London morning before New York).",
        "params": {"buffer_atr": (0.0, 0.5, 0.05), "entry_window_minutes": (30, 480, 240)},
    },
    "pre_session_sweep": {
        "label": "Pre-session liquidity sweep",
        "summary": "When price runs past the pre-session high or low and then closes back inside the range, "
                   "trade the reversal.",
        "params": {"sweep_atr": (0.0, 0.5, 0.05), "entry_window_minutes": (30, 480, 240)},
    },
    "trend_pullback": {
        "label": "Trend pullback",
        "summary": "With the fast EMA above the slow EMA, buy a bar that dips to the fast EMA and closes back "
                   "above it as a green bar (the mirror image for shorts).",
        "params": {"ema_fast": (5, 100, 20), "ema_slow": (20, 400, 50), "entry_window_minutes": (30, 540, 300)},
    },
    "session_momentum": {
        "label": "Session momentum",
        "summary": "A set time after the open, if price has travelled far since the pre-session began, follow the move.",
        "params": {"delay_minutes": (5, 240, 30), "momentum_atr": (0.1, 2.0, 0.4)},
    },
    "band_reversion": {
        "label": "Band reversion",
        "summary": "Fade a close outside a Bollinger band when the 14-bar RSI is stretched.",
        "params": {"band_period": (10, 100, 20), "band_k": (1.5, 4.0, 2.0), "rsi_level": (5.0, 45.0, 25.0),
                   "entry_window_minutes": (30, 540, 300)},
    },
}
COMMON = {"stop_atr": (0.05, 2.0, 0.25), "target_r": (0.5, 6.0, 1.5), "trend_ema": (0, 2000, 0), "vol_filter": (0.0, 2.0, 0.0)}
INTEGERS = {"range_minutes", "entry_window_minutes", "delay_minutes", "ema_fast", "ema_slow", "band_period", "trend_ema"}
DIRECTIONS = ("both", "long", "short")
BOTH_SESSIONS = ("london", "new_york")


@dataclass(frozen=True)
class Rule:
    setup: str
    params: tuple                 # sorted (name, value) pairs, so a rule can be a dictionary key
    sessions: tuple = BOTH_SESSIONS
    direction: str = "both"
    stop_atr: float = 0.25        # stop distance from entry, in daily ATR
    target_r: float = 1.5         # target distance, as a multiple of the stop distance
    trend_ema: int = 0            # 0 = off; else only buy above / sell below this EMA (in bars)
    vol_filter: float = 0.0       # 0 = off; else skip days whose ATR is below this share of its median

    # ── Making and checking rules ────────────────────────────────────────────

    @classmethod
    def make(cls, setup: str, sessions=BOTH_SESSIONS, direction: str = "both", **values) -> "Rule":
        if setup not in SETUPS:
            raise RuleError(f"unknown setup {setup!r}")
        specs = SETUPS[setup]["params"]
        unknown = set(values) - set(specs) - set(COMMON)
        if unknown:
            raise RuleError(f"{setup} has no parameter {', '.join(sorted(unknown))}")
        requested = [sessions] if isinstance(sessions, str) else list(sessions)
        if set(requested) - set(BOTH_SESSIONS) or not requested:
            raise RuleError("sessions must be london and/or new_york")
        sessions = tuple(name for name in BOTH_SESSIONS if name in requested)
        if direction not in DIRECTIONS:
            raise RuleError(f"direction must be one of {', '.join(DIRECTIONS)}")
        params = {name: _checked(name, values.get(name, spec[2]), spec) for name, spec in specs.items()}
        common = {name: _checked(name, values.get(name, spec[2]), spec) for name, spec in COMMON.items()}
        if setup == "trend_pullback" and params["ema_fast"] >= params["ema_slow"]:
            raise RuleError("ema_fast must be shorter than ema_slow")
        if setup == "opening_range_breakout" and params["entry_window_minutes"] <= params["range_minutes"]:
            raise RuleError("entry_window_minutes must be longer than range_minutes")
        return cls(setup=setup, params=tuple(sorted(params.items())), sessions=sessions, direction=direction, **common)

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        if not isinstance(data, dict):
            raise RuleError("a rule must be an object")
        values = dict(data.get("params") or {})
        for name in COMMON:
            if name in data:
                values[name] = data[name]
        return cls.make(data.get("setup"), sessions=data.get("sessions") or BOTH_SESSIONS,
                        direction=data.get("direction", "both"), **values)

    def to_dict(self) -> dict:
        return {"setup": self.setup, "params": dict(self.params), "sessions": list(self.sessions),
                "direction": self.direction, "stop_atr": self.stop_atr, "target_r": self.target_r,
                "trend_ema": self.trend_ema, "vol_filter": self.vol_filter}

    def value(self, name: str):
        return getattr(self, name) if name in COMMON else dict(self.params)[name]

    def with_value(self, name: str, value) -> "Rule":
        """The same rule with one setting changed (checked like any new rule)."""
        if name in COMMON:
            return Rule.make(self.setup, self.sessions, self.direction, **dict(self.params),
                             **{**self._common(), name: value})
        return Rule.make(self.setup, self.sessions, self.direction, **{**dict(self.params), name: value}, **self._common())

    def _common(self) -> dict:
        return {name: getattr(self, name) for name in COMMON}

    def entry_key(self) -> tuple:
        """What decides the entries, ignoring stop and target."""
        return (self.setup, self.params, self.sessions, self.direction, self.trend_ema, self.vol_filter)

    # ── Plain English ────────────────────────────────────────────────────────

    def short(self) -> str:
        p = {name: _num(value) for name, value in self.params}
        entry = {
            "opening_range_breakout": f"ORB {p.get('range_minutes')}m +{p.get('buffer_atr')}ATR",
            "pre_session_breakout": f"pre-session breakout +{p.get('buffer_atr')}ATR",
            "pre_session_sweep": f"pre-session sweep {p.get('sweep_atr')}ATR",
            "trend_pullback": f"EMA {p.get('ema_fast')}/{p.get('ema_slow')} pullback",
            "session_momentum": f"momentum {p.get('momentum_atr')}ATR at +{p.get('delay_minutes')}m",
            "band_reversion": f"BB({p.get('band_period')},{p.get('band_k')}) RSI {p.get('rsi_level')} fade",
        }[self.setup]
        extras = [f"stop {_num(self.stop_atr)}ATR", f"target {_num(self.target_r)}R"]
        if self.trend_ema:
            extras.append(f"EMA{self.trend_ema} filter")
        if self.vol_filter:
            extras.append(f"vol ≥{self.vol_filter}×median")
        if self.direction != "both":
            extras.append(f"{self.direction} only")
        return f"{entry} · {', '.join(extras)}"

    def describe(self) -> str:
        p = {name: _num(value) for name, value in self.params}
        rsi_high = _num(100 - dict(self.params).get("rsi_level", 0))
        where = " and ".join(SESSIONS[name].label for name in self.sessions)
        window = p.get("entry_window_minutes")
        side = {"both": "", "long": " Buy only.", "short": " Sell only."}[self.direction]
        entry = {
            "opening_range_breakout":
                f"Mark the high and low of the first {p.get('range_minutes')} minutes. Buy when price rises "
                f"{p.get('buffer_atr')} daily ATR above that high, or sell when it falls the same distance below "
                f"the low, up to {window} minutes after the open.",
            "pre_session_breakout":
                f"Mark the high and low of the pre-session (Asia for London, the London morning for New York). "
                f"Buy when price rises {p.get('buffer_atr')} daily ATR above that high, or sell the same distance "
                f"below the low, up to {window} minutes after the open.",
            "pre_session_sweep":
                f"Mark the pre-session high and low. If price runs at least {p.get('sweep_atr')} daily ATR above "
                f"the high and a bar then closes back below it, sell at that close (the mirror image below the low "
                f"for a buy), up to {window} minutes after the open.",
            "trend_pullback":
                f"When the {p.get('ema_fast')}-bar EMA is above the {p.get('ema_slow')}-bar EMA, buy at the close "
                f"of a green bar that dipped to the fast EMA and closed above it (the mirror image for sells), up "
                f"to {window} minutes after the open.",
            "session_momentum":
                f"{p.get('delay_minutes')} minutes after the open, if price is at least {p.get('momentum_atr')} "
                f"daily ATR above where the pre-session started, buy; if it is that far below, sell.",
            "band_reversion":
                f"Buy a close below the lower Bollinger band ({p.get('band_period')} bars, {p.get('band_k')} "
                f"standard deviations) when the 14-bar RSI is under {p.get('rsi_level')}; sell a close above the "
                f"upper band when RSI is over {rsi_high}. Up to {window} minutes after the open.",
        }[self.setup]
        exit_ = (f"Stop {_num(self.stop_atr)} daily ATR from entry; target {_num(self.target_r)} times the risk. "
                 f"Any open trade is closed at the session close, and there is at most one trade per session.")
        filters = ""
        if self.trend_ema:
            filters += f" Only buy above the {self.trend_ema}-bar EMA and only sell below it."
        if self.vol_filter:
            filters += f" Skip days when the daily ATR is below {self.vol_filter} times its 50-day median."
        return f"{where} sessions. {entry}{side} {exit_}{filters}"


def _num(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _checked(name: str, value, spec: tuple):
    low, high, _ = spec
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RuleError(f"{name} must be a number") from None
    if number != number or not low <= number <= high:
        raise RuleError(f"{name} must be between {low} and {high}")
    return int(round(number)) if name in INTEGERS else round(number, 3)


def describe_language() -> str:
    """The rule language in a few lines, for Claude's instructions and the README."""
    lines = []
    for name, setup in SETUPS.items():
        params = ", ".join(f"{p} {lo}-{hi}" for p, (lo, hi, _) in setup["params"].items())
        lines.append(f"- {name}: {setup['summary']} Parameters: {params}.")
    common = ", ".join(f"{p} {lo}-{hi}" for p, (lo, hi, _) in COMMON.items())
    lines.append(f"- Every rule also has: {common}. trend_ema 0 and vol_filter 0 mean off.")
    return "\n".join(lines)

