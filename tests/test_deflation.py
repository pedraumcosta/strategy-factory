"""The deflation module: family selection from the ledger, and the DSR
composition that used to live inline (and untested) in S5."""

import json
import math
import random

from factory.ledgers import trials
from factory.validation import deflation


def _rec(ledger, **detail):
    trials.append(ledger, detail.pop("kind", "backtest"), "r", detail)


DAY = 86400


def test_family_selection_filters_the_comparable_basis(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    _rec(ledger, sharpe=1.2, timeframe="1d", start_ts=DAY, end_ts=400 * DAY)
    _rec(ledger, kind="backtest-historic", sharpe=0.8, timeframe="1d",
         start_ts=DAY, end_ts=350 * DAY)              # seeded history counts
    _rec(ledger, sharpe=-100.0, timeframe="1d",
         start_ts=DAY, end_ts=400 * DAY)              # sentinel: out
    _rec(ledger, sharpe=0.5, timeframe="1h",
         start_ts=DAY, end_ts=400 * DAY)              # wrong timeframe: out
    _rec(ledger, sharpe=2.0, timeframe="1d",
         start_ts=DAY, end_ts=100 * DAY)              # too short: out
    _rec(ledger, timeframe="1d", start_ts=DAY, end_ts=400 * DAY)  # no sharpe: out
    fam = deflation.historic_sharpes(ledger, timeframe="1d")
    assert fam == [1.2, 0.8]


def test_deflate_composes_dsr_from_returns_and_ledger(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    rng = random.Random(3)
    for _ in range(12):
        _rec(ledger, sharpe=rng.gauss(0, 0.8), timeframe="1d",
             start_ts=DAY, end_ts=400 * DAY)
    rets = [rng.gauss(0.001, 0.01) for _ in range(500)]
    d = deflation.deflate(rets, ledger, timeframe="1d")
    assert d["n_trials"] == 12
    assert d["n_ledger_total"] == 12
    assert 0.0 <= d["dsr"] <= 1.0
    assert d["sr"] * math.sqrt(365) == d["sr_annualized"]
    assert "upper bound" in d["note"]


def test_the_family_grows_with_the_ledger(tmp_path):
    """The factory's own recorded runs deflate the next candidate: N comes
    from the ledger, never from a guess (DESIGN §1)."""
    ledger = tmp_path / "trials.jsonl"
    rng = random.Random(5)
    rets = [rng.gauss(0.001, 0.01) for _ in range(400)]
    _rec(ledger, sharpe=0.5, timeframe="1d", start_ts=DAY, end_ts=400 * DAY)
    _rec(ledger, sharpe=0.9, timeframe="1d", start_ts=DAY, end_ts=400 * DAY)
    small = deflation.deflate(rets, ledger, timeframe="1d")
    for s in (1.4, -0.2, 0.7, 1.1, 0.3, 0.8, 1.9, -0.6):
        _rec(ledger, sharpe=s, timeframe="1d", start_ts=DAY, end_ts=400 * DAY)
    big = deflation.deflate(rets, ledger, timeframe="1d")
    assert big["n_trials"] == 10 > small["n_trials"] == 2
    assert big["sr0"] > small["sr0"]  # more search, higher benchmark
    assert big["dsr"] <= small["dsr"]
