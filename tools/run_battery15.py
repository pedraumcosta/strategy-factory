"""Plan §17 topic 15: the Carver source battery — exactly three registered
constructions (two EWMAC speeds, vol-standardized carry), screened once each
on the identical perp-funded expanded panel as topic 14, with the three
topic 14 components re-screened as the regression arm (pre-committed
expectation: EXACT equality against the committed results.json). Advisory
kin correlations reported, never gated. Zero LLM spend.

  uv run python tools/run_battery15.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_battery import DATA_DIR, LEDGER, ROOT, ic_screen  # noqa: E402
from run_battery14 import COMPONENTS  # noqa: E402

from factory.universe import expanded  # noqa: E402

FUNDING_DIR = DATA_DIR / "funding"
COMMITTED_TOPIC14 = ROOT / "runs" / "battery-topic14-20261107-142927" / "results.json"

CANDIDATES = {
    "ewmac_16_64": ("(ts_ewma(close, 16) - ts_ewma(close, 64))"
                    " / (ts_std(ts_ret(close, 1), 25) * close)",
                    "cmp_distance_from_highs"),
    "ewmac_32_128": ("(ts_ewma(close, 32) - ts_ewma(close, 128))"
                     " / (ts_std(ts_ret(close, 1), 25) * close)",
                     "cmp_distance_from_highs"),
    "carry_vol": ("-ts_mean(funding, 7) / ts_std(ts_ret(close, 1), 25)",
                  "cmp_funding_carry"),
}


def pooled_spearman(a, b, start: str, end: str) -> float:
    """Advisory kin correlation: Spearman over all jointly valid (date,
    name) cells inside the registered fold span."""
    import pandas as pd
    joined = pd.concat([a.loc[start:end].stack(), b.loc[start:end].stack()],
                       axis=1).dropna()
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1], method="spearman"))


def main() -> None:
    from factory.ledgers import trials
    from factory.screens import dsl
    from factory.screens.screen import load_panels, registered_folds

    folds = registered_folds()
    span = (folds[0][1], folds[-1][2])
    perp = [b for b in expanded()
            if (FUNDING_DIR / f"{b}_USDT-funding.feather").exists()]
    panels = load_panels(DATA_DIR, perp, "1d")   # strict: full coverage
    results: dict = {}

    kin_panels = {name: dsl.evaluate(expr, panels)
                  for name, expr in COMPONENTS.items()}

    for name, (expr, kin) in CANDIDATES.items():
        fw = dsl.evaluate(expr, panels)
        r = ic_screen(name, fw, panels, folds)
        r["kin"] = kin
        r["kin_spearman"] = round(pooled_spearman(fw, kin_panels[kin], *span), 4)
        results[name] = r

    # regression arm: the topic 14 components, bit-for-bit
    committed = json.loads(COMMITTED_TOPIC14.read_text())
    regression: dict = {}
    for name, expr in COMPONENTS.items():
        regression[name] = ic_screen(name, kin_panels[name], panels, folds)
    identical = all(regression[n] == committed[n] for n in COMPONENTS)

    out_dir = ROOT / "runs" / f"battery-topic15-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    lines = [f"# §17 topic 15 battery — Carver's EWMAC and carry, "
             f"cross-sectional reading\n\n{len(perp)} perp-funded names of "
             f"the expanded universe; identical panel to topic 14; regression "
             f"arm vs {COMMITTED_TOPIC14.parent.name}: "
             f"**{'IDENTICAL' if identical else 'DIVERGED'}**.\n"]
    for name, r in results.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic15",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"]})
        verdict = "PASS" if r["passed"] else "KILL"
        lines.append(f"## {name}: **{verdict}**\n```json\n"
                     + json.dumps(r, indent=1) + "\n```\n")
        print(name, "->", verdict, json.dumps(r))
    for name, r in regression.items():
        trials.append(LEDGER, "factor_screen", out_dir.name,
                      {"factor": name, "battery": "topic15-regression",
                       "design": r["design"], "passed": r["passed"],
                       "calibration_valid": r["calibration_valid"],
                       "identical_to_committed": bool(r == committed[name])})
    if not identical:
        lines.append("## REGRESSION ARM DIVERGED\n```json\n"
                     + json.dumps(regression, indent=1) + "\n```\n")
    (out_dir / "report.md").write_text("\n".join(lines))
    (out_dir / "results.json").write_text(json.dumps(
        {**results, "_regression_identical": identical}, indent=1))
    print("regression arm:", "IDENTICAL" if identical else "DIVERGED")
    print("report:", out_dir / "report.md")


if __name__ == "__main__":
    main()
