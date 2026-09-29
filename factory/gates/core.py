"""Deterministic screen gates — the Plan's measured rules as pure functions.

Every gate exists because the manual process measured something in Sep 2026;
the provenance section is cited on each. The graveyard fixtures in
fixtures/graveyard.json hold the recorded numbers, and the test suite
requires each dead hypothesis to be re-killed by its gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GateVerdict:
    gate: str
    passed: bool
    reason: str
    numbers: dict

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.passed


def noise_floor(
    per_trade_sd: float,
    edge_gate: float,
    trades_available: int,
    z: float = 1.96,
) -> GateVerdict:
    """Plan §21: if the gate sits inside the error bars, the hypothesis is
    untestable and is not written up. Resolving a mean of `edge_gate` against
    per-trade sd needs ~(z*sd/gate)^2 trades; H4's 21-day crypto-cross hold
    had sd ≈ 15 pp against a 0.6 % gate → ~2,400 needed, ~90 available."""
    trades_needed = math.ceil((z * per_trade_sd / edge_gate) ** 2)
    ok = trades_available >= trades_needed
    return GateVerdict(
        "noise_floor",
        ok,
        f"needs ≥{trades_needed} trades to resolve a {edge_gate:.4%} edge at "
        f"sd {per_trade_sd:.2%}; history supplies {trades_available}",
        {"trades_needed": trades_needed, "trades_available": trades_available,
         "per_trade_sd": per_trade_sd, "edge_gate": edge_gate, "z": z},
    )


def cost_coverage(
    gross_edge_per_trade: float,
    roundtrip_cost: float,
    required_multiple: float = 3.0,
) -> GateVerdict:
    """Plan §12/§14 R3: gross edge must cover round-trip cost 3×, decided
    before a strategy is written. The 2020 bot died at 0.54× (0.0837 % edge
    vs 0.1556 % cost); H2 at −0.04×."""
    coverage = gross_edge_per_trade / roundtrip_cost
    ok = coverage >= required_multiple
    return GateVerdict(
        "cost_coverage",
        ok,
        f"coverage {coverage:.2f}× vs required {required_multiple:.1f}×",
        {"coverage": coverage, "gross_edge_per_trade": gross_edge_per_trade,
         "roundtrip_cost": roundtrip_cost, "required_multiple": required_multiple},
    )


def zero_fee_sanity(profit_total_at_zero_fee: float) -> GateVerdict:
    """Plan §12: negative at zero cost means no signal at all — Strategy005
    was −49.55 % over five years with fees off."""
    ok = profit_total_at_zero_fee > 0
    return GateVerdict(
        "zero_fee_sanity",
        ok,
        f"total return at zero fees: {profit_total_at_zero_fee:+.2%}",
        {"profit_total_at_zero_fee": profit_total_at_zero_fee},
    )


def control_arm(
    candidate_mean_oos: float,
    control_mean_oos: float,
    folds_won: int,
    n_folds: int,
) -> GateVerdict:
    """Plan §15: a tuned candidate must beat its own untuned defaults
    out-of-sample, in the mean AND in a majority of folds. Tuned H1 lost the
    mean (+3.24 % vs +7.40 %) and won 1 of 7 folds — hyperopt fitting noise."""
    ok = candidate_mean_oos > control_mean_oos and folds_won * 2 > n_folds
    return GateVerdict(
        "control_arm",
        ok,
        f"candidate {candidate_mean_oos:+.2f} vs control {control_mean_oos:+.2f} "
        f"mean OOS; won {folds_won}/{n_folds} folds",
        {"candidate_mean_oos": candidate_mean_oos, "control_mean_oos": control_mean_oos,
         "folds_won": folds_won, "n_folds": n_folds},
    )
