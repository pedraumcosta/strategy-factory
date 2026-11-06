"""The factory CLI.

    factory new "hypothesis idea..."      create a run
    factory run <run-id> [--to S5]        advance the pipeline
    factory approve <run-id> <gate>       sign a human gate (hg1|hg2|hg2b|hg3)
    factory status [<run-id>]             show runs / one run's stages
    factory ledger                        trial counts + LLM spend

The stage sequence, the gate topology and what each gate signs over live in
factory/orchestrator/manifest.py (the run module); this file only relays.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from factory.orchestrator import manifest as mf

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
LEDGER = ROOT / "ledgers" / "trials.jsonl"
HOLDOUT = ROOT / "ledgers" / "holdout.json"


def _run_dir(run_id: str) -> Path:
    d = RUNS / run_id
    if not (d / "manifest.json").exists():
        sys.exit(f"no run {run_id!r} under {RUNS}")
    return d


def cmd_new(args) -> None:
    run_dir = mf.new_run(args.idea, RUNS)
    print(run_dir.name)


def cmd_run(args) -> None:
    from factory.engine.lab import LabEngine
    from factory.orchestrator.runner import GateRefusal, Runner
    from factory.stages.pipeline import build_stages
    import time

    run_dir = _run_dir(args.run_id)
    stages = build_stages(LabEngine(), LEDGER, today=time.strftime("%Y-%m-%d"),
                          holdout_ledger=HOLDOUT)
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
    try:
        files, missing_optional = mf.gate_artifact_paths(run_dir, args.gate)
    except mf.GateArtifactError as e:
        sys.exit(str(e))
    for name in missing_optional:
        print(f"note: optional artifact {name} is missing — "
              f"{args.gate} signs without it")
    out = approvals.sign(run_dir, args.gate, files, notes=args.notes or "")
    print(f"signed {args.gate} over {[f.name for f in files]} -> {out}")
    # if a completed stage was waiting on this gate, the signature clears it
    from factory.orchestrator.runner import GateRefusal, acknowledge
    for stage, gate in mf.STAGE_AWAITS.items():
        if gate == args.gate:
            try:
                acknowledge(run_dir, stage)
                print(f"{stage} acknowledged — pipeline can continue")
            except GateRefusal:
                pass


def cmd_status(args) -> None:
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


def cmd_reject(args) -> None:
    from factory.orchestrator.runner import reject
    reject(_run_dir(args.run_id), args.stage, args.notes)
    print(f"{args.stage} killed by human verdict — on the record")


def cmd_replay(args) -> None:
    from factory.orchestrator.runner import replay_from
    reset = replay_from(_run_dir(args.run_id), args.from_stage)
    print(f"reset to pending: {reset}")


def cmd_dryrun_review(args) -> None:
    import time
    from factory.ledgers import holdout
    from factory.observer import review

    data_dir = Path(args.data_dir)
    r = review.assemble(data_dir)
    (data_dir / "review.json").write_text(json.dumps(r, indent=1))
    md = review.render(r)
    (data_dir / "review.md").write_text(md)
    # the passage of observed time is also holdout accruing on the ledger
    w = holdout.accrue(HOLDOUT, time.strftime("%Y%m%d"))
    print(md)
    print(f"[holdout] accruing window {w['range']}: {w['days']}d, "
          f"status {w['status']} (matures at {holdout.MATURITY_DAYS}d)")
    print(f"written: {data_dir}/review.md")


def cmd_factor_screen(args) -> None:
    """Ad-hoc measured factor screen (S1 research aid): judge any causal-DSL
    expression against ORACLE/NOISE on the registered IS folds. Every run is
    a trial on the ledger — screens are searches too."""
    from factory.ledgers import trials
    from factory.screens.screen import FactorSpec, run_screen

    universe = (args.universe.split(",") if args.universe else
                ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
                 "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"])
    spec = FactorSpec(name=args.name, expr=args.expr, universe=universe,
                      timeframe=args.timeframe)
    out_dir = Path(args.out) if args.out else ROOT / "runs" / "adhoc-screens" / args.name
    res = run_screen(spec, Path(args.data_dir).expanduser(), out_dir)
    cand = res["verdicts"][args.name]
    trials.append(LEDGER, "factor_screen", "adhoc",
                  {"factor": args.name, "expr": args.expr,
                   "passed": cand.passed,
                   "calibration_valid": res["valid"],
                   "ic": {str(h): v for h, v in cand.ic_by_horizon.items()}})
    print(res["report"])
    print(f"\nCSV: {res['csv']}")


def cmd_scenarios(args) -> None:
    """S1 scenario retrieval (Plan §17 topic 5): the k nearest historical
    analogues of the trailing window, and what followed them. Every query
    is a trial on the ledger — retrieved analogues are a multiple-
    comparisons machine with extra steps (§1.2)."""
    import numpy as np
    from factory import similarity as sim
    from factory.ledgers import holdout, trials
    from factory.screens.screen import load_panels

    horizons = [int(h) for h in args.horizons.split(",")]
    panels = load_panels(Path(args.data_dir).expanduser(), [args.symbol],
                         args.timeframe, hard_stop=None)
    close = panels["close"][args.symbol].dropna()
    x = np.log(close.to_numpy())
    dates = [d.strftime("%Y%m%d") for d in close.index]
    spans = sim.forbidden_spans(holdout.windows(HOLDOUT))
    if sim.overlaps(dates[-args.window], dates[-1], spans):
        sys.exit("the query window itself overlaps a clean/accruing holdout "
                 "range — not readable without HG2b")
    picks = sim.analogues(x, dates, args.window, args.k, horizons, spans)
    rates = sim.base_rates(picks, horizons)

    print(f"# {args.symbol} — {args.k} nearest analogues of the last "
          f"{args.window} bars ({args.timeframe}, as of {dates[-1]})\n")
    for p in picks:
        fwd = "  ".join(f"{h}d {p['fwd_log_return'][h]:+.2%}"
                        if np.isfinite(p["fwd_log_return"][h])
                        else f"{h}d (blocked/na)" for h in horizons)
        print(f"  {p['start']}-{p['end']}  dist {p['distance']:5.2f}   {fwd}")
    print("\nbase rates (forward log returns of the analogues):")
    for h, r in rates.items():
        if r["n"]:
            print(f"  {h:>3}d: n={r['n']}  mean {r['mean']:+.2%}  "
                  f"median {r['median']:+.2%}  up {r['frac_up']:.0%}")
        else:
            print(f"  {h:>3}d: no readable forward windows")
    print("\nBase rates are context for S1, not a signal: analogue counts "
          "this small resolve nothing (Plan §21).")
    trials.append(LEDGER, "scenario_query", "adhoc",
                  {"symbol": args.symbol, "timeframe": args.timeframe,
                   "window": args.window, "k": args.k, "asof": dates[-1],
                   "horizons": horizons,
                   "analogues": [{"start": p["start"], "end": p["end"],
                                  "distance": round(p["distance"], 3)}
                                 for p in picks]})


def cmd_novelty(args) -> None:
    """S7 novelty calibration (Plan §17 topic 5): how unprecedented is each
    pair's latest window, on the distribution of that same statistic over
    its own history. A calibration report, deliberately NOT a pager — the
    §17.2 rule: thresholds are chosen by a human from this report before
    anything pages on them."""
    import numpy as np
    from factory import similarity as sim
    from factory.ledgers import holdout
    from factory.screens.screen import load_panels

    symbols = (args.universe.split(",") if args.universe else
               ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
                "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"])
    panels = load_panels(Path(args.data_dir).expanduser(), symbols,
                         args.timeframe, hard_stop=None)
    spans = sim.forbidden_spans(holdout.windows(HOLDOUT))
    m = args.window
    print(f"# Novelty — nearest-neighbour distance of the last {m}-bar "
          f"window ({args.timeframe}); clean/accruing holdout windows "
          f"excluded from memory and evaluation\n")
    print(f"{'pair':>6} {'latest':>7} {'pctile':>7} {'p99':>6}  "
          f"{'days>p99 (history)':>18}")
    for sym in symbols:
        close = panels["close"][sym].dropna()
        x = np.log(close.to_numpy())
        dates = [d.strftime("%Y%m%d") for d in close.index]
        starts = range(len(x) - m + 1)
        allowed = np.array([not sim.overlaps(dates[s], dates[s + m - 1], spans)
                            for s in starts])
        nov = sim.novelty_series(x, m, allowed)
        finite = nov[np.isfinite(nov)]
        if not finite.size or not np.isfinite(nov[-1]):
            print(f"{sym:>6}  (latest window not evaluable)")
            continue
        last = nov[-1]
        pct = (finite <= last).mean()
        p99 = float(np.quantile(finite, 0.99))
        print(f"{sym:>6} {last:7.2f} {pct:7.1%} {p99:6.2f}  "
              f"{int((finite > p99).sum()):>18}")
    print("\nReading: a latest value above its own p99 says today's shape "
          "has almost no precedent in the readable history. Alarm "
          "thresholds are picked by a human from these distributions "
          "(and the COVID crash sits inside the CLEAN window — this "
          "calibration deliberately cannot see it).")


def cmd_timegpt(args) -> None:
    """S7 second alarm candidate (Plan §17 topic 5; shelf §20.17): TimeGPT
    online anomaly detection as the model-based complement to MASS. A
    calibration report, deliberately NOT a pager — nominal vs empirical
    flag rates on our own tape, and the agreement table with the MASS
    alarm, so a human can decide whether this vendor earns a threshold."""
    import numpy as np
    from factory import similarity as sim
    from factory import timegpt as tg
    from factory.ledgers import holdout, trials
    from factory.screens.screen import load_panels

    symbols = (args.universe.split(",") if args.universe else
               ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
                "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"])
    try:
        client = tg.make_client()
    except tg.TimeGPTUnavailable as e:
        sys.exit(str(e))
    panels = load_panels(Path(args.data_dir).expanduser(), symbols,
                         args.timeframe, hard_stop=None)
    spans = sim.forbidden_spans(holdout.windows(HOLDOUT))

    print(f"# TimeGPT online anomaly calibration — model {tg.MODEL}, "
          f"level {args.level}, last {args.detection_size} bars judged "
          f"({args.timeframe}); clean/accruing candles never sent\n")
    print(f"{'pair':>6} {'segment':>19} {'flags':>6} {'rate':>7} "
          f"{'both':>5} {'tg only':>8} {'mass only':>10}")
    all_flags, calls = [], 0
    pooled = {"both": 0, "timegpt_only": 0, "mass_only": 0}
    for sym in symbols:
        close = tg.readable_segment(panels["close"][sym].dropna(), spans)
        if len(close) < 4 * args.detection_size:
            print(f"{sym:>6}  (readable segment too short)")
            continue
        res = tg.detect(client, close, args.level, args.detection_size, args.h)
        calls += 1
        tail = res.tail(args.detection_size)
        flags = tail["anomaly"].to_numpy(dtype=bool)
        all_flags.append(flags)
        tail_dates = [d.strftime("%Y%m%d") for d in tail["ds"]]
        tg_dates = {d for d, f in zip(tail_dates, flags) if f}
        x = np.log(close.to_numpy(dtype=float))
        dates = [d.strftime("%Y%m%d") for d in close.index]
        mass_dates = tg.mass_crossings(
            x, dates, args.mass_window,
            np.ones(len(x) - args.mass_window + 1, bool), tail_dates)
        agr = tg.agreement(tg_dates, mass_dates)
        for k in pooled:
            pooled[k] += agr[k]
        cov = tg.coverage(flags, args.level)
        print(f"{sym:>6} {dates[0]}-{dates[-1]:>8} {cov['flagged']:>6} "
              f"{cov['rate']:7.1%} {agr['both']:>5} {agr['timegpt_only']:>8} "
              f"{agr['mass_only']:>10}")

    if all_flags:
        cov = tg.coverage(np.concatenate(all_flags), args.level)
        print(f"\npooled: {cov['flagged']} flags over {cov['n']} point-days "
              f"— empirical {cov['rate']:.2%} vs nominal "
              f"{cov['nominal']:.2%} (expected ~{cov['expected']:.1f} under "
              f"the vendor's own calibration claim)")
    print("\nReading (the §17.2 rule): an empirical rate far above nominal "
          "says the vendor's intervals are miscalibrated on this tape — "
          "shelf §20.17 measured 80% intervals covering 37.5-89.9%. The "
          "agreement table is the model-based vs model-free cross-check. "
          "A human picks thresholds from this report; nothing pages.")
    cost = round(calls * tg.COST_PER_CALL_USD, 4)
    trials.append(LEDGER, "vendor_api", "adhoc",
                  {"vendor": "nixtla", "endpoint": "detect_anomalies_online",
                   "model": tg.MODEL, "calls": calls, "cost_usd": cost,
                   "level": args.level, "detection_size": args.detection_size,
                   "note": "cost at the Standard-tier marginal rate; the "
                           "free Starter tier covers 50 calls/month"})
    print(f"\nledger: {calls} API calls recorded (${cost:.2f} at the "
          f"Standard-tier marginal rate)")


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
    s.add_argument("--to", default="S5", choices=mf.STAGES)
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("approve"); s.add_argument("run_id")
    s.add_argument("gate", choices=sorted(mf.GATE_ARTIFACTS))
    s.add_argument("--notes", default="")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("status"); s.add_argument("run_id", nargs="?")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("ledger"); s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("factor-screen"); s.add_argument("expr")
    s.add_argument("--name", default="Candidate")
    s.add_argument("--universe", default="",
                   help="comma-separated symbols; default = the 17-pair universe")
    s.add_argument("--timeframe", default="1d")
    s.add_argument("--data-dir", default="~/freqtrade-data")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_factor_screen)
    s = sub.add_parser("scenarios"); s.add_argument("symbol")
    s.add_argument("--window", type=int, default=60)
    s.add_argument("--k", type=int, default=8)
    s.add_argument("--horizons", default="7,21")
    s.add_argument("--timeframe", default="1d")
    s.add_argument("--data-dir", default="~/freqtrade-data")
    s.set_defaults(fn=cmd_scenarios)
    s = sub.add_parser("novelty")
    s.add_argument("--window", type=int, default=30)
    s.add_argument("--universe", default="",
                   help="comma-separated symbols; default = the 17-pair universe")
    s.add_argument("--timeframe", default="1d")
    s.add_argument("--data-dir", default="~/freqtrade-data")
    s.set_defaults(fn=cmd_novelty)
    s = sub.add_parser("timegpt")
    s.add_argument("--detection-size", type=int, default=90,
                   help="trailing bars the vendor judges (default 90)")
    s.add_argument("--level", type=int, default=99)
    s.add_argument("--h", type=int, default=1)
    s.add_argument("--mass-window", type=int, default=30,
                   help="MASS novelty window for the agreement table")
    s.add_argument("--universe", default="",
                   help="comma-separated symbols; default = the 17-pair universe")
    s.add_argument("--timeframe", default="1d")
    s.add_argument("--data-dir", default="~/freqtrade-data")
    s.set_defaults(fn=cmd_timegpt)
    s = sub.add_parser("dryrun-review"); s.add_argument("data_dir")
    s.set_defaults(fn=cmd_dryrun_review)
    s = sub.add_parser("reject"); s.add_argument("run_id")
    s.add_argument("stage", choices=sorted(mf.STAGE_AWAITS))
    s.add_argument("--notes", required=True)
    s.set_defaults(fn=cmd_reject)
    s = sub.add_parser("replay"); s.add_argument("run_id")
    s.add_argument("--from", dest="from_stage", required=True, choices=mf.STAGES)
    s.set_defaults(fn=cmd_replay)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
