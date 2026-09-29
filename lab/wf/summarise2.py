#!/usr/bin/env python3
"""Summarise the section-14 protocol. Roles are recovered from the fold windows plus run order:
within a fold the control runs before the optimised pair, so of two exports sharing an OOS
window the earlier is the control."""
import glob, json, os, sys, zipfile, datetime as dt, statistics as st

BR="user_data/backtest_results"
wf=json.load(open("user_data/notebooks/walkforward.json"))
def ts(d): return int(dt.datetime.strptime(d,"%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp())
W={}
for f in wf["folds"]:
    a,b=f["is"].split("-");  W[(ts(a),ts(b))]=(f["fold"],"IS")
    a,b=f["oos"].split("-"); W[(ts(a),ts(b))]=(f["fold"],"OOS")

STRAT=sys.argv[1]; SINCE=float(sys.argv[2]) if len(sys.argv)>2 else 0
recs=[]
for mp in glob.glob(f"{BR}/*.meta.json"):
    meta=json.load(open(mp))
    if STRAT not in meta: continue
    m=meta[STRAT]
    if m["backtest_start_time"] < SINCE: continue
    hit=None
    for (a,b),v in W.items():
        if abs(m["backtest_start_ts"]-a)<=3*86400 and abs(m["backtest_end_ts"]-b)<=3*86400:
            hit=v; break
    if not hit: continue
    zp=mp.replace(".meta.json",".zip")
    if not os.path.exists(zp): continue
    with zipfile.ZipFile(zp) as zf:
        n=[x for x in zf.namelist() if x.endswith(".json") and "_config" not in x and not x.endswith(f"_{STRAT}.json")][0]
        r=json.loads(zf.read(n))["strategy"][STRAT]
    tr=[t for t in r["trades"] if not t.get("open_at_end")]
    w=[t["profit_ratio"] for t in tr if t["profit_ratio"]>0]; l=[t["profit_ratio"] for t in tr if t["profit_ratio"]<=0]
    recs.append(dict(fold=hit[0], role=hit[1], t=m["backtest_start_time"],
                     n=r["total_trades"], p=r["profit_total"]*100,
                     win=(r["wins"]/r["total_trades"]*100) if r["total_trades"] else 0,
                     dd=r.get("max_drawdown_account",0)*100,
                     payoff=(st.mean(w)/abs(st.mean(l))) if w and l else float("nan")))

by={}
for r in sorted(recs,key=lambda x:x["t"]):
    k=(r["fold"],r["role"]); by.setdefault(k,[]).append(r)

print(f"=== {STRAT} — section 14 protocol ===")
print(f"  {'fold':<5}{'role':<6}{'trades':>7}{'profit%':>10}{'win%':>7}{'payoff':>8}{'maxDD%':>8}")
IS,OOS,CTL=[],[],[]
for f in sorted({r['fold'] for r in recs}):
    rows=[]
    o=by.get((f,"OOS"),[])
    if o: rows.append(("CTL",o[0]));  CTL.append(o[0]["p"])
    i=by.get((f,"IS"),[])
    if i: rows.append(("IS",i[-1]));  IS.append(i[-1]["p"])
    if len(o)>1: rows.append(("OOS",o[-1])); OOS.append(o[-1]["p"])
    elif o:      rows.append(("OOS*",o[0]))
    for lbl,r in rows:
        print(f"  {f:<5}{lbl:<6}{r['n']:>7}{r['p']:>10.2f}{r['win']:>7.1f}{r['payoff']:>8.2f}{r['dd']:>8.2f}")
    print()
if OOS:
    print(f"  mean IS {st.mean(IS):+.2f}%   mean OOS {st.mean(OOS):+.2f}%   mean CTL {st.mean(CTL):+.2f}%")
    print(f"  OOS-positive folds: {sum(1 for x in OOS if x>0)}/{len(OOS)}")
    print(f"  beat control: {sum(1 for a,b in zip(OOS,CTL) if a>b)}/{len(OOS)}")
elif CTL:
    print(f"  (no optimised arm) mean default-parameter OOS {st.mean(CTL):+.2f}%   positive {sum(1 for x in CTL if x>0)}/{len(CTL)}")
