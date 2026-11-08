"""Plan §17 topic 16: the feasibility arithmetic, run on a real universe.

Measures the UNIVERSE over the registered IS folds — mean pairwise
correlation, effective breadth, participation ratio, and the minimum
resolvable Sharpe at t >= 2 — pooled and per fold. Evaluates NO signal:
this is not a ledger trial, nothing is spent. Its output is the citation
every time-series registration must carry (prior SR >= sr_min, or the
registration is unwritable).

  uv run python tools/ts_feasibility.py               # expanded, perp-funded subset
  uv run python tools/ts_feasibility.py --legacy17    # the original 17
  uv run python tools/ts_feasibility.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_battery import DATA_DIR  # noqa: E402

from factory.screens.feasibility import feasibility  # noqa: E402
from factory.screens.screen import load_panels, registered_folds  # noqa: E402
from factory.universe import LEGACY_17, expanded  # noqa: E402

FUNDING_DIR = DATA_DIR / "funding"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy17", action="store_true",
                    help="measure the original 17-name universe")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the card as JSON")
    args = ap.parse_args()

    if args.legacy17:
        universe, label = LEGACY_17, "legacy-17"
    else:
        universe = [b for b in expanded()
                    if (FUNDING_DIR / f"{b}_USDT-funding.feather").exists()]
        label = "expanded perp-funded subset"

    folds = registered_folds()
    start, end = folds[0][1], folds[-1][2]
    panels = load_panels(DATA_DIR, universe, "1d", funding="subset")
    close = panels["close"].loc[start:end]
    card = {"universe": label, "span": [start, end],
            **feasibility(close, folds)}

    p = card["pooled"]
    print(f"universe: {label} — {card['n_names']} names, "
          f"{p['n_days']} days ({p['years']}y), span {start}..{end}")
    print(f"pooled:  rho_bar {p['rho_bar']}  n_eff {p['n_eff']}"
          + (f"  participation_ratio {p['participation_ratio']} "
             f"({p['pr_names']} names >= 80% coverage)"
             if "participation_ratio" in p else ""))
    floor = (f"sr_min {p['sr_min']}"
             + (f" .. {p['sr_min_pr']} (by participation ratio)"
                if "sr_min_pr" in p else ""))
    print(f"         minimum resolvable SR at t>=2: {floor}")
    for f in card["folds"]:
        print(f"fold {f['fold']}: rho_bar {f['rho_bar']}  n_eff {f['n_eff']}"
              f"  sr_min {f['sr_min']}  ({f['n_days']}d)")
    print("\nThe gate (Plan §17 topic 16): a time-series registration on this"
          "\nuniverse must cite a prior SR >= the pooled floor above, or it is"
          "\nunwritable. No signal was evaluated; this run is not a trial.")

    if args.json:
        args.json.write_text(json.dumps(card, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
