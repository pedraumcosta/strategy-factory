"""Fetch daily spot klines for expanded-universe names that have no feather
on disk — Plan §17 topic 13's data fetch. Source: Binance Vision monthly
spot 1d zips (delisted symbols retained — the reason the expanded universe
can be survivorship-honest). Output matches the freqtrade feather schema
the lab already uses, in the same directory:

  ~/freqtrade-data/binance/<SYM>_USDT-1d.feather  (date utc, OHLCV floats)

A file already on disk is NEVER overwritten (the 17-name regression arms
read the originals; mixed provenance — freqtrade API vs Vision zips — is
recorded in the topic 13 registration). Fetches through 2025-12 only
(HARD_STOP's year end); nothing later is needed by any registered reader.

  uv run python tools/fetch_klines.py
"""

from __future__ import annotations

import csv
import io
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from factory.universe import expanded

from build_universe import ZIP_URL, months_of  # noqa: E402  (same dir)

KLINES = "data/spot/monthly/klines/"
OUT = Path.home() / "freqtrade-data" / "binance"
COLS = ["date", "open", "high", "low", "close", "volume"]


def month_rows(sym: str, month: str) -> list[list[float]]:
    key = f"{KLINES}{sym}/1d/{sym}-1d-{month}.zip"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(ZIP_URL.format(key=key), timeout=60) as r:
                raw = r.read()
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = []
    with z.open(z.namelist()[0]) as fh:
        for row in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
            if not row or not row[0].strip().isdigit():
                continue   # header line in newer files
            ts = int(row[0])
            if ts > 10 ** 14:       # 2025+ files use microseconds
                ts //= 1000
            rows.append([ts] + [float(x) for x in row[1:6]])
    return rows


def fetch_symbol(base: str) -> None:
    f = OUT / f"{base}_USDT-1d.feather"
    if f.exists():
        print(f"{base}: already on disk, skipping")
        return
    sym = f"{base}USDT"
    months = months_of(sym)
    if not months:
        print(f"{base}: NO DATA on Vision")
        return
    rows: list[list[float]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for batch in pool.map(lambda m: month_rows(sym, m), months):
            rows.extend(batch)
    rows = sorted({r[0]: r for r in rows}.values(), key=lambda r: r[0])
    df = pd.DataFrame(rows, columns=COLS)
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    df.to_feather(f)
    print(f"{base}: {len(df)} days  {df['date'].min():%Y-%m-%d} -> "
          f"{df['date'].max():%Y-%m-%d}", flush=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for base in expanded():
        fetch_symbol(base)


if __name__ == "__main__":
    main()
