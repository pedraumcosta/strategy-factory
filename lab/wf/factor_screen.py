#!/usr/bin/env python3
"""factor_screen.py - Autotrader Plan section 20.7 step 1: the pre-fold factor screen.

Why this exists. Every rejection in sections 13-17 cost either a fold set or the 2026 holdout.
Information Coefficient, quantile monotonicity and turnover are computable from a factor and a
forward-return matrix WITHOUT running a backtest and WITHOUT touching a holdout, so this screen
is the cheapest filter in the lab. Run it before any fold. Binds to Plan section 8 U1.

What it reports, per factor:
  IC            Spearman rank correlation of factor vs forward return, per horizon, with
                t-stat and the share of months in which it is positive.
  QUANTILES     mean forward return by factor quintile - is Q5 > Q1, and is it monotone?
  TURNOVER      top-quantile composition churn, the proxy for how hard the factor trades.
  CONCENTRATION share of the top quantile's total forward return carried by its best month.
                THIS is the H3 detector: section 17 rejected H3 because September 2026 alone
                was 70 % of the profit, and that is visible in-sample if you look for it.

Calibration. Three factors are always run together so the numbers have a scale:
  NOISE      uniform random, fixed seed - the floor. A screen that lights up here is broken.
  ORACLE     the realised forward 21d return, i.e. deliberate look-ahead - the ceiling.
  XSMomentum the real factor, ret(lb)/std(lb) with lb=40, exactly as in
             user_data/strategies/XSMomentum.py (H3's fixed a-priori parameters).

Protocol. The seven walk-forward IN-SAMPLE halves only (wf/folds.txt). 2026 is never read. The
factor at date t is scored against returns from t onward, which is the horizon the strategy
actually trades: it acts at t+1 on the ranking formed at t.

Run with the research image (alphalens is not in the backtest image, and the research image has
a DIFFERENT pandas - never run a backtest with it):
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD/user_data:/freqtrade/user_data" -v "$HOME/freqtrade-data:/freqtrade/user_data/data" \
    -v "$PWD/wf:/wf" --entrypoint python3 freqtrade-lab:2026.8-research /wf/factor_screen.py
"""
import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from alphalens.utils import get_clean_factor_and_forward_returns
from alphalens.performance import (factor_information_coefficient,
                                   mean_return_by_quantile, quantile_turnover)

DATA = "/freqtrade/user_data/data/binance"
UNIVERSE = ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR", "LINK",
            "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"]
PERIODS = (1, 5, 21)
QUANTILES = 5
LOOKBACK = 40           # H3's fixed a-priori value. Not tuned here, not tunable here.
FOLDS = [("1", "2021-01-01", "2022-07-02"), ("2", "2021-07-02", "2022-12-31"),
         ("3", "2022-01-01", "2023-07-02"), ("4", "2022-07-02", "2023-12-31"),
         ("5", "2023-01-01", "2024-07-01"), ("6", "2023-07-02", "2024-12-30"),
         ("7", "2024-01-01", "2025-07-01")]
HARD_STOP = "2025-12-31"   # nothing after this is ever read. 2026 belongs to H3 and is spent.
RNG = np.random.default_rng(20260929)


def load_prices():
    cols = {}
    for sym in UNIVERSE:
        f = f"{DATA}/{sym}_USDT-1d.feather"
        if not os.path.exists(f):
            print(f"  missing: {sym}/USDT 1d")
            continue
        df = pd.read_feather(f)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        cols[sym] = df.set_index("date")["close"].astype(float)
    px = pd.DataFrame(cols).sort_index()
    px = px.loc[:HARD_STOP]
    px.index = px.index.tz_localize(None)
    return px


def build_factors(px):
    """The three factors, all as (date, asset) Series on the same index."""
    ret = px.pct_change(LOOKBACK)
    vol = px.pct_change().rolling(LOOKBACK).std()
    xsm = (ret / vol.replace(0, np.nan))
    noise = pd.DataFrame(RNG.standard_normal(px.shape), index=px.index, columns=px.columns)
    oracle = px.shift(-21) / px - 1.0          # deliberate look-ahead: the ceiling
    return {"XSMomentum": xsm, "NOISE": noise, "ORACLE": oracle}


