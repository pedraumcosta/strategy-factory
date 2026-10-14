"""The factor-screen generator: DSL causality by construction, the
ORACLE/NOISE calibration contract on synthetic prices, and S2 wiring.

H3's factor is the running example: ts_ret(close, 40) / ts_std(ts_ret(close, 1), 40).
"""

import json
from pathlib import Path

import pytest

from factory.screens import dsl
from factory.screens.screen import FactorSpec, run_screen

XSM = "ts_ret(close, 40) / ts_std(ts_ret(close, 1), 40)"


# --- DSL --------------------------------------------------------------------

def test_validate_accepts_the_h3_factor():
    dsl.validate(XSM)
    dsl.validate("cs_rank(ts_mean(volume, 20) * close) - 0.5")


@pytest.mark.parametrize("bad,why", [
    ("ts_lag(close, -1)", "negative lag would read the future"),
    ("ts_ret(close, 0)", "zero window"),
    ("ts_ret(close, n)", "window must be a literal"),
    ("close.shift(-1)", "attribute access"),
    ("__import__('os')", "unknown function"),
    ("open", "not a panel"),
    ("close[0]", "subscript"),
    ("ts_ret(close, 1) > 0", "comparison"),
    ("lambda: close", "lambda"),
    ("3.14", "no panel referenced"),
    ("ts_ret(close, 40.5)", "float window"),
    ("ts_ret(close, True)", "bool window"),
])
def test_validate_rejects(bad, why):
    with pytest.raises(dsl.FactorExprError):
        dsl.validate(bad)


def _panel(days=120, assets=6, seed=7):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=days, freq="D")
    cols = [f"A{i}" for i in range(assets)]
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.03, (days, assets)), axis=0)),
        index=idx, columns=cols)
    volume = pd.DataFrame(rng.uniform(1e5, 1e6, (days, assets)),
                          index=idx, columns=cols)
    return {"close": close, "volume": volume}


def test_evaluate_matches_hand_built_pandas():
    p = _panel()
    out = dsl.evaluate(XSM, p)
    px = p["close"]
    want = (px.pct_change(40) / px.pct_change().rolling(40).std())
    import pandas as pd
    pd.testing.assert_frame_equal(out, want)


def test_causality_by_construction():
    """The §20.10 rule, directly: the factor at date t computed from data
    <= t equals the factor at date t computed from ALL data. No revision."""
    p = _panel()
    full = dsl.evaluate(XSM, p)
    cut = 80
    trunc = dsl.evaluate(XSM, {k: v.iloc[:cut] for k, v in p.items()})
    import pandas as pd
    pd.testing.assert_frame_equal(full.iloc[:cut], trunc)


# --- the screen and its calibration contract --------------------------------

def _write_feathers(data_dir: Path, panels):
    (data_dir / "binance").mkdir(parents=True)
    import pandas as pd
    for sym in panels["close"].columns:
        df = pd.DataFrame({
            "date": pd.DatetimeIndex(panels["close"].index).tz_localize("UTC"),
            "close": panels["close"][sym].values,
            "volume": panels["volume"][sym].values,
        })
        df.to_feather(data_dir / "binance" / f"{sym}_USDT-1d.feather")


FOLDS = [("1", "2021-02-01", "2022-01-31"), ("2", "2021-08-01", "2022-07-31")]


def test_oracle_passes_noise_fails_on_random_walks(tmp_path):
    """The calibration contract on prices with NO structure: look-ahead is
    the only thing that can pass, and the seeded noise arm must not."""
    panels = _panel(days=640, assets=10, seed=11)
    _write_feathers(tmp_path, panels)
    spec = FactorSpec(name="Cand", expr=XSM,
                      universe=[f"A{i}/USDT" for i in range(10)])
    res = run_screen(spec, tmp_path, tmp_path / "out", folds=FOLDS)
    assert res["verdicts"]["ORACLE"].passed
    assert not res["verdicts"]["NOISE"].passed
    assert res["valid"]
    # momentum on a random walk earns nothing
    assert not res["verdicts"]["Cand"].passed
    # CSV is in the judge's schema and the judge can re-read it
    from factory.gates import factor as fj
    v = fj.judge_csv(res["csv"], "ORACLE")
    assert v.passed


# --- S2 wiring ---------------------------------------------------------------

CARD = {
    "name": "Cand", "premise": "p", "edge_source": "momentum",
    "cross_sectional": True,
    "universe": [f"A{i}/USDT" for i in range(10)], "timeframe": "1d",
    "holding_period_days": 10,
    "estimates": {"gross_edge_per_trade": 0.02, "per_trade_sd": 0.05,
                  "trades_available": 2000},
    "estimates_basis": "test", "parameters": {"lookback": 40},
    "provenance": "test",
    "factor": {"expr": XSM},
}


def _run_s2(tmp_path, card, data_dir):
    from factory.orchestrator import manifest as mf
    from factory.stages.pipeline import screen_stage
    run_dir = mf.new_run("x", tmp_path / "runs")
    art = run_dir / "artifacts"
    art.mkdir(exist_ok=True)
    (art / "hypothesis.json").write_text(json.dumps(card))
    ledger = tmp_path / "trials.jsonl"
    res = screen_stage(data_dir, ledger)(run_dir, mf.load(run_dir))
    return res, run_dir, ledger


def test_s2_runs_the_measured_screen_and_kills_a_dead_factor(tmp_path, monkeypatch):
    panels = _panel(days=640, assets=10, seed=11)
    _write_feathers(tmp_path / "data", panels)
    import factory.screens.screen as sc
    monkeypatch.setattr(sc, "registered_folds", lambda: FOLDS)
    res, run_dir, ledger = _run_s2(tmp_path, CARD, tmp_path / "data")
    assert res.status == "killed"
    assert "factor_screen" in res.report
    report = (run_dir / "artifacts" / "screen_report.md").read_text()
    assert "ORACLE" in report and "NOISE" in report and "valid" in report
    # the screen is a trial on the ledger — searches are counted
    kinds = [json.loads(l)["kind"] for l in open(ledger)]
    assert "factor_screen" in kinds


def test_s2_kills_cross_sectional_card_without_a_factor(tmp_path):
    card = {**CARD}
    card.pop("factor")
    res, _, _ = _run_s2(tmp_path, card, tmp_path / "nodata")
    assert res.status == "killed"
    assert "factor.expr" in res.report


def test_s2_without_data_dir_keeps_the_old_contract(tmp_path):
    res, run_dir, _ = _run_s2(tmp_path, CARD, None)
    assert res.status == "passed"
    assert "REQUIRED" in (run_dir / "artifacts" / "screen_report.md").read_text()
