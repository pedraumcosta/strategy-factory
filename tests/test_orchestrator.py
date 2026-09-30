"""M3 acceptance: a scripted run advances S2→S5 on fixtures, a failed gate
kills and stays killed, an unsigned human gate blocks, a tampered approval
is void, and a holdout cannot be spent without HG2b."""

import json
from pathlib import Path

import pytest

from factory.gates import core
from factory.ledgers import holdout, trials
from factory.orchestrator import approvals, manifest as mf
from factory.orchestrator.runner import GateRefusal, Runner, StageResult


def passed(*_a):
    return StageResult("passed")


def make_run(tmp_path, stages):
    run_dir = mf.new_run("test hypothesis", tmp_path / "runs")
    return run_dir, Runner(run_dir, stages)


def test_screen_kill_terminates_the_run(tmp_path):
    def screen(run_dir, m):
        v = core.noise_floor(per_trade_sd=0.15, edge_gate=0.006, trades_available=90)
        return StageResult("killed" if not v.passed else "passed", v.reason)

    run_dir, r = make_run(tmp_path, {"S0": passed, "S1": passed, "S2": screen})
    r.run_to("S5")
    m = mf.load(run_dir)
    assert m.stages["S2"]["status"] == "killed"
    assert m.stages["S3"]["status"] == "pending"
    assert m.next_stage() is None  # killed is terminal


def test_unsigned_hg1_blocks_s4(tmp_path):
    stages = {s: passed for s in ["S0", "S1", "S2", "S3", "S4", "S5"]}
    run_dir, r = make_run(tmp_path, stages)
    with pytest.raises(GateRefusal, match="hg1"):
        r.run_to("S5")
    assert mf.load(run_dir).stages["S4"]["status"] == "needs_human"


def test_signed_hg1_unblocks_and_run_reaches_s5(tmp_path):
    stages = {s: passed for s in ["S0", "S1", "S2", "S3", "S4", "S5"]}
    run_dir, r = make_run(tmp_path, stages)
    with pytest.raises(GateRefusal):
        r.run_to("S5")
    prereg = run_dir / "artifacts" / "prereg.md"
    prereg.write_text("# pre-registration\ncriteria...")
    approvals.sign(run_dir, "hg1", [prereg], notes="reviewed")
    r.run_to("S5")
    m = mf.load(run_dir)
    assert m.stages["S5"]["status"] == "passed"
    assert m.stages["S6"]["status"] == "pending"  # HG2 still ahead


def test_tampered_artifact_voids_the_approval(tmp_path):
    stages = {s: passed for s in ["S0", "S1", "S2", "S3", "S4"]}
    run_dir, r = make_run(tmp_path, stages)
    r.run_to("S3")  # runs S0-S3; the hg1 check happens on entering S4
    prereg = run_dir / "artifacts" / "prereg.md"
    prereg.write_text("criteria v1")
    approvals.sign(run_dir, "hg1", [prereg])
    prereg.write_text("criteria v2 — sneakily loosened")
    with pytest.raises(GateRefusal, match="changed after signing"):
        r.run_to("S4")


def test_crashed_stage_is_resumable(tmp_path):
    calls = {"n": 0}

    def flaky(run_dir, m):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("docker hiccup")
        return StageResult("passed")

    run_dir, r = make_run(tmp_path, {"S0": flaky, "S1": passed})
    with pytest.raises(RuntimeError, match="hiccup"):
        r.advance()
    assert mf.load(run_dir).stages["S0"]["status"] == "pending"
    r.advance()
    assert mf.load(run_dir).stages["S0"]["status"] == "passed"


def test_holdout_seed_matches_plan_18_2(tmp_path):
    ledger = tmp_path / "holdout.json"
    holdout.init(ledger)
    assert holdout.is_clean(ledger, "20190101-20201231")
    assert not holdout.is_clean(ledger, "20260101-20260928")


def test_holdout_refuses_spend_without_hg2b(tmp_path):
    ledger = tmp_path / "holdout.json"
    holdout.init(ledger)
    run_dir = mf.new_run("spendy", tmp_path / "runs")
    with pytest.raises(approvals.ApprovalError, match="not signed"):
        holdout.spend(ledger, "20190101-20201231", run_dir)
    assert holdout.is_clean(ledger, "20190101-20201231")  # untouched


def test_holdout_spend_with_hg2b_is_permanent(tmp_path):
    ledger = tmp_path / "holdout.json"
    holdout.init(ledger)
    run_dir = mf.new_run("spendy", tmp_path / "runs")
    dossier = run_dir / "artifacts" / "dossier.md"
    dossier.write_text("validation dossier")
    approvals.sign(run_dir, "hg2b", [dossier], notes="spend approved")
    holdout.spend(ledger, "20190101-20201231", run_dir)
    assert not holdout.is_clean(ledger, "20190101-20201231")
    with pytest.raises(holdout.HoldoutError, match="not clean"):
        holdout.spend(ledger, "20190101-20201231", run_dir)


def test_unknown_window_is_refused(tmp_path):
    ledger = tmp_path / "holdout.json"
    holdout.init(ledger)
    with pytest.raises(holdout.HoldoutError, match="unknown window"):
        holdout.is_clean(ledger, "20270101-20271231")


def test_trial_ledger_only_goes_up(tmp_path):
    ledger = tmp_path / "trials.jsonl"
    trials.append(ledger, "backtest", "run-a", {"strategy": "X"})
    trials.append(ledger, "screen", "run-a", {"gate": "noise_floor"})
    trials.append(ledger, "backtest", "run-b", {"strategy": "Y"})
    assert trials.count(ledger) == 3
    assert trials.count(ledger, run_id="run-a") == 2
    assert trials.count(ledger, kind="backtest") == 2


def test_replay_resets_killed_stage_and_after(tmp_path):
    from factory.orchestrator.runner import replay_from

    def dies(run_dir, m):
        return StageResult("killed", "factory defect, not a verdict")

    run_dir, r = make_run(tmp_path, {"S0": passed, "S1": dies})
    r.run_to("S1")
    assert mf.load(run_dir).stages["S1"]["status"] == "killed"
    reset = replay_from(run_dir, "S1")
    assert reset == ["S1"]
    m = mf.load(run_dir)
    assert m.stages["S0"]["status"] == "passed"      # untouched
    assert m.stages["S1"]["status"] == "pending"     # runnable again
    assert m.next_stage() == "S1"


def test_reject_kills_an_awaiting_stage_with_reasons(tmp_path):
    from factory.orchestrator.runner import reject

    def waits(run_dir, m):
        return StageResult("needs_human", "review me")

    run_dir, r = make_run(tmp_path, {"S0": passed, "S1": passed, "S2": passed,
                                     "S3": waits})
    with pytest.raises(GateRefusal):
        r.run_to("S3")
    with pytest.raises(GateRefusal, match="must state its reasons"):
        reject(run_dir, "S3", "  ")
    reject(run_dir, "S3", "fails its own protocol tripwire")
    m = mf.load(run_dir)
    assert m.stages["S3"]["status"] == "killed"
    assert "tripwire" in m.stages["S3"]["report"]
    assert m.next_stage() is None  # terminal
    with pytest.raises(GateRefusal, match="not awaiting"):
        reject(run_dir, "S3", "twice")
