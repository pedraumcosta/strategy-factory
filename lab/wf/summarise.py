#!/usr/bin/env python3
"""Map every backtest export onto its walk-forward fold and print the IS-vs-OOS table.

freqtrade 2026.8 ignores --export-filename, so exports land in user_data/backtest_results as
timestamped zips. Each has a .meta.json carrying the strategy name and the backtest start/end
timestamps, which identifies the fold and role unambiguously - no reliance on file ordering.
"""
import glob, json, os, zipfile, datetime as dt

BR = "user_data/backtest_results"
wf = json.load(open("user_data/notebooks/walkforward.json"))

def ts(datestr):  # 'YYYYMMDD' -> unix seconds UTC
    return int(dt.datetime.strptime(datestr, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp())

windows = {}
for f in wf["folds"]:
    a, b = f["is"].split("-"); windows[(ts(a), ts(b))] = (f["fold"], "IS")
    a, b = f["oos"].split("-"); windows[(ts(a), ts(b))] = (f["fold"], "OOS")

rows = []
for meta_path in sorted(glob.glob(f"{BR}/*.meta.json")):
    meta = json.load(open(meta_path))
    for strat, m in meta.items():
        # Match within a tolerance: when a fold's window starts exactly where the data starts,
        # freqtrade shifts the reported start forward by startup_candle_count (20h here), so an
        # exact timestamp match silently drops that fold.
        TOL = 3 * 86400
        hit = None
        for (a, b), v in windows.items():
            if abs(m["backtest_start_ts"] - a) <= TOL and abs(m["backtest_end_ts"] - b) <= TOL:
                hit = v; break
        if hit is None:
            continue
        fold, role = hit
        if strat != "BBRSIStrategy":
            role = "CTL"
        zpath = meta_path.replace(".meta.json", ".zip")
        if not os.path.exists(zpath):
            continue
        with zipfile.ZipFile(zpath) as z:
            name = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n
                    and not n.endswith(f"_{strat}.json")][0]
            res = json.loads(z.read(name))["strategy"][strat]
        rows.append(dict(fold=fold, role=role, strat=strat,
                         trades=res["total_trades"],
                         profit_pct=res["profit_total"] * 100,
                         win=(res["wins"] / res["total_trades"] * 100) if res["total_trades"] else 0,
                         dd=res.get("max_drawdown_account", res.get("max_drawdown", 0)) * 100,
                         sharpe=res.get("sharpe", 0), mtime=os.path.getmtime(meta_path)))

# keep the newest export per (fold, role)
best = {}
for r in rows:
    k = (r["fold"], r["role"])
    if k not in best or r["mtime"] > best[k]["mtime"]:
        best[k] = r

print("=== Walk-forward: 17 USDT pairs, 1h, fee 0.1%/side, 100 hyperopt epochs per fold ===")
print("  BBRSI optimised in-sample, then applied unchanged out-of-sample.")
print("  CTL = Strategy005v0, fixed rules, no parameters -> cannot be overfitted.\n")
hdr = f"  {'fold':<5}{'window':<8}{'trades':>7}{'profit%':>10}{'win%':>7}{'maxDD%':>8}{'sharpe':>8}"
print(hdr); print("  " + "-" * (len(hdr) - 2))
deg = []
for f in sorted({r["fold"] for r in best.values()}):
    for role in ("IS", "OOS", "CTL"):
        r = best.get((f, role))
        if not r: continue
        print(f"  {f:<5}{role:<8}{r['trades']:>7}{r['profit_pct']:>10.2f}{r['win']:>7.1f}{r['dd']:>8.2f}{r['sharpe']:>8.2f}")
    i, o = best.get((f, "IS")), best.get((f, "OOS"))
    if i and o: deg.append((f, i["profit_pct"], o["profit_pct"]))
    print()

if deg:
    print("=== in-sample -> out-of-sample degradation (the number that matters) ===")
    for f, i, o in deg:
        print(f"  fold {f}:  IS {i:+7.2f}%   OOS {o:+7.2f}%   delta {o-i:+7.2f} pp")
    ISm = sum(i for _, i, _ in deg) / len(deg); OOSm = sum(o for _, _, o in deg) / len(deg)
    print(f"\n  mean IS {ISm:+.2f}%   mean OOS {OOSm:+.2f}%   mean delta {OOSm-ISm:+.2f} pp")
    pos = sum(1 for _, _, o in deg if o > 0)
    print(f"  folds profitable out-of-sample: {pos}/{len(deg)}")
    ctl = [best[(f,'CTL')]['profit_pct'] for f,_,_ in deg if (f,'CTL') in best]
    if ctl:
        print(f"  mean control (unoptimised) OOS: {sum(ctl)/len(ctl):+.2f}%")
        beat = sum(1 for (f,_,o) in deg if (f,'CTL') in best and o > best[(f,'CTL')]['profit_pct'])
        print(f"  folds where optimisation beat the fixed-rule control: {beat}/{len(ctl)}")
