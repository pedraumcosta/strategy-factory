"""Plan §17 topic 11: the model-suggested battery — four registered
constructions, one run each, measured on the registered IS folds through
the §22 seams. Cross-sectional candidates run the standard IC screen with
its ORACLE/NOISE arms; conditional candidates carry the same discipline as
an ORACLE-analog (look-ahead conditioning, must pass) and a PLACEBO
(seeded random conditioning, must fail). Every result is a factor_screen
trial on the ledger. Zero LLM spend.

  uv run python tools/run_battery.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledgers" / "trials.jsonl"
FUNDING_DIR = Path.home() / "freqtrade-data" / "funding"
DATA_DIR = Path.home() / "freqtrade-data"
UNIVERSE = ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
            "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"]
SEED = 20261106
T_MIN = 2.0


# --- cross-sectional screens (the standard §22 harness, custom factor panel) ----

def ic_screen(name: str, factor_wide, panels, folds) -> dict:
    """The run_screen shape with an externally built candidate panel —
    NOISE/ORACLE arms identical to build_arms, judged by the same judge."""
    from factory.gates import factor as factor_judge
    from factory.screens.screen import ORACLE_HORIZON, PERIODS, screen_window

    close = panels["close"]
    rng = np.random.default_rng(SEED)
    arms = {
        name: factor_wide,
        "NOISE": pd.DataFrame(rng.standard_normal(close.shape),
                              index=close.index, columns=close.columns),
        "ORACLE": close.shift(-ORACLE_HORIZON) / close - 1.0,
    }
    fwd_by_p = {p: close.shift(-p) / close - 1.0 for p in PERIODS}
    rows = []
    for arm, fw in arms.items():
        for fid, s, e in folds:
            r = screen_window(fw, fwd_by_p, s, e)
            if r:
                rows.append({**r, "factor": arm, "fold": fid})
        r = screen_window(fw, fwd_by_p, folds[0][1], folds[-1][2])
        if r:
            rows.append({**r, "factor": arm, "fold": "pooled"})
    str_rows = [{k: str(v) for k, v in r.items()} for r in rows]
    verdicts = {arm: factor_judge.judge(str_rows, arm) for arm in arms}
    valid = verdicts["ORACLE"].passed and not verdicts["NOISE"].passed
    cand = verdicts[name]
    return {"design": "cross_sectional_ic", "calibration_valid": valid,
            "passed": bool(valid and cand.passed), "reason": cand.reason,
            "ic_by_horizon": {str(h): {k: round(x, 4) for k, x in v.items()}
                              for h, v in cand.ic_by_horizon.items()}}


def funding_factor(close) -> pd.DataFrame:
    """−(7d mean of daily-aggregated 8h funding) — most negative ranks top."""
    cols = {}
    for sym in UNIVERSE:
        f = FUNDING_DIR / f"{sym}_USDT-funding.feather"
        df = pd.read_feather(f)
        idx = pd.DatetimeIndex(pd.to_datetime(df["date"], utc=True)).tz_localize(None)
        daily = pd.Series(df["fundingRate"].values, index=idx).resample("D").sum(min_count=1)
        cols[sym] = daily
    fund = pd.DataFrame(cols).reindex(close.index)   # read capped by close's HARD_STOP
    return -fund.rolling(7, min_periods=5).mean()


def age_factor(close) -> pd.DataFrame:
    """−log(days since first candle): tilt away from the youngest listings."""
    first = close.apply(lambda s: s.first_valid_index())
    days = pd.DataFrame({c: (close.index - first[c]).days for c in close.columns},
                        index=close.index).astype(float)
    days = days.where(days >= 1).where(close.notna())
    return -np.log(days)


# --- conditional studies (same arm discipline, Welch t) --------------------------

def welch_t(a: pd.Series, b: pd.Series) -> float:
    a, b = a.dropna(), b.dropna()
    if len(a) < 20 or len(b) < 20:
        return float("nan")
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    return float((a.mean() - b.mean()) / math.sqrt(va + vb)) if va + vb > 0 else float("nan")


def conditional_study(name: str, basket: pd.Series, labels: dict, folds) -> dict:
    """labels = {candidate: bool Series, ORACLE: ..., PLACEBO: ...} — True rows
    vs False rows compared by Welch t per fold and pooled; ORACLE must pass,
    PLACEBO must fail, candidate judged on the pooled |t|."""
    out_t = {}
    per_fold = {}
    for arm, lab in labels.items():
        ts = []
        for fid, s, e in folds:
            w = basket.loc[s:e]
            ts.append(welch_t(w[lab.loc[s:e]], w[~lab.loc[s:e]]))
        per_fold[arm] = [round(t, 2) if t == t else None for t in ts]
        full = basket.loc[folds[0][1]:folds[-1][2]]
        lf = lab.loc[folds[0][1]:folds[-1][2]]
        out_t[arm] = welch_t(full[lf], full[~lf])
    valid = (out_t["ORACLE"] == out_t["ORACLE"] and abs(out_t["ORACLE"]) >= T_MIN
             and not (out_t["PLACEBO"] == out_t["PLACEBO"]
                      and abs(out_t["PLACEBO"]) >= T_MIN))
    t = out_t[name]
    full = basket.loc[folds[0][1]:folds[-1][2]]
    lf = labels[name].loc[folds[0][1]:folds[-1][2]]
    diff_bp = (full[lf].mean() - full[~lf].mean()) * 1e4
    return {"design": "conditional", "calibration_valid": bool(valid),
            "passed": bool(valid and t == t and abs(t) >= T_MIN),
            "pooled_t": round(t, 2) if t == t else None,
            "diff_bp_per_day": round(float(diff_bp), 2),
            "per_fold_t": per_fold[name],
            "oracle_t": round(out_t["ORACLE"], 1),
            "placebo_t": round(out_t["PLACEBO"], 2)}


def main() -> None:
    from factory.ledgers import trials
    from factory.screens.screen import load_panels, registered_folds

    folds = registered_folds()
    panels = load_panels(DATA_DIR, UNIVERSE, "1d")   # HARD_STOP capped
    close = panels["close"]
    ret = close.pct_change()
    alt = ret.drop(columns=["BTC"]).mean(axis=1)

    rng = np.random.default_rng(SEED)
    results = {}

    results["FundingCarryTilt"] = ic_screen(
        "FundingCarryTilt", funding_factor(close), panels, folds)
    results["ListingAgeEffect"] = ic_screen(
        "ListingAgeEffect", age_factor(close), panels, folds)

    btc_up = (ret["BTC"].shift(1) > 0).fillna(False)
    results["BtcLeadLag"] = conditional_study(
        "BtcLeadLag", alt,
        {"BtcLeadLag": btc_up,
         # outcome-based look-ahead conditioning, same shape as the weekend
         # study's arm: separating days by their own sign must trivially pass
         "ORACLE": (alt > alt.median()).fillna(False),
         "PLACEBO": pd.Series(rng.random(len(alt)) < btc_up.mean(),
                              index=alt.index)},
        folds)

    wk = pd.Series(close.index.dayofweek >= 5, index=close.index)
    results["WeekendSeasonality"] = conditional_study(
        "WeekendSeasonality", alt,
        {"WeekendSeasonality": wk,
         "ORACLE": (alt > alt.median()).fillna(False),
         "PLACEBO": pd.Series(rng.random(len(alt)) < wk.mean(),
                              index=alt.index)},
        folds)

    out_dir = ROOT / "runs" / f"battery-topic11-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    lines = ["# §17 topic 11 battery — model-suggested candidates\n"]
    for name, r in results.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic11",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
        verdict = "PASS" if r["passed"] else "KILL"
        lines.append(f"## {name}: **{verdict}**\n```json\n"
                     + json.dumps(r, indent=1) + "\n```\n")
        print(name, "->", verdict, json.dumps(r))
    (out_dir / "report.md").write_text("\n".join(lines))
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    print("report:", out_dir / "report.md")


if __name__ == "__main__":
    main()
