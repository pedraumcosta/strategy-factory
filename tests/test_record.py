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
                     "era": "test era", "timeframe": "4h",
                     "why_killed": "costs ate it",
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

    bat = runs / "battery-test-1"
    bat.mkdir()
    (bat / "results.json").write_text(json.dumps({
        "CandY": {"design": "conditional", "passed": False,
                  "calibration_valid": True, "pooled_t": -0.2}}))

    text = record.render(
        record.closed_families(tmp_path / "kinship.json"),
        record.graveyard_corpses(tmp_path / "graveyard.json"),
        record.pipeline_runs(runs),
        record.factor_screens(ledger),
        batteries=record.battery_screens(runs))

    assert "fam_a" in text and "all constructions of A" in text
    assert "corpse_a" in text and "cost_coverage" in text and "coverage=0.9" in text
    # the dossier questions render as labeled lines, kept out of the numbers
    assert "**era**: test era" in text and "**why_killed**: costs ate it" in text
    assert "era=" not in text
    assert "killed at S0" in text and "bad card" in text
    assert "CandX" in text and "| kill |" in text.replace("  ", " ")
    assert "CandY" in text and "pooled_t" in text
    assert "_comment" not in text


def test_every_corpse_answers_the_dossier_questions():
    """The register's contract: each graveyard entry carries all seven
    context answers (data, security, timeframe, construction, performance,
    result, why it failed)."""
    corpses = record.graveyard_corpses(ROOT / "fixtures" / "graveyard.json")
    assert corpses, "graveyard is empty?"
    for c in corpses:
        missing = [f for f in record.CONTEXT_FIELDS if f not in c["context"]]
        assert not missing, f"{c['name']} missing {missing}"


def test_battery_screens_reads_the_regression_arm_shape(tmp_path):
    """A battery with a regression arm writes {candidates, regression,
    regression_identical: bool} — the bool must not crash the reader, the
    regression candidates must not re-list, and the arm renders as one
    IDENTICAL/DIVERGED verdict row."""
    runs = tmp_path / "runs"
    bat = runs / "battery-nested-1"
    bat.mkdir(parents=True)
    (bat / "results.json").write_text(json.dumps({
        "candidates": {"CandZ": {"design": "cross_sectional_ic",
                                 "passed": False, "calibration_valid": True,
                                 "ic_by_horizon": {"1": {"t": 0.4}}}},
        "regression_identical": True,
        "regression": {"OldCand": {"design": "conditional", "passed": False,
                                   "calibration_valid": True,
                                   "pooled_t": -0.2}}}))
    rows = record.battery_screens(runs)
    assert [r["candidate"] for r in rows] == ["CandZ",
                                              "regression arm (OldCand)"]
    text = record.render([], [], [], [], batteries=rows)
    assert "CandZ" in text and "KILL" in text
    assert "regression arm (OldCand)" in text and "IDENTICAL" in text
    assert "OldCand** (conditional" not in text   # not re-listed as a result


def test_render_skips_missing_ledger(tmp_path):
    assert record.factor_screens(tmp_path / "absent.jsonl") == []


def test_real_record_renders():
    """The repo's own record renders and carries the known verdicts."""
    fixtures = ROOT / "fixtures"
    text = record.render(
        record.closed_families(fixtures / "kinship_families.json"),
        record.graveyard_corpses(fixtures / "graveyard.json"),
        record.pipeline_runs(ROOT / "runs"),
        record.factor_screens(ROOT / "ledgers" / "trials.jsonl"),
        batteries=record.battery_screens(ROOT / "runs"))
    for expected in ("lowvol_ranktilt", "FundingCarryTilt",
                     "short_term_reversal", "zero_fee_sanity"):
        assert expected in text
