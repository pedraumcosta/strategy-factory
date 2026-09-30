"""The holdout ledger: a holdout's independence is destroyed by looking at
it (Plan §18.1). The ledger is the single authority on which windows are
clean; access to a clean window requires a signed HG2b approval, and the
spend is recorded permanently. Seeded from Plan §18.2."""

from __future__ import annotations

import json
import time
from pathlib import Path

from factory.orchestrator.approvals import verify

SEED = {
    "windows": [
        {"range": "20210101-20251231", "status": "spent",
         "note": "the seven walk-forward folds (Plan §13-§15)"},
        {"range": "20260101-20260928", "status": "spent",
         "note": "H3's holdout, spent 2026-09-29 (Plan §17)"},
        {"range": "20190101-20201231", "status": "clean",
         "note": "the last untouched window; ~11-13 of 17 pairs exist; spans the 2019 bear + COVID crash (Plan §18.2)"},
    ]
}


# Calendar accrual (Plan §18.2: "calendar time regenerates for free" —
# six months of patience buys a fresh window). Data after the last spent
# window accrues; it becomes a spendable holdout only at maturity.
ACCRUAL_START = "20260929"  # day after H3's holdout ended
MATURITY_DAYS = 180


class HoldoutError(RuntimeError):
    pass


def init(ledger: Path) -> None:
    if not ledger.exists():
        ledger.write_text(json.dumps(SEED, indent=1))


def windows(ledger: Path) -> list[dict]:
    return json.loads(ledger.read_text())["windows"]


def is_clean(ledger: Path, window: str) -> bool:
    for w in windows(ledger):
        if w["range"] == window:
            return w["status"] == "clean"
    raise HoldoutError(f"unknown window {window!r} — add it to the ledger first")


def spend(ledger: Path, window: str, run_dir: Path) -> None:
    """Spend a clean window. Requires a valid HG2b signature on the run;
    refuses spent or unknown windows. Irreversible by design."""
    if not is_clean(ledger, window):
        raise HoldoutError(f"window {window} is not clean — nothing to spend")
    rec = verify(run_dir, "hg2b")  # raises unless signed and untampered
    data = json.loads(ledger.read_text())
    for w in data["windows"]:
        if w["range"] == window:
            w["status"] = "spent"
            w["spent_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            w["spent_by_run"] = run_dir.name
            w["approval"] = rec["signed_at"]
    ledger.write_text(json.dumps(data, indent=1))


def accrue(ledger: Path, as_of: str) -> dict:
    """Update the calendar-accruing window as of YYYYMMDD. Idempotent: one
    accruing entry exists at a time; it matures to 'clean' at MATURITY_DAYS
    and a new accrual then starts behind it. Spending stays HG2b-gated."""
    from datetime import date, timedelta

    def _d(x: str) -> date:
        return date(int(x[:4]), int(x[4:6]), int(x[6:8]))

    data = json.loads(ledger.read_text())
    accruing = [w for w in data["windows"] if w["status"] == "accruing"]
    start = max([ACCRUAL_START] + [w["range"].split("-")[1]
                for w in data["windows"] if w["status"] in ("clean", "spent")
                and w["range"].split("-")[1] >= ACCRUAL_START])
    if not accruing:
        w = {"range": f"{start}-{as_of}", "status": "accruing",
             "note": f"calendar accrual since {start}; matures at {MATURITY_DAYS}d (Plan §18.2)"}
        data["windows"].append(w)
    else:
        w = accruing[0]
        w["range"] = w["range"].split("-")[0] + f"-{as_of}"
    a, b = w["range"].split("-")
    days = (_d(b) - _d(a)).days
    w["days"] = days
    if days >= MATURITY_DAYS:
        w["status"] = "clean"
        w["matured_at"] = as_of
    ledger.write_text(json.dumps(data, indent=1))
    return w
