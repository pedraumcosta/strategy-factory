#!/usr/bin/env python3
"""tearsheet.py - Autotrader Plan section 20.7 step 2. REPORTING ONLY, no new gates.

Section 20.2 B's argument: H3 failed G5 because September 2026 alone was 70 % of the profit
(section 17), and establishing that took a --breakdown month table and a careful reading. A
monthly-returns heatmap and an underwater plot show it instantly. So every candidate gets one.

Two things freqtrade 2026.8 already puts in every export, which this script simply uses:
  *_wallet.feather        per-currency balance per date -> sum total_quote = a true
                          mark-to-market equity curve, not a trade-close P&L sum.
  *_market_change.feather 'rel_mean' = the EQUAL-WEIGHT mean change of the whole pairlist.
                          That is the G-passive benchmark (section 22), already computed, so
                          G-passive is evaluable on every run ever exported at no cost.

Usage (research image - pyfolio is not in the backtest image, and the research image has a
DIFFERENT pandas, so never run a backtest with it):
  docker run --rm --user "$(id -u):$(id -g)" -e PYTHONPATH=/wf \
    -v "$PWD/user_data:/freqtrade/user_data" -v "$PWD/wf:/wf" \
    --entrypoint python3 freqtrade-lab:2026.8-research /wf/tearsheet.py [TAG|--list]

TAG is the export stamp, e.g. 2026-09-29_15-17-02. Default is H3's holdout run.
"""
import glob
import io
import json
import os
import sys
import warnings
import zipfile

warnings.filterwarnings("ignore")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BR = "/freqtrade/user_data/backtest_results"
OUT = "/freqtrade/user_data/tearsheets"
DEFAULT_TAG = "2026-09-29_15-17-02"       # H3's holdout: 123 trades, +7.33 %, section 17


def list_exports():
    rows = []
    for m in sorted(glob.glob(f"{BR}/*.meta.json")):
        d = json.load(open(m))
        for strat, v in d.items():
            rows.append(dict(tag=os.path.basename(m)[len("backtest-result-"):-len(".meta.json")],
                             strategy=strat,
                             start=pd.to_datetime(v["backtest_start_ts"], unit="s").date(),
                             end=pd.to_datetime(v["backtest_end_ts"], unit="s").date()))
    return pd.DataFrame(rows)


def load(tag):
    zp = f"{BR}/backtest-result-{tag}.zip"
    z = zipfile.ZipFile(zp)
    names = z.namelist()
    main = [n for n in names if n.endswith(".json") and "_config" not in n
            and n.count("_") == 1][0]
    res = json.loads(z.read(main))["strategy"]
    strat = list(res)[0]
    r = res[strat]

    wname = [n for n in names if n.endswith("_wallet.feather")]
    mname = [n for n in names if n.endswith("_market_change.feather")]
    if not wname:
        raise SystemExit(f"{tag}: no wallet.feather in the export - rerun the backtest to get one")
    w = pd.read_feather(io.BytesIO(z.read(wname[0])))
    equity = w.groupby("date")["total_quote"].sum().sort_index()
    equity.index = pd.DatetimeIndex(equity.index).tz_localize(None).normalize()
    equity = equity.groupby(level=0).last()
    rets = equity.pct_change().dropna()

    # EXPOSURE: the share of equity actually in the market. Needed because a low-exposure book
    # fails a raw total-return comparison against buy-and-hold for reasons that have nothing to
    # do with skill - see the G-passive caveat in section 23.
    stake = (json.loads(z.read([n for n in names if n.endswith("_config.json")][0]))
             .get("stake_currency", "USDT"))
    w2 = w.copy()
    w2["date"] = pd.DatetimeIndex(w2["date"]).tz_localize(None).normalize()
    tot_by_day = w2.groupby("date")["total_quote"].sum()
    cash_by_day = (w2[w2.currency == stake].groupby("date")["total_quote"].sum()
                   .reindex(tot_by_day.index).fillna(0.0))
    exposure = (1.0 - cash_by_day / tot_by_day.replace(0, np.nan)).clip(0, None)
    exposure = exposure.groupby(level=0).last()

    bench = None
    if mname:
        mc = pd.read_feather(io.BytesIO(z.read(mname[0])))
        b = mc.set_index("date")["rel_mean"].sort_index()
        b.index = pd.DatetimeIndex(b.index).tz_localize(None).normalize()
        b = b.groupby(level=0).last()           # one row per day, no duplicate labels
        bench = ((1 + b) / (1 + b).shift(1) - 1).dropna()   # rel_mean is cumulative -> daily
    return strat, r, equity, rets, bench, exposure


def monthly(x):
    return (1 + x).resample("ME").prod() - 1


