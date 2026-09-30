"""M4 acceptance — re-judge H3 (XSMomentum, fixed defaults) under U1's
purged splitter, through the assembled S5.

Three questions, each answered with a run rather than an argument:

1. Does the factory's S5 reproduce the recorded §15 control column
   (mean OOS +7.40 %, 4/7 folds positive) on the same OOS windows?
2. How much of each fold's in-sample activity sat inside the purge zone —
   the leak surface a hyperopt objective was allowed to fit and purging now
   removes? (For H3 itself the answer changes nothing: fixed parameters,
   identical OOS windows — its rejection is not a splitter artifact.)
3. What is H3's five-year Sharpe worth after deflation by the 276+ trials
   actually on the ledger?

All windows are spent research data (Plan §18.2); nothing clean is touched.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from factory.engine.lab import LabEngine
from factory.ledgers import trials
from factory.orchestrator import manifest as mf
from factory.stages.validate import ValidateSpec, run_validation
from factory.validation import splitter

ROOT = Path(__file__).resolve().parents[1]
WF = json.loads((ROOT / "lab" / "user_data" / "notebooks" / "walkforward.json").read_text())
LEDGER = ROOT / "ledgers" / "trials.jsonl"
GOLDEN = json.loads((ROOT / "fixtures" / "golden" / "reference.json").read_text())

# Autotrader Plan §15, "Control (defaults)" column — the recorded target.
RECORDED_CONTROL = {1: -2.24, 2: 4.72, 3: 15.62, 4: 1.38, 5: 10.25, 6: -3.08, 7: 25.12}


def max_hold_days() -> int:
    fmt = "%Y-%m-%d %H:%M:%S%z"
    worst = 0.0
    for pair, o, c, _p in GOLDEN["expect"]["trades"]:
        dt = (datetime.strptime(c, fmt) - datetime.strptime(o, fmt)).total_seconds() / 86400
        worst = max(worst, dt)
    return int(worst) + 1


def boundary_exposure(engine: LabEngine, purge_days: int) -> list[dict]:
    """Per original fold: trades in the IS window that OPEN inside the last
    `purge_days` before the IS/OOS boundary. Their labels are formed at the
    boundary, which is exactly what a hyperopt objective on this window was
    allowed to fit and what the purge removes."""
    out = []
    for f in WF["folds"]:
        is_range = f["is"]
        boundary = datetime.strptime(is_range.split("-")[1], "%Y%m%d").replace(tzinfo=timezone.utc)
        r = engine.backtest("XSMomentum", "1d", is_range, 0.001)
        trials.append(LEDGER, "backtest", "m4-rejudge",
                      {"strategy": "XSMomentum", "timerange": is_range,
                       "fee": 0.001, "why": "boundary exposure measurement"})
        fmt = "%Y-%m-%d %H:%M:%S%z"
        in_zone = [t for t in r.trades
                   if (boundary - datetime.strptime(t.open_date, fmt)).days < purge_days]
        pnl_zone = sum(t.profit_abs for t in in_zone)
        pnl_all = sum(t.profit_abs for t in r.trades)
        out.append({
            "fold": f["fold"], "is": is_range, "trades": r.trade_count,
            "trades_in_purge_zone": len(in_zone),
            "zone_share_of_trades": len(in_zone) / r.trade_count if r.trade_count else 0,
            "zone_pnl_abs": pnl_zone, "is_pnl_abs": pnl_all,
        })
    return out


if __name__ == "__main__":
    engine = LabEngine()
    purge = max(30, max_hold_days())
    print(f"max hold in the golden run: {max_hold_days() - 1} days -> purge_days={purge}")

    folds = splitter.purge_existing(WF, purge_days=purge)
    for f, orig in zip(folds, WF["folds"]):
        assert f.test_timerange() == orig["oos"]  # OOS identical by construction

    run_dir = mf.new_run("M4 acceptance: re-judge H3 under the purged splitter", ROOT / "runs")
    m = mf.load(run_dir)
    for s in ["S0", "S1", "S2", "S3", "S4"]:
        m.stages[s] = {"status": "passed",
                       "report": "method-validation rerun of a recorded result; not a new hypothesis"}
    mf.save(run_dir, m)

    print("running S5 (7 OOS folds + 5-point cost sweep + full range + DSR)...")
    spec = ValidateSpec(
        strategy="XSMomentum", timeframe="1d", fee=0.001, folds=folds,
        full_timerange="20210101-20260101",
        notes={"purge_days": purge,
               "why": "M4 acceptance; all windows already spent (Plan §18.2)"},
    )
    res = run_validation(engine, spec, run_dir, LEDGER)
    d = json.loads((run_dir / "artifacts" / "dossier.json").read_text())

    print("measuring boundary exposure on the original IS windows...")
    exposure = boundary_exposure(engine, purge)

    comparison = {
        "recorded_control_§15": RECORDED_CONTROL,
        "factory_oos": {f["fold"]: round(f["profit_total"] * 100, 2)
                        for f in d["walkforward"]["folds"]},
        "recorded_mean": 7.40,
        "factory_mean": round(d["walkforward"]["mean_oos"] * 100, 2),
        "boundary_exposure": exposure,
        "stage_result": {"status": res.status, "report": res.report},
    }
    (run_dir / "artifacts" / "rejudge_comparison.json").write_text(
        json.dumps(comparison, indent=1))

    print(f"\n{'fold':>4} {'recorded':>10} {'factory':>10}")
    for k in sorted(RECORDED_CONTROL):
        print(f"{k:>4} {RECORDED_CONTROL[k]:>+9.2f}% {comparison['factory_oos'].get(k, float('nan')):>+9.2f}%")
    print(f"mean {comparison['recorded_mean']:>+9.2f}% {comparison['factory_mean']:>+9.2f}%")
    print(f"\nboundary exposure (per fold, purge zone = last {purge}d of IS):")
    for e in exposure:
        print(f"  fold {e['fold']}: {e['trades_in_purge_zone']}/{e['trades']} trades open in zone "
              f"({e['zone_share_of_trades']:.1%}), zone P&L {e['zone_pnl_abs']:+.1f} of {e['is_pnl_abs']:+.1f}")
    ds = d.get("deflated_sharpe", {})
    if "dsr" in ds:
        print(f"\nH3 five-year: SR {ds['sr_annualized']:.2f} annualized, "
              f"n_trials={ds['n_trials']} -> SR0={ds['sr0']:.4f}/period, DSR={ds['dsr']:.3f}")
    print(f"\nS5 verdict: {res.status} — {res.report}")
    print(f"run dir: {run_dir}")
