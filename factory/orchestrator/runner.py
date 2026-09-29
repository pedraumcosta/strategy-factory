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
        m.stages[s].pop("blocked_on", None)
        mf.save(self.run_dir, m)
        return s

    def run_to(self, last_stage: str) -> None:
        """Advance until `last_stage` completes, a kill, or a human gate."""
        while True:
            m = mf.load(self.run_dir)
            nxt = m.next_stage()
            if nxt is None or mf.STAGES.index(nxt) > mf.STAGES.index(last_stage):
                return
            self.advance()
            if mf.load(self.run_dir).is_killed():
                return
