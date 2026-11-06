"""S5 — the validation stage: the full gauntlet on in-sample folds.

Deterministic by design: purged walk-forward OOS runs, a cost sweep with
the zero-fee sanity and cost-coverage gates (the cost model carries the
card's turnover — a tilt is charged what it transacts at S5 exactly as at
S2), and a deflated Sharpe whose trial count comes from the ledger. Emits
a dossier (json + md) and, when papermill is available, executes the
review notebook that is HG2's reviewing surface. The stage never passes a
run outright: the best it returns is needs_human — HG2 is a judgment, not
a checkbox.

The engine here is a RecordedEngine: every backtest it runs is already a
trial on the ledger, so this stage appends nothing by hand. DSR, the tear
sheet and G-passive are all computed from ONE parse of the full-range
export (gpassive.curves_from_export: the daily mark-to-market curve), so
they cannot drift onto different return series. A failure computing them
raises — the runner marks the stage resumable; an uncomputable dossier
section is a factory defect, not a footnote.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path

from factory.costs import WORKING, CostModel
from factory.gates import core
from factory.orchestrator import manifest as mf
from factory.orchestrator.runner import StageResult
from factory.validation import deflation
from factory.validation.splitter import Fold


@dataclass
class ValidateSpec:
    strategy: str
    timeframe: str
    folds: list[Fold]
    full_timerange: str
    costs: CostModel = WORKING
    turnover_per_trade: float = 1.0  # from the card — Plan §17.10
    strategy_path: Path | None = None
    periods_per_year: int = 365
    notes: dict = field(default_factory=dict)

    @property
    def fee(self) -> float:
        return self.costs.fee_per_side


def run_validation(engine, spec: ValidateSpec, run_dir: Path,
                   trial_ledger: Path) -> StageResult:
    art = mf.artifacts_dir(run_dir)
    dossier: dict = {"spec": {
        "strategy": spec.strategy, "timeframe": spec.timeframe, "fee": spec.fee,
        "turnover_per_trade": spec.turnover_per_trade,
        "folds": [{"n": f.n, "train": f.train_timerange(), "test": f.test_timerange(),
                   "purge_gap_days": f.purge_gap_days} for f in spec.folds],
        "full_timerange": spec.full_timerange, **spec.notes,
    }}

    def bt(timerange: str, fee: float, why: str):
        return engine.backtest(
            spec.strategy, spec.timeframe, timerange, fee,
            run_id=run_dir.name, why=why, strategy_path=spec.strategy_path,
        )

    # 1 — purged walk-forward OOS
    folds_out = []
    for f in spec.folds:
        r = bt(f.test_timerange(), spec.fee, f"oos fold {f.n}")
        folds_out.append({"fold": f.n, "test": f.test_timerange(),
                          "trades": r.trade_count, "profit_total": r.profit_total})
    oos = [f["profit_total"] for f in folds_out]
    dossier["walkforward"] = {
        "folds": folds_out,
        "mean_oos": sum(oos) / len(oos),
        "positive_folds": sum(p > 0 for p in oos),
    }

    # 2 — cost sweep incl. zero fee
    sweep = []
    for fee in spec.costs.sweep_fees:
        r = bt(spec.full_timerange, fee, "cost sweep")
        sweep.append({"fee": fee, "trades": r.trade_count,
                      "profit_total": r.profit_total,
                      # per-trade return ON STAKE — the 3x rule's basis
                      "mean_per_trade": r.profit_mean})
    dossier["cost_sweep"] = sweep
    zero = next(s for s in sweep if s["fee"] == 0.0)
    gates = [
        core.zero_fee_sanity(zero["profit_total"]),
        spec.costs.coverage(zero["mean_per_trade"],
                            turnover_per_trade=spec.turnover_per_trade),
    ]

    # 3 — full-range run at the working fee: ONE export parse feeds DSR,
    # the tear sheet and G-passive the same daily mark-to-market series
    full = bt(spec.full_timerange, spec.fee, "full range")
    dossier["full_range"] = {"trades": full.trade_count,
                             "profit_total": full.profit_total,
                             **trade_shape(full.trades)}
    from factory.validation import gpassive
    curves = gpassive.curves_from_export(full.export_zip, spec.strategy)
    dossier["deflated_sharpe"] = deflation.deflate(
        curves.rets.tolist(), trial_ledger, spec.timeframe,
        spec.periods_per_year)

    # 4 — tear sheet + G-passive (§22/§23) from the same curves
    tear, gp = gpassive.judge(curves, spec.periods_per_year)
    if gpassive.render_png(curves, spec.strategy, art / mf.TEARSHEET_PNG):
        tear["figure"] = mf.TEARSHEET_PNG
    dossier["tear_sheet"] = tear
    dossier["g_passive"] = gp

    dossier["gates"] = [
        {"gate": g.gate, "passed": g.passed, "reason": g.reason, "numbers": g.numbers}
        for g in gates
    ]
    killed = [g for g in gates if not g.passed]

    (art / mf.DOSSIER_JSON).write_text(json.dumps(dossier, indent=1))
    (art / mf.DOSSIER_MD).write_text(_render_md(dossier))
    _execute_notebook(run_dir)

    if killed:
        return StageResult("killed",
                           "; ".join(f"{g.gate}: {g.reason}" for g in killed),
                           {"dossier": f"artifacts/{mf.DOSSIER_JSON}"})
    return StageResult("needs_human",
                       "all deterministic gates passed — HG2 review required",
                       {"dossier": f"artifacts/{mf.DOSSIER_JSON}"})


def trade_shape(trades) -> dict:
    """Protocol-checkable facts from the trade list: the maximum realized
    holding period (a pre-registration that sized its purge must be able to
    verify it) and monthly P&L concentration (G-conc — one month carrying
    the result is the §17 failure; not screenable, so it must at least be
    REPORTED here, even though the judgment stays human)."""
    if not trades:
        return {"max_hold_days": 0, "best_month_share": None}
    fmt = "%Y-%m-%d %H:%M:%S%z"
    max_hold = 0.0
    monthly: dict[str, float] = defaultdict(float)
    total = 0.0
    for t in trades:
        o = datetime.strptime(t.open_date, fmt)
        c = datetime.strptime(t.close_date, fmt)
        max_hold = max(max_hold, (c - o).total_seconds() / 86400)
        monthly[c.strftime("%Y-%m")] += t.profit_abs
        total += t.profit_abs
    best_month, best_pnl = max(monthly.items(), key=lambda kv: kv[1])
    share = best_pnl / total if total > 0 else None
    return {"max_hold_days": round(max_hold, 1),
            "best_month": best_month,
            "best_month_share": None if share is None else round(share, 3)}


def _render_md(d: dict) -> str:
    w, sp = d["walkforward"], d["spec"]
    lines = [
        f"# Validation dossier — {sp['strategy']}",
        "",
        f"Timeframe {sp['timeframe']}, fee {sp['fee']}, full range {sp['full_timerange']}.",
        "",
        "## Purged walk-forward (OOS)",
        "",
        "| fold | test window | trades | return |",
        "|---|---|---|---|",
    ]
    for f in w["folds"]:
        lines.append(f"| {f['fold']} | {f['test']} | {f['trades']} | {f['profit_total']:+.2%} |")
    lines += [f"| **mean** | | | **{w['mean_oos']:+.2%}** ({w['positive_folds']}/{len(w['folds'])} positive) |",
              "", "## Cost sweep", "",
              "| fee/side | trades | total return | mean/trade |", "|---|---|---|---|"]
    for s in d["cost_sweep"]:
        lines.append(f"| {s['fee']:.4f} | {s['trades']} | {s['profit_total']:+.2%} | {s['mean_per_trade']:+.4%} |")
    fr = d["full_range"]
    lines += ["", "## Trade shape (full range)", "",
              f"- max realized hold: **{fr.get('max_hold_days', '?')} days** "
              f"(check against the pre-registered purge)",
              f"- best month {fr.get('best_month', '?')} holds "
              f"**{fr['best_month_share']:.0%}** of total profit (G-conc)"
              if fr.get("best_month_share") is not None else
              "- monthly concentration: not computable (no/negative total)"]
    ds = d.get("deflated_sharpe", {})
    lines += ["", "## Deflated Sharpe", ""]
    if "dsr" in ds:
        lines += [
            f"- annualized SR **{ds['sr_annualized']:.2f}** over {ds['n_obs']} daily obs "
            f"(skew {ds['skew']:+.2f}, kurt {ds['kurt']:.1f})",
            f"- deflation family {ds['n_trials']} trials (ledger total {ds.get('n_ledger_total', '?')}) → expected max per-period SR {ds['sr0']:.4f}",
            f"- **DSR = {ds['dsr']:.3f}** — {ds['note']}",
        ]
    else:
        lines.append(f"- {ds.get('error', 'not computed')}")
    ts = d.get("tear_sheet", {})
    lines += ["", "## Tear sheet (mark-to-market)", ""]
    if "mtm_total_return" in ts:
        lines += [
            f"- total return **{ts['mtm_total_return']:+.2%}**, max drawdown "
            f"**{ts['mtm_max_drawdown']:.2%}** (daily mark-to-market incl. "
            f"open positions — stricter than freqtrade's trade-close figures)",
            f"- annualized Sharpe **{ts['sharpe_annualized']:.2f}** [365-day year]",
            f"- positive months: {ts['positive_months']} of {ts['months']}",
        ]
        if ts.get("best_month_share_mtm") is not None:
            lines.append(f"- best month {ts['best_month']} = "
                         f"**{ts['best_month_share_mtm']:.0%}** of total "
                         f"return (G-conc, MTM basis)")
        if ts.get("monthly"):
            lines += ["", "| month | strategy | universe |", "|---|---|---|"]
            for row in ts["monthly"]:
                u = f"{row['universe']:+.2%}" if "universe" in row else "—"
                lines.append(f"| {row['month']} | {row['strategy']:+.2%} | {u} |")
        if ts.get("figure"):
            lines.append(f"\n![tear sheet]({ts['figure']})")
    else:
        lines.append(f"- {ts.get('error', 'not computed')}")
    gp = d.get("g_passive", {})
    lines += ["", "## G-passive (§23 form)", ""]
    if "pass_sharpe" in gp:
        lines += [
            f"- realized exposure **{gp['exposure_mean']:.1%}** — benchmark "
            f"scaled to it for the return comparison",
            f"- return: strategy {gp['strategy_total']:+.2%} vs scaled "
            f"universe {gp['universe_scaled_total']:+.2%} "
            f"(**{gp['excess_pp_vs_scaled']:+.2f} pp**) → "
            f"{'PASS' if gp['pass_scaled_return'] else '**FAIL**'}",
            f"- Sharpe (load-bearing): strategy **{gp['sharpe_strategy']:.2f}** "
            f"vs universe **{gp['sharpe_universe']:.2f}** → "
            f"{'PASS' if gp['pass_sharpe'] else '**FAIL**'}",
            f"- months beaten: {gp['months_beaten']} overall — "
            f"{gp['up_months_beaten']} in universe-up months, "
            f"{gp['down_months_beaten']} in universe-down months",
            f"- raw fully-invested comparison (context only): "
            f"{gp['excess_pp_raw']:+.2f} pp vs universe "
            f"{gp['universe_total']:+.2%}",
        ]
    else:
        lines.append(f"- {gp.get('error', 'not computed')}")
    lines += ["", "## Gates", ""]
    for g in d["gates"]:
        lines.append(f"- {'PASS' if g['passed'] else '**FAIL**'} `{g['gate']}` — {g['reason']}")
    return "\n".join(lines) + "\n"


def _execute_notebook(run_dir: Path) -> None:
    tmpl = Path(__file__).resolve().parents[2] / "notebooks" / "validation_review.ipynb"
    if not tmpl.exists():
        return
    try:
        import papermill
    except ImportError:
        return
    papermill.execute_notebook(
        str(tmpl), str(run_dir / "artifacts" / "validation_review.executed.ipynb"),
        parameters={"dossier_dir": str(run_dir / "artifacts")},
        progress_bar=False,
    )
