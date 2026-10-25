"""Getting XAUUSD bars: from a CSV export, or made up for trying the council out.

load_csv() reads the common export formats (MetaTrader, Dukascopy, HistData, plain ISO times) and
returns bars indexed in UTC. Say which time zone the file's clock uses: MetaTrader exports use the
broker's server time, which is usually not UTC.

synthetic() makes gold-like random data. It is for tests and demos only: a rule found on it means
nothing for real trading.
"""
from pathlib import Path

import numpy as np
import pandas as pd

TIME_COLUMNS = ("time", "datetime", "timestamp", "gmt time", "local time", "date")
VOLUME_COLUMNS = ("volume", "tickvol", "tick_volume", "vol")
FORMATS = ("ISO8601", "%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S",
           "%Y%m%d %H%M%S", "%Y%m%d %H:%M:%S", "%Y%m%d %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M")


def load_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    path = Path(path)
    with path.open() as handle:
        first = handle.readline()
    sep = "\t" if "\t" in first else ";" if first.count(";") > first.count(",") else ","
    has_header = any(ch.isalpha() for ch in first.replace("e+", "").replace("E+", ""))
    raw = pd.read_csv(path, sep=sep, header=0 if has_header else None)
    if not has_header:  # HistData and similar: time, open, high, low, close[, volume]
        raw.columns = ["time", "open", "high", "low", "close", "volume", "extra"][:raw.shape[1]]
    raw.columns = [str(c).strip().strip("<>").strip().lower() for c in raw.columns]

    if "date" in raw.columns and "time" in raw.columns:
        stamps = raw["date"].astype(str).str.strip() + " " + raw["time"].astype(str).str.strip()
    else:
        column = next((c for c in TIME_COLUMNS if c in raw.columns), None)
        if column is None:
            raise ValueError(f"no time column found in {path.name}: expected one of {', '.join(TIME_COLUMNS)}")
        stamps = raw[column]
    index = _parse_times(stamps, tz)

    missing = [c for c in ("open", "high", "low", "close") if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name} has no {', '.join(missing)} column")
    bars = pd.DataFrame({c: pd.to_numeric(raw[c], errors="coerce").to_numpy() for c in ("open", "high", "low", "close")},
                        index=index)
    volume = next((c for c in VOLUME_COLUMNS if c in raw.columns), None)
    if volume:
        bars["volume"] = pd.to_numeric(raw[volume], errors="coerce").to_numpy()
    bars = bars[bars.index.notna()].dropna(subset=["open", "high", "low", "close"])
    bars = bars[~bars.index.duplicated()].sort_index()
    if bars.empty:
        raise ValueError(f"no usable bars in {path.name}")
    median = float(bars["close"].median())
    if not 100 < median < 100_000:
        raise ValueError(f"prices around {median:.2f} don't look like XAUUSD in US dollars")
    return bars


def _parse_times(stamps: pd.Series, tz: str) -> pd.DatetimeIndex:
    if pd.api.types.is_numeric_dtype(stamps):  # epoch seconds or milliseconds
        unit = "ms" if float(stamps.iloc[0]) > 1e11 else "s"
        return pd.DatetimeIndex(pd.to_datetime(stamps, unit=unit, utc=True))
    stamps = stamps.astype(str).str.strip()
    sample = stamps.head(50)
    for fmt in FORMATS:
        try:
            pd.to_datetime(sample, format=fmt)
        except (ValueError, TypeError):
            continue
        parsed = pd.DatetimeIndex(pd.to_datetime(stamps, format=fmt, errors="coerce"))
        break
    else:
        raise ValueError(f"couldn't read times like {stamps.iloc[0]!r}")
    if parsed.tz is None:
        parsed = parsed.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    return parsed.tz_convert("UTC")


