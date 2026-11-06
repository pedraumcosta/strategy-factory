"""MASS-style similarity (Plan §17 topic 5): the distance is what MASS
means (z-normalized Euclidean, checked against brute force), retrieval is
shape- not scale-based, and the holdout lockout holds at this seam — clean
and accruing windows are invisible to analogue retrieval, forward reads,
and novelty evaluation alike."""

import numpy as np
import pandas as pd
import pytest

from factory import similarity as sim


def dates_for(n, start="2021-01-01"):
    return [d.strftime("%Y%m%d")
            for d in pd.date_range(start, periods=n, freq="D")]


# --- the distance -------------------------------------------------------------

def test_profile_matches_brute_force():
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.standard_normal(300))
    m = 30
    q = x[100:130]
    d = sim.distance_profile(q, x)
    for s in (0, 57, 100, 241):
        w, qq = x[s:s + m], q
        zw = (w - w.mean()) / w.std()
        zq = (qq - qq.mean()) / qq.std()
        assert d[s] == pytest.approx(float(np.linalg.norm(zq - zw)), abs=1e-8)
    assert d[100] == pytest.approx(0.0, abs=1e-9)


def test_flat_windows_have_no_shape():
    x = np.ones(100)
    x[60:] = np.arange(40)
    d = sim.distance_profile(x[-30:], x)
    assert np.isinf(d[0])                       # flat window: never a match
    q = np.ones(30)
    assert np.isinf(sim.distance_profile(q, x)).all()  # flat query matches nothing


# --- analogues ----------------------------------------------------------------

def motif_series(n=400, m=40, copies=((50, 3.0, 5.0), (300, 0.5, -2.0)), seed=5):
    """Low-amplitude noise with the same motif planted at different scales
    and offsets; returns (x, motif starts)."""
    rng = np.random.default_rng(seed)
    x = 0.05 * rng.standard_normal(n)
    motif = np.sin(np.linspace(0, 6 * np.pi, m))
    for start, scale, shift in copies:
        x[start:start + m] = shift + scale * motif + 0.01 * rng.standard_normal(m)
    return x


def test_retrieval_is_shape_based_and_finds_the_planted_motif():
    m = 40
    x = motif_series()
    dates = dates_for(len(x))
    # query = the small, shifted copy (ends at 339); the big copy at 50
    # must be the nearest analogue despite the 6x scale and offset
    picks = sim.analogues(x, dates, m, k=2, horizons=[5], spans=[],
                          asof_idx=339)
    assert picks[0]["start"] == dates[50]
    assert picks[0]["distance"] < 1.0           # near-identical shape
    assert picks[1]["distance"] > 3 * picks[0]["distance"]  # noise is far


def test_analogues_never_overlap_the_query_or_each_other():
    x = motif_series()
    dates = dates_for(len(x))
    m, asof = 40, 339
    picks = sim.analogues(x, dates, m, k=5, horizons=[5], spans=[],
                          asof_idx=asof)
    starts = [dates.index(p["start"]) for p in picks]
    assert all(s + m - 1 <= asof - m for s in starts)       # strictly earlier
    starts.sort()
    assert all(b - a >= m for a, b in zip(starts, starts[1:]))  # exclusion


def test_forbidden_windows_are_invisible_to_retrieval():
    m = 40
    x = motif_series()
    dates = dates_for(len(x))
    # the only true analogue (bars 50..89) falls inside a clean span
    spans = sim.forbidden_spans(
        [{"range": f"{dates[40]}-{dates[100]}", "status": "clean"}])
    picks = sim.analogues(x, dates, m, k=1, horizons=[5], spans=spans,
                          asof_idx=339)
    assert picks[0]["start"] != dates[50]
    assert picks[0]["distance"] > 1.0           # only noise remains


def test_forward_reads_crossing_a_span_or_the_data_end_are_nan():
    m = 40
    x = motif_series()
    dates = dates_for(len(x))
    # a span right after the motif copy at 50: its forward read is blocked
    spans = [(dates[95], dates[120])]
    picks = sim.analogues(x, dates, m, k=1, horizons=[10, 3], spans=spans,
                          asof_idx=339)
    assert picks[0]["start"] == dates[50]       # the window itself is readable
    assert np.isnan(picks[0]["fwd_log_return"][10])   # 89+10 crosses the span
    assert np.isfinite(picks[0]["fwd_log_return"][3])  # 89+3 does not
    rates = sim.base_rates(picks, [10, 3])
    assert rates[10]["n"] == 0 and rates[3]["n"] == 1


# --- novelty ------------------------------------------------------------------

def test_novelty_flags_the_unprecedented_window():
    t = np.arange(500, dtype=float)
    x = np.sin(2 * np.pi * t / 25)              # every window has precedent
    m = 50
    periodic = sim.novelty_series(x, m)
    assert np.nanmax(periodic[-100:]) < 0.1     # deep memory, nothing new
    x2 = x.copy()
    x2[-m:] = np.linspace(0, 1, m) ** 3         # a shape no sine window has
    nov = sim.novelty_series(x2, m)
    # every all-time-high novelty window touches the ramp (sine/ramp
    # mixtures may beat the pure ramp window — also unprecedented shapes)
    assert int(np.nanargmax(nov)) > len(nov) - 2 * m
    assert nov[-1] > 1.0                        # the ramp window itself: loud
    assert nov[-1] > 100 * np.nanmax(periodic[-100:])


def test_novelty_respects_the_allowed_mask():
    m = 40
    x = motif_series()
    n_windows = len(x) - m + 1
    # window 300 (the small copy)'s only real neighbour is the copy at 50
    free = sim.novelty_series(x, m)
    allowed = np.ones(n_windows, bool)
    allowed[10:100] = False                     # make the copy unreadable
    masked = sim.novelty_series(x, m, allowed)
    assert free[300] < 1.0                      # precedent found
    assert masked[300] > 3 * free[300]          # memory redacted: novel now
    assert np.isnan(masked[50])                 # not evaluated inside the mask


def test_forbidden_spans_parsing_and_overlap():
    spans = sim.forbidden_spans([
        {"range": "20190101-20201231", "status": "clean"},
        {"range": "20210101-20251231", "status": "spent"},
        {"range": "20260929-", "status": "accruing"},
    ])
    assert spans == [("20190101", "20201231"), ("20260929", "99999999")]
    assert sim.overlaps("20201230", "20210105", spans)    # touches clean
    assert not sim.overlaps("20210101", "20260928", spans)  # spent is readable
    assert sim.overlaps("20260901", "20261001", spans)    # runs into accrual
