#!/usr/bin/env python3
"""spread_screen.py - Autotrader Plan section 20.7 step 4: the H4 arithmetic kill switch.

Question, and the only question: when a Kalman/DLM residual on a BTC-quoted cross is
traded as single-pair mean reversion, does one round trip capture >= 3x round-trip cost
GROSS? If not, H4 dies here and no pre-registration gets written.

Protocol, fixed before the run:
  * Windows      the 7 walk-forward IN-SAMPLE windows only (wf/folds.txt). The OOS halves
                 and all of 2026 are untouched. This is a screen, not an evaluation.
  * Timeframe    1d. Section 20.3 note 1 fixed the holding period at days, not hours.
  * Model A      local-level Kalman on log(close) of the CROSS itself - the directly
                 tradable object. Residual = one-step-ahead prediction error.
  * Model B      time-varying [alpha, beta] Kalman regression of log(ALT/USDT) on
                 log(BTC/USDT). Reported to test section 20.3 note 2: the ETH/BTC
                 shortcut is only the hedged spread if beta ~ 1.
  * Grid         q in {1e-4, 1e-3, 1e-2}, k in {1.0, 1.5, 2.0, 2.5}. DECLARED, and the
                 headline is the MEDIAN over the grid, never the max - section 15's lesson.
  * Causality    residual from bar t, position entered at t+1 close, exited at t+1 close
                 after the exit triggers at t. 60-bar burn-in dropped. Residual sigma is a
                 rolling 60-bar std of PRIOR prediction errors.
  * Gate         mean signed gross return per round trip, in percent, vs
                 0.600 % (3 x 0.2 % round trip, the section 14 R3 assumption of 0.1 %/side)
                 0.467 % (3 x 0.1556 % round trip, the 2020 measured fee with BNB discount)
"""
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint

DATA = "/freqtrade/user_data/data/binance"
COST_STRICT = 0.600   # percent, 3 x 0.2 % round trip
COST_LENIENT = 0.4668  # percent, 3 x 0.1556 % round trip
QS = [1e-4, 1e-3, 1e-2]
KS = [1.0, 1.5, 2.0, 2.5]
BURN = 60
MAXHOLD = 30
CROSSES = ["ETH", "BNB", "SOL", "ADA", "XRP", "LTC", "LINK", "TRX",
           "DOGE", "AVAX", "NEAR", "UNI", "HBAR", "ZEC"]
FOLDS = [("1", "2021-01-01", "2022-07-02"), ("2", "2021-07-02", "2022-12-31"),
         ("3", "2022-01-01", "2023-07-02"), ("4", "2022-07-02", "2023-12-31"),
         ("5", "2023-01-01", "2024-07-01"), ("6", "2023-07-02", "2024-12-30"),
         ("7", "2024-01-01", "2025-07-01")]


def load(sym, quote, tf="1d"):
    f = f"{DATA}/{sym}_{quote}-{tf}.feather"
    if not os.path.exists(f):
        return None
    df = pd.read_feather(f)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")["close"].astype(float)


def kalman_local_level(y, q):
    """One-step-ahead prediction errors of a local-level model. R=1, Q=q."""
    n = len(y)
    e = np.full(n, np.nan)
    mu, P = y[0], 1e6
    for t in range(n):
        Pp = P + q
        e[t] = y[t] - mu                      # residual vs the PRIOR mean: causal
        F = Pp + 1.0
        K = Pp / F
        mu = mu + K * e[t]
        P = (1.0 - K) * Pp
    return e


def kalman_regression(y, x, q):
    """Time-varying [alpha, beta]. Returns one-step-ahead errors and the beta path."""
    n = len(y)
    e = np.full(n, np.nan)
    betas = np.full(n, np.nan)
    a = np.array([0.0, 1.0])
    P = np.eye(2) * 1e6
    Q = np.eye(2) * q
    for t in range(n):
        F = np.array([1.0, x[t]])
        P = P + Q
        yhat = F @ a
        e[t] = y[t] - yhat
        S = F @ P @ F + 1.0
        K = (P @ F) / S
        a = a + K * e[t]
        P = P - np.outer(K, F @ P)
        betas[t] = a[1]
    return e, betas


