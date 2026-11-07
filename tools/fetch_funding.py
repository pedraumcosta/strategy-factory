"""Fetch Binance USDT-perp funding-rate history for the 17-pair universe
(Plan §17 topic 11's registered data family). Raw history is stored beside
the price data OUTSIDE the repo — ~/freqtrade-data/funding/<SYM>_USDT-funding.feather
— one row per 8h funding event. Fetches everything available; READERS cap
at the screen's HARD_STOP (the holdout rule lives at the read seam, same
as load_panels).

  uv run python tools/fetch_funding.py
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OUT = Path.home() / "freqtrade-data" / "funding"
UNIVERSE = ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
            "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"]
START_MS = 1546300800000   # 2019-01-01, before the first Binance perp listing


def fetch_symbol(sym: str) -> pd.DataFrame:
    rows, start = [], START_MS
    while True:
        q = f"?symbol={sym}USDT&startTime={start}&limit=1000"
        with urllib.request.urlopen(URL + q, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000:
            break
        start = nxt
        time.sleep(0.15)   # stay far under the rate limit
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    return df[["date", "fundingRate"]].drop_duplicates("date").sort_values("date")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sym in UNIVERSE:
        f = OUT / f"{sym}_USDT-funding.feather"
        df = fetch_symbol(sym)
        if df.empty:
            print(f"{sym}: NO DATA")
            continue
        df.reset_index(drop=True).to_feather(f)
        print(f"{sym}: {len(df)} events  {df['date'].min():%Y-%m-%d} -> "
              f"{df['date'].max():%Y-%m-%d}")


if __name__ == "__main__":
    main()
