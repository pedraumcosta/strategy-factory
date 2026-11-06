"""MASS-style similarity search — Plan §17 topic 5 (shelf §20.12).

Two consumers, one algorithm:

  S1 scenarios — "when did the market last look like this, and what
  followed": retrieve the k nearest non-overlapping historical analogues
  of the trailing window and report their forward base rates. Every query
  is a trial the ledger must count (§1.2: analogues are a
  multiple-comparisons machine with extra steps) — the CLI appends it.

  S7 novelty — "today resembles nothing in memory": the distance from the
  latest window to its nearest earlier non-overlapping neighbour, placed
  on the distribution of that same statistic over history. Calibration
  before paging (the §17.2 rule): this module reports what a threshold
  WOULD have done historically; wiring an actual pager happens only after
  a human picks the threshold from that report.

The distance is MASS's: Euclidean between z-normalized windows (shape,
not scale), computed here on log prices. At this project's scale (~3,200
daily bars) the FFT trick MASS exists for buys nothing, so the profile is
a direct vectorized computation — same semantics, testable against brute
force (tests/test_similarity.py).

The holdout lockout holds at this seam too: windows whose candles — or
whose forward-return reads — overlap a clean or accruing holdout range
are invisible to retrieval, and novelty is not evaluated inside them. A
similarity scan is a read like any other; the RecordedEngine refuses
these windows for backtests and this module refuses them for analogues.
"""

from __future__ import annotations

import numpy as np

FORBIDDEN_STATUS = ("clean", "accruing")
EPS = 1e-9


# --- holdout masking ----------------------------------------------------------

def forbidden_spans(holdout_windows: list[dict]) -> list[tuple[str, str]]:
    """[(a, b)] date-string spans (inclusive) retrieval must not read."""
    out = []
    for w in holdout_windows:
        if w["status"] in FORBIDDEN_STATUS:
            a, b = w["range"].split("-")
            out.append((a, b or "99999999"))
    return out


def overlaps(d0: str, d1: str, spans: list[tuple[str, str]]) -> bool:
    return any(d0 <= b and d1 >= a for a, b in spans)


# --- the distance -------------------------------------------------------------

def _window_matrix(x: np.ndarray, m: int) -> np.ndarray:
    return np.lib.stride_tricks.sliding_window_view(np.asarray(x, float), m)


def _znorm(w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rows z-normalized; second return marks rows with real variation —
    a flat window has no shape and never matches anything."""
    mu = w.mean(axis=-1, keepdims=True)
    sd = w.std(axis=-1, keepdims=True)
    ok = (sd > EPS).ravel()
    z = (w - mu) / np.where(sd > EPS, sd, 1.0)
    return z, ok


def distance_profile(query: np.ndarray, x: np.ndarray) -> np.ndarray:
    """z-normalized Euclidean distance from `query` (length m) to every
    length-m window of `x`, indexed by window start. inf where undefined."""
    m = len(query)
    zq, qok = _znorm(np.asarray(query, float)[None, :])
    z, ok = _znorm(_window_matrix(x, m))
    if not qok[0]:
        return np.full(len(z), np.inf)
    d = np.sqrt(((z - zq[0]) ** 2).sum(axis=1))
    d[~ok] = np.inf
    return d


# --- S7: novelty --------------------------------------------------------------

def novelty_series(x: np.ndarray, m: int,
                   allowed: np.ndarray | None = None) -> np.ndarray:
    """For each window start s, the distance to its nearest EARLIER
    non-overlapping (start <= s - m) allowed window. NaN where there is no
    eligible neighbour yet, where the window itself is not allowed, or
    where it is flat. High = this shape has no precedent in memory."""
    w = _window_matrix(x, m)
    z, ok = _znorm(w)
    nw = len(z)
    allowed = np.ones(nw, bool) if allowed is None else allowed.copy()
    allowed &= ok
    # rows are z-normalized with ddof=0, so |row|^2 == m and
    # d^2(i, j) = 2m - 2 <z_i, z_j>
    gram = z @ z.T
    d = np.sqrt(np.clip(2 * m - 2 * gram, 0, None))
    out = np.full(nw, np.nan)
    for i in range(m, nw):
        if not allowed[i]:
            continue
        cand = np.flatnonzero(allowed[: i - m + 1])
        if cand.size:
            out[i] = d[i, cand].min()
    return out


# --- S1: analogues ------------------------------------------------------------

def analogues(x: np.ndarray, dates: list[str], m: int, k: int,
              horizons: list[int], spans: list[tuple[str, str]],
              asof_idx: int | None = None) -> list[dict]:
    """The k nearest non-overlapping historical analogues of the window
    ending at `asof_idx` (default: the last bar), with what followed.
    Analogue windows overlapping a forbidden span are invisible; a forward
    read that would cross one (or run off the data) reports NaN."""
    n = len(x)
    asof = n - 1 if asof_idx is None else asof_idx
    if asof - m + 1 < 0:
        raise ValueError(f"window {m} does not fit before index {asof}")
    d = distance_profile(x[asof - m + 1: asof + 1], x)
    starts = np.arange(len(d))
    ends = starts + m - 1
    eligible = ends <= asof - m                      # strictly earlier, no overlap
    for s in starts[eligible]:
        if overlaps(dates[s], dates[s + m - 1], spans):
            eligible[s] = False
    d = np.where(eligible, d, np.inf)

    picks: list[dict] = []
    while len(picks) < k and np.isfinite(d).any():
        s = int(np.argmin(d))
        e = s + m - 1
        fwd = {}
        for h in horizons:
            if e + h < n and not overlaps(dates[e + 1], dates[e + h], spans):
                fwd[h] = float(x[e + h] - x[e])      # log-return over horizon
            else:
                fwd[h] = float("nan")
        picks.append({"start": dates[s], "end": dates[e],
                      "distance": float(d[s]), "fwd_log_return": fwd})
        d[max(0, s - m + 1): s + m] = np.inf          # exclusion zone
    return picks


def base_rates(picks: list[dict], horizons: list[int]) -> dict:
    """What followed the analogues, as a per-horizon summary."""
    out = {}
    for h in horizons:
        r = np.array([p["fwd_log_return"][h] for p in picks])
        r = r[np.isfinite(r)]
        out[h] = {"n": int(r.size),
                  "mean": float(r.mean()) if r.size else None,
                  "median": float(np.median(r)) if r.size else None,
                  "frac_up": float((r > 0).mean()) if r.size else None}
    return out
