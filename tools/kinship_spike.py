"""The §17 topic 2 spike runner: every backend answers the same labeled
kinship cases; the report is accuracy, Brier, ECE, latency and cost side by
side. Go/no-go was committed in advance (Plan §17 topic 2): Jev earns an
ADVISORY S0 flag only if it matches the recorded verdicts at least as well
as the cheap LLM and its probabilities verify as calibrated here.

  uv run python tools/kinship_spike.py --backends haiku,opus
  uv run python tools/kinship_spike.py --backends jev        # needs TYPESAFE_API_KEY
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ledgers" / "trials.jsonl"

BACKENDS = {
    "opus": ("claude-opus-5-5", "the pinned stage model"),
    "haiku": ("claude-haiku-5-5", "the cheap comparator"),
    "jev": ("jev-1.14.0", "the decision model under test"),
}


def run_backend(name: str, cases: list[dict], families: dict) -> dict:
    from factory import decisions as dec

    results, failures = [], 0
    for case in cases:
        try:
            if name == "jev":
                v = dec.jev_kinship(case["card"], families)
            else:
                v = dec.claude_kinship(case["card"], families,
                                       model=BACKENDS[name][0])
        except (ValueError, KeyError) as e:
            failures += 1
            print(f"    {case['id']}: UNPARSEABLE ({e})")
            continue
        ok = v.choice == case["label"]
        results.append((v, case["label"], case))
        print(f"    {case['id']:>18}: {'ok ' if ok else 'MISS'} "
              f"chose {v.choice} (conf {v.confidence:.2f}, "
              f"{v.latency_s:.1f}s, ${v.cost_usd:.4f})")
    pairs = [(v, label) for v, label, _ in results]
    acc = sum(v.choice == label for v, label in pairs) / len(pairs)
    return {
        "model": results[0][0].model if results else BACKENDS[name][0],
        "n": len(pairs), "unparseable": failures,
        "accuracy": acc,
        "brier": dec.brier(pairs),
        "ece": dec.ece(pairs),
        "mean_latency_s": sum(v.latency_s for v, _ in pairs) / len(pairs),
        "total_cost_usd": sum(v.cost_usd for v, _ in pairs),
        "misses": [{"id": c["id"], "label": label, "chose": v.choice,
                    "confidence": round(v.confidence, 3)}
                   for v, label, c in results if v.choice != label],
    }


def main() -> None:
    from factory.env import load_env
    load_env()
    p = argparse.ArgumentParser()
    p.add_argument("--backends", default="haiku,opus")
    args = p.parse_args()

    from factory.ledgers import trials

    families = {k: v for k, v in
                json.loads((ROOT / "fixtures" / "kinship_families.json")
                           .read_text()).items() if not k.startswith("_")}
    cases = json.loads((ROOT / "fixtures" / "kinship_eval.json")
                       .read_text())["cases"]
    by_kind: dict[str, int] = {}
    for c in cases:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    print(f"# Kinship spike — {len(cases)} labeled cases {by_kind}, "
          f"{len(families)} closed families + novel\n")

    out_dir = ROOT / "runs" / f"spike-kinship-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    summary = {}
    for name in args.backends.split(","):
        print(f"  backend {name} ({BACKENDS[name][0]}):")
        s = run_backend(name.strip(), cases, families)
        summary[name] = s
        kind = "vendor_api" if name == "jev" else "llm"
        trials.append(LEDGER, kind, out_dir.name,
                      {"stage": "spike-kinship", "model": s["model"],
                       "calls": s["n"], "cost_usd": round(s["total_cost_usd"], 4)})
        print(f"  -> acc {s['accuracy']:.0%}  brier {s['brier']:.3f}  "
              f"ece {s['ece']:.3f}  lat {s['mean_latency_s']:.1f}s  "
              f"cost ${s['total_cost_usd']:.3f}\n")

    (out_dir / "results.json").write_text(json.dumps(summary, indent=1))
    lines = ["# Kinship spike results\n",
             "| backend | model | acc | brier | ECE | mean lat | total cost |",
             "|---|---|---|---|---|---|---|"]
    for name, s in summary.items():
        lines.append(f"| {name} | {s['model']} | {s['accuracy']:.0%} | "
                     f"{s['brier']:.3f} | {s['ece']:.3f} | "
                     f"{s['mean_latency_s']:.1f}s | ${s['total_cost_usd']:.3f} |")
    lines.append("\nMisses per backend:")
    for name, s in summary.items():
        for m in s["misses"]:
            lines.append(f"- {name}: {m['id']} -> chose {m['chose']} "
                         f"(true {m['label']}, conf {m['confidence']})")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"report: {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
