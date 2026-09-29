"""Human gates are signatures over artifact hashes, not vibes.

`sign` records what was reviewed (path -> sha256). `verify` re-hashes:
if any reviewed artifact changed after signing, the approval is void and
the orchestrator refuses to advance (re-approve after re-review)."""

from __future__ import annotations

import getpass
import hashlib
import json
import time
from pathlib import Path


class ApprovalError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sign(run_dir: Path, gate: str, artifacts: list[Path], notes: str = "") -> Path:
    if not artifacts:
        raise ApprovalError("an approval must name the artifacts that were reviewed")
    rec = {
        "gate": gate,
        "signed_by": getpass.getuser(),
        "signed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": notes,
        "artifact_hashes": {str(p.relative_to(run_dir)): _sha(p) for p in artifacts},
    }
    out = run_dir / "approvals" / f"{gate}.json"
    out.write_text(json.dumps(rec, indent=1))
    return out


def verify(run_dir: Path, gate: str) -> dict:
    """Return the approval record iff present and still valid."""
    f = run_dir / "approvals" / f"{gate}.json"
    if not f.exists():
        raise ApprovalError(f"gate {gate} is not signed")
    rec = json.loads(f.read_text())
    for rel, digest in rec["artifact_hashes"].items():
        p = run_dir / rel
        if not p.exists() or _sha(p) != digest:
            raise ApprovalError(
                f"gate {gate} approval is void: {rel} changed after signing — re-review"
            )
    return rec
