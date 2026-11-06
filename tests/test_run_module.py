"""The run module's gate topology and artifact layout: approvals sign over
a DEFINED set, and method-validation reruns enter the pipeline through an
interface instead of forged stage dicts."""

import pytest

from factory.orchestrator import manifest as mf


def test_gate_artifacts_refuse_to_shrink_silently(tmp_path):
    run_dir = mf.new_run("sign me", tmp_path / "runs")
    art = run_dir / "artifacts"
    # hg2 without its dossier: refused, not signed-over-less
    with pytest.raises(mf.GateArtifactError, match="dossier.json"):
        mf.gate_artifact_paths(run_dir, "hg2")
    (art / "dossier.json").write_text("{}")
    (art / "dossier.md").write_text("# dossier")
    # required artifacts present, optional tearsheet absent: sign, but say so
    paths, missing_optional = mf.gate_artifact_paths(run_dir, "hg2")
    assert [p.name for p in paths] == ["dossier.json", "dossier.md"]
    assert missing_optional == ["tearsheet.png"]
    (art / "tearsheet.png").write_bytes(b"png")
    paths, missing_optional = mf.gate_artifact_paths(run_dir, "hg2")
    assert [p.name for p in paths] == ["dossier.json", "dossier.md", "tearsheet.png"]
    assert missing_optional == []


def test_every_gate_signs_over_known_artifact_names():
    for gate, names in mf.GATE_ARTIFACTS.items():
        assert names, f"{gate} signs over nothing"
    # the gates the topology references all exist in GATE_ARTIFACTS
    for gate in list(mf.HUMAN_GATES_BEFORE.values()) + list(mf.STAGE_AWAITS.values()):
        assert gate in mf.GATE_ARTIFACTS


def test_skip_to_marks_prior_stages_passed_on_the_record(tmp_path):
    run_dir = mf.new_run("method validation", tmp_path / "runs")
    m = mf.load(run_dir)
    skipped = m.skip_to("S5", "rerun of a recorded result; not a new hypothesis")
    assert skipped == ["S0", "S1", "S2", "S3", "S4"]
    mf.save(run_dir, m)
    m = mf.load(run_dir)
    assert m.next_stage() == "S5"
    assert all(m.stages[s]["status"] == "passed" for s in skipped)
    assert "not a new hypothesis" in m.stages["S0"]["report"]
