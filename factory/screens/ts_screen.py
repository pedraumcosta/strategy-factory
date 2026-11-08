"""The time-series screen — Plan §17 topic 16.

The §22 contract carried into the time-series approach. ONE pre-committed
portfolio convention, no variant space: position w_{i,t} ∝ forecast_{i,t}
/ σ_{i,t} with σ the 25-day rolling std of 1-day returns (the vol window
every Carver construction in topic 15 used), normalized to unit gross
Σ|w| = 1 over the names valid at t (at least 3, or the date is NaN),
rebalanced daily at the next close, zero costs. The judge is the pooled
|t| ≥ 2 on the book's DAILY returns over the registered IS folds.

Why a book and not a pooled per-name t: same-date observations on a
co-moving universe are far fewer effective observations than they count
(the crypto panel: 52 names ≈ 2 effective), so a stacked t overstates
evidence by ≈ sqrt(N / N_eff). One book return per date internalizes the
cross-sectional dependence by construction and lands the measurement in
the same unit as the priors — book Sharpe.

Calibration arms, the §22 contract verbatim: ORACLE (tomorrow's return as
today's forecast, built HERE by the harness — look-ahead stays unwritable
in the DSL) must pass; NOISE (seeded iid normal) must fail. Either
violation invalidates the RUN, whatever the candidate did.

Admissibility is NOT this module's job: the feasibility gate
(factory/screens/feasibility.py) binds at registration time, and by its
first measurement no single-rule time-series trial is writable on today's
crypto universe — this module ships proven on synthetic panels and idle
on real ones, until a universe's arithmetic admits it.
"""

from __future__ import annotations

import math

VOL_WINDOW = 25
MIN_NAMES = 3
MIN_DAYS = 60          # fewer book days than this is not a measurement
T_MIN = 2.0
ANN_FACTOR = 365       # crypto calendar; a universe descriptor owns this
SEED = 20261108


def book_returns(forecast, close):
    """Daily returns of the registered book. Causal by construction: the
    weight at t uses rows <= t and earns the t -> t+1 return via shift."""
    import numpy as np

    r1 = close.pct_change()
    vol = r1.rolling(VOL_WINDOW).std()
    w = (forecast / vol.where(vol > 0)).replace([np.inf, -np.inf], float("nan"))
    gross = w.abs().sum(axis=1)
    n = w.notna().sum(axis=1)
    w = w.div(gross.where((gross > 0) & (n >= MIN_NAMES)), axis=0)
    return (w.shift(1) * r1).sum(axis=1, min_count=1)


def window_stats(book, start: str, end: str) -> dict | None:
    """One (arm, window) row, or None when the window is too thin."""
    s = book.loc[start:end].dropna()
    if len(s) < MIN_DAYS:
        return None
    mean, std = float(s.mean()), float(s.std())
    if std <= 0:
        return None
    return {"n_days": len(s), "mean_bp": round(mean * 1e4, 2),
            "t": round(mean / (std / math.sqrt(len(s))), 2),
            "sr_ann": round(mean / std * math.sqrt(ANN_FACTOR), 3)}


def run_ts_screen(name: str, expr: str, panels: dict,
                  folds: list[tuple[str, str, str]], seed: int = SEED) -> dict:
    """The full calibrated time-series screen for one DSL expression.
    Returns the dict a battery would land on the ledger
    (design: time_series_book)."""
    import numpy as np
    import pandas as pd

    from factory.screens import dsl

    close = panels["close"]
    rng = np.random.default_rng(seed)
    arms = {
        name: dsl.evaluate(expr, panels),
        "NOISE": pd.DataFrame(rng.standard_normal(close.shape),
                              index=close.index, columns=close.columns),
        "ORACLE": close.shift(-1) / close - 1.0,
    }
    rows, pooled = [], {}
    for arm, fc in arms.items():
        book = book_returns(fc, close)
        for fid, s, e in folds:
            r = window_stats(book, s, e)
            if r:
                rows.append({**r, "factor": arm, "fold": fid})
        p = window_stats(book, folds[0][1], folds[-1][2])
        if p:
            rows.append({**p, "factor": arm, "fold": "pooled"})
            pooled[arm] = p

    def _passes(arm: str) -> bool:
        p = pooled.get(arm)
        return bool(p and abs(p["t"]) >= T_MIN)

    valid = _passes("ORACLE") and not _passes("NOISE")
    return {"design": "time_series_book", "calibration_valid": valid,
            "passed": bool(valid and _passes(name)),
            "pooled": pooled, "rows": rows}
