"""The dry-run review (S7 → HG3 surface): turn the deploy box's observer
data into a judgment-ready report.

The 30-day dry-run is the Plan §6 Phase-3 gate and the best holdout
available (§18.2) — this module is how that review is conducted *through
the factory*: fetch observer_data/ + dryrun.sqlite (tools/fetch_dryrun.sh),
then `factory dryrun-review <dir>` renders stats, uptime, alerts, trades
and the latest parity report into review.md + a notebook. The verdict
stays human, like every gate worth having.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from factory.observer.parity import dryrun_trades

REVIEW_TARGET_DAYS = 30


def snapshot_stats(snapshots: Path) -> dict:
    n = ok = alerts = 0
    first = last = None
    open_trades_max = 0
    states: dict[str, int] = {}
    with open(snapshots) as f:
        for line in f:
            s = json.loads(line)
            n += 1
            first = first or s["at"]
            last = s["at"]
            if s.get("ok"):
                ok += 1
                st = s.get("state") or "?"
                states[st] = states.get(st, 0) + 1
                open_trades_max = max(open_trades_max, s.get("open_trades") or 0)
            else:
                alerts += 1
    days = 0.0
    if first and last and n > 1:
        fmt = "%Y-%m-%dT%H:%M:%S%z"
        days = (datetime.strptime(last, fmt) - datetime.strptime(first, fmt)
                ).total_seconds() / 86400
    return {"snapshots": n, "ok": ok, "failed": alerts,
            "uptime_ratio": ok / n if n else None,
            "first": first, "last": last, "observed_days": round(days, 2),
            "states": states, "open_trades_max": open_trades_max}


def trade_stats(db: Path) -> dict:
    trades = dryrun_trades(db)
    closed = [t for t in trades if not t["is_open"]
              and t["profit_ratio"] is not None]
    return {"trades": len(trades), "open": sum(t["is_open"] for t in trades),
            "closed": len(closed),
            "wins": sum(t["profit_ratio"] > 0 for t in closed),
            "mean_profit_ratio": (sum(t["profit_ratio"] for t in closed)
                                  / len(closed) if closed else None)}


def assemble(data_dir: Path) -> dict:
    """data_dir holds a fetched observer_data/ (snapshots.jsonl,
    parity_report.md) and dryrun.sqlite."""
    out: dict = {"generated_at": datetime.now().astimezone().isoformat(),
                 "source_dir": str(data_dir)}
    snaps = data_dir / "snapshots.jsonl"
    out["observation"] = (snapshot_stats(snaps) if snaps.exists()
                          else {"error": "no snapshots.jsonl"})
    db = data_dir / "dryrun.sqlite"
    out["trading"] = (trade_stats(db) if db.exists()
                      else {"error": "no dryrun.sqlite"})
    parity_md = data_dir / "parity_report.md"
    out["parity_report"] = (parity_md.read_text() if parity_md.exists()
                            else "(no parity report fetched)")
    days = out["observation"].get("observed_days") or 0
    out["review_complete"] = days >= REVIEW_TARGET_DAYS
    out["days_remaining"] = max(0, round(REVIEW_TARGET_DAYS - days, 1))
    return out


def render(r: dict) -> str:
    o, t = r["observation"], r["trading"]
    lines = [f"# Dry-run review — generated {r['generated_at'][:16]}", ""]
    if r["review_complete"]:
        lines.append(f"**The {REVIEW_TARGET_DAYS}-day window is complete.** "
                     "This review is HG3 evidence: judge it, then approve or "
                     "reject.")
    else:
        lines.append(f"**Interim review** — {o.get('observed_days', 0)} days "
                     f"observed, {r['days_remaining']} to go before the "
                     f"{REVIEW_TARGET_DAYS}-day gate can be judged.")
    lines += ["", "## Observation", ""]
    if "error" in o:
        lines.append(f"- {o['error']}")
    else:
        lines += [
            f"- {o['snapshots']} snapshots from {o['first']} to {o['last']} "
            f"({o['observed_days']} days)",
            f"- uptime: **{o['uptime_ratio']:.1%}** ok "
            f"({o['failed']} failed polls, each one an alert)",
            f"- bot states seen: {o['states']}; max concurrent open trades: "
            f"{o['open_trades_max']}",
        ]
    lines += ["", "## Trading (dry-run DB)", ""]
    if "error" in t:
        lines.append(f"- {t['error']}")
    else:
        lines.append(f"- {t['trades']} trades ({t['open']} open, "
                     f"{t['closed']} closed, {t['wins']} wins)")
        if t["mean_profit_ratio"] is not None:
            lines.append(f"- mean profit ratio on closed trades: "
                         f"{t['mean_profit_ratio']:+.4%}")
    lines += ["", "## Latest parity report", "", r["parity_report"].rstrip(),
              "", "## What this review cannot tell you", "",
              "- Nothing here validates the *strategy* — dry-run measures "
              "execution reality (uptime, fills, parity), not edge.",
              "- A clean 30-day window is also fresh holdout data accruing "
              "on the ledger; spending it still requires HG2b."]
    return "\n".join(lines) + "\n"