def resample(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Bars of `minutes` minutes, labelled by their opening time. Finer bars are combined;
    coarser bars can't be split, so they are refused."""
    step = bars.index.to_series().diff().dropna().dt.total_seconds().median() / 60 if len(bars) > 1 else minutes
    if step > minutes + 1e-9:
        raise ValueError(f"the data has {step:g}-minute bars, coarser than the {minutes}-minute timeframe asked for")
    if abs(step - minutes) < 1e-9:
        return bars
    rules = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in bars.columns:
        rules["volume"] = "sum"
    return bars.resample(f"{minutes}min", label="left", closed="left").agg(rules).dropna(subset=["open"])


# ── Synthetic gold, for tests and demos ──────────────────────────────────────

# Relative volatility by New York hour: quiet Asia, busier London, busiest New York morning.
HOURLY_VOL = {**{h: 0.6 for h in (18, 19, 20, 21, 22, 23, 0, 1, 2)}, **{h: 1.0 for h in (3, 4, 5, 6, 7)},
              8: 1.9, 9: 1.7, 10: 1.5, **{h: 0.8 for h in (11, 12, 13, 14, 15, 16)}}


def synthetic(start: str = "2021-01-04", days: int = 730, seed: int = 7, price: float = 1800.0,
              edge: float = 0.0, daily_vol: float = 0.011, drift: float = 0.06) -> pd.DataFrame:
    """Five-minute gold-like bars: trading Sunday 18:00 to Friday 17:00 New York time with a daily
    break at 17:00, volatility that clusters from day to day, fat tails and a session rhythm.

    Each bar's high and low are drawn as the extremes of a continuous path between its open and close
    (a Brownian bridge), as in real tick-built bars. Coarse sub-steps would make every stop order fill
    better than it could in reality, which shows up as a fake breakout edge.

    drift is the yearly upward trend (gold's long-run rise). edge > 0 plants a known pattern for tests: after each London and New York session's first 30
    minutes, price drifts for two hours in the direction of that first half hour."""
    rng = np.random.default_rng(seed)
    stamps = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    ny = stamps.tz_convert("America/New_York").tz_localize(None)
    hour, weekday = np.asarray(ny.hour), np.asarray(ny.day_of_week)
    trading = (hour != 17) & (weekday != 5) & ~((weekday == 4) & (hour >= 17)) & ~((weekday == 6) & (hour < 18))
    stamps, ny, hour = stamps[trading], ny[trading], hour[trading]

    trade_day = (ny + pd.Timedelta(hours=7)).values.astype("datetime64[D]")
    _, day_of_bar = np.unique(trade_day, return_inverse=True)
    n_days = day_of_bar.max() + 1
    regime = np.zeros(n_days)
    shocks = rng.normal(0, 0.25 * np.sqrt(1 - 0.97 ** 2), n_days)
    for i in range(1, n_days):
        regime[i] = 0.97 * regime[i - 1] + shocks[i]
    vol_of_day = daily_vol * np.exp(regime - 0.25 ** 2 / 2)

    weight = np.array([HOURLY_VOL.get(h, 0.0) for h in range(24)])[hour]
    weight = weight / np.sqrt(np.mean(weight ** 2) * 276)  # a full day of bars adds up to the day's volatility
    bar_vol = vol_of_day[day_of_bar] * weight
    moves = rng.standard_t(4, size=len(stamps)) / np.sqrt(2.0) * bar_vol + drift / (252 * 276)

    if edge:
        for tz in ("Europe/London", "America/New_York"):
            local = stamps.tz_convert(tz).tz_localize(None)
            minutes = np.asarray(local.hour * 60 + local.minute) - 8 * 60
            day = local.values.astype("datetime64[D]")
            first = (minutes >= 0) & (minutes < 30)
            follow = (minutes >= 30) & (minutes < 150)
            opening = pd.Series(moves[first]).groupby(day[first]).sum()
            direction = np.sign(pd.Series(day[follow]).map(opening).fillna(0).to_numpy())
            moves[follow] += direction * edge * bar_vol[follow]

    close = np.log(price) + np.cumsum(moves)
    open_ = np.concatenate([[np.log(price)], close[:-1]])
    up = (moves + np.sqrt(moves ** 2 - 2 * bar_vol ** 2 * np.log(rng.uniform(size=len(moves))))) / 2
    down = (moves - np.sqrt(moves ** 2 - 2 * bar_vol ** 2 * np.log(rng.uniform(size=len(moves))))) / 2
    return pd.DataFrame({"open": np.exp(open_), "high": np.exp(open_ + up), "low": np.exp(open_ + down),
                         "close": np.exp(close)}, index=stamps).round(2)
