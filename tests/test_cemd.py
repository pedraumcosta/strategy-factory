"""Causal EMD (Plan §17.4): the grammar admits it, the causal contract
holds, and the decomposition means what the names say.

The test that earns the feature its place is prefix invariance — compute
the feature on a prefix of the series, then on a longer series, and every
overlapping value must be IDENTICAL. That is the §20.10 rule ("every
feature reconstructible from data <= t, no revision of past values") as an
executable fact instead of a review checklist item."""

import numpy as np
import pandas as pd
import pytest

from factory.screens import cemd, dsl


def walk(n, seed=7, drift=0.0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(drift + 0.02 * rng.standard_normal(n)))


def frame(values):
    return pd.DataFrame({"A": values},
                        index=pd.date_range("2022-01-01", periods=len(values)))


# --- grammar ----------------------------------------------------------------

def test_grammar_admits_the_emd_pair_and_composition():
    dsl.validate("ts_emd_trend(close, 128)")
    dsl.validate("cs_rank(close - ts_emd_noise(close, 64))")


def test_grammar_refuses_numerology_windows():
    with pytest.raises(dsl.FactorExprError, match="64"):
        dsl.validate("ts_emd_trend(close, 30)")
    with pytest.raises(dsl.FactorExprError):
        dsl.validate("ts_emd_noise(close, 366)")


# --- the causal contract ----------------------------------------------------

def test_prefix_invariance_no_value_is_ever_revised():
    full = frame(walk(300))
    prefix = full.iloc[:220]
    for mode in ("trend", "noise"):
        a = cemd.rolling(full, 64, mode).iloc[:220]
        b = cemd.rolling(prefix, 64, mode)
        pd.testing.assert_frame_equal(a, b)


def test_warmup_and_nan_poisoning():
    vals = walk(100)
    vals[80] = np.nan
    out = cemd.rolling(frame(vals), 64, "trend")
    assert out.iloc[:63].isna().all().all()          # warm-up
    assert out.iloc[80:100].isna().all().all()       # NaN poisons its windows
    assert out.iloc[63:80].notna().all().all()


# --- the decomposition means what the names say -------------------------------

def test_trend_tracks_the_slow_component_noise_the_fast():
    t = np.arange(420, dtype=float)
    slow = 0.05 * t                                   # the trend
    fast = 2.0 * np.sin(2 * np.pi * t / 8)            # the oscillation
    x = frame(100 + slow + fast)
    trend = cemd.rolling(x, 128, "trend").iloc[128:].to_numpy().ravel()
    noise = cemd.rolling(x, 128, "noise").iloc[128:].to_numpy().ravel()
    target_slow = (100 + slow)[128:]
    target_fast = fast[128:]
    # the residue rides the slow component, far from the raw signal's wiggle
    assert np.abs(trend - target_slow).mean() < 0.5 * np.abs(fast).mean()
    # IMF1 is in phase with the injected oscillation
    assert np.corrcoef(noise, target_fast)[0, 1] > 0.8


def test_monotone_window_is_all_trend():
    noise, trend = cemd.decompose_last(np.linspace(1.0, 2.0, 64))
    assert noise == 0.0 and trend == 2.0


def test_deterministic():
    w = walk(128)
    assert cemd.decompose_last(w) == cemd.decompose_last(w)


# --- end to end through the DSL ----------------------------------------------

def test_evaluate_runs_a_denoised_composite():
    panels = {"close": pd.DataFrame(
        {"A": walk(200, seed=1), "B": walk(200, seed=2)},
        index=pd.date_range("2022-01-01", periods=200))}
    out = dsl.evaluate("cs_rank(close - ts_emd_noise(close, 64))", panels)
    assert out.shape == (200, 2)
    assert out.iloc[64:].notna().all().all()
    assert ((out.iloc[64:] >= 0) & (out.iloc[64:] <= 1)).all().all()
