"""The tested register — everything this project has tried, rendered from
the machine record. Four sources, none hand-maintained:

  fixtures/graveyard.json         the corpses and their recorded kill numbers
  fixtures/kinship_families.json  the closed idea-space each kill's prereg shut
  runs/*/manifest.json            every pipeline run's stage-by-stage outcome
  ledgers/trials.jsonl            every factor_screen trial ever run

`factory record` renders them as one markdown report. The report is a QUERY:
when it looks wrong, fix the record it reads, never the rendering — a
hand-edited register would drift the way any duplicated fact does.
"""

from __future__ import annotations

import json
from pathlib import Path


def closed_families(kinship_path: Path) -> list[dict]:
    """[{name, description}] — the closed idea-space scopes."""
    data = json.loads(kinship_path.read_text())
    return [{"name": k, "description": v.get("description", "")}
            for k, v in data.items() if not k.startswith("_")]


# the dossier questions every corpse answers (prose, not re-killed by gates)
CONTEXT_FIELDS = ("era", "data", "universe", "timeframe", "construction",
                  "performance", "why_killed")


def graveyard_corpses(graveyard_path: Path) -> list[dict]:
    """[{name, killed_by, context: {...}, numbers: {field: value}}] from the
    fixture — context answers the dossier questions, numbers are what the
    test suite re-kills."""
    data = json.loads(graveyard_path.read_text())
    out = []
    for name, rec in data.items():
        if name.startswith("_"):
            continue
        numbers = {k: v for k, v in rec.items()
                   if k not in ("killed_by", "source") + CONTEXT_FIELDS}
        context = {k: rec[k] for k in CONTEXT_FIELDS if rec.get(k)}
        out.append({"name": name, "killed_by": rec.get("killed_by", "?"),
                    "source": rec.get("source", ""), "context": context,
                    "numbers": numbers})
    return out


def battery_screens(runs_dir: Path) -> list[dict]:
    """[{battery, candidate, design, passed, calibration_valid, stats}] from
    every committed runs/battery-*/results.json, oldest first."""
    out = []
    for d in sorted(runs_dir.glob("battery-*")) if runs_dir.is_dir() else []:
        f = d / "results.json"
        if not f.exists():
            continue
        for name, r in json.loads(f.read_text()).items():
            stats = {k: v for k, v in r.items()
                     if k not in ("design", "passed", "calibration_valid",
                                  "reason")}
            out.append({"battery": d.name, "candidate": name,
                        "design": r.get("design", "?"),
                        "passed": bool(r.get("passed")),
                        "calibration_valid": r.get("calibration_valid"),
                        "stats": stats})
    return out


def pipeline_runs(runs_dir: Path) -> list[dict]:
    """[{run_id, prompt, outcome, stages: [(stage, status, report)]}] for
    every directory under runs/ holding a manifest, oldest first."""
    from factory.orchestrator import manifest as mf

    out = []
    for d in sorted(runs_dir.iterdir()) if runs_dir.is_dir() else []:
        if not (d / "manifest.json").exists():
            continue
        m = mf.load(d)
        stages = [(s, st["status"], st.get("report") or "")
                  for s, st in m.stages.items() if st["status"] != "pending"]
        if m.is_killed():
            dead = next((s for s, st, _ in reversed(stages) if st == "killed"),
                        "?")
            outcome = f"killed at {dead}"
        elif m.next_stage() is None:
            outcome = "complete"
        else:
            outcome = f"open — next {m.next_stage()}"
        card = {}
        card_file = d / "artifacts" / "hypothesis.json"
        if card_file.exists():   # artifacts are local-only (gitignored)
            try:
                c = json.loads(card_file.read_text())
                card = {"name": c.get("name"),
                        "universe": f"{len(c.get('universe', []))} pairs",
                        "timeframe": c.get("timeframe"),
                        "factor": (c.get("factor") or {}).get("expr"),
                        "estimates": c.get("estimates")}
            except (ValueError, OSError):
                card = {}
        out.append({"run_id": d.name, "prompt": m.prompt,
                    "outcome": outcome, "stages": stages, "card": card})
    return out


def factor_screens(ledger_path: Path) -> list[dict]:
    """Every factor_screen trial on the ledger, in ledger order."""
    out = []
    if not ledger_path.exists():
        return out
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") != "factor_screen":
            continue
        out.append({"at": str(r.get("at", ""))[:10],
                    "factor": r.get("factor", "?"),
                    "passed": bool(r.get("passed")),
                    "calibration_valid": r.get("calibration_valid"),
                    "run_id": r.get("run_id", "")})
    return out


def render(families: list[dict], corpses: list[dict],
           runs: list[dict], screens: list[dict],
           batteries: list[dict] | None = None) -> str:
    lines = ["# The tested register", "",
             "Rendered from the machine record (graveyard, kinship scopes, "
             "run manifests, trial ledger). Fix the record, not the report.",
             ""]

    lines += [f"## Closed idea-space families ({len(families)})", ""]
    for f in families:
        lines.append(f"- **{f['name']}** — {f['description']}")
    lines.append("")

    lines += [f"## Graveyard corpses — the full dossiers ({len(corpses)})", ""]
    for c in corpses:
        nums = ", ".join(f"{k}={v}" for k, v in c["numbers"].items())
        lines.append(f"### {c['name']} — killed by `{c['killed_by']}`"
                     + (f" ({nums})" if nums else ""))
        for field in CONTEXT_FIELDS:
            if field in c["context"]:
                lines.append(f"- **{field}**: {c['context'][field]}")
        if c["source"]:
            lines.append(f"- **source**: {c['source']}")
        lines.append("")

    if batteries:
        lines += [f"## Battery screens — deterministic, no LLM "
                  f"({len(batteries)} trials)", "",
                  "All on the 17-pair Binance USDT universe, 1d bars, the "
                  "registered IS folds (hard stop 2025-12-31); funding "
                  "candidates read the 8h perp funding history "
                  "(tools/fetch_funding.py).", ""]
        for b in batteries:
            stats = json.dumps(b["stats"]) if b["stats"] else ""
            calib = ("valid" if b["calibration_valid"]
                     else "INVALID — run self-rejected")
            lines.append(f"- **{b['candidate']}** ({b['design']}, "
                         f"{b['battery']}) — "
                         f"{'PASS' if b['passed'] else 'KILL'}, "
                         f"calibration {calib}"
                         + (f" — {stats}" if stats else ""))
        lines.append("")

    lines += [f"## Pipeline runs ({len(runs)})", ""]
    for r in runs:
        lines.append(f"### {r['run_id']} — {r['outcome']}")
        lines.append(f"> {r['prompt'][:200]}")
        card = r.get("card") or {}
        if card:
            bits = [f"{k}={v}" for k, v in card.items()
                    if v and k != "estimates"]
            if card.get("estimates"):
                bits.append("estimates=" + json.dumps(card["estimates"]))
            lines.append("- card: " + ", ".join(bits))
        for stage, status, report in r["stages"]:
            lines.append(f"- {stage} **{status}**"
                         + (f" — {report}" if report else ""))
        lines.append("")

    lines += [f"## Factor-screen trials on the ledger ({len(screens)})", "",
              "| date | factor | passed | calibration | run |",
              "|---|---|---|---|---|"]
    for s in screens:
        calib = ("valid" if s["calibration_valid"]
                 else "INVALID" if s["calibration_valid"] is False else "—")
        lines.append(f"| {s['at']} | {s['factor']} | "
                     f"{'PASS' if s['passed'] else 'kill'} | {calib} | "
                     f"{s['run_id']} |")
    lines.append("")
    return "\n".join(lines)
