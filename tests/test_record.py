"""The tested register renders from the machine record alone — synthetic
sources first, then a smoke test on the repo's real fixtures/ledger."""

import json
from pathlib import Path

from factory import record

ROOT = Path(__file__).resolve().parents[1]


def test_render_from_synthetic_sources(tmp_path):
    (tmp_path / "kinship.json").write_text(json.dumps({
        "_comment": "x",
        "fam_a": {"description": "all constructions of A on this universe"},
    }))
    (tmp_path / "graveyard.json").write_text(json.dumps({
        "_comment": "x",
        "corpse_a": {"killed_by": "cost_coverage", "coverage": 0.9,
                     "source": "run r1"},
    }))
    ledger = tmp_path / "trials.jsonl"
    ledger.write_text(json.dumps({
        "kind": "factor_screen", "at": "2026-11-06T10:00:00",
        "factor": "CandX", "passed": False, "calibration_valid": True,
        "run_id": "battery-1"}) + "\n" + json.dumps({
        "kind": "llm", "at": "2026-11-06T10:00:00"}) + "\n")

    from factory.orchestrator import manifest as mf
    runs = tmp_path / "runs"
    run_dir = mf.new_run("test hypothesis about A", runs)
    m = mf.load(run_dir)
    m.stages["S0"] = {"status": "killed", "report": "bad card"}
    mf.save(run_dir, m)

    text = record.render(
        record.closed_families(tmp_path / "kinship.json"),
        record.graveyard_corpses(tmp_path / "graveyard.json"),
        record.pipeline_runs(runs),
        record.factor_screens(ledger))

    assert "fam_a" in text and "all constructions of A" in text
    assert "corpse_a" in text and "cost_coverage" in text and "coverage=0.9" in text
    assert "killed at S0" in text and "bad card" in text
    assert "CandX" in text and "| kill |" in text.replace("  ", " ")
    assert "_comment" not in text


def test_render_skips_missing_ledger(tmp_path):
    assert record.factor_screens(tmp_path / "absent.jsonl") == []


def test_real_record_renders():
    """The repo's own record renders and carries the known verdicts."""
    fixtures = ROOT / "fixtures"
    text = record.render(
        record.closed_families(fixtures / "kinship_families.json"),
        record.graveyard_corpses(fixtures / "graveyard.json"),
        record.pipeline_runs(ROOT / "runs"),
        record.factor_screens(ROOT / "ledgers" / "trials.jsonl"))
    for expected in ("lowvol_ranktilt", "FundingCarryTilt",
                     "short_term_reversal", "zero_fee_sanity"):
        assert expected in text
