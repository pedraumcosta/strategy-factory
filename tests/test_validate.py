"""S5 with a fake engine: dossier written, trials appended, gates decide."""

import json
from datetime import date
from pathlib import Path

from factory.engine.lab import BacktestResult, Trade
from factory.orchestrator import manifest as mf
from factory.stages.validate import ValidateSpec, run_validation
from factory.validation.splitter import Fold


class FakeEngine:
    """Profitable at zero fee, eaten alive by costs — or hopeless, per mode."""

    def __init__(self, hopeless=False):
        self.hopeless = hopeless
        self.calls = []

    def backtest(self, strategy, timeframe, timerange, fee, strategy_path=None):
        self.calls.append((timerange, fee))
        # healthy mode: mean/trade 0.8% vs 0.2% roundtrip = 4x coverage
        base = -0.10 if self.hopeless else 0.40
        total = base - fee * 100  # fees hurt
        trades = [Trade("BTC/USDT", "2022-01-01 00:00:00+00:00",
                        "2022-01-03 00:00:00+00:00", total)]
        return BacktestResult(strategy, 50, total * 1000, total,
                              trades, export_zip=Path("/nonexistent.zip"),
                              profit_mean=total / 50)


FOLDS = [Fold(1, date(2021, 1, 1), date(2022, 6, 2), date(2022, 7, 2), date(2022, 12, 31)),
         Fold(2, date(2021, 7, 2), date(2022, 12, 1), date(2022, 12, 31), date(2023, 7, 1))]


def make_spec():
    return ValidateSpec(strategy="X", timeframe="1d", fee=0.001,
                        folds=FOLDS, full_timerange="20210101-20260101")


def test_dossier_written_and_trials_counted(tmp_path):
    run_dir = mf.new_run("validate me", tmp_path / "runs")
    ledger = tmp_path / "trials.jsonl"
    res = run_validation(FakeEngine(), make_spec(), run_dir, ledger)
    d = json.loads((run_dir / "artifacts" / "dossier.json").read_text())
    assert len(d["walkforward"]["folds"]) == 2
    assert len(d["cost_sweep"]) == 5
    # 2 folds + 5 sweep + 1 full range, every one on the ledger
    assert sum(1 for _ in open(ledger)) == 8
    assert (run_dir / "artifacts" / "dossier.md").exists()
    # DSR gracefully unavailable (fake export zip)
    assert "error" in d["deflated_sharpe"]


def test_never_passes_outright_only_needs_human(tmp_path):
    run_dir = mf.new_run("good one", tmp_path / "runs")
    res = run_validation(FakeEngine(), make_spec(), run_dir, tmp_path / "t.jsonl")
    assert res.status == "needs_human"  # HG2 is a judgment, not a checkbox


def test_hopeless_strategy_is_killed_by_zero_fee_gate(tmp_path):
    run_dir = mf.new_run("hopeless", tmp_path / "runs")
    res = run_validation(FakeEngine(hopeless=True), make_spec(),
                         run_dir, tmp_path / "t.jsonl")
    assert res.status == "killed"
    assert "zero_fee_sanity" in res.report
