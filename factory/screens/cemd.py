"""Causal EMD — the topic-4 feature family (Plan §17.4; shelf rule §20.10).

Standard EMD is anticausal: every IMF value depends on the whole series, so
yesterday's "trend" changes when today's bar arrives. The causal form
recomputes the decomposition per bar on the trailing window ending at t and
keeps ONLY the newest value of each output. That makes the feature
reconstructible from data <= t with no revision of past values — the §20.10
rule met at the transform layer, by construction, which is exactly how the
factor DSL earns the right to expose it.

Two features per decomposition, chosen so the grammar can compose the rest:

  trend(x, n)  — the residue at t: what is left after every oscillatory
                 mode is stripped (regime / trend context)
  noise(x, n)  — IMF1 at t: the fastest mode (the denoise target;
                 `close - ts_emd_noise(close, n)` is the denoised price)

The sifting numerics come from PyEMD's plain EMD — deterministic (no
ensemble noise), cubic splines — pinned as a dependency rather than
hand-rolled, because envelope boundary handling is where home-made EMDs go
quietly wrong. The causal contract (prefix invariance) is OURS and is what
tests/test_cemd.py actually proves.

A window the sifter finds no oscillation in (short, monotone) is all trend:
(noise, trend) = (0, x_t). Any NaN in the window poisons the value to NaN.
"""

from __future__ import annotations

import numpy as np


def decompose_last(window: np.ndarray) -> tuple[float, float]:
    """(noise, trend) at the window's LAST sample: IMF1 and the residue."""
    from PyEMD import EMD  # heavy import kept local

    x = np.asarray(window, dtype=float)
    if np.isnan(x).any():
        return (np.nan, np.nan)
    emd = EMD(spline_kind="cubic")
    emd.emd(x)
    imfs, residue = emd.get_imfs_and_residue()
    if imfs.shape[0] == 0:
        return (0.0, float(x[-1]))
    return (float(imfs[0][-1]), float(residue[-1]))


def rolling(df, n: int, mode: str):
    """Per-bar causal EMD over a wide (date x asset) frame; `mode` is
    "trend" or "noise". One decomposition per bar per asset — the compute
    budget this costs is measured by tools/cemd_budget.py."""
    idx = {"noise": 0, "trend": 1}[mode]
    return df.rolling(n).apply(lambda w: decompose_last(w)[idx], raw=True)
