"""Fetch Binance USDT-perp funding-rate history (Plan §17 topic 11's
registered data family; topic 13 extends it to the expanded universe).
Raw history is stored beside the price data OUTSIDE the repo —
~/freqtrade-data/funding/<SYM>_USDT-funding.feather — one row per 8h
funding event. Fetches everything available; READERS cap at the screen's
HARD_STOP (the holdout rule lives at the read seam, same as load_panels).

A file already on disk is never refetched or overwritten (the regression
arms read the originals). A name that never had a USDT perp returns no
events and gets no file — load_panels' `subset` mode records it as NaN.

  uv run python tools/fetch_funding.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

from factory.universe import LEGACY_17, expanded

URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OUT = Path.home() / "freqtrade-data" / "funding"
START_MS = 1546300800000   # 2019-01-01, before the first Binance perp listing


def universe() -> list[str]:
    try:
        return sorted(set(LEGACY_17) | set(expanded()))
    except FileNotFoundError:       # expanded universe not built yet
        return list(LEGACY_17)


def fetch_symbol(sym: str) -> pd.DataFrame:
    rows, start = [], START_MS
    while True:
        q = f"?symbol={sym}USDT&startTime={start}&limit=1000"
        try:
            with urllib.request.urlopen(URL + q, timeout=30) as r:
                batch = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 400:      # no such perp symbol — not an error
                return pd.DataFrame()
            raise
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
    for sym in universe():
        f = OUT / f"{sym}_USDT-funding.feather"
        if f.exists():
            print(f"{sym}: already fetched, skipping")
            continue
        df = fetch_symbol(sym)
        if df.empty:
            print(f"{sym}: NO DATA")
            continue
        df.reset_index(drop=True).to_feather(f)
        print(f"{sym}: {len(df)} events  {df['date'].min():%Y-%m-%d} -> "
              f"{df['date'].max():%Y-%m-%d}")


if __name__ == "__main__":
    main()
