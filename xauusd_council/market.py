"""The market as the bots see it: XAUUSD bars cut into London and New York sessions.

Sessions follow local clock time, so daylight saving is handled by the time zones themselves:
  London    08:00-17:00 Europe/London
  New York  08:00-17:00 America/New_York
Each session also has a pre-session window, the range that breakouts and sweeps are measured against:
  London    00:00 London time to the London open (the Asian session)
  New York  the London open to the New York open (the London morning)

Every session-day becomes one row of a fixed-width grid with one column per bar, so a rule can be
tested on every day at once with numpy instead of bar by bar.

Distances are measured in daily ATR: the average true range of the 14 previous trading days (a
trading day ends at 17:00 New York time, as gold's does). Only past days are used, so a rule never
sees the day it is trading.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Session:
    name: str
    label: str
    tz: str
    open_minute: int    # minutes after local midnight
    close_minute: int


SESSIONS = {
    "london": Session("london", "London", "Europe/London", 8 * 60, 17 * 60),
    "new_york": Session("new_york", "New York", "America/New_York", 8 * 60, 17 * 60),
}
ATR_DAYS = 14
VOL_MEDIAN_DAYS = 50  # the vol filter compares today's ATR with its median over this many days
MIN_COVERAGE = 0.8    # a session-day needs 80% of its bars, so holidays and data gaps are skipped
TIMEFRAMES = (1, 5, 10, 15, 30, 60)


def day_numbers(naive_local: pd.DatetimeIndex) -> np.ndarray:
    """Calendar days since 1970-01-01, whatever resolution pandas chose for the timestamps."""
    return naive_local.values.astype("datetime64[D]").astype(np.int64)


def day_label(day: int) -> str:
    return str(np.datetime64(int(day), "D"))


@dataclass
class Panel:
    """One session: a row per trading day, a column per bar from the open to the close."""
    session: Session
    days: np.ndarray      # (D,) day numbers, local date of the session
    index: np.ndarray     # (D, W) row in the bar table, -1 where a bar is missing
    open: np.ndarray      # (D, W)
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    last_col: np.ndarray  # (D,) the last bar of each session-day
    datr: np.ndarray      # (D,) daily ATR known before the day started
    datr_rel: np.ndarray  # (D,) that ATR divided by its recent median
    pre_open: np.ndarray  # (D,) first price of the pre-session window
    pre_high: np.ndarray
    pre_low: np.ndarray

    @property
    def width(self) -> int:
        return self.index.shape[1]


class Market:
    def __init__(self, bars: pd.DataFrame, bar_minutes: int = 5):
        if bar_minutes not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES} minutes")
        if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
            raise ValueError("bars need a time-zone-aware DatetimeIndex (UTC)")
        self.bars = bars.sort_index()
        self.bar_minutes = bar_minutes
        self.close = self.bars["close"].to_numpy(float)
        self._indicators: dict = {}
        datr = self._daily_atr()
        self.panels = {name: self._panel(session, datr) for name, session in SESSIONS.items()}
        days = np.unique(np.concatenate([panel.days for panel in self.panels.values()]))
        if len(days) < ATR_DAYS * 2:
            raise ValueError("not enough data: the council needs at least a few months of London and New York sessions")
        self.days = days

    # ── Building the grids ───────────────────────────────────────────────────

    def _daily_atr(self) -> pd.DataFrame:
        ny = self.bars.index.tz_convert("America/New_York").tz_localize(None)
        trade_day = day_numbers(ny + pd.Timedelta(hours=7))  # 17:00 New York starts the next day
        daily = self.bars.groupby(trade_day).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
        previous = daily["close"].shift(1)
        true_range = pd.concat([daily["high"] - daily["low"], (daily["high"] - previous).abs(),
                                (daily["low"] - previous).abs()], axis=1).max(axis=1)
        datr = true_range.rolling(ATR_DAYS).mean().shift(1)  # yesterday's value: known before today
        median = datr.rolling(VOL_MEDIAN_DAYS, min_periods=ATR_DAYS).median()
        return pd.DataFrame({"datr": datr, "datr_rel": datr / median})

    def _panel(self, session: Session, datr: pd.DataFrame) -> Panel:
        index = self.bars.index
        local = index.tz_convert(session.tz).tz_localize(None)
        minutes = np.asarray(local.hour * 60 + local.minute)
        weekday = np.asarray(local.day_of_week)
        days = day_numbers(local)
        width = (session.close_minute - session.open_minute) // self.bar_minutes

        inside = (minutes >= session.open_minute) & (minutes < session.close_minute) & (weekday < 5)
        rows, row_of = np.unique(days[inside], return_inverse=True)
        grid = np.full((len(rows), width), -1, dtype=np.int64)
        grid[row_of, (minutes[inside] - session.open_minute) // self.bar_minutes] = np.flatnonzero(inside)

        # The pre-session window, keyed by the same local date as the session.
        london = index.tz_convert("Europe/London").tz_localize(None)
        london_minutes = np.asarray(london.hour * 60 + london.minute)
        london_open = SESSIONS["london"].open_minute
        if session.name == "london":
            pre = (london_minutes < london_open) & (weekday < 5)
        else:  # from the London open to the New York open, the same calendar date in both cities
            pre = (london_minutes >= london_open) & (minutes < session.open_minute) & (weekday < 5)
        window = self.bars[pre].groupby(days[pre]).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"))
        window = window.reindex(rows)
        daily = datr.reindex(rows)

        covered = (grid >= 0).sum(axis=1)
        keep = ((covered >= MIN_COVERAGE * width) & np.isfinite(daily["datr"].to_numpy()) & (daily["datr"].to_numpy() > 0)
                & np.isfinite(window["high"].to_numpy()))
        grid = grid[keep]
        valid = grid >= 0
        safe = np.where(valid, grid, 0)

        def cells(column):
            return np.where(valid, self.bars[column].to_numpy(float)[safe], np.nan)

        last_col = width - 1 - np.argmax(valid[:, ::-1], axis=1)
        return Panel(session=session, days=rows[keep], index=grid, open=cells("open"), high=cells("high"),
                     low=cells("low"), close=cells("close"), last_col=last_col,
                     datr=daily["datr"].to_numpy()[keep], datr_rel=daily["datr_rel"].to_numpy()[keep],
                     pre_open=window["open"].to_numpy()[keep], pre_high=window["high"].to_numpy()[keep],
                     pre_low=window["low"].to_numpy()[keep])

    # ── Indicators, computed once on the continuous series and laid on the grid ──

    def indicator(self, panel: Panel, kind: str, *args) -> np.ndarray:
        key = (panel.session.name, kind, args)
        if key not in self._indicators:
            series = self._series(kind, *args)
            valid = panel.index >= 0
            self._indicators[key] = np.where(valid, series[np.where(valid, panel.index, 0)], np.nan)
        return self._indicators[key]

    def _series(self, kind: str, *args) -> np.ndarray:
        close = pd.Series(self.close)
        if kind == "ema":
            return close.ewm(span=args[0], adjust=False).mean().to_numpy()
        if kind == "ema_prev":
            return close.ewm(span=args[0], adjust=False).mean().shift(1).to_numpy()
        if kind == "close_prev":
            return close.shift(1).to_numpy()
        if kind == "band_mid":
            return close.rolling(args[0]).mean().to_numpy()
        if kind == "band_sd":
            return close.rolling(args[0]).std(ddof=0).to_numpy()
        if kind == "rsi":
            change = close.diff()
            gain = change.clip(lower=0).ewm(alpha=1 / args[0], adjust=False).mean()
            loss = (-change.clip(upper=0)).ewm(alpha=1 / args[0], adjust=False).mean()
            return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100).to_numpy()
        raise ValueError(f"unknown indicator {kind}")

    # ── Periods ──────────────────────────────────────────────────────────────

    def split(self, holdout: float) -> tuple[tuple[int, int], tuple[int, int]]:
        """(train, holdout) as inclusive day ranges: the last `holdout` share of days is held out."""
        if not 0 < holdout < 0.9:
            raise ValueError("holdout must be between 0 and 0.9")
        cut = int(len(self.days) * (1 - holdout))
        return (int(self.days[0]), int(self.days[cut - 1])), (int(self.days[cut]), int(self.days[-1]))
