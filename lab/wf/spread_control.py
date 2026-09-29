#!/usr/bin/env python3
"""spread_control.py - the control for spread_screen.py, Plan section 20.7 step 4.

Four crosses showed a positive grid median. Before believing any of it, three controls:

 C1 DRIFT      is the per-trade return just the pair's own ~21-day drift? Compare the rule's
               mean per trade against buy-and-hold over a matched holding period, and report
               how long/short-biased the rule actually is. Mean reversion that is really drift
               will satisfy  mean_rule ~ drift * (long_frac - short_frac).
 C2 RANDOM     same trade count, same holding period, entries drawn at random (200 draws).
               If the rule sits inside the random band it has no timing information at all.
 C3 FOLD CONC  is the pooled mean carried by one fold? This is section 17's G5 lesson.
"""
import itertools
import os

import numpy as np
import pandas as pd

DATA = "/freqtrade/user_data/data/binance"
QS = [1e-4, 1e-3, 1e-2]
KS = [1.0, 1.5, 2.0, 2.5]
BURN, MAXHOLD = 60, 30
PAIRS = ["UNI", "TRX", "LINK", "LTC", "ETH", "SOL", "DOGE"]
FOLDS = [("1", "2021-01-01", "2022-07-02"), ("2", "2021-07-02", "2022-12-31"),
         ("3", "2022-01-01", "2023-07-02"), ("4", "2022-07-02", "2023-12-31"),
         ("5", "2023-01-01", "2024-07-01"), ("6", "2023-07-02", "2024-12-30"),
         ("7", "2024-01-01", "2025-07-01")]
RNG = np.random.default_rng(20260929)


def load(sym, quote):
    f = f"{DATA}/{sym}_{quote}-1d.feather"
    if not os.path.exists(f):
        return None
    df = pd.read_feather(f)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")["close"].astype(float)


def kalman(y, q):
    n = len(y)
    e = np.full(n, np.nan)
    mu, P = y[0], 1e6
    for t in range(n):
        Pp = P + q
        e[t] = y[t] - mu
        F = Pp + 1.0
        K = Pp / F
        mu, P = mu + K * e[t], (1.0 - K) * Pp
    return e


def trade(px, e, k):
    n = len(px)
    sig = pd.Series(e).rolling(BURN).std().shift(1).to_numpy()
    z = e / sig
    out = []
    pos, entry_i, direction = 0, None, 0
    for t in range(BURN, n - 1):
        if not np.isfinite(z[t]):
            continue
        if pos == 0:
            if abs(z[t]) >= k:
                direction = -1 if z[t] > 0 else 1
                pos, entry_i = 1, t + 1
        else:
            if ((direction == 1 and z[t] >= 0) or (direction == -1 and z[t] <= 0)
                    or (t + 1 - entry_i) >= MAXHOLD):
                out.append((direction * (px[t + 1] / px[entry_i] - 1.0) * 100.0,
                            t + 1 - entry_i, direction))
                pos, entry_i, direction = 0, None, 0
    return out


def random_control(px, n_trades, hold, direction_mix, draws=200):
    """Matched-count, matched-hold, random-entry control. Returns the mean-per-trade band."""
    n = len(px)
    means = []
    hold = max(1, int(round(hold)))
    for _ in range(draws):
        idx = RNG.integers(BURN, max(BURN + 1, n - hold - 1), size=n_trades)
        d = RNG.choice([1, -1], size=n_trades, p=[direction_mix, 1 - direction_mix])
        r = d * (px[idx + hold] / px[idx] - 1.0) * 100.0
        means.append(r.mean())
    return float(np.percentile(means, 5)), float(np.median(means)), float(np.percentile(means, 95))


