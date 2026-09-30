"""Seed the trial ledger from the lab's recorded export history.

Every backtest export under lab/user_data/backtest_results/ is a trial that
was actually run in Sep 2026 (plus this repo's own reruns). Importing them
makes the ledger's N honest from day one instead of starting the odometer
at zero with 275 trials already spent. Idempotent: refuses to run if the
ledger already has seeded records.
"""

import json
import zipfile
from pathlib import Path

from factory.ledgers import trials

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "lab" / "user_data" / "backtest_results"
LEDGER = ROOT / "ledgers" / "trials.jsonl"

if __name__ == "__main__":
    if trials.count(LEDGER, kind="backtest-historic"):
        raise SystemExit("ledger already seeded — refusing to double-count")
    n = 0
    for meta in sorted(RESULTS.glob("*.meta.json")):
        meta_d = json.loads(meta.read_text())
        zpath = meta.with_name(meta.name.replace(".meta.json", ".zip"))
        for strategy, info in meta_d.items():
            sharpe = None
            try:
                with zipfile.ZipFile(zpath) as z:
                    d = json.loads(z.read(zpath.name.replace(".zip", ".json")))
                s = d["strategy"][strategy]
                sharpe = s.get("sharpe")
                detail = {
                    "strategy": strategy,
                    "timeframe": info.get("timeframe"),
                    "start_ts": info.get("backtest_start_ts"),
                    "end_ts": info.get("backtest_end_ts"),
                    "trades": s.get("total_trades"),
                    "profit_total": s.get("profit_total"),
                    "sharpe": sharpe,
                }
            except Exception as e:  # unreadable export is still a spent trial
                detail = {"strategy": strategy, "unreadable": str(e)}
            trials.append(LEDGER, "backtest-historic", f"lab:{meta.stem}", detail)
            n += 1
    print(f"seeded {n} historic trials into {LEDGER}")
    print(f"NOTE: hyperopt epochs (user_data/hyperopt_results/, ~1.5 GB of "
          f"per-epoch dumps) are additional trials not counted here — the "
          f"true N is higher, so any DSR computed from this ledger is an "
          f"UNDER-deflation. Recorded in the dossier alongside the number.")
