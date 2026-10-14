"""Tear-sheet numbers and the G-passive judgment (Plan §22, corrected by
§23), computed natively from a backtest export zip — S5 no longer needs a
manual run of the lab research image to produce them.

Freqtrade writes two artifacts into every export that make this free:
  *_wallet.feather          per-currency balance per date — total_quote
                            summed per day is a true mark-to-market daily
                            equity curve, stricter than trade-close P&L;
  *_market_change.feather   'rel_mean' = cumulative equal-weight change of
                            the whole pairlist — the G-passive benchmark.

The §23 correction is load-bearing: these books run at low realized
exposure (H3: ~9%, beta ~0), so a raw total-return comparison against a
fully-invested benchmark mostly measures market direction. The binding
comparisons are (a) return vs the universe SCALED to the candidate's own
realized exposure, (b) Sharpe vs the universe — scale-invariant, so the
raw benchmark serves — and (c) the monthly score split by benchmark-up vs
benchmark-down months, so direction-dependence shows. The raw
fully-invested comparison is reported as context only.

Reporting for HG2: verdicts are computed and printed, the kill stays
human — same contract as G-conc in trade_shape().
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from factory.validation import dsr as dsr_mod


@dataclass
class Curves:
    equity: object    # pd.Series: daily mark-to-market equity
    rets: object      # pd.Series: daily strategy returns
    bench: object     # pd.Series | None: daily equal-weight universe returns
    exposure: object  # pd.Series: share of equity in the market, per day


def _daily(idx):
    import pandas as pd

    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def curves_from_export(export_zip: Path, strategy: str) -> Curves:
    import pandas as pd  # heavy import kept local

    with zipfile.ZipFile(export_zip) as z:
        names = z.namelist()

        def one(suffix: str) -> str | None:
            hits = [n for n in names if n.endswith(suffix)]
            return hits[0] if hits else None

        wname = one(f"_{strategy}_wallet.feather") or one("_wallet.feather")
        if wname is None:
            raise ValueError(f"no wallet.feather in {export_zip.name} — "
                             "rerun the backtest to get one")
        w = pd.read_feather(io.BytesIO(z.read(wname)))
        mname = one("_market_change.feather")
        mc = pd.read_feather(io.BytesIO(z.read(mname))) if mname else None
        cname = one("_config.json")
        stake = (json.loads(z.read(cname)).get("stake_currency", "USDT")
                 if cname else "USDT")

    # sum currencies per timestamp, then keep the last reading per day
    tot = w.groupby("date")["total_quote"].sum().sort_index()
    tot.index = _daily(tot.index)
    equity = tot.groupby(level=0).last()

    cash = (w[w["currency"] == stake].groupby("date")["total_quote"]
            .sum().sort_index())
    cash.index = _daily(cash.index)
    cash = cash.groupby(level=0).last().reindex(equity.index).fillna(0.0)
    exposure = (1.0 - cash / equity.where(equity != 0)).clip(lower=0)

    rets = equity.pct_change().dropna()

    bench = None
    if mc is not None:
        b = mc.set_index(_daily(mc["date"]))["rel_mean"].sort_index()
        b = b.groupby(level=0).last()
        # rel_mean is cumulative -> daily returns
        bench = ((1 + b) / (1 + b).shift(1) - 1).dropna()
    return Curves(equity=equity, rets=rets, bench=bench, exposure=exposure)


def monthly(x):
    return (1 + x).resample("ME").prod() - 1


def judge(c: Curves, periods_per_year: int = 365) -> tuple[dict, dict]:
    """-> (tear_sheet, g_passive) dossier sections."""
    rets = c.rets
    tot = float((1 + rets).prod() - 1)
    dd = c.equity / c.equity.cummax() - 1
    sr = dsr_mod.sharpe(rets.tolist(), periods_per_year)
    m = monthly(rets)

    tear: dict = {
        "mtm_total_return": tot,
        "mtm_max_drawdown": float(dd.min()),
        "sharpe_annualized": sr,
        "months": len(m),
        "positive_months": int((m > 0).sum()),
    }
    if len(m) and tot > 0:
        # §17's G5 metric on the mark-to-market basis (trade_shape reports
        # the trade-close basis; both belong in the dossier)
        tear["best_month"] = m.idxmax().strftime("%Y-%m")
        tear["best_month_share_mtm"] = round(float(m.max() / tot), 3)

    if c.bench is None:
        tear["monthly"] = [{"month": d.strftime("%Y-%m"), "strategy": float(v)}
                           for d, v in m.items()]
        return tear, {"error": "no market_change.feather in the export — "
                               "G-passive benchmark unavailable"}

    bench = c.bench.reindex(rets.index).fillna(0.0)
    exp = float(c.exposure.reindex(rets.index).mean())
    btot = float((1 + bench).prod() - 1)
    # the like-for-like benchmark: the universe held at the candidate's own
    # realized exposure, the rest in cash
    scaled = float((1 + bench * exp).prod() - 1)
    sr_b = dsr_mod.sharpe(bench.tolist(), periods_per_year)

    mb = monthly(bench)
    beaten = m > mb
    up = mb > 0
    tear["monthly"] = [{"month": d.strftime("%Y-%m"), "strategy": float(v),
                        "universe": float(mb.loc[d])} for d, v in m.items()]

    g_passive = {
        "exposure_mean": round(exp, 4),
        "strategy_total": tot,
        "universe_total": btot,
        "universe_scaled_total": scaled,
        "excess_pp_vs_scaled": round((tot - scaled) * 100, 2),
        "excess_pp_raw": round((tot - btot) * 100, 2),
        "sharpe_strategy": round(sr, 3),
        "sharpe_universe": round(sr_b, 3),
        "months_beaten": f"{int(beaten.sum())}/{len(m)}",
        "up_months_beaten": f"{int((beaten & up).sum())}/{int(up.sum())}",
        "down_months_beaten": f"{int((beaten & ~up).sum())}/{int((~up).sum())}",
        "pass_sharpe": bool(sr > sr_b),
        "pass_scaled_return": bool(tot > scaled),
        "pass_raw_context_only": bool(tot > btot),
        "note": ("§23 form: the Sharpe comparison is load-bearing — at low "
                 "exposure the scaled-return margin is weak; the raw "
                 "fully-invested comparison is context, never a verdict"),
    }
    return tear, g_passive


def render_png(c: Curves, strategy: str, out: Path) -> bool:
    """The three load-bearing pictures: equity vs benchmark, underwater,
    monthly bars. Optional — returns False when matplotlib is absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    m = monthly(c.rets)
    dd = c.equity / c.equity.cummax() - 1
    fig, ax = plt.subplots(3, 1, figsize=(11, 12),
                           gridspec_kw={"height_ratios": [2, 1.4, 1.4]})
    eq = c.equity / c.equity.iloc[0]
    ax[0].plot(eq.index, (eq - 1) * 100, lw=1.8,
               label=f"{strategy} (mark-to-market)")
    if c.bench is not None:
        bc = (1 + c.bench).cumprod()
        ax[0].plot(bc.index, (bc - 1) * 100, lw=1.4, ls="--",
                   label="equal-weight universe (G-passive benchmark)")
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_title(strategy, fontsize=11)
    ax[0].set_ylabel("cumulative return %")
    ax[0].legend(fontsize=8)
    ax[0].grid(alpha=0.25)

    ax[1].fill_between(dd.index, dd.values * 100, 0, color="firebrick",
                       alpha=0.35)
    ax[1].set_title("underwater — depth and duration of every drawdown",
                    fontsize=10)
    ax[1].set_ylabel("drawdown %")
    ax[1].grid(alpha=0.25)

    cols = ["seagreen" if v > 0 else "firebrick" for v in m.values]
    ax[2].bar([d.strftime("%Y-%m") for d in m.index], m.values * 100,
              color=cols, alpha=0.85)
    if c.bench is not None:
        mb = monthly(c.bench.reindex(c.rets.index).fillna(0.0))
        k = min(len(m), len(mb))
        ax[2].plot(range(k), mb.values[:k] * 100, "k.--", lw=1, ms=5,
                   label="equal-weight universe")
        ax[2].legend(fontsize=8)
    ax[2].axhline(0, color="k", lw=0.6)
    ax[2].set_title("monthly returns — return concentration is visible "
                    "here or nowhere", fontsize=10)
    ax[2].set_ylabel("%")
    ax[2].tick_params(axis="x", rotation=60, labelsize=8)
    ax[2].grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return True