def gpassive_sweep():
    """G-passive (section 22) on EVERY export that carries a market_change.feather.

    This is retroactive and free: the equal-weight universe benchmark was written into every
    backtest export all along, so every result in sections 13-17 can be re-judged against
    buy-and-hold without rerunning anything. Reads only already-spent windows.
    """
    rows = []
    for zp in sorted(glob.glob(f"{BR}/*.zip")):
        tag = os.path.basename(zp)[len("backtest-result-"):-len(".zip")]
        try:
            strat, r, equity, rets, bench, exposure = load(tag)
        except Exception:
            continue
        if bench is None or len(rets) < 20:
            continue
        tot = (1 + rets).prod() - 1
        btot = (1 + bench).prod() - 1
        m, mb = monthly(rets), monthly(bench)
        k = min(len(m), len(mb))
        exp = float(exposure.reindex(rets.index).mean())
        # the like-for-like benchmark: the universe held at the candidate's own exposure,
        # the rest in cash. This is what isolates timing/selection from simply being invested.
        scaled = (1 + bench.reindex(rets.index).fillna(0.0) * exp).prod() - 1
        rows.append(dict(strategy=strat, tag=tag,
                         start=str(equity.index.min().date()), end=str(equity.index.max().date()),
                         days=len(equity), trades=r["total_trades"], exposure=exp,
                         strat_pct=tot * 100, universe_pct=btot * 100,
                         excess_pp=(tot - btot) * 100,
                         scaled_pct=scaled * 100, excess_vs_scaled_pp=(tot - scaled) * 100,
                         months_beaten=f"{int((m.values[:k] > mb.values[:k]).sum())}/{k}",
                         passes=tot > btot, passes_scaled=tot > scaled))
    df = pd.DataFrame(rows)
    if df.empty:
        print("no exports carry a market_change.feather")
        return
    # one row per (strategy, window): keep the newest export
    df = df.sort_values("tag").groupby(["strategy", "start", "end"], as_index=False).last()
    df = df.sort_values(["strategy", "start"])
    df.to_csv("/freqtrade/user_data/gpassive.csv", index=False)
    pd.set_option("display.width", 200, "display.max_rows", 400)
    print("=" * 110)
    print("G-PASSIVE, RETROACTIVE - every exported run vs the equal-weight universe it traded")
    print("  The benchmark was in market_change.feather all along. Nothing was rerun.")
    print("=" * 110)
    print(df[["strategy", "start", "end", "trades", "exposure", "strat_pct", "universe_pct",
              "excess_pp", "scaled_pct", "excess_vs_scaled_pp", "passes",
              "passes_scaled"]].round(3).to_string(index=False))
    print(f"\nRAW G-passive (vs fully-invested buy-and-hold): "
          f"{int(df.passes.sum())} of {len(df)} runs pass")
    print(f"EXPOSURE-SCALED G-passive (vs the universe held at the candidate's own exposure): "
          f"{int(df.passes_scaled.sum())} of {len(df)} runs pass")
    print("  The scaled column is the one that means something - see section 23.")
    for st, g in df.groupby("strategy"):
        print(f"  {st:<16} raw {int(g.passes.sum())}/{len(g)}   "
              f"scaled {int(g.passes_scaled.sum())}/{len(g)}   "
              f"mean exposure {g.exposure.mean():.2f}")
    print("\nCSV: user_data/gpassive.csv")


