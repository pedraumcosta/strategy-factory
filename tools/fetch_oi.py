"""Fetch Binance USDT-perp open-interest history for the 17-pair universe
(Plan §17 topic 12's registered data family). Source: data.binance.vision
daily metrics zips (5-minute rows; published from 2021-12-01). We keep ONE
row per day — the last snapshot of the UTC day — as the day's OI, stored
beside the price data OUTSIDE the repo:

  ~/freqtrade-data/oi/<SYM>_USDT-oi.feather   (date, sum_open_interest)

Fetches everything available through HARD_STOP's year end; READERS cap at
HARD_STOP at the read seam, same as load_panels. A missing day (404 —
Vision has gaps around exchange incidents) is skipped and counted.

  uv run python tools/fetch_oi.py
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

URL = ("https://data.binance.vision/data/futures/um/daily/metrics/"
       "{sym}USDT/{sym}USDT-metrics-{day}.zip")
OUT = Path.home() / "freqtrade-data" / "oi"
UNIVERSE = ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
            "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"]
START = date(2021, 12, 1)   # first day Vision publishes metrics
END = date(2025, 12, 31)    # HARD_STOP; nothing after is needed


def day_oi(sym: str, day: date) -> tuple[str, float] | None:
    url = URL.format(sym=sym, day=day.isoformat())
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = list(csv.DictReader(
        io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")))
    if not rows:
        return None
    last = rows[-1]
    return day.isoformat(), float(last["sum_open_interest"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sym in UNIVERSE:
        f = OUT / f"{sym}_USDT-oi.feather"
        if f.exists():
            print(f"{sym}: already fetched, skipping")
            continue
        recs, misses = [], 0
        day = START
        while day <= END:
            got = day_oi(sym, day)
            if got:
                recs.append(got)
            else:
                misses += 1
            day += timedelta(days=1)
            time.sleep(0.05)
        if not recs:
            print(f"{sym}: NO DATA")
            continue
        df = pd.DataFrame(recs, columns=["date", "sum_open_interest"])
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df.to_feather(f)
        print(f"{sym}: {len(recs)} days ({misses} missing) "
              f"{df['date'].min():%Y-%m-%d} -> {df['date'].max():%Y-%m-%d}",
              flush=True)


if __name__ == "__main__":
    main()
