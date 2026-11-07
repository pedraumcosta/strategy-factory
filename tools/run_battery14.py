"""Plan §17 topic 14: the composite battery — exactly two registered
composite constructions, screened once each on the perp-funded subset of
the expanded universe, beside their three components re-screened on the
IDENTICAL panel so the comparison is like-for-like. Zero LLM spend.

The registered pass bar is double: the standing §22 judge (calibration
valid, pooled IC |t| >= 2 at a registered horizon) AND the composite's
pooled h21 IC must exceed the best of its own components' on the same run
— otherwise composition added nothing and the battery closes.

  uv run python tools/run_battery14.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_battery import DATA_DIR, LEDGER, ROOT, ic_screen  # noqa: E402

from factory.universe import expanded  # noqa: E402

FUNDING_DIR = DATA_DIR / "funding"

COMPONENTS = {
    "cmp_funding_carry": "-ts_mean(funding, 7)",
    "cmp_distance_from_highs": "close / ts_max(close, 90)",
    "cmp_low_volatility": "-ts_std(ts_ret(close, 1), 60)",
}
COMPOSITES = {
    "CarryBreakoutComposite": (
        "cs_zscore(-ts_mean(funding, 7)) + cs_zscore(close / ts_max(close, 90))",
        ("cmp_funding_carry", "cmp_distance_from_highs")),
    "CarryBreakoutQuietComposite": (
        "cs_zscore(-ts_mean(funding, 7)) + cs_zscore(close / ts_max(close, 90))"
        " + cs_zscore(-ts_std(ts_ret(close, 1), 60))",
        ("cmp_funding_carry", "cmp_distance_from_highs", "cmp_low_volatility")),
}


def pooled_h21_ic(result: dict) -> float:
    return float(result["ic_by_horizon"]["21"]["mean"])


def main() -> None:
    from factory.ledgers import trials
    from factory.screens import dsl
    from factory.screens.screen import load_panels, registered_folds

    folds = registered_folds()
    perp = [b for b in expanded()
            if (FUNDING_DIR / f"{b}_USDT-funding.feather").exists()]
    panels = load_panels(DATA_DIR, perp, "1d")   # strict: full coverage
    results: dict = {}

    for name, expr in COMPONENTS.items():
        results[name] = ic_screen(name, dsl.evaluate(expr, panels),
                                  panels, folds)
    for name, (expr, comps) in COMPOSITES.items():
        r = ic_screen(name, dsl.evaluate(expr, panels), panels, folds)
        best_cmp = max(pooled_h21_ic(results[c]) for c in comps)
        r["best_component_h21_ic"] = round(best_cmp, 4)
        r["beats_components"] = bool(pooled_h21_ic(r) > best_cmp)
        r["passed"] = bool(r["passed"] and r["beats_components"])
        results[name] = r

    out_dir = ROOT / "runs" / f"battery-topic14-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    lines = [f"# §17 topic 14 battery — two registered composites vs their "
             f"own components\n\n{len(perp)} perp-funded names of the "
             f"expanded universe; identical panel for every arm.\n"]
    for name, r in results.items():
        battery = "topic14-components" if name in COMPONENTS else "topic14"
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": battery,
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
        verdict = "PASS" if r["passed"] else ("FAIL" if name in COMPONENTS
                                              else "KILL")
        lines.append(f"## {name}: **{verdict}**\n```json\n"
                     + json.dumps(r, indent=1) + "\n```\n")
        print(name, "->", verdict, json.dumps(r))
    (out_dir / "report.md").write_text("\n".join(lines))
    (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    print("report:", out_dir / "report.md")


if __name__ == "__main__":
    main()
