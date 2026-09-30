"""Deterministic pipeline runner. LLM judgment lives inside stages; this
module only sequences, checks gates, and records. A stage is a callable
`fn(run_dir, manifest) -> StageResult`; deterministic gates decide the
transition and LLM output never self-certifies."""

from __future__ import annotations

import time
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

        st = m.stages[s]
        if st["status"] == "needs_human" and st.get("completed"):
            # The stage finished its work and a human must act; re-running it
            # would loop forever (this exact spin cost 24 CPU-minutes once).
            gate = mf.STAGE_AWAITS.get(s, "?")
            raise GateRefusal(
                f"{s} finished and awaits human acknowledgement — review its "
                f"artifacts, then: factory approve <run> {gate}"
            )

        gate = mf.HUMAN_GATES_BEFORE.get(s)
        if gate is not None:
            try:
                verify(self.run_dir, gate)
            except ApprovalError as e:
                m.stages[s]["status"] = "needs_human"
                m.stages[s]["blocked_on"] = str(e)
                mf.save(self.run_dir, m)
                raise GateRefusal(f"{s} requires signed {gate}: {e}") from e

        fn = self.stages.get(s)
        if fn is None:
            raise GateRefusal(f"no implementation registered for stage {s}")

        m.stages[s] = {"status": "running", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        mf.save(self.run_dir, m)
        try:
            result = fn(self.run_dir, m)
        except Exception:
            m.stages[s]["status"] = "pending"  # resumable
            m.stages[s]["error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            mf.save(self.run_dir, m)
            raise
        m.stages[s].update(
            status=result.status, report=result.report, data=result.data,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
        if result.status == "needs_human":
            m.stages[s]["completed"] = True  # work done; human must act
        m.stages[s].pop("blocked_on", None)
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
            st = m.stages[done]
            if st["status"] == "needs_human" and st.get("completed"):
                gate = mf.STAGE_AWAITS.get(done, "?")
                raise GateRefusal(
                    f"{done} finished and awaits human acknowledgement — "
                    f"review its artifacts, then: factory approve <run> {gate}"
                )


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
            m.stages[s] = {"status": "pending",
                           "replayed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            reset.append(s)
    mf.save(run_dir, m)
    return reset


def acknowledge(run_dir: Path, stage: str, ) -> None:
    """Clear a completed needs_human stage after its gate was signed.
    Verifies the signature (and that the reviewed artifacts are unchanged)
    before marking the stage passed — the human action IS the transition."""
    gate = mf.STAGE_AWAITS.get(stage)
    if gate is None:
        raise GateRefusal(f"stage {stage} does not await a human gate")
    m = mf.load(run_dir)
    st = m.stages[stage]
    if not (st["status"] == "needs_human" and st.get("completed")):
        raise GateRefusal(f"stage {stage} is not awaiting acknowledgement "
                          f"(status {st['status']!r})")
    verify(run_dir, gate)  # raises unless signed and untampered
    st["status"] = "passed"
    st["acknowledged_by"] = gate
    st["acknowledged_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    mf.save(run_dir, m)
