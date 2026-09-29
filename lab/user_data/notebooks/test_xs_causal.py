"""Direct causality test: does the rank at date t change when data after t is removed?"""
import numpy as np, pandas as pd
from freqtrade.configuration import Configuration
from freqtrade.data.history import load_pair_history

cfg = Configuration.from_files(["/freqtrade/user_data/config.json"])
pairs = cfg["exchange"]["pair_whitelist"]; LB = 40

def ranks(max_date=None):
    series = {}
    for p in pairs:
        df = load_pair_history(datadir=cfg["datadir"], timeframe="1d", pair=p, data_format="feather")
        if df.empty: continue
        d = df.set_index("date")["close"].astype(float)
        if max_date is not None: d = d.loc[d.index <= max_date]
        ret = d.pct_change(LB); vol = d.pct_change().rolling(LB).std()
        series[p] = (ret / vol.replace(0, np.nan)).rename(p)
    panel = pd.concat(series.values(), axis=1).sort_index()
    return panel.rank(axis=1, ascending=False, method="first").shift(1)

full = ranks()
T = pd.Timestamp("2024-06-01", tz="UTC")
trunc = ranks(max_date=T)
common = full.index.intersection(trunc.index)
a, b = full.loc[common], trunc.loc[common]
diff = (a.fillna(-1) != b.fillna(-1))
print(f"  dates compared          : {len(common)}")
print(f"  cells differing         : {int(diff.values.sum())} / {diff.size}")
if diff.values.sum():
    rows = diff.any(axis=1)
    print(f"  first differing date    : {common[rows][0]}")
    print("  -> REAL look-ahead in the ranking")
else:
    print("  -> ranking is causal: truncation changes nothing at shared dates")

# Second check: does a pair's OWN rank depend on other pairs' future data availability?
print(f"\n  pairs present in panel  : {full.shape[1]}")
print(f"  NaN rank cells (full)   : {int(full.isna().values.sum())}")
