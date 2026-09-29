#!/usr/bin/env python3
"""factor_portfolio.py - the fix to factor_screen.py's concentration metric, and the
closest thing to H3 that can be computed without freqtrade.

The problem it fixes. factor_screen.py measured concentration as the monthly mean of
OVERLAPPING 21-day top-quintile forward returns. Section 17 measured something else: the
monthly P&L of a top-k portfolio over 123 trades. The first is a far smoother object, which
is why the screen's concentration number for XSMomentum (13.0 %) came out BELOW the noise
control (19.5 %) - the metric was not measuring what it claimed to. This script measures the
portfolio, which is the thing section 17's G5 was about.

Built: a daily-rebalanced, equal-weight, long-only top-k portfolio on the same factor
(k=3, matching H3's fixed a-priori top_k), against an equal-weight-all-17 passive control.
Returns are gross - cost is applied separately at the measured rate so the two questions stay
separate, exactly as section 13 insisted.

Protocol: the 7 walk-forward IN-SAMPLE halves only. 2026 is never read.
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import factor_screen as fs

TOPK = 3                 # H3's fixed value
COST_RT = 0.1556 / 100   # measured 2020 round trip, section 12
px = fs.load_prices()
ret1 = px.pct_change()
lb = fs.LOOKBACK
score = px.pct_change(lb) / px.pct_change().rolling(lb).std().replace(0, np.nan)


def portfolio(score_wide, start, end, k=TOPK, lag=2):
    """Equal-weight long-only top-k, rebalanced daily. lag=2 mirrors the strategy's
    score(t-1) -> signal(t) -> fill(t+1) chain, so this is not kinder than the real thing."""
    sc = score_wide.loc[start:end]
    r = ret1.loc[start:end]
    rank = sc.rank(axis=1, ascending=False, method="first")
    w = (rank <= k).astype(float)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).shift(lag)
    port = (w * r).sum(axis=1, min_count=1)
    turn = w.diff().abs().sum(axis=1) / 2.0        # one-way weight change per day
    ew = r.mean(axis=1)
    return port.dropna(), ew.reindex(port.dropna().index), turn.reindex(port.dropna().index)


def stats(p, ew, turn, label):
    mon = (1 + p).resample("ME").prod() - 1
    monew = (1 + ew).resample("ME").prod() - 1
    tot = (1 + p).prod() - 1
    totew = (1 + ew).prod() - 1
    pos = mon[mon > 0].sum()
    cost_drag = turn.sum() * COST_RT
    return dict(label=label, months=len(mon),
                gross_total_pct=tot * 100, equalweight_total_pct=totew * 100,
                excess_pct=(tot - totew) * 100,
                net_total_pct=(tot - cost_drag) * 100,
                cost_drag_pct=cost_drag * 100,
                turnover_per_day=turn.mean(),
                best_month_share_pct=(mon.max() / pos * 100) if pos > 0 else np.nan,
                pos_months_pct=(mon > 0).mean() * 100,
                beat_ew_months_pct=(mon > monew).mean() * 100)


rows = []
for fid, s, e in fs.FOLDS:
    p, ew, t = portfolio(score, s, e)
    rows.append({**stats(p, ew, t, f"fold {fid}"), "fold": fid})
p, ew, t = portfolio(score, fs.FOLDS[0][1], fs.FOLDS[-1][2])
rows.append({**stats(p, ew, t, "POOLED"), "fold": "pooled"})
df = pd.DataFrame(rows)
df.to_csv("/freqtrade/user_data/factor_portfolio.csv", index=False)
pd.set_option("display.width", 220)

print("=" * 108)
print(f"TOP-{TOPK} PORTFOLIO vs EQUAL-WEIGHT-17, gross, 2-bar lag, in-sample halves only")
print("=" * 108)
print(df.set_index("fold")[["gross_total_pct", "equalweight_total_pct", "excess_pct",
                            "cost_drag_pct", "net_total_pct", "turnover_per_day"]]
      .round(2).to_string())
x = df[df.fold != "pooled"]
print(f"\nfolds where top-{TOPK} beat equal weight GROSS: {int((x.excess_pct > 0).sum())} of {len(x)}")
print(f"folds with a positive gross return:            {int((x.gross_total_pct > 0).sum())} of {len(x)}")
print(f"folds with a positive NET return:              {int((x.net_total_pct > 0).sum())} of {len(x)}")

print("\n" + "=" * 108)
print("CONCENTRATION, measured on the PORTFOLIO - the metric factor_screen.py got wrong")
print("  best_month_share = single best month / sum of all positive months.")
print("  Section 17 rejected H3 on the holdout at 70 %. This is the in-sample analogue.")
print("=" * 108)
print(df.set_index("fold")[["months", "best_month_share_pct", "pos_months_pct",
                            "beat_ew_months_pct"]].round(1).to_string())

print("\n" + "=" * 108)
print("CONTROLS - same construction on the two calibration factors")
print("=" * 108)
rng = np.random.default_rng(20260929)
noise = pd.DataFrame(rng.standard_normal(px.shape), index=px.index, columns=px.columns)
oracle = px.shift(-21) / px - 1.0
ctl = []
for nm, sw in (("XSMomentum", score), ("NOISE", noise), ("ORACLE", oracle)):
    pp, ee, tt = portfolio(sw, fs.FOLDS[0][1], fs.FOLDS[-1][2])
    ctl.append({**stats(pp, ee, tt, nm), "factor": nm})
c = pd.DataFrame(ctl).set_index("factor")
print(c[["gross_total_pct", "equalweight_total_pct", "excess_pct", "net_total_pct",
         "turnover_per_day", "best_month_share_pct", "pos_months_pct"]].round(2).to_string())

print("\n" + "=" * 108)
print("THE 3x COST TEST on the top-k portfolio")
print("=" * 108)
pooled = df[df.fold == "pooled"].iloc[0]
# per-round-trip edge: excess return spread over the number of round trips implied by turnover
rt = t.sum()          # total one-way weight turnover = round trips in units of full positions
edge_per_rt = (pooled.excess_pct / 100) / rt * 100 if rt > 0 else np.nan
print(f"total one-way turnover (round trips, position units): {rt:.1f}")
print(f"gross excess over equal weight: {pooled.excess_pct:+.2f} %")
print(f"=> gross excess per round trip: {edge_per_rt:+.4f} %")
print(f"   gate: 0.600 % (3 x 0.2 %) / 0.467 % (3 x 0.1556 %)")
print(f"   cost coverage: {edge_per_rt / (0.1556):.2f}x  (needs 3x)")
print("\nCSV: user_data/factor_portfolio.csv")
