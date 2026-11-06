"""TimeGPT online anomaly detection — the registered SECOND observer alarm
(Plan §17 topic 5; shelf verdict Autotrader Plan §20.17): Nixtla's hosted
`detect_anomalies_online` as the model-based complement to the model-free
MASS distance in factory/similarity.py.

The three caveats from the registration, answered in code:

  paid vendor API — every run appends a `vendor_api` record to the trial
  ledger with the call count and a conservative cost estimate, so the
  odometer sees it (free Starter tier: 50 calls/month; one 17-pair run
  is 17 calls).

  uncalibrated intervals until proven otherwise (§17.2) — this module is a
  CALIBRATION REPORT, not a pager: it places the vendor's nominal exceedance
  rate (1 - level) next to the empirical flag rate on our own tape, and next
  to the MASS alarm's reading of the same days. Thresholds are picked by a
  human from the report before anything pages.

  AD-on-the-data-being-judged is the self-reference mistake — only the last
  `detection_size` bars are judged, against forecasts conditioned on the
  prior history, and the model version is pinned and logged per run (a
  silent vendor upgrade breaks a calibrated gate quietly).

The holdout lockout holds at this seam like every other: what is SENT to
the vendor is the trailing contiguous readable segment — no candle from a
clean or accruing window ever leaves the machine. (In practice: the clean
2019-2020 window caps the segment at 2021-01-01, and accruing bars trim it
on the right.)
"""

from __future__ import annotations

import os

import numpy as np

MODEL = "timegpt-1"            # pinned; logged per run
FREQ = "D"
# marginal Standard-tier rate ($99 / 10,000 calls), the conservative
# estimate the ledger carries even while the free tier covers the run
COST_PER_CALL_USD = 0.0099


class TimeGPTUnavailable(RuntimeError):
    pass


def make_client():
    """The real Nixtla client, or a clean refusal naming the one step a
    human must do (sign up, set the key)."""
    key = os.environ.get("NIXTLA_API_KEY")
    if not key:
        raise TimeGPTUnavailable(
            "NIXTLA_API_KEY is not set. Create a key at "
            "https://dashboard.nixtla.io (free Starter tier: 50 API "
            "calls/month — one 17-pair calibration run is 17) and export "
            "NIXTLA_API_KEY before running `factory timegpt`.")
    try:
        from nixtla import NixtlaClient
    except ImportError as e:
        raise TimeGPTUnavailable(
            "the `nixtla` package is not installed — `uv sync` (it is a "
            "project dependency) or `uv add nixtla`.") from e
    return NixtlaClient(api_key=key)


# --- holdout masking of what leaves the machine --------------------------------

def readable_segment(close, spans):
    """The trailing CONTIGUOUS run of bars whose dates overlap no forbidden
    span — the only candles this module may send to the vendor. Trailing
    forbidden bars (the accruing window) are trimmed first; the walk back
    then stops at the first forbidden date (the clean window's right edge)."""
    dates = [d.strftime("%Y%m%d") for d in close.index]
    from factory import similarity as sim
    allowed = [not sim.overlaps(d, d, spans) for d in dates]
    last = max((i for i, a in enumerate(allowed) if a), default=None)
    if last is None:
        return close.iloc[0:0]
    first = last
    while first > 0 and allowed[first - 1]:
        first -= 1
    return close.iloc[first:last + 1]


# --- the vendor call ------------------------------------------------------------

def detect(client, close, level: int, detection_size: int, h: int):
    """One `detect_anomalies_online` call on a (pre-masked) close series;
    returns the normalized frame: columns ds, anomaly (bool),
    anomaly_score (float), restricted to the judged tail."""
    import pandas as pd

    df = pd.DataFrame({"unique_id": "series", "ds": close.index,
                       "y": close.to_numpy(dtype=float)})
    out = client.detect_anomalies_online(
        df=df, time_col="ds", target_col="y", freq=FREQ, h=h,
        level=level, detection_size=detection_size, model=MODEL)
    out = out.rename(columns={c: c.lower() for c in out.columns})
    return out[["ds", "anomaly", "anomaly_score"]].reset_index(drop=True)


# --- the calibration arithmetic (§17.2: our tape, not their distribution) -------

def coverage(flags: np.ndarray, level: int) -> dict:
    """Empirical flag rate vs the nominal exceedance the level claims."""
    n = int(flags.size)
    k = int(flags.sum())
    nominal = (100 - level) / 100
    return {"n": n, "flagged": k,
            "rate": k / n if n else float("nan"),
            "nominal": nominal,
            "expected": nominal * n}


def mass_crossings(x: np.ndarray, dates: list[str], m: int,
                   allowed: np.ndarray, tail_dates: list[str]) -> set[str]:
    """The dates inside `tail_dates` whose MASS novelty (window m, ending
    that day) exceeds its own historical p99 — the model-free alarm's
    reading of the same days, for the agreement table."""
    from factory import similarity as sim

    nov = sim.novelty_series(x, m, allowed)
    finite = nov[np.isfinite(nov)]
    if not finite.size:
        return set()
    p99 = float(np.quantile(finite, 0.99))
    end_date_of = {dates[s + m - 1]: s for s in range(len(nov))}
    out = set()
    for d in tail_dates:
        s = end_date_of.get(d)
        if s is not None and np.isfinite(nov[s]) and nov[s] > p99:
            out.add(d)
    return out


def agreement(tg_dates: set[str], mass_dates: set[str]) -> dict:
    return {"both": len(tg_dates & mass_dates),
            "timegpt_only": len(tg_dates - mass_dates),
            "mass_only": len(mass_dates - tg_dates)}
