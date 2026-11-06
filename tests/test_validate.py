"""S5 through the RecordedEngine seam: the engine records every backtest as
a trial, the dossier is written, gates decide — and DSR, tear sheet and
G-passive are COMPUTED (from a real synthetic export), not asserted into
their error branches."""

import json
from datetime import date
from pathlib import Path

import pytest

from factory.engine.lab import BacktestResult, Trade
from factory.engine.recorded import RecordedEngine
from factory.orchestrator import manifest as mf
from factory.stages.validate import ValidateSpec, run_validation
from factory.validation.splitter import Fold

from tests.test_gpassive import make_export


class FakeEngine:
    """Profitable at zero fee, eaten alive by costs — `base` sets the scale.
    Produces a REAL export zip (wallet + market_change feathers) so the
    full-range analytics compute instead of erroring."""

    data_dir = None

    def __init__(self, tmp_path, base=0.40, sharpe=1.2):
        self.base = base
        self.export = make_export(tmp_path, strategy="X")
        self.sharpe = sharpe
        self.calls = []

    def backtest(self, strategy, timeframe, timerange, fee, strategy_path=None):
        self.calls.append((timerange, fee))
        total = self.base - fee * 100  # fees hurt
        trades = [Trade("BTC/USDT", "2022-01-01 00:00:00+00:00",
                        "2022-01-03 00:00:00+00:00", total)]
        return BacktestResult(strategy, 50, total * 1000, total,
                              trades, export_zip=self.export,
                              profit_mean=total / 50, sharpe=self.sharpe,
                              timeframe=timeframe)


class BrokenExportEngine(FakeEngine):
    def backtest(self, *a, **kw):
        r = super().backtest(*a, **kw)
        r.export_zip = Path("/nonexistent.zip")
        return r


FOLDS = [Fold(1, date(2021, 1, 1), date(2022, 6, 2), date(2022, 7, 2), date(2022, 12, 31)),
         Fold(2, date(2021, 7, 2), date(2022, 12, 1), date(2022, 12, 31), date(2023, 7, 1))]


def make_spec(**kw):
    return ValidateSpec(strategy="X", timeframe="1d", folds=FOLDS,
                        full_timerange="20210101-20260101", **kw)


def test_dossier_written_and_trials_counted(tmp_path):
    run_dir = mf.new_run("validate me", tmp_path / "runs")
    ledger = tmp_path / "trials.jsonl"
    engine = RecordedEngine(FakeEngine(tmp_path), ledger)
    res = run_validation(engine, make_spec(), run_dir, ledger)
    d = json.loads((run_dir / "artifacts" / "dossier.json").read_text())
    assert len(d["walkforward"]["folds"]) == 2
    assert len(d["cost_sweep"]) == 5
    # 2 folds + 5 sweep + 1 full range, every one put on the ledger BY THE
    # ENGINE — no stage appends by hand
    records = [json.loads(l) for l in open(ledger)]
    assert len(records) == 8
    assert all(r["kind"] == "backtest" and "sharpe" in r and "start_ts" in r
               for r in records)
    assert (run_dir / "artifacts" / "dossier.md").exists()
    # DSR and G-passive are computed, not "unavailable"
    ds = d["deflated_sharpe"]
    assert "dsr" in ds and "error" not in ds
    # the factory's own full-range runs (5 sweep + 1 full, all >=300d, 1d)
    # joined the deflation family: N grows with the ledger
    assert ds["n_trials"] == 6
    assert "mtm_total_return" in d["tear_sheet"]
    assert "pass_sharpe" in d["g_passive"]
    assert "G-passive" in (run_dir / "artifacts" / "dossier.md").read_text()


def test_never_passes_outright_only_needs_human(tmp_path):
    run_dir = mf.new_run("good one", tmp_path / "runs")
    ledger = tmp_path / "t.jsonl"
    res = run_validation(RecordedEngine(FakeEngine(tmp_path), ledger),
                         make_spec(), run_dir, ledger)
    assert res.status == "needs_human"  # HG2 is a judgment, not a checkbox


def test_hopeless_strategy_is_killed_by_zero_fee_gate(tmp_path):
    run_dir = mf.new_run("hopeless", tmp_path / "runs")
    ledger = tmp_path / "t.jsonl"
    res = run_validation(RecordedEngine(FakeEngine(tmp_path, base=-0.10), ledger),
                         make_spec(), run_dir, ledger)
    assert res.status == "killed"
    assert "zero_fee_sanity" in res.report


def test_s5_charges_a_tilt_what_it_transacts(tmp_path):
    """The §17.10 gate holds at S5, not only at S2: a thin measured edge
    (0.08%/trade at zero fee) dies against a full round trip but clears it
    at the card's declared 10% turnover — S5 reads the same turnover S2
    already charged for."""
    ledger = tmp_path / "t.jsonl"
    run_dir = mf.new_run("full turnover", tmp_path / "runs")
    res = run_validation(RecordedEngine(FakeEngine(tmp_path, base=0.04), ledger),
                         make_spec(), run_dir, ledger)
    assert res.status == "killed" and "cost_coverage" in res.report

    run_dir = mf.new_run("tilt", tmp_path / "runs")
    res = run_validation(RecordedEngine(FakeEngine(tmp_path, base=0.04), ledger),
                         make_spec(turnover_per_trade=0.1), run_dir, ledger)
    assert res.status == "needs_human"
    d = json.loads((run_dir / "artifacts" / "dossier.json").read_text())
    cov = next(g for g in d["gates"] if g["gate"] == "cost_coverage")
    assert cov["numbers"]["turnover_per_trade"] == 0.1


def test_unreadable_export_is_a_loud_failure_not_a_footnote(tmp_path):
    """An uncomputable DSR/tear sheet is a factory defect: it raises (the
    runner marks the stage resumable) instead of writing an 'unavailable'
    dossier that stays green."""
    ledger = tmp_path / "t.jsonl"
    run_dir = mf.new_run("broken export", tmp_path / "runs")
    with pytest.raises(Exception):
        run_validation(RecordedEngine(BrokenExportEngine(tmp_path), ledger),
                       make_spec(), run_dir, ledger)
