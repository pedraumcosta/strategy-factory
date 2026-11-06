"""The run module. Manifest-first state (runs/<id>/manifest.json is
authoritative; any index is derived; a run directory is self-describing and
diffs in git) — and the one home for the stage sequence, the gate topology
(which gate guards which stage, and what each gate signs over), the
artifact layout, and every stage-record transition. The runner sequences;
the CLI relays; neither hand-edits stage dicts or invents artifact paths.
"""

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

# --- artifact layout ---------------------------------------------------------

CARD_JSON = "hypothesis.json"
CARD_MD = "hypothesis.md"
RESEARCH_MD = "research.md"
SCREEN_REPORT_MD = "screen_report.md"
PREREG_MD = "prereg.md"
DOSSIER_JSON = "dossier.json"
DOSSIER_MD = "dossier.md"
TEARSHEET_PNG = "tearsheet.png"

# What each gate signs over: the artifacts the human is certifying they read.
# hg3 guards S6 deploy (DESIGN §2); S6/S7 have no stage implementation yet,
# so the entry is topology waiting for its stage, not a dead key.
GATE_ARTIFACTS = {
    "hg1": [PREREG_MD, CARD_JSON, SCREEN_REPORT_MD],
    "hg2": [DOSSIER_JSON, DOSSIER_MD, TEARSHEET_PNG],
    "hg2b": [DOSSIER_JSON, PREREG_MD],
    "hg3": [DOSSIER_JSON],
}
# Artifacts a gate may legitimately lack (tearsheet needs matplotlib).
# A missing REQUIRED artifact refuses the signature instead of silently
# shrinking what the gate signs over.
OPTIONAL_GATE_ARTIFACTS = {TEARSHEET_PNG}


class GateArtifactError(RuntimeError):
    pass


def artifacts_dir(run_dir: Path) -> Path:
    a = run_dir / "artifacts"
    a.mkdir(exist_ok=True)
    return a


def gate_artifact_paths(run_dir: Path, gate: str) -> tuple[list[Path], list[str]]:
    """(paths the gate signs over, names of optional artifacts that are
    missing). Raises GateArtifactError when a required artifact is absent —
    an approval must never silently sign over less than the gate defines."""
    art = run_dir / "artifacts"
    paths, missing_optional = [], []
    for name in GATE_ARTIFACTS[gate]:
        p = art / name
        if p.exists():
            paths.append(p)
        elif name in OPTIONAL_GATE_ARTIFACTS:
            missing_optional.append(name)
        else:
            raise GateArtifactError(
                f"cannot sign {gate}: required artifact {name} is missing "
                f"under {art}")
    return paths, missing_optional


def approve_command(run_id: str, gate: str) -> str:
    """The one spelling of the CLI approval invocation."""
    return f"factory approve {run_id} {gate}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


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

    # --- stage-record transitions (the only writers of stage dicts) --------

    def start(self, stage: str) -> None:
        self.stages[stage] = {"status": "running", "started_at": _now()}

    def finish(self, stage: str, status: str, report: str, data: dict) -> None:
        self.stages[stage].update(status=status, report=report, data=data,
                                  finished_at=_now())
        if status == "needs_human":
            self.stages[stage]["completed"] = True  # work done; human must act
        self.stages[stage].pop("blocked_on", None)

    def record_error(self, stage: str) -> None:
        """A crashed stage goes back to pending: resumable, on the record."""
        self.stages[stage]["status"] = "pending"
        self.stages[stage]["error_at"] = _now()

    def block_on_gate(self, stage: str, why: str) -> None:
        self.stages[stage]["status"] = "needs_human"
        self.stages[stage]["blocked_on"] = why

    def awaiting_human(self, stage: str) -> bool:
        """The stage finished its work and a human must act on its gate."""
        st = self.stages[stage]
        return st["status"] == "needs_human" and bool(st.get("completed"))

    def acknowledge(self, stage: str, gate: str) -> None:
        self.stages[stage]["status"] = "passed"
        self.stages[stage]["acknowledged_by"] = gate
        self.stages[stage]["acknowledged_at"] = _now()

    def kill_by_human(self, stage: str, reason: str) -> None:
        st = self.stages[stage]
        st["status"] = "killed"
        st["report"] = f"rejected by human: {reason}"
        st["rejected_at"] = _now()

    def reset(self, stage: str) -> None:
        self.stages[stage] = {"status": "pending", "replayed_at": _now()}

    def skip_to(self, stage: str, note: str) -> list[str]:
        """Mark every stage before `stage` passed with `note` as its report —
        the legitimate interface for method-validation reruns that enter the
        pipeline midway (tools/rejudge_h3.py), instead of forging stage
        dicts by hand."""
        skipped = []
        for s in STAGES[:STAGES.index(stage)]:
            if self.stages[s]["status"] == "pending":
                self.stages[s] = {"status": "passed", "report": note,
                                  "skipped_at": _now()}
                skipped.append(s)
        return skipped


def _slug(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())[:4]
    return "-".join(words) or "run"


def new_run(prompt: str, runs_dir: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{_slug(prompt)}"
    run_dir = runs_dir / run_id
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "approvals").mkdir()
    m = Manifest(run_id=run_id, prompt=prompt, created_at=_now())
    save(run_dir, m)
    return run_dir


def load(run_dir: Path) -> Manifest:
    d = json.loads((run_dir / "manifest.json").read_text())
    return Manifest(**d)


def save(run_dir: Path, m: Manifest) -> None:
    (run_dir / "manifest.json").write_text(json.dumps(asdict(m), indent=1))