rows = []
for sym in PAIRS:
    cross = load(sym, "BTC")
    if cross is None:
        continue
    for fid, s, en in FOLDS:
        c = cross.loc[s:en].dropna()
        if len(c) < BURN + 60:
            continue
        px, y = c.to_numpy(), np.log(c.to_numpy())
        for q, k in itertools.product(QS, KS):
            tr = trade(px, kalman(y, q), k)
            if not tr:
                continue
            r = np.array([t[0] for t in tr])
            h = np.array([t[1] for t in tr])
            d = np.array([t[2] for t in tr])
            longf = float((d == 1).mean())
            mh = int(round(h.mean()))
            # C1: matched-horizon buy-and-hold drift, same window
            bh = (px[mh:] / px[:-mh] - 1.0) * 100.0
            drift = float(bh.mean())
            lo, mid, hi = random_control(px, len(r), h.mean(), longf)
            rows.append(dict(pair=f"{sym}/BTC", fold=fid, q=q, k=k, n=len(r),
                             mean_pct=float(r.mean()), hold=float(h.mean()), long_frac=longf,
                             drift_matched=drift, implied_drift=drift * (2 * longf - 1),
                             rnd_p5=lo, rnd_med=mid, rnd_p95=hi))

df = pd.DataFrame(rows)
df.to_csv("/freqtrade/user_data/spread_control.csv", index=False)
pd.set_option("display.width", 220, "display.max_rows", 300)

print("=" * 104)
print("C1 - DRIFT. 'implied_drift' = matched-horizon buy-and-hold drift x (long_frac - short_frac).")
print("     If mean_pct tracks implied_drift, the 'edge' is the pair bleeding against BTC, not reversion.")
print("=" * 104)
agg = df.groupby("pair").agg(trades=("n", "sum"),
                             mean_pct=("mean_pct", "median"),
                             long_frac=("long_frac", "median"),
                             drift_matched=("drift_matched", "median"),
                             implied_drift=("implied_drift", "median"),
                             hold=("hold", "median"))
agg["gap"] = agg.mean_pct - agg.implied_drift
print(agg.round(3).to_string())
r2 = np.corrcoef(df.mean_pct, df.implied_drift)[0, 1]
print("\ncorr(mean_pct, implied_drift) over all %d grid x fold cells = %.3f   (r^2 = %.3f)"
      % (len(df), r2, r2 ** 2))

print("\n" + "=" * 104)
print("C2 - RANDOM ENTRY, matched count / hold / long-short mix. 200 draws, 5th-95th pct band.")
print("=" * 104)
c2 = df.groupby("pair").agg(mean_pct=("mean_pct", "median"), rnd_p5=("rnd_p5", "median"),
                            rnd_med=("rnd_med", "median"), rnd_p95=("rnd_p95", "median"))
c2["inside_band"] = (c2.mean_pct >= c2.rnd_p5) & (c2.mean_pct <= c2.rnd_p95)
print(c2.round(3).to_string())
cell_in = ((df.mean_pct >= df.rnd_p5) & (df.mean_pct <= df.rnd_p95)).mean() * 100
print("\ngrid x fold cells whose result sits INSIDE its own random band: %.1f %% of %d"
      % (cell_in, len(df)))
print("cells that beat their random 95th percentile: %.1f %%"
      % ((df.mean_pct > df.rnd_p95).mean() * 100))

print("\n" + "=" * 104)
print("C3 - FOLD CONCENTRATION of the four that 'cleared' (median over the grid, per fold)")
print("=" * 104)
piv = df[df.pair.isin(["UNI/BTC", "TRX/BTC", "LINK/BTC", "LTC/BTC"])].groupby(
    ["pair", "fold"]).mean_pct.median().unstack()
print(piv.round(2).to_string())
print("\nfolds positive, out of 7:")
print((piv > 0).sum(axis=1).to_string())
print("\nshare of the pooled sum carried by the single best fold:")
for p in piv.index:
    v = piv.loc[p].dropna()
    tot = v.sum()
    print("  %-9s best fold %+.2f of total %+.2f  -> %.0f %%"
          % (p, v.max(), tot, 100 * v.max() / tot if tot > 0 else float("nan")))
