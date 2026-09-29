"""M1 golden test: the factory must reproduce the recorded reference backtest
exactly — trade count exact, entry/exit timestamps exact, P&L within 1e-8.
(The Plan §5 coupling artifact, reused as the engine adapter's acceptance test.)
"""

import json
from pathlib import Path

import pytest

from factory.engine.lab import LabEngine

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "reference.json"


@pytest.mark.golden
def test_reference_backtest_reproduces_exactly():
    ref = json.loads(FIXTURE.read_text())
    result = LabEngine().backtest(**ref["spec"])
    expect = ref["expect"]

    assert result.trade_count == expect["trade_count"]
    assert result.trades_digest() == expect["trades_digest"]  # pairs + timestamps exact
    assert abs(result.profit_total_abs - expect["profit_total_abs"]) < 1e-8

    got = sorted([t.pair, t.open_date, t.close_date, t.profit_abs] for t in result.trades)
    want = sorted(expect["trades"])
    for g, w in zip(got, want):
        assert g[:3] == w[:3]
        assert abs(g[3] - w[3]) < 1e-8
