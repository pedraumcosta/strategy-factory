#!/usr/bin/env python3
"""
Backtest-vs-dry-run parity check - Autotrader Plan Phase 2 gate (d).

The 2020 failure was never noticing that live behaviour did not match the backtest. This
compares the two directly over the SAME window and the same strategy: it reads the dry-run
sqlite and a backtest export, then reports the divergence on the things that actually matter.

Usage (inside the container):
  python parity.py <dryrun.sqlite> <backtest-export.json>
"""
import json, sqlite3, sys
from collections import Counter

def load_dryrun(path):
    c = sqlite3.connect(path)
    cols = {r[1] for r in c.execute("pragma table_info(trades)")}
    exit_col = "exit_reason" if "exit_reason" in cols else "sell_reason"
    rows = list(c.execute(
        f"select pair, open_date, close_date, close_profit, {exit_col}, is_open from trades"))
    return [dict(pair=r[0], open=r[1], close=r[2], profit=r[3], reason=r[4], is_open=r[5]) for r in rows]

def load_backtest(path):
    d = json.load(open(path))
    strat = next(iter(d["strategy"].values()))
    return [dict(pair=t["pair"], open=t["open_date"], close=t["close_date"],
                 profit=t.get("profit_ratio", t.get("profit_percent")),
                 reason=t.get("exit_reason", t.get("sell_reason")), is_open=t.get("open_at_end"))
            for t in strat["trades"]], strat

def summarise(name, trades):
    closed = [t for t in trades if not t["is_open"]]
    n = len(closed)
    tot = sum(t["profit"] or 0 for t in closed)
    wins = sum(1 for t in closed if (t["profit"] or 0) > 0)
    print(f"  {name:<12} trades={n:<5} sum_profit_ratio={tot:+.4f} "
          f"mean={tot/n*100 if n else 0:+.4f}% win={wins/n*100 if n else 0:.1f}%")
    return dict(n=n, tot=tot, wins=wins, closed=closed)

if __name__ == "__main__":
    dr = load_dryrun(sys.argv[1])
    bt, meta = load_backtest(sys.argv[2])
    print("=== parity: dry-run vs backtest ===")
    a = summarise("dry-run", dr)
    b = summarise("backtest", bt)
    print()
    if a["n"] and b["n"]:
        print(f"  trade-count ratio     : {a['n']/b['n']:.2f}x   (1.00 = perfect)")
        print(f"  mean-profit difference: {(a['tot']/a['n'] - b['tot']/b['n'])*100:+.4f} pp per trade")
    print(f"\n  exit reasons dry-run : {Counter(t['reason'] for t in a['closed']).most_common()}")
    print(f"  exit reasons backtest: {Counter(t['reason'] for t in b['closed']).most_common()}")
    pa, pb = Counter(t["pair"] for t in a["closed"]), Counter(t["pair"] for t in b["closed"])
    print("\n  per-pair trade counts (dry-run / backtest):")
    for p in sorted(set(pa) | set(pb)):
        print(f"    {p:<12} {pa.get(p,0):>4} / {pb.get(p,0):>4}")
