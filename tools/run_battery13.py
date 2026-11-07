"""Plan §17 topic 13: the calibration battery at expanded breadth — the
five registered constructions re-run once each on the expanded universe,
plus the regression arm: topic 11 re-run bit-for-bit on the LEGACY_17
universe and diffed against its committed results (pre-committed
expectation: EXACT equality). Reuses tools/run_battery.py's harness
functions unchanged, same as topic 12 did. Zero LLM spend.

The pre-committed interpretation travels with the code: these are
CALIBRATION measurements of component IC at wider breadth — a PASS
reopens no closed family and sends nothing to S0 (docs/PLAN.md §17.13).

  uv run python tools/run_battery13.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_battery import (DATA_DIR, LEDGER, ROOT, SEED, UNIVERSE,  # noqa: E402
                         age_factor, conditional_study, funding_factor,
                         ic_screen)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from factory.universe import expanded  # noqa: E402

REFERENCE_11 = ROOT / "runs" / "battery-topic11-20261106-204942" / "results.json"

# the §17.8 four, DSL-verbatim, exactly as registered
DSL_CONSTRUCTIONS = {
    "short_term_reversal": "-ts_ret(close, 5)",
    "low_volatility": "-ts_std(ts_ret(close, 1), 60)",
    "volume_shock": "ts_mean(volume, 5) / ts_mean(volume, 60)",
    "distance_from_highs": "close / ts_max(close, 90)",
}


def main() -> None:
    from factory.ledgers import trials
    from factory.screens import dsl
    from factory.screens.screen import load_panels, registered_folds

    folds = registered_folds()
    universe = expanded()
    panels = load_panels(DATA_DIR, universe, "1d", funding="subset")
    close = panels["close"]
    perp_subset = sorted(panels["funding"].columns[
        panels["funding"].notna().any()]) if "funding" in panels else []

    results: dict = {}
    for name, expr in DSL_CONSTRUCTIONS.items():
        results[name] = ic_screen(name, dsl.evaluate(expr, panels),
                                  panels, folds)
    # FundingCarryTilt in its battery form (run_battery.funding_factor's
    # math, computed from the subset-mode panel: daily-summed events,
    # rolling(7, min_periods=5).mean(), negated)
    fct = -panels["funding"].rolling(7, min_periods=5).mean()
    results["FundingCarryTilt"] = ic_screen("FundingCarryTilt", fct,
                                            panels, folds)

    # --- the regression arm: topic 11 bit-for-bit on LEGACY_17 --------------
    panels17 = load_panels(DATA_DIR, UNIVERSE, "1d")
    close17 = panels17["close"]
    regression: dict = {}
    regression["FundingCarryTilt"] = ic_screen(
        "FundingCarryTilt", funding_factor(close17), panels17, folds)
    regression["ListingAgeEffect"] = ic_screen(
        "ListingAgeEffect", age_factor(close17), panels17, folds)
    ret = close17.pct_change()
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
    wk = pd.Series(close17.index.dayofweek >= 5, index=close17.index)
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

    # --- record --------------------------------------------------------------
    out_dir = ROOT / "runs" / f"battery-topic13-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    meta = {"universe_names": len(universe),
            "perp_subset_names": len(perp_subset),
            "calibration_only": "a PASS reopens no closed family and sends "
                                "nothing to S0 (Plan §17.13)"}
    lines = [f"# §17 topic 13 battery — the five registered constructions "
             f"at expanded breadth\n\n{len(universe)} names "
             f"({len(perp_subset)} perp-funded); calibration measurements "
             f"only — no family reopens, nothing enters S0.\n"]
    for name, r in results.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic13",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
        verdict = "PASS" if r["passed"] else "FAIL"
        lines.append(f"## {name}: **{verdict}**\n```json\n"
                     + json.dumps(r, indent=1) + "\n```\n")
        print(name, "->", verdict, json.dumps(r))
    for name, r in regression.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic13-regression",
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
        {"meta": meta, "calibration": results,
         "regression_identical": regression_ok,
         "regression": regression}, indent=1))
    print("report:", out_dir / "report.md")


if __name__ == "__main__":
    main()
