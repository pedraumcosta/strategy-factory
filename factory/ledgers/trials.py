"""The trial ledger: append-only, deliberately humiliating — the count only
goes up. Every backtest, hyperopt, screen and re-run appends a record, which
is what makes a deflated/trials-adjusted Sharpe computable instead of
aspirational (the gap Plan §20/§24 named)."""

from __future__ import annotations

import json
import time
from pathlib import Path


def append(ledger: Path, kind: str, run_id: str, detail: dict) -> None:
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "kind": kind, "run_id": run_id, **detail}
    with open(ledger, "a") as f:
        f.write(json.dumps(rec) + "\n")


def count(ledger: Path, run_id: str | None = None, kind: str | None = None) -> int:
    if not ledger.exists():
        return 0
    n = 0
    with open(ledger) as f:
        for line in f:
            r = json.loads(line)
            if run_id is not None and r["run_id"] != run_id:
                continue
            if kind is not None and r["kind"] != kind:
                continue
            n += 1
    return n
