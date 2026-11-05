"""M2 acceptance: the graveyard is the test suite. Every hypothesis the
manual process killed must be re-killed by the right gate for the right
documented reason — and each gate must also be able to pass, so a kill
means something."""

import json
from pathlib import Path

import pytest

from factory.gates import core, factor

ROOT = Path(__file__).resolve().parents[1]
GRAVEYARD = json.loads((ROOT / "fixtures" / "graveyard.json").read_text())


# --- the corpses stay dead -------------------------------------------------

def test_strategy005_dies_at_zero_fee_sanity():
    f = GRAVEYARD["strategy005"]
    v = core.zero_fee_sanity(f["profit_total_at_zero_fee"])
    assert not v.passed


def test_2020_bot_dies_at_cost_coverage():
    f = GRAVEYARD["bot2020_costs"]
    v = core.cost_coverage(f["gross_edge_per_trade"], f["roundtrip_cost"])
    assert not v.passed
    assert 0.5 < v.numbers["coverage"] < 0.6  # the recorded 0.54x


def test_h2_dies_at_cost_coverage():
    f = GRAVEYARD["h2_trendvoltarget"]
    edge = f["cost_coverage_recorded"] * f["roundtrip_cost"]
    v = core.cost_coverage(edge, f["roundtrip_cost"])
    assert not v.passed
    assert v.numbers["coverage"] == pytest.approx(-0.04)


def test_h1_tuned_dies_at_control_arm():
    f = GRAVEYARD["h1_xsmomentum_tuned"]
    v = core.control_arm(
        f["candidate_mean_oos"], f["control_mean_oos"], f["folds_won"], f["n_folds"]
    )
    assert not v.passed


def test_h4_dies_at_noise_floor():
    f = GRAVEYARD["h4_kalman_spread"]
    v = core.noise_floor(f["per_trade_sd"], f["edge_gate"], f["trades_available"])
    assert not v.passed
    # Plan §21's ~2,400: z=1.96 gives exactly 2401
    assert v.numbers["trades_needed"] == pytest.approx(
        f["trades_needed_recorded"], rel=0.05
    )


def test_h1h3_factor_dies_at_factor_screen():
    f = GRAVEYARD["h1h3_factor"]
    v = factor.judge_csv(ROOT / f["screen_csv"], f["factor"])
    assert not v.passed
    # Plan §22: IC negative at every screened horizon
    assert all(v.ic_by_horizon[h]["mean"] < 0 for h in factor.HORIZONS)


# --- and the gates can pass, so a kill means something ---------------------

def test_gates_pass_on_healthy_numbers():
    assert core.zero_fee_sanity(0.30).passed
    assert core.cost_coverage(0.006, 0.001556).passed          # 3.9x
    assert core.control_arm(9.0, 7.4, 5, 7).passed
    assert core.noise_floor(0.02, 0.006, 200).passed           # needs ~43


def test_oracle_arm_passes_the_factor_screen():
    """The look-ahead ORACLE arm is the screen's positive control: if the
    judge kills it too, the judge is broken, not the factor."""
    f = GRAVEYARD["h1h3_factor"]
    v = factor.judge_csv(ROOT / f["screen_csv"], "ORACLE")
    assert v.passed


def test_noise_arm_fails_the_factor_screen():
    f = GRAVEYARD["h1h3_factor"]
    v = factor.judge_csv(ROOT / f["screen_csv"], "NOISE")
    assert not v.passed


# --- §17.10: turnover-aware cost coverage ------------------------------------

def test_cost_coverage_default_turnover_is_the_old_gate():
    """turnover_per_trade defaults to 1.0 and must be bit-identical to the
    pre-§17.10 gate — the graveyard's cost kills depend on it."""
    old = core.cost_coverage(0.000837, 0.001556)
    explicit = core.cost_coverage(0.000837, 0.001556, turnover_per_trade=1.0)
    assert old.passed == explicit.passed == False
    assert old.numbers["coverage"] == explicit.numbers["coverage"]


def test_cost_coverage_scales_cost_by_turnover():
    """A weekly rebalance that transacts 10% of the position pays 10% of a
    round trip: 0.25% edge against 0.02% effective cost is 12.5x."""
    v = core.cost_coverage(0.0025, 0.002, turnover_per_trade=0.1)
    assert v.passed
    assert abs(v.numbers["coverage"] - 12.5) < 1e-9
    # the same card charged a full round trip fails — the §17.8 pincer
    assert not core.cost_coverage(0.0025, 0.002).passed
