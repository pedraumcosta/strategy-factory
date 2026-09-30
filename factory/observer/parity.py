"""Phase-3 parity (Autotrader Plan §6 gate (d)): compare the dry-run's
recorded trades against a backtest of the SAME strategy over the SAME
elapsed window. Divergence measures what backtests do not model —
slippage, fill timing, partial data — and after 30 days it is the best
holdout evidence available (Plan §18.2).

Stdlib only: reads the dry-run sqlite directly and the backtest export
zip. The daily loop on the deploy box runs: download recent data →
backtest the elapsed window → this compare → parity_report.md.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path


def dryrun_trades(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT pair, open_date, close_date, close_profit, is_open "
            "FROM trades ORDER BY open_date").fetchall()
    finally:
        con.close()
    return [{"pair": p, "open_date": o, "close_date": c,
             "profit_ratio": pr, "is_open": bool(io)}
            for p, o, c, pr, io in rows]


def backtest_trades(export_zip: Path, strategy: str) -> list[dict]:
    with zipfile.ZipFile(export_zip) as z:
        data = json.loads(z.read(export_zip.name.replace(".zip", ".json")))
    return [{"pair": t["pair"], "open_date": t["open_date"],
             "close_date": t["close_date"], "profit_ratio": t["profit_ratio"]}
            for t in data["strategy"][strategy]["trades"]]


def _day(ts: str) -> str:
    return ts[:10]


def compare(dry: list[dict], bt: list[dict],
            tolerance_days: int = 1) -> dict:
    """Match trades on (pair, open day ± tolerance). Entry timing is the
    load-bearing comparison: a 1d strategy must enter on the same candle in
    both worlds; exits may drift with intrabar stop behavior."""
    matched, unmatched_dry = [], []
    pool = list(bt)
    for d in dry:
        hit = None
        d_open = datetime.fromisoformat(_day(d["open_date"]))
        for b in pool:
            if b["pair"] != d["pair"]:
                continue
            b_open = datetime.fromisoformat(_day(b["open_date"]))
            if abs((d_open - b_open).days) <= tolerance_days:
                hit = b
                break
        if hit is None:
            unmatched_dry.append(d)
        else:
            pool.remove(hit)
            delta = (None if d["is_open"] or d["profit_ratio"] is None
                     else d["profit_ratio"] - hit["profit_ratio"])
            matched.append({"pair": d["pair"], "open": _day(d["open_date"]),
                            "profit_delta": delta})
    closed_deltas = [m["profit_delta"] for m in matched
                     if m["profit_delta"] is not None]
    return {
        "dry_trades": len(dry),
        "backtest_trades": len(bt),
        "matched": len(matched),
        "dry_only": [{"pair": t["pair"], "open": _day(t["open_date"])}
                     for t in unmatched_dry],
        "backtest_only": [{"pair": t["pair"], "open": _day(t["open_date"])}
                          for t in pool],
        "mean_abs_profit_delta": (sum(abs(x) for x in closed_deltas)
                                  / len(closed_deltas)
                                  if closed_deltas else None),
        "matches": matched,
    }


def render(rep: dict, strategy: str, window: str) -> str:
    lines = [f"# Parity report — {strategy} ({window})", "",
             f"- dry-run trades: {rep['dry_trades']}  |  backtest trades: "
             f"{rep['backtest_trades']}  |  matched: {rep['matched']}"]
    if rep["mean_abs_profit_delta"] is not None:
        lines.append(f"- mean |profit delta| on matched closed trades: "
                     f"{rep['mean_abs_profit_delta']:.4%}")
    for key, label in (("dry_only", "dry-run only (backtest missed)"),
                       ("backtest_only", "backtest only (dry-run missed)")):
        if rep[key]:
            lines.append(f"- **{label}:** " + ", ".join(
                f"{t['pair']}@{t['open']}" for t in rep[key]))
    if rep["dry_trades"] == 0 and rep["backtest_trades"] == 0:
        lines.append("- no trades on either side yet — parity vacuously "
                     "holds; the report existing is the point")
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--export", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    dry = dryrun_trades(Path(args.db))
    bt = backtest_trades(Path(args.export), args.strategy)
    rep = compare(dry, bt)
    window = f"as of {datetime.now():%Y-%m-%d}"
    Path(args.out).write_text(render(rep, args.strategy, window))
    print(json.dumps({k: rep[k] for k in
                      ("dry_trades", "backtest_trades", "matched")}))


if __name__ == "__main__":
    main()