def main():
    os.makedirs(OUT, exist_ok=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TAG
    if arg == "--list":
        print(list_exports().to_string(index=False))
        return
    if arg == "--gpassive":
        gpassive_sweep()
        return
    strat, r, equity, rets, bench, exposure = load(arg)

    print("=" * 96)
    print(f"TEAR SHEET - {strat}, export {arg}")
    print(f"  {equity.index.min().date()} -> {equity.index.max().date()}, "
          f"{len(equity)} days, {r['total_trades']} trades")
    print("=" * 96)

    tot = (1 + rets).prod() - 1
    print(f"  total return (mark-to-market equity) {tot*100:+.2f} %"
          f"   | freqtrade reports {r['profit_total']*100:+.2f} %")
    dd = (equity / equity.cummax() - 1)
    print(f"  max drawdown {dd.min()*100:.2f} %   | freqtrade reports "
          f"{r.get('max_drawdown_account', 0)*100:.2f} %")
    print("    (these differ by design: freqtrade measures at trade-close points, this measures"
          " DAILY\n     mark-to-market including open positions, so it is the stricter number)")
    ann = (1 + rets.mean()) ** 365 - 1
    vol = rets.std() * np.sqrt(365)
    print(f"  annualised return {ann*100:+.1f} %   vol {vol*100:.1f} %   "
          f"Sharpe {ann/vol if vol else float('nan'):.2f}   [365-day year]")
    print("    (pyfolio below annualises on a 252-day EQUITY year; crypto trades 365, so its"
          "\n     Sharpe and annual figures read low here. Use these, not those.)")

    print("\n--- MONTHLY RETURNS, the picture section 20.2 B asked for ---")
    m = monthly(rets)
    mb = monthly(bench) if bench is not None else None
    for i, (d, v) in enumerate(m.items()):
        bar = "#" * int(abs(v) * 200)
        extra = f"   universe {mb.iloc[i]*100:+7.2f} %" if mb is not None and i < len(mb) else ""
        print(f"  {d.strftime('%Y-%m')}  {v*100:+7.2f} %  {bar}{extra}")
    pos = m[m > 0].sum()
    print(f"\n  positive months: {int((m>0).sum())} of {len(m)}")
    bm = m.idxmax().strftime('%Y-%m')
    print(f"  best month {bm} = {m.max()*100:+.2f} %")
    print(f"    as a share of TOTAL return          {m.max()/tot*100:5.0f} %   "
          f"<- this is section 17's G5 metric (it reported 70 % for H3)")
    print(f"    as a share of positive months' sum  {m.max()/pos*100:5.0f} %")
    top2 = m.nlargest(2)
    print(f"  best TWO months {', '.join(d.strftime('%Y-%m') for d in top2.index)} = "
          f"{top2.sum()/tot*100:.0f} % of total return")
    print("  (two denominators because they answer different questions; report both and say which)")

    if bench is not None:
        btot = (1 + bench).prod() - 1
        print("\n--- G-PASSIVE (section 22), from the export's own market_change.feather ---")
        print(f"  strategy {tot*100:+.2f} %   equal-weight universe {btot*100:+.2f} %   "
              f"excess {(tot-btot)*100:+.2f} pp")
        if mb is not None:
            k = min(len(m), len(mb))
            print(f"  months beating the universe: {int((m.values[:k] > mb.values[:k]).sum())} of {k}")
        print(f"  VERDICT: {'PASS' if tot > btot else 'FAIL'} - "
              f"{'beats' if tot > btot else 'loses to'} equal-weight buy-and-hold")

    # ---- the two load-bearing pictures, plus the benchmark overlay ----
    fig, ax = plt.subplots(3, 1, figsize=(11, 12),
                           gridspec_kw={"height_ratios": [2, 1.4, 1.4]})
    eq = equity / equity.iloc[0]
    ax[0].plot(eq.index, (eq - 1) * 100, lw=1.8, label=f"{strat} (mark-to-market)")
    if bench is not None:
        bc = (1 + bench).cumprod()
        ax[0].plot(bc.index, (bc - 1) * 100, lw=1.4, ls="--",
                   label="equal-weight universe (G-passive benchmark)")
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_title(f"{strat} — {arg}", fontsize=11)
    ax[0].set_ylabel("cumulative return %")
    ax[0].legend(fontsize=8)
    ax[0].grid(alpha=0.25)

    ax[1].fill_between(dd.index, dd.values * 100, 0, color="firebrick", alpha=0.35)
    ax[1].set_title("underwater — depth and duration of every drawdown", fontsize=10)
    ax[1].set_ylabel("drawdown %")
    ax[1].grid(alpha=0.25)

    cols = ["seagreen" if v > 0 else "firebrick" for v in m.values]
    ax[2].bar([d.strftime("%Y-%m") for d in m.index], m.values * 100, color=cols, alpha=0.85)
    if mb is not None:
        k = min(len(m), len(mb))
        ax[2].plot(range(k), mb.values[:k] * 100, "k.--", lw=1, ms=5,
                   label="equal-weight universe")
        ax[2].legend(fontsize=8)
    ax[2].axhline(0, color="k", lw=0.6)
    ax[2].set_title("monthly returns — return concentration is visible here or nowhere",
                    fontsize=10)
    ax[2].set_ylabel("%")
    ax[2].tick_params(axis="x", rotation=60, labelsize=8)
    ax[2].grid(alpha=0.25, axis="y")
    fig.tight_layout()
    png = f"{OUT}/{strat}-{arg}.png"
    fig.savefig(png, dpi=110)
    print(f"\n  figure: user_data/tearsheets/{os.path.basename(png)}")

    # pyfolio's own tear sheet, for the metrics this script does not reimplement
    try:
        import pyfolio as pf
        stats = pf.timeseries.perf_stats(rets)
        print("\n--- pyfolio perf_stats (reporting only, never a gate) ---")
        print(stats.round(3).to_string())
        b = bench.reindex(rets.index).fillna(0.0) if bench is not None else None
        with plt.rc_context({"figure.max_open_warning": 0}):
            fig2 = pf.create_returns_tear_sheet(rets, benchmark_rets=b, return_fig=True)
            fig2.savefig(f"{OUT}/{strat}-{arg}-pyfolio.png", dpi=90)
        print(f"  figure: user_data/tearsheets/{strat}-{arg}-pyfolio.png")
    except Exception as e:
        print(f"\n  (pyfolio tear sheet skipped: {e})")


if __name__ == "__main__":
    main()
