"""The §21 feasibility arithmetic as the standing time-series gate — Plan
§17 topic 16.

Measures a UNIVERSE, never a signal: mean pairwise correlation of daily
returns, effective breadth N_eff = N / (1 + (N-1)·ρ̄), the eigenvalue
participation ratio (Σλ)²/Σλ², and the minimum resolvable Sharpe at
t ≥ 2, SR_min = 2 / sqrt(years · N_eff) — pooled and per fold.

The gate it implements binds at REGISTRATION time: no time-series trial
may be registered without citing these numbers for its universe and a
prior SR ≥ SR_min. Running this module is not a ledger trial — no signal
is evaluated, nothing is spent. First measurement (2026-11-08, the
52-name perp-funded crypto panel): ρ̄ ≈ 0.49 → N_eff ≈ 2 of 52, pooled
floor ≈ 0.5–0.7 against Carver's single-rule prior 0.2–0.3 — the gate
REFUSES single-rule TS registrations on that universe.
"""

from __future__ import annotations

import math

MIN_CORR_DAYS = 250     # pairwise floor for a correlation to count
COVERAGE_FLOOR = 0.80   # names entering the participation-ratio estimate
T_RESOLVE = 2.0         # the standing judge bar the floor is derived from


class InfeasibleUniverseError(ValueError):
    """A time-series registration cited a prior below the universe's floor."""


def assert_feasible(prior_sr: float, sr_min: float) -> None:
    """The registration-time gate, as code: prior SR must clear the floor."""
    if not prior_sr >= sr_min:
        raise InfeasibleUniverseError(
            f"prior SR {prior_sr:.2f} is below the universe's minimum "
            f"resolvable SR {sr_min:.2f} at t >= {T_RESOLVE:.0f} — the trial "
            "could not be read, pass or fail; the registration is unwritable "
            "(Plan §17 topic 16)")


def _window(returns, ann_factor: int) -> dict | None:
    """Feasibility stats for one wide daily-returns window."""
    import numpy as np

    alive = returns.columns[returns.notna().sum() >= MIN_CORR_DAYS]
    if len(alive) < 2:
        return None
    r = returns[alive]
    corr = r.corr(min_periods=MIN_CORR_DAYS)
    tri = corr.values[np.triu_indices_from(corr.values, k=1)]
    tri = tri[~np.isnan(tri)]
    if not len(tri):
        return None
    rho = float(tri.mean())
    n = len(alive)
    n_eff = n / (1 + (n - 1) * rho) if rho > 0 else float(n)

    # participation ratio over the well-covered names (a complete matrix)
    cov_names = [c for c in alive
                 if r[c].notna().mean() >= COVERAGE_FLOOR]
    pr = pr_n = None
    if len(cov_names) >= 2:
        cm = r[cov_names].corr(min_periods=MIN_CORR_DAYS)
        cm = cm.dropna(axis=0, how="any").dropna(axis=1, how="any")
        keep = cm.index.intersection(cm.columns)
        cm = cm.loc[keep, keep]
        if len(cm) >= 2:
            lam = np.linalg.eigvalsh(cm.values)
            pr = float(lam.sum() ** 2 / (lam ** 2).sum())
            pr_n = len(cm)

    n_days = int(returns.notna().any(axis=1).sum())
    years = n_days / ann_factor
    out = {
        "n_days": n_days, "years": round(years, 2),
        "n_corr_names": n, "rho_bar": round(rho, 4),
        "n_eff": round(n_eff, 2),
        "sr_min": round(T_RESOLVE / math.sqrt(years * n_eff), 3),
    }
    if pr is not None:
        out["participation_ratio"] = round(pr, 2)
        out["pr_names"] = pr_n
        out["sr_min_pr"] = round(T_RESOLVE / math.sqrt(years * pr), 3)
    return out


def feasibility(close, folds=None, ann_factor: int = 365) -> dict:
    """The universe's feasibility card: pooled over the whole of `close`
    (the caller slices to the registered span), plus one row per fold."""
    returns = close.pct_change()
    out = {"n_names": close.shape[1],
           "pooled": _window(returns, ann_factor), "folds": []}
    for fid, s, e in folds or []:
        w = _window(returns.loc[s:e], ann_factor)
        if w:
            out["folds"].append({"fold": fid, "start": s, "end": e, **w})
    return out
