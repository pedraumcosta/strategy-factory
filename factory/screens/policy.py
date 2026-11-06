"""S2's screen policy as its own module: card in, verdict and report out.

The interface takes its dependencies — price data dir, registered folds,
the cost model — instead of reaching for globals, and returns a structured
outcome instead of only rendered markdown. The stage wiring in
factory/stages/pipeline.py loads the card, hands it here, writes the
report artifact and appends the measured screen to the trial ledger; the
policy itself produces no ledger side effects.

Whether a cross-sectional card may pass without a measured factor screen
is explicit in the outcome (`measured`), not an accident of configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from factory import card as card_mod
from factory.costs import WORKING, CostModel
from factory.gates import core
from factory.gates.core import GateVerdict


@dataclass
class ScreenOutcome:
    passed: bool
    summary: str
    reasons: list[str]                      # kill reasons; empty when passed
    report_md: str                          # "" when no report was produced
    gates: list[GateVerdict] = field(default_factory=list)
    measured: bool = False                  # did the measured factor screen run
    factor_trial: dict | None = None        # ledger detail when it did


def screen(card: dict, *, out_dir: Path, data_dir: Path | None = None,
           folds: list[tuple[str, str, str]] | None = None,
           costs: CostModel = WORKING) -> ScreenOutcome:
    """Estimate screens always; for a cross-sectional card with price data
    available, ALSO the measured factor screen (Plan §22) — the cheapest
    kill in the method, run before any fold or holdout is spent."""
    est = card["estimates"]
    problems = card_mod.validate_estimates(est)
    if problems:
        return ScreenOutcome(False, "invalid estimates", problems, "")

    turnover = card_mod.turnover(card)
    verdicts = [
        core.noise_floor(est["per_trade_sd"],
                         costs.edge_gate(est["gross_edge_per_trade"]),
                         int(est["trades_available"])),
        costs.coverage(est["gross_edge_per_trade"],
                       turnover_per_trade=turnover),
    ]
    lines = [f"# Screen report — {card['name']}", "",
             "Screens run on the card's declared estimates (see "
             "estimates_basis); measured screens follow in S5.", ""]
    lines += [v.md_line() for v in verdicts]

    extra_kill = None
    measured = False
    factor_trial = None
    if card.get("cross_sectional"):
        expr = (card.get("factor") or {}).get("expr")
        if not expr:
            extra_kill = ("cross-sectional card declares no factor.expr "
                          "(causal DSL) — the measured screen (Plan §22) "
                          "cannot run")
            lines += ["", f"- **FAIL** `factor_screen` — {extra_kill}"]
        elif data_dir is None:
            lines += ["", "**Cross-sectional card: a measured factor "
                          "screen (ORACLE + NOISE arms) is REQUIRED "
                          "before S5** (Plan §22) — no price data dir "
                          "configured, run it manually."]
        else:
            from factory.screens.screen import FactorSpec, run_screen
            try:
                res = run_screen(
                    FactorSpec(name=card["name"], expr=expr,
                               universe=card["universe"],
                               timeframe=card["timeframe"]),
                    data_dir, out_dir, folds=folds)
            except Exception as e:
                res = None
                extra_kill = f"factor screen failed to run: {e}"
                lines += ["", f"- **FAIL** `factor_screen` — {extra_kill}"]
            if res is not None:
                measured = True
                lines += ["", res["report"]]
                cand = res["verdicts"][card["name"]]
                factor_trial = {"factor": card["name"], "expr": expr,
                                "passed": cand.passed,
                                "calibration_valid": res["valid"],
                                "ic": {str(h): v for h, v in
                                       cand.ic_by_horizon.items()}}
                if not res["valid"]:
                    extra_kill = ("factor screen calibration INVALID "
                                  "(ORACLE/NOISE contract broken) — "
                                  "fix the screen, not the factor")
                elif not cand.passed:
                    extra_kill = f"factor_screen: {cand.reason}"

    reasons = [f"{v.gate}: {v.reason}" for v in verdicts if not v.passed]
    if extra_kill:
        reasons.append(extra_kill)
    summary = ("estimate screens clear"
               + ("; measured factor screen passed" if measured
                  else "; measured screens due in S5"))
    return ScreenOutcome(not reasons, summary, reasons,
                         "\n".join(lines) + "\n", verdicts,
                         measured, factor_trial)
