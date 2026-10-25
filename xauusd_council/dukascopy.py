"""Download free XAUUSD one-minute candles (UTC) from Dukascopy's public data feed.

There is one file per day:
  https://datafeed.dukascopy.com/datafeed/XAUUSD/{year}/{month - 1:02}/{day:02}/BID_candles_min_1.bi5
(the month counts from 00). Each file is LZMA-compressed. Each 24-byte record holds the seconds after
midnight, then open, close, low and high in thousandths of a dollar, then the volume. Minutes with no
trading are stored as flat zero-volume candles, and are dropped here.

Downloaded days are kept in a cache folder, so an interrupted download picks up where it stopped.
"""
import lzma
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

URL = "https://datafeed.dukascopy.com/datafeed/{symbol}/{year:04d}/{month:02d}/{day:02d}/{side}_candles_min_1.bi5"
RECORD = np.dtype([("seconds", ">u4"), ("open", ">u4"), ("close", ">u4"), ("low", ">u4"), ("high", ">u4"),
                   ("volume", ">f4")])
POINT = 1000  # XAUUSD prices are stored in thousandths of a dollar
HEADERS = {"User-Agent": "Mozilla/5.0 (xauusd-council)"}


def parse_day(raw: bytes, day: date) -> pd.DataFrame:
    """One day's file → bars indexed in UTC. Raises ValueError if the layout isn't what we expect."""
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    data = lzma.decompress(raw)
    if len(data) % RECORD.itemsize:
        raise ValueError(f"{day}: file size {len(data)} is not a whole number of candles")
    records = np.frombuffer(data, dtype=RECORD)
    records = records[records["volume"] > 0]
    start = pd.Timestamp(day, tz="UTC")
    bars = pd.DataFrame({
        "open": records["open"] / POINT, "high": records["high"] / POINT, "low": records["low"] / POINT,
        "close": records["close"] / POINT, "volume": records["volume"].astype(float),
    }, index=start + pd.to_timedelta(records["seconds"].astype(np.int64), unit="s"))
    if len(bars):
        sane = (bars["low"] <= bars[["open", "close"]].min(axis=1)) & (bars["high"] >= bars[["open", "close"]].max(axis=1))
        if sane.mean() < 0.99 or not 100 < bars["close"].median() < 100_000:
            raise ValueError(f"{day}: candles don't look like XAUUSD; the file layout may have changed")
    return bars


def _download(day: date, symbol: str, side: str, cache: Path) -> bytes:
    path = cache / f"{symbol}_{side}_{day.isoformat()}.bi5"
    if path.exists():
        return path.read_bytes()
    url = URL.format(symbol=symbol, year=day.year, month=day.month - 1, day=day.day, side=side)
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 404:
                raw = b""
                break
            response.raise_for_status()
            raw = response.content
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    path.write_bytes(raw)
    return raw


def fetch(start: date, end: date, out: Path, symbol: str = "XAUUSD", side: str = "BID",
          cache: Path | None = None, workers: int = 6, progress=print) -> Path:
    """Download every weekday from start to end (inclusive) and write one CSV of UTC one-minute bars."""
    cache = cache or out.parent / "dukascopy-cache"
    cache.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [day for day in days if day.weekday() != 5]  # nothing trades on Saturday (UTC)
    frames = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (day, raw) in enumerate(zip(days, pool.map(lambda d: _download(d, symbol, side, cache), days))):
            frames.append(parse_day(raw, day))
            if progress and (i + 1) % 50 == 0:
                progress(f"  {i + 1}/{len(days)} days ({day})")
    bars = pd.concat([f for f in frames if len(f)]).sort_index() if any(len(f) for f in frames) else None
    if bars is None:
        raise ValueError("Dukascopy returned no candles for those dates")
    out.parent.mkdir(parents=True, exist_ok=True)
    bars.index.name = "time"
    bars.to_csv(out, date_format="%Y-%m-%dT%H:%M:%SZ")
    return out
