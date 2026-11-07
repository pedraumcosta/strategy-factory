"""The hypothesis card — one home for the card schema.

The card is S0's output and every later stage's input. Everything a later
stage would otherwise kill on for being malformed is rejected HERE, at
intake: estimate field types, the turnover_per_trade range (Plan §17.10),
and a cross-sectional card's factor.expr, validated against the causal DSL
grammar so S2's measured screen (Plan §22) is runnable by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

from factory import universe
from factory.orchestrator import manifest as mf
from factory.screens import dsl

TIMEFRAMES = {"1d", "4h", "1h"}
REQUIRED_FIELDS = [
    "name", "premise", "edge_source", "cross_sectional", "universe",
    "timeframe", "holding_period_days", "estimates", "estimates_basis",
    "parameters", "provenance",
]


def load(run_dir: Path) -> dict:
    return json.loads((mf.artifacts_dir(run_dir) / mf.CARD_JSON).read_text())


def turnover(card: dict) -> float:
    """Share of the position a trade actually transacts. Default 1.0 (an
    entry/exit trade turns the whole position) keeps every pre-§17.10
    verdict unchanged."""
    return float(card.get("estimates", {}).get("turnover_per_trade", 1.0))


def validate_estimates(est: dict) -> list[str]:
    problems = []
    for k in ("gross_edge_per_trade", "per_trade_sd", "trades_available"):
        if not isinstance(est.get(k), (int, float)):
            problems.append(f"estimates.{k} must be a number")
    t = est.get("turnover_per_trade", 1.0)
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        problems.append("estimates.turnover_per_trade must be a number")
    elif not 0 < float(t) <= 1:
        problems.append(
            f"turnover_per_trade {t} outside (0, 1] — a trade cannot "
            f"transact more than its position")
    # Relational sanity on the gate inputs the card itself authors. The sd
    # is the quadratic lever on the noise floor (trades_needed ~ sd^2), so
    # understating it is THE way to game S2; the prompt forbids that in
    # prose, this forbids it in code.
    edge, sd, n = (est.get("gross_edge_per_trade"), est.get("per_trade_sd"),
                   est.get("trades_available"))
    if isinstance(edge, (int, float)) and not 0 < float(edge) < 0.5:
        problems.append(
            f"gross_edge_per_trade {edge} outside (0, 0.5) — a per-trade "
            f"edge must be positive and under 50%")
    if isinstance(sd, (int, float)) and isinstance(edge, (int, float)) \
            and 0 < float(edge) and float(sd) < float(edge):
        problems.append(
            f"per_trade_sd {sd} below gross_edge_per_trade {edge} — a "
            f"per-trade Sharpe above 1 is not an estimate, it is a number "
            f"picked to clear the noise floor")
    if isinstance(n, (int, float)) and float(n) < 1:
        problems.append(f"trades_available {n} must be at least 1")
    return problems


def validate(card: dict) -> list[str]:
    problems = [f"missing field {k!r}" for k in REQUIRED_FIELDS if k not in card]
    if problems:
        return problems
    if not str(card["name"]).isidentifier():
        problems.append(f"name {card['name']!r} is not a valid class name")
    if card["timeframe"] not in TIMEFRAMES:
        problems.append(f"timeframe {card['timeframe']!r} not in {sorted(TIMEFRAMES)}")
    u = card["universe"]
    if not (isinstance(u, list) and u):
        problems.append("universe must be a non-empty list of pairs")
    else:
        names = {str(p).split("/")[0].upper() for p in u}
        unknown = sorted(names - universe.known())
        if unknown:
            problems.append(
                f"universe names outside the registered universes "
                f"(factory/universe.py, §17 topic 13): {unknown}")
    problems += validate_estimates(card.get("estimates", {}))
    if not (isinstance(card["parameters"], dict) and card["parameters"]):
        problems.append("parameters must be a non-empty dict of a-priori values")
    if card.get("cross_sectional"):
        expr = (card.get("factor") or {}).get("expr")
        if not expr:
            problems.append(
                "cross-sectional card declares no factor.expr (causal DSL) — "
                "the measured screen (Plan §22) cannot run")
        else:
            try:
                dsl.validate(expr)
            except dsl.FactorExprError as e:
                problems.append(f"factor.expr rejected by the causal DSL: {e}")
    return problems
