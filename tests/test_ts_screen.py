"""Plan §17 topic 16 — the time-series seam, proven on synthetic panels.

The seam ships idle on the real universe (the feasibility gate refuses it),
so every proof here is synthetic: calibration arms behave on a pure random
walk, the book is causal under future-row perturbation, the registered
conventions (unit gross, >= 3 names) hold, the feasibility arithmetic
collapses on clones and expands on independents, and the per-universe DSL
validation enforces the level-safety rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factory.screens import dsl
from factory.screens.feasibility import (InfeasibleUniverseError,
                                         assert_feasible, feasibility)
from factory.screens.ts_screen import VOL_WINDOW, book_returns, run_ts_screen
from factory.universe import (PanelSpec, UniverseDescriptor,
                              crypto_binance_legacy17)


def _close(n_days=900, n_names=12, seed=7, sigma=0.03):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=n_days, freq="D")
    rets = rng.normal(0, sigma, (n_days, n_names))
    return pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx,
                        columns=[f"N{i}" for i in range(n_names)])


FOLDS = [("1", "2021-04-01", "2022-04-01"), ("2", "2022-04-01", "2023-04-01")]


def test_calibration_oracle_passes_noise_fails_on_a_random_walk():
    panels = {"close": _close(), "volume": None, "funding": None}
    res = run_ts_screen("cand", "ts_ewma(close, 16) - ts_ewma(close, 64)",
                        panels, FOLDS)
    assert res["calibration_valid"]
    assert res["pooled"]["ORACLE"]["t"] >= 2          # look-ahead must pass
    assert abs(res["pooled"]["NOISE"]["t"]) < 2       # seeded noise must fail
    assert not res["passed"]                          # no edge in a random walk
    assert res["design"] == "time_series_book"


def test_book_is_causal_under_future_perturbation():
    close = _close(seed=11)
    cut = 600
    tampered = close.copy()
    tampered.iloc[cut:] *= 1.37
    base = book_returns(close.pct_change(20), close)
    tamp = book_returns(tampered.pct_change(20), tampered)
    # the book at date i uses weights from i-1 and the return into i:
    # tampering rows >= cut may change nothing strictly before cut
    pd.testing.assert_series_equal(base.iloc[:cut], tamp.iloc[:cut])


def test_book_invariant_to_forecast_scale():
    close = _close(seed=3)
    fc = close.pct_change(10)
    pd.testing.assert_series_equal(book_returns(fc, close),
                                   book_returns(fc * 7.3, close))


def test_min_names_floor_blanks_the_book():
    close = _close(n_names=4, seed=5)
    fc = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    fc[["N2", "N3"]] = np.nan                          # 2 valid names < 3
    assert book_returns(fc, close).iloc[VOL_WINDOW + 2:].isna().all()


def test_neff_collapses_on_clones_and_expands_on_independents():
    rng = np.random.default_rng(5)
    idx = pd.date_range("2021-01-01", periods=1000, freq="D")
    base = rng.normal(0, 0.03, 1000)
    clones = pd.DataFrame(
        {f"C{i}": 100 * np.exp(np.cumsum(base + rng.normal(0, 1e-4, 1000)))
         for i in range(8)}, index=idx)
    indep = _close(n_days=1000, n_names=8, seed=9)
    fc, fi = feasibility(clones)["pooled"], feasibility(indep)["pooled"]
    assert fc["n_eff"] < 1.2
    assert fi["n_eff"] > 6
    assert fc["sr_min"] > fi["sr_min"]                 # co-movement raises the floor
    assert fi["participation_ratio"] > fc["participation_ratio"]


def test_the_gate_refuses_a_prior_below_the_floor():
    assert_feasible(prior_sr=0.3, sr_min=0.2)          # admissible
    with pytest.raises(InfeasibleUniverseError):
        assert_feasible(prior_sr=0.3, sr_min=0.6)      # the crypto verdict's shape


def test_level_safety_rule_for_a_futures_like_universe():
    desc = UniverseDescriptor(
        name="futures-like", symbols=("A",),
        panels={"close": PanelSpec("back-adjusted continuous; returns-safe "
                                   "only", level_safe=False)})
    dsl.validate_for_universe("ts_mean(ts_ret(close, 1), 20)", desc)   # ok
    with pytest.raises(dsl.FactorExprError):
        dsl.validate_for_universe("close / ts_max(close, 90)", desc)
    with pytest.raises(dsl.FactorExprError):
        dsl.validate_for_universe("ts_ret(log(close), 1)", desc)       # wrapped level


def test_crypto_descriptor_accepts_the_living_constructions():
    desc = crypto_binance_legacy17()
    for expr in ("-ts_mean(funding, 7)",
                 "close / ts_max(close, 90)",
                 "(ts_ewma(close, 16) - ts_ewma(close, 64))"
                 " / (ts_std(ts_ret(close, 1), 25) * close)"):
        dsl.validate_for_universe(expr, desc)


def test_unknown_panel_for_a_universe_is_rejected():
    desc = UniverseDescriptor(name="equities-like", symbols=("A",),
                              panels={"close": PanelSpec("close at t")})
    with pytest.raises(dsl.FactorExprError):
        dsl.validate_for_universe("-ts_mean(funding, 7)", desc)
