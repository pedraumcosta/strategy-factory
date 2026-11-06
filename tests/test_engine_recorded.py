"""RecordedEngine: every backtest is a trial with one canonical payload,
and the holdout lockout holds at the seam — for every caller."""

import json
from pathlib import Path

import pytest

from factory.engine.lab import BacktestResult
from factory.engine.recorded import HoldoutRefusal, RecordedEngine
from factory.ledgers import holdout


class Inner:
    data_dir = Path("/price/data")

    def __init__(self):
        self.calls = []

    def backtest(self, strategy, timeframe, timerange, fee, strategy_path=None):
        self.calls.append(timerange)
        return BacktestResult(strategy, 3, 1.0, 0.05, [], None,
                              profit_mean=0.004, sharpe=1.1)


def test_every_backtest_is_a_trial_with_the_canonical_payload(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    eng = RecordedEngine(Inner(), ledger)
    r = eng.backtest("X", "1d", "20210101-20220101", 0.001,
                     run_id="run-1", why="unit test")
    assert r.trade_count == 3
    rec = json.loads(ledger.read_text())
    assert rec["kind"] == "backtest" and rec["run_id"] == "run-1"
    assert rec["why"] == "unit test" and rec["fee"] == 0.001
    assert rec["sharpe"] == 1.1 and rec["timeframe"] == "1d"
    # window timestamps make the record usable by the deflation family
    assert rec["end_ts"] - rec["start_ts"] == 365 * 86400


def test_data_dir_is_delegated():
    assert RecordedEngine(Inner(), Path("x")).data_dir == Path("/price/data")


def test_clean_and_accruing_windows_are_refused(tmp_path):
    hl = tmp_path / "holdout.json"
    holdout.init(hl)                      # clean: 20190101-20201231
    holdout.accrue(hl, "20261101")        # accruing: 20260929-20261101
    ledger = tmp_path / "trials.jsonl"
    inner = Inner()
    eng = RecordedEngine(inner, ledger, holdout_ledger=hl)

    # touching the clean window: refused before any data is read
    with pytest.raises(HoldoutRefusal, match="clean"):
        eng.backtest("X", "1d", "20190601-20200101", 0.001,
                     run_id="r", why="should refuse")
    # open-ended range runs into the accruing window
    with pytest.raises(HoldoutRefusal, match="accruing"):
        eng.backtest("X", "1d", "20260901-", 0.001,
                     run_id="r", why="should refuse")
    assert inner.calls == []              # the inner engine never ran
    assert not ledger.exists()            # refusals are not trials

    # spent research windows run fine (the S5 full range)
    eng.backtest("X", "1d", "20210101-20260101", 0.001,
                 run_id="r", why="spent research window")
    assert inner.calls == ["20210101-20260101"]
