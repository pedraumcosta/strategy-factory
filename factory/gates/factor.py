"""Judge a factor-screen CSV (lab/wf/factor_screen.py output).

Plan §22: a ranking factor earns a fold set only if some horizon shows
significantly positive pooled IC. The screen always runs beside an ORACLE
(look-ahead) arm and a NOISE arm so the numbers have a scale; the judge is
applied per arm. The H1/H3 factor (ret40/std40) came out negative at every
horizon (pooled t to −6.1) — the screen would have saved the 2026 holdout.
Concentration is NOT screenable (Plan §22); this gate cannot promise the
tear sheet won't kill.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

HORIZONS = (1, 5, 21)


@dataclass(frozen=True)
class FactorVerdict:
    factor: str
    passed: bool
    reason: str
    ic_by_horizon: dict  # horizon -> {"mean": pooled IC, "t": pooled t}


def _pooled(rows: list[dict], h: int) -> tuple[float, float]:
    """Pool per-fold monthly IC series: weight fold means by month count,
    combine variances, recompute t on the pooled sample."""
    means = [float(r[f"ic_mean_{h}"]) for r in rows]
    sds = [float(r[f"ic_std_{h}"]) for r in rows]
    ns = [int(float(r[f"ic_nmonths_{h}"])) for r in rows]
    n = sum(ns)
    mean = sum(m * k for m, k in zip(means, ns)) / n
    # pooled second moment -> variance
    m2 = sum((s * s + m * m) * k for s, m, k in zip(sds, means, ns)) / n
    var = max(m2 - mean * mean, 1e-18)
    t = mean / math.sqrt(var / n)
    return mean, t


def judge(rows: list[dict], factor: str, t_min: float = 2.0) -> FactorVerdict:
    mine = [r for r in rows if r["factor"] == factor]
    if not mine:
        raise ValueError(f"no rows for factor {factor!r}")
    ic = {}
    for h in HORIZONS:
        mean, t = _pooled(mine, h)
        ic[h] = {"mean": mean, "t": t}
    best_h = max(ic, key=lambda h: ic[h]["t"])
    ok = ic[best_h]["mean"] > 0 and ic[best_h]["t"] >= t_min
    detail = ", ".join(f"h{h}: IC {v['mean']:+.4f} (t {v['t']:+.1f})" for h, v in ic.items())
    return FactorVerdict(
        factor,
        ok,
        f"best horizon {best_h}d needs IC>0 with t≥{t_min}; {detail}",
        ic,
    )


def judge_csv(path: Path, factor: str, t_min: float = 2.0) -> FactorVerdict:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return judge(rows, factor, t_min)
