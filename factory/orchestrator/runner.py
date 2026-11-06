"""Deterministic pipeline runner. LLM judgment lives inside stages; this
module only sequences, checks gates, and records. A stage is a callable
`fn(run_dir, manifest) -> StageResult`; deterministic gates decide the
transition and LLM output never self-certifies. Stage-record transitions
themselves live on the Manifest (the run module) — the runner never edits
stage dicts by hand."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from factory.orchestrator import manifest as mf
from factory.orchestrator.approvals import ApprovalError, verify


@dataclass
class StageResult:
    status: str  # passed | killed | needs_human
    report: str = ""
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ("passed", "killed", "needs_human"):
            raise ValueError(f"bad stage status {self.status!r}")


class GateRefusal(RuntimeError):
    pass


def _awaits_msg(stage: str) -> str:
    gate = mf.STAGE_AWAITS.get(stage, "?")
    return (f"{stage} finished and awaits human acknowledgement — review its "
            f"artifacts, then: {mf.approve_command('<run>', gate)}")


class Runner:
    def __init__(self, run_dir: Path, stages: dict[str, Callable]):
        self.run_dir = run_dir
        self.stages = stages

    def advance(self) -> str | None:
        """Run the next pending stage. Returns the stage id, or None when
        there is nothing to do (finished or killed)."""
        m = mf.load(self.run_dir)
        s = m.next_stage()
        if s is None:
            return None

        if m.awaiting_human(s):
            # The stage finished its work and a human must act; re-running it
            # would loop forever (this exact spin cost 24 CPU-minutes once).
            raise GateRefusal(_awaits_msg(s))

        gate = mf.HUMAN_GATES_BEFORE.get(s)
        if gate is not None:
            try:
                verify(self.run_dir, gate)
            except ApprovalError as e:
                m.block_on_gate(s, str(e))
                mf.save(self.run_dir, m)
                raise GateRefusal(f"{s} requires signed {gate}: {e}") from e

        fn = self.stages.get(s)
        if fn is None:
            raise GateRefusal(f"no implementation registered for stage {s}")

        m.start(s)
        mf.save(self.run_dir, m)
        try:
            result = fn(self.run_dir, m)
        except Exception:
            m.record_error(s)  # resumable
            mf.save(self.run_dir, m)
            raise
        m.finish(s, result.status, result.report, result.data)
        mf.save(self.run_dir, m)
        return s

    def run_to(self, last_stage: str) -> None:
        """Advance until `last_stage` completes, a kill, or a human gate."""
        prev = None
        while True:
            m = mf.load(self.run_dir)
            nxt = m.next_stage()
            if nxt is None or mf.STAGES.index(nxt) > mf.STAGES.index(last_stage):
                return
            if nxt == prev and m.stages[nxt]["status"] == "needs_human":
                raise GateRefusal(f"{nxt} still needs a human; refusing to spin")
            prev = nxt
            done = self.advance()
            m = mf.load(self.run_dir)
            if m.is_killed():
                return
            if m.awaiting_human(done):
                raise GateRefusal(_awaits_msg(done))


def replay_from(run_dir: Path, stage: str) -> list[str]:
    """Reset `stage` and everything after it to pending (artifacts are kept
    and simply regenerated). For factory defects, not for retrying a judged
    hypothesis: signed approvals survive only because the artifacts they
    hash are untouched — if a replayed stage rewrites one, the approval
    voids itself on the next gate check, which is the design working."""
    m = mf.load(run_dir)
    reset = []
    for s in mf.STAGES[mf.STAGES.index(stage):]:
        if m.stages[s]["status"] != "pending":
            m.reset(s)
            reset.append(s)
    mf.save(run_dir, m)
    return reset


def reject(run_dir: Path, stage: str, reason: str) -> None:
    """The other half of a human gate: kill a completed needs_human stage
    with the reviewer's reasoning on the record. Terminal, like any kill."""
    if not reason.strip():
        raise GateRefusal("a rejection must state its reasons")
    m = mf.load(run_dir)
    if not m.awaiting_human(stage):
        raise GateRefusal(f"stage {stage} is not awaiting a human verdict "
                          f"(status {m.stages[stage]['status']!r})")
    m.kill_by_human(stage, reason)
    mf.save(run_dir, m)


def acknowledge(run_dir: Path, stage: str) -> None:
    """Clear a completed needs_human stage after its gate was signed.
    Verifies the signature (and that the reviewed artifacts are unchanged)
    before marking the stage passed — the human action IS the transition."""
    gate = mf.STAGE_AWAITS.get(stage)
    if gate is None:
        raise GateRefusal(f"stage {stage} does not await a human gate")
    m = mf.load(run_dir)
    if not m.awaiting_human(stage):
        raise GateRefusal(f"stage {stage} is not awaiting acknowledgement "
                          f"(status {m.stages[stage]['status']!r})")
    verify(run_dir, gate)  # raises unless signed and untampered
    m.acknowledge(stage, gate)
    mf.save(run_dir, m)
