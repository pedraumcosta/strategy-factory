"""Manifest-first run state: runs/<id>/manifest.json is authoritative.
Any index is derived; a run directory is self-describing and diffs in git."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

STAGES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]
STAGE_NAMES = {
    "S0": "intake", "S1": "research", "S2": "screen", "S3": "preregister",
    "S4": "implement", "S5": "validate", "S6": "deploy", "S7": "observe",
}
# Human gates that must be signed BEFORE the keyed stage may start.
HUMAN_GATES_BEFORE = {"S4": "hg1", "S6": "hg2"}
# Stages that END in needs_human: the gate whose signature acknowledges them.
STAGE_AWAITS = {"S3": "hg1", "S5": "hg2"}
TERMINAL = {"killed"}
STATUSES = {"pending", "running", "passed", "killed", "needs_human"}


@dataclass
class Manifest:
    run_id: str
    prompt: str
    created_at: str
    stages: dict = field(default_factory=lambda: {s: {"status": "pending"} for s in STAGES})

    def next_stage(self) -> str | None:
        for s in STAGES:
            st = self.stages[s]["status"]
            if st in TERMINAL:
                return None
            if st in ("pending", "needs_human"):
                return s
            if st == "running":
                raise RuntimeError(f"{s} marked running — resume or repair first")
        return None

    def is_killed(self) -> bool:
        return any(self.stages[s]["status"] == "killed" for s in STAGES)


def _slug(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())[:4]
    return "-".join(words) or "run"


def new_run(prompt: str, runs_dir: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{_slug(prompt)}"
    run_dir = runs_dir / run_id
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "approvals").mkdir()
    m = Manifest(run_id=run_id, prompt=prompt,
                 created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    save(run_dir, m)
    return run_dir


def load(run_dir: Path) -> Manifest:
    d = json.loads((run_dir / "manifest.json").read_text())
    return Manifest(**d)


def save(run_dir: Path, m: Manifest) -> None:
    (run_dir / "manifest.json").write_text(json.dumps(asdict(m), indent=1))
