"""S5 — the validation stage: the full gauntlet on in-sample folds.

Deterministic by design: purged walk-forward OOS runs, a cost sweep with
the zero-fee sanity and cost-coverage gates, and a deflated Sharpe whose
trial count comes from the ledger. Emits a dossier (json + md) and, when
papermill is available, executes the review notebook that is HG2's
reviewing surface. The stage never passes a run outright: the best it
returns is needs_human — HG2 is a judgment, not a checkbox.
"""

from __future__ import annotations

import io
import json
import math
import statistics
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from factory.gates import core
from factory.ledgers import trials
from factory.orchestrator.runner import StageResult
from factory.validation import dsr as dsr_mod
from factory.validation.splitter import Fold


@dataclass
class ValidateSpec:
    strategy: str
    timeframe: str
    fee: float
    folds: list[Fold]
    full_timerange: str
    cost_fees: tuple = (0.0, 0.0005, 0.001, 0.002, 0.003)
    strategy_path: Path | None = None
    periods_per_year: int = 365
    notes: dict = field(default_factory=dict)


def daily_returns_from_export(export_zip: Path, strategy: str) -> list[float]:
    """The export bundles a true daily mark-to-market equity curve
    (*_wallet.feather — found in Plan §23). Daily returns from it."""
    import pandas as pd  # heavy import kept local

    with zipfile.ZipFile(export_zip) as z:
        name = export_zip.name.replace(".zip", f"_{strategy}_wallet.feather")
        df = pd.read_feather(io.BytesIO(z.read(name)))
    # long format: one row per (date, currency); equity = total_quote summed
    eq = df.groupby("date")["total_quote"].sum().sort_index()
    rets = eq.pct_change().dropna()
    return rets[rets.abs() < float("inf")].tolist()


def run_validation(engine, spec: ValidateSpec, run_dir: Path,
                   trial_ledger: Path) -> StageResult:
    art = run_dir / "artifacts"
    art.mkdir(exist_ok=True)
    dossier: dict = {"spec": {
        "strategy": spec.strategy, "timeframe": spec.timeframe, "fee": spec.fee,
        "folds": [{"n": f.n, "train": f.train_timerange(), "test": f.test_timerange(),
                   "purge_gap_days": f.purge_gap_days} for f in spec.folds],
        "full_timerange": spec.full_timerange, **spec.notes,
    }}

    def bt(timerange: str, fee: float, why: str):
        r = engine.backtest(
            spec.strategy, spec.timeframe, timerange, fee,
            strategy_path=spec.strategy_path,
        )
        trials.append(trial_ledger, "backtest", run_dir.name, {
            "strategy": spec.strategy, "timerange": timerange,
            "fee": fee, "why": why,
            "trades": r.trade_count, "profit_total": r.profit_total,
            "profit_mean": r.profit_mean,
        })
        return r

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
    for fee in spec.cost_fees:
        r = bt(spec.full_timerange, fee, "cost sweep")
        sweep.append({"fee": fee, "trades": r.trade_count,
                      "profit_total": r.profit_total,
                      # per-trade return ON STAKE — the 3x rule's basis
                      "mean_per_trade": r.profit_mean})
    dossier["cost_sweep"] = sweep
    zero = next(s for s in sweep if s["fee"] == 0.0)
    gates = [core.zero_fee_sanity(zero["profit_total"])]
    roundtrip = 2 * spec.fee
    gates.append(core.cost_coverage(zero["mean_per_trade"], roundtrip))

    # 3 — deflated Sharpe from the full-range run at the working fee
    full = bt(spec.full_timerange, spec.fee, "full range")
    dossier["full_range"] = {"trades": full.trade_count,
                             "profit_total": full.profit_total}
    try:
        rets = daily_returns_from_export(full.export_zip, spec.strategy)
        sr_ann = dsr_mod.sharpe(rets, spec.periods_per_year)
        skew, kurt = dsr_mod.moments(rets)
        # Deflation family: trials on a comparable basis only — same
        # timeframe, window >= 300d, finite recorded Sharpe. Mixing 1h
        # hyperopt spam (sentinel values to -100) into the variance would
        # make SR0 meaningless. Both counts are reported.
        family = _historic_sharpes(trial_ledger, timeframe=spec.timeframe,
                                   min_days=300)
        n_ledger = trials.count(trial_ledger)
        sr_var = (statistics.variance(family) / spec.periods_per_year
                  if len(family) >= 2 else 0.01 / spec.periods_per_year)
        d = dsr_mod.dsr(sr=sr_ann / math.sqrt(spec.periods_per_year),
                        n_obs=len(rets), n_trials=max(len(family), 2),
                        sr_var=sr_var, skew=skew, kurt=kurt)
        d["sr_annualized"] = sr_ann
        d["n_ledger_total"] = n_ledger
        d["note"] = (f"deflated within the comparable-basis family "
                     f"({len(family)} trials, {spec.timeframe}, >=300d); the "
                     f"full ledger holds {n_ledger} trials and hyperopt "
                     f"epochs are uncounted, so the true search was wider — "
                     f"treat DSR as an upper bound")
        dossier["deflated_sharpe"] = d
    except Exception as e:
        dossier["deflated_sharpe"] = {"error": f"unavailable: {e}"}

    dossier["gates"] = [
        {"gate": g.gate, "passed": g.passed, "reason": g.reason, "numbers": g.numbers}
        for g in gates
    ]
    killed = [g for g in gates if not g.passed]

    (art / "dossier.json").write_text(json.dumps(dossier, indent=1))
    (art / "dossier.md").write_text(_render_md(dossier))
    _execute_notebook(run_dir)

    if killed:
        return StageResult("killed",
                           "; ".join(f"{g.gate}: {g.reason}" for g in killed),
                           {"dossier": "artifacts/dossier.json"})
    return StageResult("needs_human",
                       "all deterministic gates passed — HG2 review required",
                       {"dossier": "artifacts/dossier.json"})


def _historic_sharpes(ledger: Path, timeframe: str | None = None,
                      min_days: int = 0) -> list[float]:
    out = []
    if not ledger.exists():
        return out
    with open(ledger) as f:
        for line in f:
            r = json.loads(line)
            v = r.get("sharpe")
            if not isinstance(v, (int, float)) or abs(v) > 50:
                continue  # missing or sentinel
            if timeframe is not None and r.get("timeframe") != timeframe:
                continue
            if min_days and not (
                r.get("start_ts") and r.get("end_ts")
                and (r["end_ts"] - r["start_ts"]) >= min_days * 86400
            ):
                continue
            out.append(float(v))
    return out


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
