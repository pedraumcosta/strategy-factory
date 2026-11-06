"""The cost model: one home for fee basis, round-trip, the 3x multiple and
turnover scaling — the constants S2/S4/S5 used to each hold themselves."""

import pytest

from factory.costs import WORKING, CostModel


def test_working_model_matches_the_recorded_basis():
    # 0.1%/side, the working fee basis — S2's old ROUNDTRIP=0.002 and
    # S4/S5's old fee=0.001 literals, now one fact
    assert WORKING.fee_per_side == 0.001
    assert WORKING.roundtrip == 0.002
    assert WORKING.required_multiple == 3.0
    assert 0.0 in WORKING.sweep_fees and WORKING.fee_per_side in WORKING.sweep_fees


def test_edge_gate_is_the_resolution_target():
    """Plan §17.10: the smaller of the claimed edge and the 3x full-round-trip
    edge. A turnover-1 card's gate is always the 3x edge; a cheap tilt is
    tested against its own claim."""
    assert WORKING.edge_gate(0.02) == pytest.approx(0.006)    # claim above 3x
    assert WORKING.edge_gate(0.0025) == pytest.approx(0.0025)  # the tilt claim


def test_coverage_scales_cost_by_turnover():
    v = WORKING.coverage(0.0025, turnover_per_trade=0.1)
    assert v.passed and v.numbers["coverage"] == pytest.approx(12.5)
    assert not WORKING.coverage(0.0025).passed  # full round trip: 1.25x


def test_sweep_must_cover_the_sanity_and_working_points():
    with pytest.raises(ValueError):
        CostModel(sweep_fees=(0.0005, 0.001))        # no zero-fee point
    with pytest.raises(ValueError):
        CostModel(fee_per_side=0.002,
                  sweep_fees=(0.0, 0.001))           # working fee not swept
