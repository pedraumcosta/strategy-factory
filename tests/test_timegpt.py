"""The TimeGPT second alarm (Plan §17 topic 5, shelf §20.17): the holdout
lockout holds on what LEAVES THE MACHINE — no clean/accruing candle is ever
in the frame sent to the vendor — the calibration arithmetic is our own, and
a missing key refuses cleanly instead of half-running. No test touches the
live API: the client is a stub."""

import os

import numpy as np
import pandas as pd
import pytest

from factory import timegpt as tg


def close_series(n=400, start="2021-01-01", seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.Series(100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n))),
                     index=idx)


class StubClient:
    """Records the frame it was sent; flags the last 3 judged bars."""

    def __init__(self):
        self.sent = None
        self.kwargs = None

    def detect_anomalies_online(self, df, **kwargs):
        self.sent = df
        self.kwargs = kwargs
        tail = df.tail(kwargs["detection_size"]).copy()
        tail["anomaly"] = False
        tail.iloc[-3:, tail.columns.get_loc("anomaly")] = True
        tail["anomaly_score"] = np.linspace(0.1, 5.0, len(tail))
        return tail[["unique_id", "ds", "y", "anomaly", "anomaly_score"]]


# --- the holdout seam: what leaves the machine ---------------------------------

def test_readable_segment_trims_accruing_and_stops_at_clean():
    close = close_series(n=2300, start="2020-06-01")  # spans clean + accruing
    spans = [("20190101", "20201231"), ("20260929", "99999999")]
    seg = tg.readable_segment(close, spans)
    assert seg.index[0].strftime("%Y%m%d") == "20210101"   # clean caps the left
    assert seg.index[-1].strftime("%Y%m%d") <= "20260928"  # accruing trims right
    assert len(seg) > 2000                                  # the spent run survives


def test_readable_segment_empty_when_everything_is_forbidden():
    close = close_series(n=50, start="2019-03-01")
    seg = tg.readable_segment(close, [("20190101", "20201231")])
    assert len(seg) == 0


def test_no_forbidden_candle_is_ever_sent():
    close = close_series(n=2300, start="2020-06-01")
    spans = [("20190101", "20201231"), ("20260929", "99999999")]
    seg = tg.readable_segment(close, spans)
    client = StubClient()
    tg.detect(client, seg, level=99, detection_size=90, h=1)
    from factory import similarity as sim
    sent_dates = [d.strftime("%Y%m%d") for d in client.sent["ds"]]
    assert sent_dates and not any(sim.overlaps(d, d, spans) for d in sent_dates)


def test_detect_pins_the_model_and_normalizes_output():
    close = close_series()
    client = StubClient()
    out = tg.detect(client, close, level=95, detection_size=60, h=1)
    assert client.kwargs["model"] == tg.MODEL
    assert client.kwargs["level"] == 95
    assert list(out.columns) == ["ds", "anomaly", "anomaly_score"]
    assert out["anomaly"].sum() == 3


# --- the calibration arithmetic -------------------------------------------------

def test_coverage_places_empirical_next_to_nominal():
    flags = np.zeros(200, bool)
    flags[:6] = True
    cov = tg.coverage(flags, level=99)
    assert cov["flagged"] == 6 and cov["n"] == 200
    assert cov["rate"] == pytest.approx(0.03)
    assert cov["nominal"] == pytest.approx(0.01)
    assert cov["expected"] == pytest.approx(2.0)


def test_mass_crossings_finds_the_planted_novel_tail():
    t = np.arange(500, dtype=float)
    x = np.sin(2 * np.pi * t / 25)
    m = 50
    x2 = x.copy()
    x2[-m:] = np.linspace(0, 1, m) ** 3          # unprecedented tail shape
    dates = [d.strftime("%Y%m%d")
             for d in pd.date_range("2021-01-01", periods=len(x2), freq="D")]
    allowed = np.ones(len(x2) - m + 1, bool)
    tail = dates[-30:]
    crossed = tg.mass_crossings(x2, dates, m, allowed, tail)
    # the alarm fires as the ramp arrives (sine/ramp mixture windows can
    # out-score the pure ramp window, so the exact final day may sit at p99)
    assert crossed and all(d in dates[-2 * m:] for d in crossed)
    quiet = tg.mass_crossings(x, dates, m, allowed, tail)
    assert quiet == set()                         # periodic tape: no crossing


def test_agreement_table():
    agr = tg.agreement({"a", "b", "c"}, {"b", "c", "d"})
    assert agr == {"both": 2, "timegpt_only": 1, "mass_only": 1}


# --- the refusal ----------------------------------------------------------------

def test_missing_key_refuses_cleanly(monkeypatch):
    monkeypatch.delenv("NIXTLA_API_KEY", raising=False)
    with pytest.raises(tg.TimeGPTUnavailable, match="NIXTLA_API_KEY"):
        tg.make_client()