def screen(factor_wide, px, start, end, label):
    """Alphalens on one window. Returns a dict of scalars plus the per-period tables."""
    f = factor_wide.loc[start:end].stack(future_stack=True).dropna()
    if len(f) < 200:
        return None
    f.index = f.index.set_names(["date", "asset"])
    try:
        data = get_clean_factor_and_forward_returns(
            f, px, quantiles=QUANTILES, periods=PERIODS, max_loss=0.5)
    except Exception as e:
        print(f"    {label}: alphalens refused the input ({e})")
        return None

    ic = factor_information_coefficient(data)
    qmean, _ = mean_return_by_quantile(data, by_date=False)
    qbydate, _ = mean_return_by_quantile(data, by_date=True)

    out = {"label": label, "n_obs": len(data), "ic": ic, "qmean": qmean}
    for p in PERIODS:
        col = f"{p}D"
        s = ic[col].dropna()
        out[f"ic_mean_{p}"] = s.mean()
        out[f"ic_std_{p}"] = s.std()
        out[f"ic_t_{p}"] = s.mean() / (s.std() / np.sqrt(len(s))) if s.std() > 0 else np.nan
        m = s.resample("ME").mean()
        out[f"ic_posmonths_{p}"] = (m > 0).mean() * 100
        out[f"ic_nmonths_{p}"] = len(m)

    # quantile spread and monotonicity on the 21D horizon
    q21 = qmean["21D"]
    out["q_top"] = q21.iloc[-1] * 100
    out["q_bot"] = q21.iloc[0] * 100
    out["q_spread"] = (q21.iloc[-1] - q21.iloc[0]) * 100
    d = np.diff(q21.values)
    out["q_monotone_steps"] = int((d > 0).sum())

    # turnover of the top quantile - the churn proxy
    try:
        out["turnover_top"] = quantile_turnover(data["factor_quantile"], QUANTILES, 1).mean()
    except Exception:
        out["turnover_top"] = np.nan

    # CONCENTRATION: monthly mean 21D return of the top quantile
    try:
        top = qbydate["21D"].xs(QUANTILES, level="factor_quantile")
        mon = top.resample("ME").mean().dropna()
        pos = mon[mon > 0].sum()
        out["conc_best_month"] = (mon.max() / pos * 100) if pos > 0 else np.nan
        out["conc_posmonths"] = (mon > 0).mean() * 100
        out["conc_nmonths"] = len(mon)
    except Exception:
        out["conc_best_month"] = out["conc_posmonths"] = out["conc_nmonths"] = np.nan
    return out


def main():
    px = load_prices()
    print(f"universe {px.shape[1]} pairs, {px.shape[0]} daily bars, "
          f"{px.index.min().date()} -> {px.index.max().date()} (hard stop {HARD_STOP})")
    factors = build_factors(px)

    rows = []
    for name, fw in factors.items():
        for fid, s, e in FOLDS:
            r = screen(fw, px, s, e, f"{name} f{fid}")
            if r:
                r.update(factor=name, fold=fid)
                rows.append(r)
        r = screen(fw, px, FOLDS[0][1], FOLDS[-1][2], f"{name} POOLED")
        if r:
            r.update(factor=name, fold="pooled")
            rows.append(r)

    df = pd.DataFrame([{k: v for k, v in r.items()
                        if k not in ("ic", "qmean", "label")} for r in rows])
    df.to_csv("/freqtrade/user_data/factor_screen.csv", index=False)
    pd.set_option("display.width", 220, "display.max_rows", 200)

    print("\n" + "=" * 104)
    print("CALIBRATED SCREEN - pooled over the 7 in-sample halves, 2021-01-01 -> 2025-07-01")
    print("=" * 104)
    p = df[df.fold == "pooled"].set_index("factor")
    tbl = p[["n_obs", "ic_mean_1", "ic_t_1", "ic_mean_5", "ic_t_5", "ic_mean_21", "ic_t_21",
             "ic_posmonths_21", "q_spread", "q_monotone_steps", "turnover_top"]]
    print(tbl.round(4).to_string())
    print("\nreading: ORACLE is the ceiling (deliberate look-ahead), NOISE is the floor.")
    print("q_monotone_steps is out of 4 - a real factor steps up across every quintile.")

    print("\n" + "=" * 104)
    print("QUANTILE PROFILE, 21D mean forward return in %, pooled")
    print("=" * 104)
    for r in rows:
        if r["fold"] == "pooled":
            q = (r["qmean"]["21D"] * 100).round(3)
            print(f"  {r['factor']:<11} " + "  ".join(f"Q{i}={v:+.3f}" for i, v in
                                                      zip(q.index, q.values)))

    print("\n" + "=" * 104)
    print("CONCENTRATION - the H3 detector. Top quantile's 21D return by month.")
    print("  conc_best_month = single best month as a share of all positive months' sum.")
    print("  Section 17 rejected H3 at 70 % concentrated in one month, measured on the holdout.")
    print("=" * 104)
    print(p[["conc_best_month", "conc_posmonths", "conc_nmonths"]].round(1).to_string())

    print("\n" + "=" * 104)
    print("PER-FOLD STABILITY of XSMomentum (the thing a single pooled number hides)")
    print("=" * 104)
    x = df[(df.factor == "XSMomentum") & (df.fold != "pooled")].set_index("fold")
    print(x[["ic_mean_1", "ic_mean_5", "ic_mean_21", "ic_posmonths_21", "q_spread",
             "q_monotone_steps", "conc_best_month"]].round(4).to_string())
    print(f"\nfolds with positive 21D IC: {int((x.ic_mean_21 > 0).sum())} of {len(x)}")
    print(f"folds with a positive Q5-Q1 spread: {int((x.q_spread > 0).sum())} of {len(x)}")
    print(f"folds with all 4 quintile steps monotone: {int((x.q_monotone_steps == 4).sum())} of {len(x)}")
    print("\nCSV: user_data/factor_screen.csv")


if __name__ == "__main__":
    main()
