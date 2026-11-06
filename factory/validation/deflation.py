"""Deflated Sharpe behind one interface: a returns series and the trial
ledger in, the DSR dossier section out.

This module owns what used to be 25 inline lines in S5: the deflation
family selection (which ledger records count as comparable trials), the
annualized→per-period conversion, the small-family variance fallback, and
the ledger fields it depends on — `sharpe`, `timeframe`, `start_ts`,
`end_ts`, written by RecordedEngine for the factory's own runs and by
tools/seed_trials_from_lab.py for the lab history. The factory's own
trials therefore join the family: DSR's N grows with the ledger instead of
freezing at the seeded history.

A failure here raises. S5 treats an uncomputable DSR as a factory defect
(stage resumable), never as a quiet dossier footnote.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from factory.ledgers import trials
from factory.validation import dsr as dsr_mod

# Family membership: same timeframe, window at least this long, finite
# recorded Sharpe. Mixing 1h hyperopt spam (sentinel values to -100) into
# the variance would make SR0 meaningless.
MIN_FAMILY_DAYS = 300
SENTINEL_ABS_SHARPE = 50


def historic_sharpes(ledger: Path, timeframe: str | None = None,
                     min_days: int = MIN_FAMILY_DAYS) -> list[float]:
    """Annualized Sharpes of the comparable-basis family on the ledger."""
    out = []
    if not ledger.exists():
        return out
    with open(ledger) as f:
        for line in f:
            r = json.loads(line)
            v = r.get("sharpe")
            if not isinstance(v, (int, float)) or abs(v) > SENTINEL_ABS_SHARPE:
                continue  # missing or sentinel
            if timeframe is not None and r.get("timeframe") != timeframe:
                continue
            if min_days and not (
                r.get("start_ts") and r.get("end_ts")
                and (r["end_ts"] - r["start_ts"]) >= min_days * 86400
            ):
                continue
            out.append(float(v))
    return out


def deflate(rets: list[float], ledger: Path, timeframe: str,
            periods_per_year: int = 365) -> dict:
    """DSR of a per-period (daily mark-to-market) return series, deflated by
    the comparable-basis family on the trial ledger."""
    ppy = periods_per_year
    sr_ann = dsr_mod.sharpe(rets, ppy)
    skew, kurt = dsr_mod.moments(rets)
    family = historic_sharpes(ledger, timeframe=timeframe)
    n_ledger = trials.count(ledger)
    sr_var = (statistics.variance(family) / ppy
              if len(family) >= 2 else 0.01 / ppy)
    d = dsr_mod.dsr(sr=sr_ann / math.sqrt(ppy), n_obs=len(rets),
                    n_trials=max(len(family), 2), sr_var=sr_var,
                    skew=skew, kurt=kurt)
    d["sr_annualized"] = sr_ann
    d["n_ledger_total"] = n_ledger
    d["note"] = (f"deflated within the comparable-basis family "
                 f"({len(family)} trials, {timeframe}, >={MIN_FAMILY_DAYS}d); "
                 f"the full ledger holds {n_ledger} trials and hyperopt "
                 f"epochs are uncounted, so the true search was wider — "
                 f"treat DSR as an upper bound")
    return d
