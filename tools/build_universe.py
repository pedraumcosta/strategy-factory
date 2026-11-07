"""Build the expanded universe — Plan §17 topic 13's pre-committed rule,
executed. Enumerates ALL Binance spot *USDT symbols from Binance Vision's
monthly-klines listing (Vision retains delisted symbols — that is the
survivorship-honesty reason to enumerate there and not from the live
exchange API), applies the registered filters, and writes
factory/universe_expanded.json with the per-name evidence:

  1. exclude stablecoin/fiat bases (explicit list), leveraged tokens
     (UP/DOWN/BULL/BEAR suffix whose stem is itself a listed base) and
     wrapped-peg duplicates (WBTC, WBETH, BETH);
  2. first monthly 1d file <= 2023-12 and >= 24 monthly files <= 2025-12;
  3. median daily quote volume >= US$10M over the name's OWN last 365
     available days <= HARD_STOP (a delisted name is judged on its final
     year — that keeps it in rather than erasing it);
  4. if more than 80 qualify, the top 80 by that median; union LEGACY_17.

  uv run python tools/build_universe.py
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from factory.universe import EXPANDED_JSON, LEGACY_17

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINES = "data/spot/monthly/klines/"
ZIP_URL = "https://data.binance.vision/{key}"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

FIRST_MONTH_MAX = "2023-12"   # >= 2 years of history before HARD_STOP
LAST_MONTH = "2025-12"        # HARD_STOP's year end; nothing later is read
MIN_MONTHS = 24
MIN_MEDIAN_QUOTE_VOL = 10_000_000.0
MAX_NAMES = 80
LIQUIDITY_DAYS = 365

STABLE_FIAT = {
    "USDC", "TUSD", "BUSD", "FDUSD", "USDP", "PAX", "DAI", "SUSD", "USDS",
    "USDE", "UST", "USTC", "PYUSD", "AEUR", "EUR", "EURI", "GBP", "AUD",
    "BRL", "TRY", "RUB", "UAH", "NGN", "BIDR", "IDRT", "BKRW", "ZAR",
    "VAI", "USD1", "XUSD",
}
WRAPPED = {"WBTC", "WBETH", "BETH"}


def _s3_list(prefix: str, want: str) -> list[str]:
    """Paginated S3 listing: want='prefix' -> CommonPrefixes, 'key' -> Keys."""
    out, marker = [], None
    while True:
        q = {"delimiter": "/", "prefix": prefix}
        if marker:
            q["marker"] = marker
        with urllib.request.urlopen(
                f"{S3}?{urllib.parse.urlencode(q)}", timeout=60) as r:
            root = ET.fromstring(r.read())
        if want == "prefix":
            batch = [e.text for e in root.iter(f"{NS}Prefix") if e.text != prefix]
        else:
            batch = [e.text for e in root.iter(f"{NS}Key")]
        out.extend(batch)
        if (root.findtext(f"{NS}IsTruncated") or "false") != "true":
            return out
        marker = root.findtext(f"{NS}NextMarker") or (batch and batch[-1])
        if not marker:
            return out


def months_of(sym: str) -> list[str]:
    """Sorted 'YYYY-MM' list of this symbol's monthly 1d zips <= LAST_MONTH."""
    keys = _s3_list(f"{KLINES}{sym}/1d/", "key")
    months = sorted(k.rsplit("-1d-", 1)[1][:7] for k in keys
                    if k.endswith(".zip"))
    return [m for m in months if m <= LAST_MONTH]


def month_quote_vols(sym: str, month: str) -> list[tuple[int, float]]:
    """(open_time_ms, quote_volume) per daily row of one monthly zip."""
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
            rows.append((ts, float(row[7])))
    return rows


def judge(sym: str) -> dict | None:
    months = months_of(sym)
    if not months or months[0] > FIRST_MONTH_MAX or len(months) < MIN_MONTHS:
        return None
    daily: list[tuple[int, float]] = []
    for m in months[-13:]:          # 13 months safely cover 365 days
        daily.extend(month_quote_vols(sym, m))
    daily = sorted(set(daily))[-LIQUIDITY_DAYS:]
    med = median(v for _, v in daily) if daily else 0.0
    if med < MIN_MEDIAN_QUOTE_VOL:
        return None
    return {"first_month": months[0], "last_month": months[-1],
            "months": len(months), "median_quote_vol_usd": round(med)}


def main() -> None:
    prefixes = _s3_list(KLINES, "prefix")
    all_syms = sorted(p.rstrip("/").rsplit("/", 1)[1] for p in prefixes)
    bases = {s[:-4] for s in all_syms if s.endswith("USDT")}

    candidates = []
    for s in all_syms:
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLE_FIAT or base in WRAPPED or not base:
            continue
        if ((base.endswith("UP") and base[:-2] in bases) or
                (base.endswith("DOWN") and base[:-4] in bases) or
                (base.endswith(("BULL", "BEAR")) and base[:-4] in bases)):
            continue
        candidates.append(base)
    print(f"{len(candidates)} candidate bases after name filters")

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for base, meta in zip(candidates,
                              pool.map(lambda b: judge(f"{b}USDT"), candidates)):
            if meta:
                results[base] = meta
                print(f"  {base}: {meta['first_month']} -> {meta['last_month']}"
                      f"  medianQV ${meta['median_quote_vol_usd']:,}", flush=True)

    if len(results) > MAX_NAMES:
        keep = sorted(results, key=lambda b: -results[b]["median_quote_vol_usd"])
        keep = set(keep[:MAX_NAMES]) | (set(LEGACY_17) & set(results))
    else:
        keep = set(results)
    missing_legacy = sorted(set(LEGACY_17) - keep)
    if missing_legacy:
        raise SystemExit(f"legacy names failed the rule: {missing_legacy} — "
                         "the rule or the data needs looking at, not patching")
    out = {"rule": {"first_month_max": FIRST_MONTH_MAX, "last_month": LAST_MONTH,
                    "min_months": MIN_MONTHS,
                    "min_median_quote_vol_usd": MIN_MEDIAN_QUOTE_VOL,
                    "max_names": MAX_NAMES, "liquidity_days": LIQUIDITY_DAYS,
                    "built_at": time.strftime("%Y-%m-%d")},
           "symbols": {b: results[b] for b in sorted(keep)}}
    EXPANDED_JSON.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {EXPANDED_JSON}: {len(keep)} names")


if __name__ == "__main__":
    main()
