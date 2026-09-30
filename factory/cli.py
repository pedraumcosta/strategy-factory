"""The factory CLI.

    factory new "hypothesis idea..."      create a run
    factory run <run-id> [--to S5]        advance the pipeline
    factory approve <run-id> <gate>       sign a human gate (hg1|hg2|hg2b|hg3)
    factory status [<run-id>]             show runs / one run's stages
    factory ledger                        trial counts + LLM spend
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
LEDGER = ROOT / "ledgers" / "trials.jsonl"

# What each gate signs over: the artifacts the human is certifying they read.
GATE_ARTIFACTS = {
    "hg1": ["prereg.md", "hypothesis.json", "screen_report.md"],
    "hg2": ["dossier.json", "dossier.md"],
    "hg2b": ["dossier.json", "prereg.md"],
    "hg3": ["dossier.json"],
}


def _run_dir(run_id: str) -> Path:
    d = RUNS / run_id
    if not (d / "manifest.json").exists():
        sys.exit(f"no run {run_id!r} under {RUNS}")
    return d


def cmd_new(args) -> None:
    from factory.orchestrator import manifest as mf
    run_dir = mf.new_run(args.idea, RUNS)
    print(run_dir.name)


def cmd_run(args) -> None:
    from factory.engine.lab import LabEngine
    from factory.orchestrator import manifest as mf
    from factory.orchestrator.runner import GateRefusal, Runner
    from factory.stages.pipeline import build_stages
    import time

    run_dir = _run_dir(args.run_id)
    stages = build_stages(LabEngine(), LEDGER, today=time.strftime("%Y-%m-%d"))
    runner = Runner(run_dir, stages)
    try:
        runner.run_to(args.to)
    except GateRefusal as e:
        print(f"blocked: {e}")
    m = mf.load(run_dir)
    for s, st in m.stages.items():
        if st["status"] != "pending":
            print(f"{s}: {st['status']}" + (f" — {st.get('report', '')}" if st.get("report") else ""))


def cmd_approve(args) -> None:
    from factory.orchestrator import approvals
    run_dir = _run_dir(args.run_id)
    art = run_dir / "artifacts"
    files = [art / f for f in GATE_ARTIFACTS[args.gate] if (art / f).exists()]
    if not files:
        sys.exit(f"nothing to sign: none of {GATE_ARTIFACTS[args.gate]} exist yet")
    out = approvals.sign(run_dir, args.gate, files, notes=args.notes or "")
    print(f"signed {args.gate} over {[f.name for f in files]} -> {out}")
    # if a completed stage was waiting on this gate, the signature clears it
    from factory.orchestrator import manifest as mf
    from factory.orchestrator.runner import GateRefusal, acknowledge
    for stage, gate in mf.STAGE_AWAITS.items():
        if gate == args.gate:
            try:
                acknowledge(run_dir, stage)
                print(f"{stage} acknowledged — pipeline can continue")
            except GateRefusal:
                pass


def cmd_status(args) -> None:
    from factory.orchestrator import manifest as mf
    if args.run_id:
        m = mf.load(_run_dir(args.run_id))
        print(m.prompt)
        for s, st in m.stages.items():
            line = f"  {s} {mf.STAGE_NAMES[s]:<12} {st['status']}"
            if st.get("report"):
                line += f" — {st['report']}"
            print(line)
    else:
        for d in sorted(RUNS.iterdir()):
            if (d / "manifest.json").exists():
                m = mf.load(d)
                nxt = "done/killed" if m.is_killed() or m.next_stage() is None else m.next_stage()
                print(f"{d.name}  [next: {nxt}]  {m.prompt[:60]}")


def cmd_replay(args) -> None:
    from factory.orchestrator.runner import replay_from
    reset = replay_from(_run_dir(args.run_id), args.from_stage)
    print(f"reset to pending: {reset}")


def cmd_ledger(args) -> None:
    if not LEDGER.exists():
        print("empty ledger")
        return
    kinds: dict[str, int] = {}
    spend = 0.0
    for line in open(LEDGER):
        r = json.loads(line)
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        if isinstance(r.get("cost_usd"), (int, float)):
            spend += r["cost_usd"]
    for k, n in sorted(kinds.items()):
        print(f"{k}: {n}")
    print(f"total trials: {sum(kinds.values())}")
    print(f"LLM spend on ledger: ${spend:.2f} (budget $100/month)")


def main() -> None:
    p = argparse.ArgumentParser(prog="factory", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new"); s.add_argument("idea"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("run"); s.add_argument("run_id")
    s.add_argument("--to", default="S5", choices=["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"])
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("approve"); s.add_argument("run_id")
    s.add_argument("gate", choices=sorted(GATE_ARTIFACTS))
    s.add_argument("--notes", default="")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("status"); s.add_argument("run_id", nargs="?")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("ledger"); s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("replay"); s.add_argument("run_id")
    s.add_argument("--from", dest="from_stage", required=True,
                   choices=["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"])
    s.set_defaults(fn=cmd_replay)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
