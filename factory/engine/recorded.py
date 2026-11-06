"""Every backtest is a trial, and the holdout lockout holds for every
caller — invariants of the seam, not conventions repeated at call sites.

RecordedEngine wraps any engine adapter (the docker LabEngine in
production, fakes in tests — two adapters, so the seam is real) and is the
only form of engine the stages see:

- every backtest is appended to the trial ledger with one canonical
  payload, including the Sharpe, timeframe and window timestamps that the
  deflation family (factory/validation/deflation.py) reads back;
- a requested timerange that touches a clean or accruing window on the
  holdout ledger is refused before any data is read. Spending a clean
  window goes through holdout.spend with a signed HG2b — never through
  here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timezone
from datetime import datetime as _dt
from pathlib import Path
from typing import Protocol

from factory.engine.lab import BacktestResult
from factory.ledgers import holdout, trials


class Engine(Protocol):
    """What an engine adapter must supply at this seam."""

    data_dir: Path | None

    def backtest(self, strategy: str, timeframe: str, timerange: str,
                 fee: float, strategy_path: Path | None = None) -> BacktestResult:
        ...


class HoldoutRefusal(RuntimeError):
    pass


def _ts(yyyymmdd: str) -> int:
    d = date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    return int(_dt(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


@dataclass
class RecordedEngine:
    engine: Engine
    trial_ledger: Path
    holdout_ledger: Path | None = None

    @property
    def data_dir(self) -> Path | None:
        return getattr(self.engine, "data_dir", None)

    def backtest(self, strategy: str, timeframe: str, timerange: str,
                 fee: float, *, run_id: str, why: str,
                 strategy_path: Path | None = None) -> BacktestResult:
        self._refuse_protected_windows(timerange)
        r = self.engine.backtest(strategy, timeframe, timerange, fee,
                                 strategy_path=strategy_path)
        a, _, b = timerange.partition("-")
        trials.append(self.trial_ledger, "backtest", run_id, {
            "strategy": strategy, "timeframe": timeframe,
            "timerange": timerange, "fee": fee, "why": why,
            "trades": r.trade_count, "profit_total": r.profit_total,
            "profit_mean": r.profit_mean, "sharpe": r.sharpe,
            "start_ts": _ts(a) if a else None,
            "end_ts": _ts(b) if b else None,
        })
        return r

    def _refuse_protected_windows(self, timerange: str) -> None:
        if self.holdout_ledger is None or not self.holdout_ledger.exists():
            return
        # [a, b) in YYYYMMDD; a missing bound is unbounded on that side.
        # Same-length date strings compare correctly as strings.
        a, _, b = timerange.partition("-")
        for w in holdout.windows(self.holdout_ledger):
            if w["status"] not in ("clean", "accruing"):
                continue
            ws, we = w["range"].split("-")
            if (not b or ws < b) and (not a or a <= we):
                raise HoldoutRefusal(
                    f"timerange {timerange} touches the {w['status']} holdout "
                    f"window {w['range']} — holdout data is not mounted "
                    f"without a signed HG2b (holdout.spend), never through "
                    f"the engine")
