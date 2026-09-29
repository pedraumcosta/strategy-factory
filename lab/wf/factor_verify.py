#!/usr/bin/env python3
"""factor_verify.py - does the screen's verdict survive scrutiny, and does it contradict
sections 15/17? Three checks, because the screen says XSMomentum's IC is significantly
NEGATIVE while H3 earned +50.21 % over 5 years.

 V1 DEMEANED?  alphalens' mean_return_by_quantile defaults to demeaned=True, i.e. returns
               RELATIVE to the universe mean. Re-run with demeaned=False and put the
               equal-weight universe return beside it. If Q5 is absolutely positive but
               relatively negative, H3's profit was BETA, not the factor.
 V2 LAG        the strategy scores at t-1, signals at t, fills at t+1. Test lags 0/1/2 so the
               screen is not being kinder or harsher than the strategy it is screening.
 V3 HORIZON    H3 does not hold 21 days; it holds while the pair stays in the top k. Measure
               the top-quantile forward return across horizons 1..42 to see if there is a
               short window where the factor works before it turns over.
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from alphalens.utils import get_clean_factor_and_forward_returns
from alphalens.performance import mean_return_by_quantile, factor_information_coefficient

import factor_screen as fs

px = fs.load_prices()
ret = px.pct_change(fs.LOOKBACK)
vol = px.pct_change().rolling(fs.LOOKBACK).std()
XSM = ret / vol.replace(0, np.nan)
S, E = fs.FOLDS[0][1], fs.FOLDS[-1][2]


def prep(factor_wide, periods, lag=0):
    f = factor_wide.shift(lag).loc[S:E].stack(future_stack=True).dropna()
    f.index = f.index.set_names(["date", "asset"])
    return get_clean_factor_and_forward_returns(f, px, quantiles=fs.QUANTILES,
                                               periods=periods, max_loss=0.5)


print("=" * 100)
print("V1 - DEMEANED vs RAW. 21D mean forward return by quintile, pooled over the 7 IS halves.")
print("=" * 100)
d = prep(XSM, (1, 5, 21))
dem, _ = mean_return_by_quantile(d, by_date=False, demeaned=True)
raw, _ = mean_return_by_quantile(d, by_date=False, demeaned=False)
cmp = pd.DataFrame({"relative_%": dem["21D"] * 100, "absolute_%": raw["21D"] * 100})
print(cmp.round(3).to_string())

# the universe benchmark: equal-weight mean 21D forward return over the same dates
fwd21 = (px.shift(-21) / px - 1.0).loc[S:E]
ew = fwd21.mean(axis=1).mean() * 100
print(f"\nequal-weight universe mean 21D forward return over the same window: {ew:+.3f} %")
print(f"top quintile absolute: {raw['21D'].iloc[-1]*100:+.3f} %   "
      f"-> excess over equal weight: {raw['21D'].iloc[-1]*100 - ew:+.3f} %")
print(f"bottom quintile absolute: {raw['21D'].iloc[0]*100:+.3f} %")
print("\nVERDICT V1: " + ("the factor's top bucket beats equal weight in ABSOLUTE terms but the "
                          "screen demeans, so the negative IC is a RELATIVE statement"
                          if raw["21D"].iloc[-1] * 100 > ew else
                          "the top bucket loses to equal weight in ABSOLUTE terms too - "
                          "the factor is not merely beta-flattered, it is adverse"))

print("\n" + "=" * 100)
print("V2 - LAG SENSITIVITY. The strategy's decision chain is score(t-1) -> signal(t) -> fill(t+1).")
print("=" * 100)
rows = []
for lag in (0, 1, 2):
    dd = prep(XSM, (1, 5, 21), lag=lag)
    ic = factor_information_coefficient(dd)
    r, _ = mean_return_by_quantile(dd, by_date=False, demeaned=True)
    rows.append(dict(lag=lag,
                     ic1=ic["1D"].mean(), ic5=ic["5D"].mean(), ic21=ic["21D"].mean(),
                     t21=ic["21D"].mean() / (ic["21D"].std() / np.sqrt(ic["21D"].count())),
                     q5_rel=r["21D"].iloc[-1] * 100, spread=(r["21D"].iloc[-1] - r["21D"].iloc[0]) * 100))
print(pd.DataFrame(rows).round(4).to_string(index=False))

print("\n" + "=" * 100)
print("V3 - HORIZON SCAN. Top-quintile forward return (relative and absolute) by horizon.")
print("=" * 100)
hz = (1, 2, 3, 5, 8, 13, 21, 34, 42)
dd = prep(XSM, hz)
dem2, _ = mean_return_by_quantile(dd, by_date=False, demeaned=True)
raw2, _ = mean_return_by_quantile(dd, by_date=False, demeaned=False)
ic2 = factor_information_coefficient(dd)
out = []
for p in hz:
    c = f"{p}D"
    ewh = ((px.shift(-p) / px - 1.0).loc[S:E].mean(axis=1).mean()) * 100
    out.append(dict(horizon=c,
                    ic=ic2[c].mean(),
                    ic_t=ic2[c].mean() / (ic2[c].std() / np.sqrt(ic2[c].count())),
                    q5_rel_pct=dem2[c].iloc[-1] * 100,
                    q5_abs_pct=raw2[c].iloc[-1] * 100,
                    equalweight_pct=ewh,
                    excess_pct=raw2[c].iloc[-1] * 100 - ewh,
                    per_day_excess_bp=(raw2[c].iloc[-1] * 100 - ewh) / p * 100))
o = pd.DataFrame(out)
print(o.round(4).to_string(index=False))
best = o.loc[o.excess_pct.idxmax()]
print(f"\nbest horizon by excess over equal weight: {best.horizon} at {best.excess_pct:+.3f} % "
      f"({best.per_day_excess_bp:+.1f} bp/day)")
print("horizons where the top quintile beats equal weight: "
      f"{int((o.excess_pct > 0).sum())} of {len(o)}")
print("horizons with a positive IC: %d of %d" % (int((o.ic > 0).sum()), len(o)))
