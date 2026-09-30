"""Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado 2012,
2014) — the trials-adjusted Sharpe the Plan (§20/§24) named as missing.

The deflation benchmark SR0 is the Sharpe one expects from the BEST of N
unskilled trials, so N must come from the trial ledger (every backtest,
screen and re-run recorded), never from a guess. Stdlib only: NormalDist
supplies Phi and its inverse.
"""

from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def sharpe(returns: list[float], periods_per_year: int = 365) -> float:
    """Annualized Sharpe of a per-period return series (crypto trades 365
    days: the lab's tear sheet uses 365, pyfolio's 252 reads low — lab
    README §8)."""
    n = len(returns)
    if n < 2:
        raise ValueError("need at least 2 returns")
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var == 0:
        raise ValueError("zero-variance returns")
    return mean / math.sqrt(var) * math.sqrt(periods_per_year)


def moments(returns: list[float]) -> tuple[float, float]:
    """(skewness, kurtosis) — kurtosis is raw (normal = 3), as the PSR
    formula expects."""
    n = len(returns)
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 == 0:
        raise ValueError("zero-variance returns")
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def psr(sr: float, sr_benchmark: float, n_obs: int,
        skew: float = 0.0, kurt: float = 3.0) -> float:
    """P[true SR > sr_benchmark] given an observed per-period `sr` over
    `n_obs` observations with the given return moments. Both Sharpes are
    PER-PERIOD (not annualized)."""
    denom = math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr * sr)
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / denom
    return _N.cdf(z)


def expected_max_sharpe(n_trials: int, sr_var: float) -> float:
    """E[max SR] across `n_trials` unskilled trials whose SRs have variance
    `sr_var` (per-period). The deflation benchmark."""
    if n_trials < 2:
        return 0.0
    e = math.e
    return math.sqrt(sr_var) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * e))
    )


def dsr(sr: float, n_obs: int, n_trials: int, sr_var: float,
        skew: float = 0.0, kurt: float = 3.0) -> dict:
    """Deflated Sharpe: PSR against the expected-max-of-N benchmark.
    All Sharpes per-period."""
    sr0 = expected_max_sharpe(n_trials, sr_var)
    p = psr(sr, sr0, n_obs, skew, kurt)
    return {"dsr": p, "sr0": sr0, "n_trials": n_trials, "n_obs": n_obs,
            "sr": sr, "sr_var": sr_var, "skew": skew, "kurt": kurt}
