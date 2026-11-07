"""Plan §17 topic 12: the user-sourced battery — three testable registered
constructions, one run each, plus the regression arm: topic 11 re-run
bit-for-bit and diffed against its committed results (pre-committed
expectation: EXACT equality). Reuses tools/run_battery.py's harness
functions unchanged — that reuse is what makes the regression arm a test
of data/seam integrity rather than of a rewrite. Zero LLM spend.

  uv run python tools/run_battery12.py

OiPriceDivergence runs only when ~/freqtrade-data/oi/ holds all 17
feathers (tools/fetch_oi.py); otherwise it is reported as pending and a
later invocation records it in its own run directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_battery import (LEDGER, ROOT, SEED, UNIVERSE, age_factor,  # noqa: E402
                         conditional_study, funding_factor, ic_screen)

DATA_DIR = Path.home() / "freqtrade-data"
OI_DIR = DATA_DIR / "oi"
REFERENCE_11 = ROOT / "runs" / "battery-topic11-20261106-204942" / "results.json"
LEADERS = ("ETH", "SOL")
ALTS = [s for s in UNIVERSE if s not in ("BTC",) + LEADERS]   # 14 names


def cascade_factor(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(gated factor over the 14 alts, alt close panel). Leader signal
    s_t = mean(3d ETH, SOL) - 3d BTC; on s_t>0 days the factor is the
    NEGATIVE of each alt's own 3d return (laggards rank top)."""
    r3 = close.pct_change(3)
    s = r3[list(LEADERS)].mean(axis=1) - r3["BTC"]
    fac = (-r3[ALTS]).where(s > 0, other=np.nan)
    return fac, close[ALTS]


def session_returns(close_1h: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(us, nonus) day-indexed equal-weight basket session returns from 1h
    bars. US = bars 13:00-19:00 UTC of day d (covering 13:00->20:00);
    non-US = bars 20:00-23:00 of d-1 plus 00:00-12:00 of d."""
    ret = close_1h.pct_change().mean(axis=1)   # equal-weight hourly basket
    hours = ret.index.hour
    day = ret.index.normalize()
    us = ret[(hours >= 13) & (hours <= 19)].groupby(
        day[(hours >= 13) & (hours <= 19)]).sum()
    # evening bars belong to the NEXT day's pre-US window
    shifted_day = day.where(hours < 20, day + pd.Timedelta(days=1))
    pre = ret[(hours >= 20) | (hours <= 12)].groupby(
        shifted_day[(hours >= 20) | (hours <= 12)]).sum()
    idx = us.index.intersection(pre.index)
    return us.loc[idx], pre.loc[idx]


def oi_divergence_factor(close: pd.DataFrame) -> pd.DataFrame | None:
    """-(z_cs(dlog OI 24h) - z_cs(ret 24h)); None while the fetch is short."""
    cols = {}
    for sym in UNIVERSE:
        f = OI_DIR / f"{sym}_USDT-oi.feather"
        if not f.exists():
            return None
        df = pd.read_feather(f)
        idx = pd.DatetimeIndex(
            pd.to_datetime(df["date"], utc=True)).tz_localize(None)
        cols[sym] = pd.Series(df["sum_open_interest"].values, index=idx)
    oi = pd.DataFrame(cols).reindex(close.index)   # read capped by close
    dlog_oi = np.log(oi).diff()
    r1 = close.pct_change()

    def zcs(x: pd.DataFrame) -> pd.DataFrame:
        return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)

    return -(zcs(dlog_oi) - zcs(r1))


def main() -> None:
    from factory.ledgers import trials
    from factory.screens.screen import load_panels, registered_folds

    folds = registered_folds()
    panels = load_panels(DATA_DIR, UNIVERSE, "1d")
    close = panels["close"]
    results: dict = {}

    # --- the three registered candidates -----------------------------------
    fac, alt_close = cascade_factor(close)
    results["EthBtcSectorCascade"] = ic_screen(
        "EthBtcSectorCascade", fac, {"close": alt_close}, folds)

    close_1h = load_panels(DATA_DIR, UNIVERSE, "1h")["close"]
    us, pre = session_returns(close_1h)
    rng = np.random.default_rng(SEED)
    fade = (pre < 0)
    results["UsMarketOpenDrift"] = conditional_study(
        "UsMarketOpenDrift", us,
        {"UsMarketOpenDrift": fade,
         "ORACLE": (us > us.median()).fillna(False),
         "PLACEBO": pd.Series(rng.random(len(us)) < fade.mean(),
                              index=us.index)},
        folds)

    oi_fac = oi_divergence_factor(close)
    if oi_fac is not None:
        results["OiPriceDivergence"] = ic_screen(
            "OiPriceDivergence", oi_fac, panels, folds)
    else:
        print("OiPriceDivergence: OI fetch incomplete — pending")

    # --- the regression arm: topic 11 bit-for-bit --------------------------
    regression: dict = {}
    regression["FundingCarryTilt"] = ic_screen(
        "FundingCarryTilt", funding_factor(close), panels, folds)
    regression["ListingAgeEffect"] = ic_screen(
        "ListingAgeEffect", age_factor(close), panels, folds)
    ret = close.pct_change()
    alt = ret.drop(columns=["BTC"]).mean(axis=1)
    rng = np.random.default_rng(SEED)   # same fresh stream as run_battery.main
    btc_up = (ret["BTC"].shift(1) > 0).fillna(False)
    regression["BtcLeadLag"] = conditional_study(
        "BtcLeadLag", alt,
        {"BtcLeadLag": btc_up,
         "ORACLE": (alt > alt.median()).fillna(False),
         "PLACEBO": pd.Series(rng.random(len(alt)) < btc_up.mean(),
                              index=alt.index)},
        folds)
    wk = pd.Series(close.index.dayofweek >= 5, index=close.index)
    regression["WeekendSeasonality"] = conditional_study(
        "WeekendSeasonality", alt,
        {"WeekendSeasonality": wk,
         "ORACLE": (alt > alt.median()).fillna(False),
         "PLACEBO": pd.Series(rng.random(len(alt)) < wk.mean(),
                              index=alt.index)},
        folds)

    reference = json.loads(REFERENCE_11.read_text())
    diffs = {name: {"got": regression[name], "expected": reference[name]}
             for name in reference
             if json.loads(json.dumps(regression[name])) != reference[name]}
    regression_ok = not diffs

    # --- record -------------------------------------------------------------
    out_dir = ROOT / "runs" / f"battery-topic12-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    lines = ["# §17 topic 12 battery — user-sourced candidates\n"]
    for name, r in results.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic12",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
        verdict = "PASS" if r["passed"] else "KILL"
        lines.append(f"## {name}: **{verdict}**\n```json\n"
                     + json.dumps(r, indent=1) + "\n```\n")
        print(name, "->", verdict, json.dumps(r))
    for name, r in regression.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic12-regression",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
    lines.append("## Regression arm (topic 11 re-run): "
                 + ("**IDENTICAL** — every number matches the committed "
                    "results.json" if regression_ok
                    else "**DIVERGED** — data/seam integrity alarm\n```json\n"
                    + json.dumps(diffs, indent=1) + "\n```"))
    print("regression:", "IDENTICAL" if regression_ok else "DIVERGED")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    (out_dir / "results.json").write_text(json.dumps(
        {"candidates": results, "regression_identical": regression_ok,
         "regression": regression}, indent=1))
    print("report:", out_dir / "report.md")


if __name__ == "__main__":
    main()
