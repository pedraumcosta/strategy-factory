"""G-passive (§22/§23) + tear sheet from a synthetic export zip.

The fixture is built to make the §23 verdicts checkable by hand:
- 91 days (Jan–Mar 2024), equity compounding ~+0.2%/day with a small
  alternating wiggle (so variance is nonzero);
- the book holds 90% stake currency → realized exposure 0.10;
- the universe does +1%/day in January, −1%/day in February, +0.1%/day
  in March, written as a CUMULATIVE rel_mean like freqtrade does.
"""

import io
import json
import zipfile

import pytest

from factory.validation import gpassive


def make_export(tmp_path, strategy="X", with_bench=True):
    import pandas as pd

    days = 91
    dates = pd.date_range("2024-01-01", periods=days, freq="D", tz="UTC")
    equity, eq = [], 1000.0
    for i in range(days):
        equity.append(eq)
        eq *= 1.002 + (0.001 if i % 2 else -0.001)
    rows = []
    for d, e in zip(dates, equity):
        rows.append({"date": d, "currency": "USDT", "total_quote": e * 0.9})
        rows.append({"date": d, "currency": "BTC", "total_quote": e * 0.1})
    wallet = pd.DataFrame(rows)

    cum, acc = [], 1.0
    for d in dates:
        acc *= 1 + (0.01 if d.month == 1 else -0.01 if d.month == 2 else 0.001)
        cum.append(acc - 1)
    mc = pd.DataFrame({"date": dates, "rel_mean": cum})

    zp = tmp_path / "backtest-result-testtag.zip"
    with zipfile.ZipFile(zp, "w") as z:
        frames = [(f"backtest-result-testtag_{strategy}_wallet.feather", wallet)]
        if with_bench:
            frames.append(("backtest-result-testtag_market_change.feather", mc))
        for name, df in frames:
            buf = io.BytesIO()
            df.to_feather(buf)
            z.writestr(name, buf.getvalue())
        z.writestr("backtest-result-testtag_config.json",
                   json.dumps({"stake_currency": "USDT"}))
    return zp


def test_judge_the_section_23_form(tmp_path):
    c = gpassive.curves_from_export(make_export(tmp_path), "X")
    tear, gp = gpassive.judge(c)

    # exposure: 10% of equity is not in the stake currency, every day
    assert gp["exposure_mean"] == pytest.approx(0.10, abs=1e-6)
    # scaling shrinks a positive benchmark toward cash
    assert 0 < gp["universe_scaled_total"] < gp["universe_total"]
    # steady +0.2%/day beats a whipsawing universe on Sharpe
    assert gp["pass_sharpe"] and gp["sharpe_strategy"] > gp["sharpe_universe"]
    assert gp["pass_scaled_return"]
    # direction split: Jan (+36%) is unbeatable, Feb (−25%) and Mar (+3%) are not
    assert gp["up_months_beaten"] == "1/2"
    assert gp["down_months_beaten"] == "1/1"
    assert gp["months_beaten"] == "2/3"

    assert tear["months"] == 3 and tear["positive_months"] == 3
    assert tear["mtm_total_return"] == pytest.approx(
        gp["strategy_total"], abs=1e-12)
    assert tear["mtm_max_drawdown"] <= 0
    assert len(tear["monthly"]) == 3 and "universe" in tear["monthly"][0]


def test_missing_benchmark_degrades_not_crashes(tmp_path):
    c = gpassive.curves_from_export(make_export(tmp_path, with_bench=False), "X")
    assert c.bench is None
    tear, gp = gpassive.judge(c)
    assert "error" in gp
    assert "mtm_total_return" in tear  # tear sheet still computed


def test_missing_wallet_is_a_loud_error(tmp_path):
    zp = tmp_path / "backtest-result-empty.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("backtest-result-empty.json", "{}")
    with pytest.raises(ValueError, match="wallet.feather"):
        gpassive.curves_from_export(zp, "X")


def test_render_png_writes_a_figure_or_declines(tmp_path):
    c = gpassive.curves_from_export(make_export(tmp_path), "X")
    out = tmp_path / "tearsheet.png"
    ok = gpassive.render_png(c, "X", out)
    assert ok == out.exists()  # matplotlib present -> file; absent -> False
