"""M8: the dry-run review assembles honestly from fetched artifacts."""

import json
import sqlite3
from pathlib import Path

from factory.observer import review


def write_snapshots(p: Path, rows):
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_review_reports_uptime_alerts_and_interim_status(tmp_path):
    write_snapshots(tmp_path / "snapshots.jsonl", [
        {"at": "2026-09-30T10:00:00+0000", "ok": False, "error": "booting"},
        {"at": "2026-09-30T10:05:00+0000", "ok": True, "state": "running", "open_trades": 0},
        {"at": "2026-10-02T10:05:00+0000", "ok": True, "state": "running", "open_trades": 3},
    ])
    con = sqlite3.connect(tmp_path / "dryrun.sqlite")
    con.execute("CREATE TABLE trades (pair TEXT, open_date TEXT, "
                "close_date TEXT, close_profit REAL, is_open INTEGER)")
    con.executemany("INSERT INTO trades VALUES (?,?,?,?,?)", [
        ("BTC/USDT", "2026-09-30", "2026-10-01", 0.01, 0),
        ("ETH/USDT", "2026-10-01", None, None, 1),
    ])
    con.commit(); con.close()
    (tmp_path / "parity_report.md").write_text("# Parity report — X\n- ok\n")

    r = review.assemble(tmp_path)
    assert r["observation"]["snapshots"] == 3
    assert r["observation"]["failed"] == 1
    assert r["observation"]["uptime_ratio"] == 2 / 3
    assert r["observation"]["open_trades_max"] == 3
    assert r["trading"] == {"trades": 2, "open": 1, "closed": 1, "wins": 1,
                            "mean_profit_ratio": 0.01}
    assert not r["review_complete"]          # ~2 days observed, not 30
    md = review.render(r)
    assert "Interim review" in md and "days" in md
    assert "Parity report — X" in md
    assert "cannot tell you" in md


def test_review_survives_missing_artifacts(tmp_path):
    r = review.assemble(tmp_path)
    assert "error" in r["observation"] and "error" in r["trading"]
    assert "no parity report" in r["parity_report"]
    review.render(r)  # must not raise


def test_thirty_days_flips_to_judgeable(tmp_path):
    write_snapshots(tmp_path / "snapshots.jsonl", [
        {"at": "2026-09-30T10:00:00+0000", "ok": True, "state": "running", "open_trades": 0},
        {"at": "2026-10-31T10:00:00+0000", "ok": True, "state": "running", "open_trades": 1},
    ])
    r = review.assemble(tmp_path)
    assert r["review_complete"]
    assert "HG3 evidence" in review.render(r)
