"""The factor-screen generator — Plan §20.7 step 1, run natively by the
factory. M2 wired the judge (factory/gates/factor.py); this is the half
that generates the judge's evidence for an ARBITRARY factor, so S2 no
longer stamps "a measured screen is REQUIRED" and waits for a human to
hand-edit the lab script.

It replicates lab/wf/factor_screen.py in plain pandas — no alphalens, so
no research image and no docker: the daily cross-sectional Spearman IC
(rank Pearson, pairwise-complete, ties averaged — scipy.spearmanr's
definition) per horizon and window, plus the report columns (quintile
profile on demeaned forward returns, top-quintile turnover, top-quintile
monthly concentration — the H3 detector). Same CSV schema, so the same
judge runs unchanged.

The calibration contract is structural: every run carries a NOISE arm
(seeded random — the floor) and an ORACLE arm (realized forward 21d
return, deliberate look-ahead — the ceiling, and unwritable in the DSL).
If ORACLE fails the judge or NOISE passes it, the screen RUN is invalid,
whatever the candidate did.

Protocol: the registered walk-forward IN-SAMPLE halves only
(lab/user_data/notebooks/walkforward.json), hard stop 2025-12-31 —
2026 onward is holdout and is never read here.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from factory.gates import factor as factor_judge

ROOT = Path(__file__).resolve().parents[2]
WALKFORWARD = ROOT / "lab" / "user_data" / "notebooks" / "walkforward.json"
HARD_STOP = "2025-12-31"   # nothing after this is ever read; 2026+ is holdout
PERIODS = (1, 5, 21)
QUANTILES = 5
EXCHANGE = "binance"
MIN_OBS = 200              # same floor as the lab screen
ORACLE_HORIZON = 21


@dataclass
class FactorSpec:
    name: str
    expr: str
    universe: list[str] = field(default_factory=list)  # "BTC/USDT" or "BTC"
    timeframe: str = "1d"
    seed: int = 20260929


def registered_folds() -> list[tuple[str, str, str]]:
    """(fold id, start, end) from the registered walk-forward IS halves."""
    wf = json.loads(WALKFORWARD.read_text())
    out = []
    for f in wf["folds"]:
        s, e = f["is"].split("-")
        out.append((str(f["fold"]),
                    f"{s[:4]}-{s[4:6]}-{s[6:]}", f"{e[:4]}-{e[4:6]}-{e[6:]}"))
    return out


def load_panels(data_dir: Path, universe: list[str],
                timeframe: str = "1d") -> dict:
    """{close, volume} wide panels from <data_dir>/<EXCHANGE>/SYM_USDT-<tf>.feather,
    tz-naive daily index, capped at HARD_STOP."""
    import pandas as pd

    closes, vols, missing = {}, {}, []
    for pair in universe:
        sym = pair.split("/")[0].upper()
        f = data_dir / EXCHANGE / f"{sym}_USDT-{timeframe}.feather"
        if not f.exists():
            missing.append(sym)
            continue
        df = pd.read_feather(f)
        idx = pd.DatetimeIndex(pd.to_datetime(df["date"], utc=True)).tz_localize(None)
        closes[sym] = pd.Series(df["close"].astype(float).values, index=idx)
        vols[sym] = pd.Series(df["volume"].astype(float).values, index=idx)
    if missing:
        raise FileNotFoundError(
            f"no {timeframe} data for {missing} under {data_dir / EXCHANGE}")
    close = pd.DataFrame(closes).sort_index().loc[:HARD_STOP]
    volume = pd.DataFrame(vols).sort_index().loc[:HARD_STOP]
    return {"close": close, "volume": volume}


def _rowwise_pearson(a, b):
    am = a.sub(a.mean(axis=1), axis=0)
    bm = b.sub(b.mean(axis=1), axis=0)
    num = (am * bm).sum(axis=1)
    den = (am.pow(2).sum(axis=1) * bm.pow(2).sum(axis=1)) ** 0.5
    return num / den.where(den != 0)


def daily_ic(factor_wide, fwd):
    """Per-date cross-sectional Spearman IC: Pearson of average ranks over
    the jointly non-NaN assets; dates with <3 pairs are NaN."""
    valid = factor_wide.notna() & fwd.notna()
    f = factor_wide.where(valid).rank(axis=1)
    r = fwd.where(valid).rank(axis=1)
    ic = _rowwise_pearson(f, r)
    return ic.where(valid.sum(axis=1) >= 3)


def screen_window(factor_wide, fwd_by_p: dict, start: str, end: str) -> dict | None:
    """One (factor, window) row in the lab screen's schema, or None when the
    window holds too few observations."""
    f = factor_wide.loc[start:end]
    fwd21 = fwd_by_p[ORACLE_HORIZON].loc[start:end]
    valid = f.notna() & fwd21.notna()
    n_obs = int(valid.sum().sum())
    if n_obs < MIN_OBS:
        return None
    out: dict = {"n_obs": n_obs}

    for p in PERIODS:
        s = daily_ic(f, fwd_by_p[p].loc[start:end]).dropna()
        if len(s) < 2:
            return None
        out[f"ic_mean_{p}"] = s.mean()
        out[f"ic_std_{p}"] = s.std()
        out[f"ic_t_{p}"] = s.mean() / (s.std() / math.sqrt(len(s))) if s.std() > 0 else float("nan")
        m = s.resample("ME").mean()
        out[f"ic_posmonths_{p}"] = float((m > 0).mean() * 100)
        out[f"ic_nmonths_{p}"] = len(m)

    # quintile profile on the 21d horizon, demeaned per date (universe-relative)
    import pandas as pd

    fv = f.where(valid)

    def _qcut(row):
        if row.notna().sum() < QUANTILES:
            return pd.Series(float("nan"), index=row.index)
        return pd.qcut(row, QUANTILES, labels=False, duplicates="drop")

    q = fv.rank(axis=1, method="first").apply(_qcut, axis=1) + 1
    dm = fwd21.sub(fwd21.mean(axis=1), axis=0)
    stacked = pd.DataFrame({"q": q.stack(), "r": dm.stack()}).dropna()
    qmean = stacked.groupby("q")["r"].mean()
    if len(qmean) == QUANTILES:
        out["q_top"] = qmean.iloc[-1] * 100
        out["q_bot"] = qmean.iloc[0] * 100
        out["q_spread"] = (qmean.iloc[-1] - qmean.iloc[0]) * 100
        steps = qmean.diff().dropna()
        out["q_monotone_steps"] = int((steps > 0).sum())
    else:
        out["q_top"] = out["q_bot"] = out["q_spread"] = float("nan")
        out["q_monotone_steps"] = 0

    # top-quintile turnover: share of names new vs the previous date
    top = q.eq(QUANTILES)
    prev = top.shift(1).fillna(False).astype(bool)
    new = (top & ~prev).sum(axis=1)
    size = top.sum(axis=1)
    rate = (new / size.where(size > 0)).iloc[1:].dropna()
    out["turnover_top"] = float(rate.mean()) if len(rate) else float("nan")

    # CONCENTRATION, the H3 detector: top-quintile mean 21d demeaned return
    # by date -> monthly; best month as a share of all positive months' sum
    top_r = dm.where(top).mean(axis=1)
    mon = top_r.resample("ME").mean().dropna()
    pos = mon[mon > 0].sum()
    out["conc_best_month"] = float(mon.max() / pos * 100) if pos > 0 else float("nan")
    out["conc_posmonths"] = float((mon > 0).mean() * 100) if len(mon) else float("nan")
    out["conc_nmonths"] = len(mon)
    return out


def build_arms(spec: FactorSpec, panels: dict) -> dict:
    """candidate + the two calibration arms. ORACLE is built HERE, by the
    harness — the DSL cannot express look-ahead, which is the point."""
    import numpy as np
    import pandas as pd

    from factory.screens import dsl

    close = panels["close"]
    rng = np.random.default_rng(spec.seed)
    noise = pd.DataFrame(rng.standard_normal(close.shape),
                         index=close.index, columns=close.columns)
    oracle = close.shift(-ORACLE_HORIZON) / close - 1.0
    return {spec.name: dsl.evaluate(spec.expr, panels),
            "NOISE": noise, "ORACLE": oracle}


def run_screen(spec: FactorSpec, data_dir: Path, out_dir: Path,
               folds: list[tuple[str, str, str]] | None = None) -> dict:
    """Run the full calibrated screen; write factor_screen.csv in the
    judge's schema; judge all three arms. Returns
    {valid, verdicts: {arm: FactorVerdict}, csv, report}."""
    folds = folds or registered_folds()
    panels = load_panels(data_dir, spec.universe, spec.timeframe)
    arms = build_arms(spec, panels)
    fwd_by_p = {p: panels["close"].shift(-p) / panels["close"] - 1.0
                for p in PERIODS}

    rows = []
    for name, fw in arms.items():
        for fid, s, e in folds:
            r = screen_window(fw, fwd_by_p, s, e)
            if r:
                rows.append({**r, "factor": name, "fold": fid})
        r = screen_window(fw, fwd_by_p, folds[0][1], folds[-1][2])
        if r:
            rows.append({**r, "factor": name, "fold": "pooled"})

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "factor_screen.csv"
    cols = list(rows[0].keys()) if rows else ["factor", "fold"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    verdicts = {name: factor_judge.judge(
        [{k: str(v) for k, v in r.items()} for r in rows], name)
        for name in arms}
    oracle_ok = verdicts["ORACLE"].passed
    noise_ok = not verdicts["NOISE"].passed
    valid = oracle_ok and noise_ok
    report = _render(spec, verdicts, valid, len(rows))
    return {"valid": valid, "verdicts": verdicts, "csv": csv_path,
            "report": report}


def _render(spec: FactorSpec, verdicts: dict, valid: bool, n_rows: int) -> str:
    lines = ["", f"**Measured factor screen** — `{spec.expr}` over "
                 f"{len(spec.universe)} pairs, {spec.timeframe}, the "
                 f"registered IS folds (hard stop {HARD_STOP}); "
                 f"{n_rows} window rows."]
    for name in (spec.name, "ORACLE", "NOISE"):
        v = verdicts[name]
        want = ("must pass (ceiling)" if name == "ORACLE"
                else "must fail (floor)" if name == "NOISE" else "the candidate")
        lines.append(f"- {'PASS' if v.passed else 'FAIL'} `{name}` ({want}) — {v.reason}")
    lines.append("- calibration " +
                 ("**valid**: ORACLE passed, NOISE failed." if valid else
                  "**INVALID**: the screen run itself is broken — "
                  "no candidate verdict can be read from it."))
    lines.append("- Concentration is NOT screenable (Plan §22): this screen "
                 "passing promises nothing about the tear sheet at S5.")
    return "\n".join(lines)