def trade(px, e, k):
    """Causal mean-reversion round trips on the residual. Returns signed gross % per trade."""
    n = len(px)
    sig = pd.Series(e).rolling(BURN).std().shift(1).to_numpy()
    z = e / sig
    trades = []
    pos, entry_i, direction = 0, None, 0
    for t in range(BURN, n - 1):
        if not np.isfinite(z[t]):
            continue
        if pos == 0:
            if abs(z[t]) >= k:
                direction = -1 if z[t] > 0 else 1   # fade the deviation
                pos, entry_i = 1, t + 1             # enter at NEXT bar's close
        else:
            crossed = (direction == 1 and z[t] >= 0) or (direction == -1 and z[t] <= 0)
            if crossed or (t + 1 - entry_i) >= MAXHOLD:
                exit_i = t + 1
                r = direction * (px[exit_i] / px[entry_i] - 1.0) * 100.0
                trades.append((r, exit_i - entry_i))
                pos, entry_i, direction = 0, None, 0
    return trades


def main():
    rows = []
    betarows = []
    for sym in CROSSES:
        cross = load(sym, "BTC")
        alt = load(sym, "USDT")
        btc = load("BTC", "USDT")
        if cross is None or alt is None or btc is None:
            print(f"skip {sym}: missing data", file=sys.stderr)
            continue
        for fid, s, en in FOLDS:
            c = cross.loc[s:en].dropna()
            if len(c) < BURN + 60:
                continue
            px = c.to_numpy()
            y = np.log(px)

            # cointegration of the two USDT legs, and stationarity of the cross itself
            j = pd.concat([np.log(alt.loc[s:en]), np.log(btc.loc[s:en])], axis=1).dropna()
            try:
                adf_p = adfuller(y, autolag="AIC")[1]
            except Exception:
                adf_p = np.nan
            try:
                eg_p = coint(j.iloc[:, 0], j.iloc[:, 1])[1] if len(j) > BURN else np.nan
            except Exception:
                eg_p = np.nan

            # Model B: beta path, to check the "trade the cross instead" shortcut
            if len(j) == len(c):
                _, betas = kalman_regression(j.iloc[:, 0].to_numpy(),
                                             j.iloc[:, 1].to_numpy(), 1e-3)
                bb = betas[BURN:]
                betarows.append(dict(pair=f"{sym}/BTC", fold=fid,
                                     beta_med=float(np.nanmedian(bb)),
                                     beta_p10=float(np.nanpercentile(bb, 10)),
                                     beta_p90=float(np.nanpercentile(bb, 90))))

            for q, k in itertools.product(QS, KS):
                e = kalman_local_level(y, q)
                tr = trade(px, e, k)
                if not tr:
                    rows.append(dict(pair=f"{sym}/BTC", fold=fid, q=q, k=k, n=0,
                                     mean_pct=np.nan, med_pct=np.nan, absmean_pct=np.nan,
                                     winrate=np.nan, hold=np.nan, adf_p=adf_p, eg_p=eg_p))
                    continue
                r = np.array([t[0] for t in tr])
                h = np.array([t[1] for t in tr])
                rows.append(dict(pair=f"{sym}/BTC", fold=fid, q=q, k=k, n=len(r),
                                 mean_pct=float(r.mean()), med_pct=float(np.median(r)),
                                 absmean_pct=float(np.abs(r).mean()),
                                 winrate=float((r > 0).mean() * 100),
                                 hold=float(h.mean()), adf_p=adf_p, eg_p=eg_p))
    df = pd.DataFrame(rows)
    bdf = pd.DataFrame(betarows)
    df.to_csv("/freqtrade/user_data/spread_screen.csv", index=False)
    bdf.to_csv("/freqtrade/user_data/spread_screen_beta.csv", index=False)

    pd.set_option("display.width", 200, "display.max_rows", 400)
    print("=" * 96)
    print("GATE: mean signed gross %% per round trip must clear %.3f %% (strict) / %.3f %% (lenient)"
          % (COST_STRICT, COST_LENIENT))
    print("=" * 96)

    print("\n--- ETH/BTC, the named candidate: every grid cell, pooled over the 7 IS folds ---")
    eth = df[df.pair == "ETH/BTC"]
    g = eth.groupby(["q", "k"]).apply(
        lambda d: pd.Series({
            "trades": d.n.sum(),
            "mean_pct": np.average(d.mean_pct.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "absmean_pct": np.average(d.absmean_pct.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "winrate": np.average(d.winrate.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "hold_bars": np.average(d.hold.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "folds_pos": int((d.mean_pct > 0).sum()),
        }), include_groups=False)
    print(g.round(3).to_string())
    print("\nHEADLINE (median over the declared grid) mean_pct = %.4f %%" % g.mean_pct.median())
    print("        (max over the grid, for reference only)  = %.4f %%" % g.mean_pct.max())

    print("\n--- all 14 crosses, median over the grid, pooled over the 7 IS folds ---")
    per = df.groupby(["pair", "q", "k"]).apply(
        lambda d: pd.Series({
            "trades": d.n.sum(),
            "mean_pct": np.average(d.mean_pct.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "absmean_pct": np.average(d.absmean_pct.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
            "hold": np.average(d.hold.fillna(0), weights=d.n.clip(lower=0) + 1e-9),
        }), include_groups=False).reset_index()
    summ = per.groupby("pair").agg(trades=("trades", "sum"),
                                   mean_med=("mean_pct", "median"),
                                   mean_max=("mean_pct", "max"),
                                   travel_med=("absmean_pct", "median"),
                                   hold_med=("hold", "median")).sort_values("mean_med",
                                                                           ascending=False)
    summ["clears_strict"] = summ.mean_med >= COST_STRICT
    summ["clears_lenient"] = summ.mean_med >= COST_LENIENT
    print(summ.round(3).to_string())
    print("\nCrosses whose GRID MEDIAN clears the strict gate: %d of %d"
          % (int(summ.clears_strict.sum()), len(summ)))
    print("Crosses whose GRID MAX   clears the strict gate: %d of %d"
          % (int((summ.mean_max >= COST_STRICT).sum()), len(summ)))

    print("\n--- stationarity / cointegration per fold, in-sample only (p-values) ---")
    st = df.groupby(["pair", "fold"]).first().reset_index()[["pair", "fold", "adf_p", "eg_p"]]
    piv = st.pivot(index="pair", columns="fold", values="adf_p")
    print("ADF on log(cross level), p-value:")
    print(piv.round(3).to_string())
    print("\nfolds with ADF p<0.05 (cross is mean-reverting at all), per pair:")
    print((piv < 0.05).sum(axis=1).to_string())
    pivb = st.pivot(index="pair", columns="fold", values="eg_p")
    print("\nEngle-Granger on the two USDT legs, p-value:")
    print(pivb.round(3).to_string())
    print("\nfolds with EG p<0.05, per pair:")
    print((pivb < 0.05).sum(axis=1).to_string())

    print("\n--- Model B: the hedge-ratio beta path (is the cross the hedged spread? beta~1) ---")
    if not bdf.empty:
        bs = bdf.groupby("pair").agg(beta_med=("beta_med", "median"),
                                     p10=("beta_p10", "median"),
                                     p90=("beta_p90", "median"))
        print(bs.round(3).to_string())
    print("\nDone. CSVs in user_data/spread_screen*.csv")


if __name__ == "__main__":
    main()
