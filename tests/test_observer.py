"""Observer: parity matching and the poller's judgment of a snapshot."""

import json
import sqlite3
import zipfile
from pathlib import Path

from factory.observer import parity, poller


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE trades (pair TEXT, open_date TEXT, "
                "close_date TEXT, close_profit REAL, is_open INTEGER)")
    con.executemany("INSERT INTO trades VALUES (?,?,?,?,?)", rows)
    con.commit(); con.close()


def make_export(path: Path, strategy, trades):
    inner = path.name.replace(".zip", ".json")
    payload = {"strategy": {strategy: {"trades": trades}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(inner, json.dumps(payload))


def bt_trade(pair, o, c, pr):
    return {"pair": pair, "open_date": o, "close_date": c, "profit_ratio": pr}


def test_parity_matches_within_tolerance_and_flags_the_rest(tmp_path):
    db = tmp_path / "dryrun.sqlite"
    make_db(db, [
        ("BTC/USDT", "2026-10-01 00:00:00", "2026-10-05 00:00:00", 0.012, 0),
        ("ETH/USDT", "2026-10-02 00:00:00", None, None, 1),        # still open
        ("SOL/USDT", "2026-10-03 00:00:00", "2026-10-04 00:00:00", -0.01, 0),
    ])
    exp = tmp_path / "backtest-result-x.zip"
    make_export(exp, "Toy", [
        bt_trade("BTC/USDT", "2026-10-02 00:00:00+00:00", "2026-10-05 00:00:00+00:00", 0.010),
        bt_trade("ETH/USDT", "2026-10-02 00:00:00+00:00", "2026-10-06 00:00:00+00:00", 0.02),
        bt_trade("ADA/USDT", "2026-10-01 00:00:00+00:00", "2026-10-02 00:00:00+00:00", 0.001),
    ])
    rep = parity.compare(parity.dryrun_trades(db), parity.backtest_trades(exp, "Toy"))
    assert rep["matched"] == 2                      # BTC (±1d) and ETH
    assert rep["dry_only"] == [{"pair": "SOL/USDT", "open": "2026-10-03"}]
    assert rep["backtest_only"] == [{"pair": "ADA/USDT", "open": "2026-10-01"}]
    assert rep["mean_abs_profit_delta"] == abs(0.012 - 0.010)  # open trade excluded
    text = parity.render(rep, "Toy", "test window")
    assert "dry-run only" in text and "SOL/USDT@2026-10-03" in text


def test_parity_report_with_no_trades_is_still_a_report():
    rep = parity.compare([], [])
    text = parity.render(rep, "Toy", "day 0")
    assert "vacuously" in text


def test_poller_judges_snapshots():
    assert poller.problems({"ok": False, "error": "conn refused"}) \
        == ["freqtrade API unreachable: conn refused"]
    assert poller.problems({"ok": True, "state": "stopped"}) \
        == ["bot state is 'stopped', expected 'running'"]
    assert poller.problems({"ok": True, "state": "running"}) == []
