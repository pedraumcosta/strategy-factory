"""PSR/DSR sanity anchored to the formulas' fixed points."""

import math
import random

import pytest

from factory.validation import dsr


def test_sharpe_annualization():
    rets = [0.001, -0.002, 0.003, 0.0, 0.002, -0.001] * 50
    sr = dsr.sharpe(rets, periods_per_year=365)
    n = len(rets)
    mean = sum(rets) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
    assert sr == pytest.approx(mean / sd * math.sqrt(365))


def test_psr_is_half_at_the_benchmark():
    # observed SR equal to the benchmark -> exactly 0.5
    assert dsr.psr(0.05, 0.05, n_obs=300) == pytest.approx(0.5)


def test_psr_increases_with_observations():
    a = dsr.psr(0.10, 0.05, n_obs=50)
    b = dsr.psr(0.10, 0.05, n_obs=500)
    assert b > a > 0.5


def test_negative_skew_fat_tails_reduce_psr():
    base = dsr.psr(0.10, 0.0, 300, skew=0.0, kurt=3.0)
    ugly = dsr.psr(0.10, 0.0, 300, skew=-1.5, kurt=8.0)
    assert ugly < base


def test_expected_max_sharpe_grows_with_trials():
    v = 0.01
    assert dsr.expected_max_sharpe(1, v) == 0.0
    s10, s100 = dsr.expected_max_sharpe(10, v), dsr.expected_max_sharpe(100, v)
    assert 0 < s10 < s100


def test_dsr_deflates_with_trial_count():
    """The same observed Sharpe becomes less believable the more was tried —
    the whole point of recording every trial in the ledger."""
    kw = dict(sr=0.08, n_obs=365, sr_var=0.002, skew=-0.5, kurt=5.0)
    d1 = dsr.dsr(n_trials=2, **kw)
    d62 = dsr.dsr(n_trials=62, **kw)
    assert d62["sr0"] > d1["sr0"]
    assert d62["dsr"] < d1["dsr"]


def test_dsr_detects_pure_noise():
    """Best of many coin flips should NOT clear its own deflation benchmark
    (calibration in the spirit of the factor screen's NOISE arm)."""
    rng = random.Random(7)
    n_trials, n_obs = 50, 500
    srs = []
    for _ in range(n_trials):
        rets = [rng.gauss(0, 0.01) for _ in range(n_obs)]
        srs.append(dsr.sharpe(rets, 365) / math.sqrt(365))  # per-period
    best = max(srs)
    mean_sr = sum(srs) / len(srs)
    var_sr = sum((s - mean_sr) ** 2 for s in srs) / (len(srs) - 1)
    out = dsr.dsr(sr=best, n_obs=n_obs, n_trials=n_trials, sr_var=var_sr)
    assert out["dsr"] < 0.95  # no confident skill claim from noise
