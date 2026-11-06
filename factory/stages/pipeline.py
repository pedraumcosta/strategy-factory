"""The staged pipeline: S0 intake, S1 research, S2 screen, S3 pre-register,
S4 implement, S5 validate — wired for the Runner.

This module is wiring: the card schema lives in factory/card.py, the S2
policy in factory/screens/policy.py, the cost model in factory/costs.py,
and every engine the stages see is a RecordedEngine (every backtest is a
trial; holdout windows are refused at the seam).

Every LLM stage has the same shape: the agent writes artifact files, a
deterministic validator judges them (the agent never self-certifies), and
the agent call itself is appended to the trial ledger with its dollar cost
— the $100/month odometer (Plan §11f) counts tokens as well as backtests.
Stage builders take an injectable `agent_fn` so tests run without tokens.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from factory import card as card_mod
from factory.costs import WORKING
from factory.engine.recorded import RecordedEngine
from factory.ledgers import trials
from factory.orchestrator import manifest as mf
from factory.orchestrator.runner import StageResult
from factory.screens import policy
from factory.stages import llm
from factory.stages.validate import ValidateSpec, run_validation
from factory.validation import splitter

ROOT = Path(__file__).resolve().parents[2]
# Source patterns that killed real strategies via lookahead; S4 refuses them.
FORBIDDEN = [
    (r"shift\(\s*-", "negative shift reads the future"),
    (r"center\s*=\s*True", "centered window reads the future"),
    (r"\.hyper_opt|IntParameter|DecimalParameter|CategoricalParameter",
     "strategy must not be tunable (Plan §15)"),
    (r"order_types|entry_pricing|exit_pricing",
     "execution pricing belongs to the lab config, not the strategy"),
    (r"sklearn|fit_transform|\.fit\(",
     "fitted objects inside a strategy violate the causal-fit rule "
     "(parameters are fixed a priori; Plan §17 topic 6)"),
]
# Scoped to populate_* bodies only: there the frame is the full history, so
# iloc[-1] reads the last bar of the backtest. In runtime callbacks
# (custom_stake_amount, custom_exit, ...) the analyzed frame is truncated to
# the current candle and iloc[-1] is "now" — the standard freqtrade pattern.
FORBIDDEN_IN_POPULATE = [
    (r"iloc\[\s*-1\s*\]", "whole-frame iloc[-1] inside populate_* is a lookahead"),
]


def _log_llm(ledger: Path, run_dir: Path, stage: str, out: dict) -> None:
    trials.append(ledger, "llm", run_dir.name,
                  {"stage": stage, "cost_usd": out.get("cost_usd"),
                   "num_turns": out.get("num_turns"),
                   "model": out.get("model"),
                   "duration_s": out.get("duration_s")})


# --- S0 intake --------------------------------------------------------------

def intake_stage(agent_fn=None, ledger: Path | None = None):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = mf.artifacts_dir(run_dir)
        out = agent_fn(prompt=llm.load_prompt("intake", idea=manifest.prompt),
                       cwd=art, allowed_tools=["Write", "Read"])
        if ledger:
            _log_llm(ledger, run_dir, "S0", out)
        try:
            card = card_mod.load(run_dir)
        except Exception as e:
            return StageResult("killed", f"intake produced no readable card: {e}")
        problems = card_mod.validate(card)
        if problems:
            return StageResult("killed", "invalid hypothesis card: " + "; ".join(problems))
        if not (art / mf.CARD_MD).exists():
            return StageResult("killed", f"{mf.CARD_MD} missing")
        return StageResult("passed", f"card for {card['name']}", {"name": card["name"]})

    return stage


# --- S1 research ------------------------------------------------------------

RESEARCH_SECTIONS = ["## Sources", "## Cost model of the sources",
                     "## Anti-patterns check", "## Parameter priors", "## Verdict"]


def research_stage(agent_fn=None, ledger: Path | None = None,
                   library_dir: Path | None = None):
    agent_fn = agent_fn or llm.run_agent
    lib = library_dir or (ROOT.parent.parent / "Library")

    def stage(run_dir, manifest) -> StageResult:
        art = mf.artifacts_dir(run_dir)
        out = agent_fn(
            prompt=llm.load_prompt("research", library_dir=lib),
            cwd=art,
            allowed_tools=["Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
        )
        if ledger:
            _log_llm(ledger, run_dir, "S1", out)
        f = art / mf.RESEARCH_MD
        if not f.exists():
            return StageResult("killed", f"{mf.RESEARCH_MD} missing")
        text = f.read_text()
        missing = [s for s in RESEARCH_SECTIONS if s not in text]
        if missing:
            return StageResult("killed", f"research.md missing sections: {missing}")
        if len(text) < 1500:
            return StageResult("killed", "research.md too thin to be a research memo")
        return StageResult("passed", "research memo written")

    return stage


# --- S2 screen (deterministic) ----------------------------------------------

def screen_stage(data_dir: Path | None = None, trial_ledger: Path | None = None,
                 folds: list[tuple[str, str, str]] | None = None):
    """S2 wiring over factory/screens/policy.py: load the card, run the
    policy, write the report artifact, put the measured screen on the
    ledger (searches are trials too)."""
    def stage(run_dir, manifest) -> StageResult:
        card = card_mod.load(run_dir)
        art = mf.artifacts_dir(run_dir)
        out = policy.screen(card, out_dir=art, data_dir=data_dir, folds=folds)
        if out.report_md:
            (art / mf.SCREEN_REPORT_MD).write_text(out.report_md)
        if out.factor_trial and trial_ledger:
            trials.append(trial_ledger, "factor_screen", run_dir.name,
                          out.factor_trial)
        if not out.passed:
            return StageResult("killed", "; ".join(out.reasons))
        return StageResult("passed", out.summary,
                           {"gates": [{"gate": g.gate, "passed": g.passed}
                                      for g in out.gates],
                            "measured_factor_screen": out.measured})

    return stage


# --- S3 pre-register --------------------------------------------------------

PREREG_SECTIONS = ["## Hypothesis", "## Fixed parameters", "## Protocol",
                   "## Pass criteria", "## Trial budget", "## Committed consequences"]


def prereg_stage(agent_fn=None, ledger: Path | None = None, today: str = ""):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = mf.artifacts_dir(run_dir)
        out = agent_fn(prompt=llm.load_prompt("preregister", today=today),
                       cwd=art, allowed_tools=["Read", "Write"])
        if ledger:
            _log_llm(ledger, run_dir, "S3", out)
        f = art / mf.PREREG_MD
        if not f.exists():
            return StageResult("killed", f"{mf.PREREG_MD} missing")
        missing = [s for s in PREREG_SECTIONS if s not in f.read_text()]
        if missing:
            return StageResult("killed", f"prereg.md missing sections: {missing}")
        return StageResult(
            "needs_human",
            f"pre-registration drafted — review artifacts/{mf.PREREG_MD} and "
            f"sign: {mf.approve_command(run_dir.name, 'hg1')}",
        )

    return stage


# --- S4 implement -----------------------------------------------------------

def check_strategy_source(src: str, name: str) -> list[str]:
    problems = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"does not parse: {e}"]
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if name not in classes:
        problems.append(f"no class {name} (found {classes})")
    if "INTERFACE_VERSION" not in src:
        problems.append("missing INTERFACE_VERSION")
    for pattern, why in FORBIDDEN:
        if re.search(pattern, src):
            problems.append(f"forbidden pattern /{pattern}/ — {why}")
    populate_src = "\n".join(
        ast.get_source_segment(src, n) or ""
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("populate"))
    for pattern, why in FORBIDDEN_IN_POPULATE:
        if re.search(pattern, populate_src):
            problems.append(f"forbidden pattern /{pattern}/ — {why}")
    return problems


def implement_stage(engine, trial_ledger: Path, agent_fn=None,
                    smoke_timerange: str = "20210101-20210901"):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = mf.artifacts_dir(run_dir)
        card = card_mod.load(run_dir)
        name = card["name"]
        out = agent_fn(prompt=llm.load_prompt("implement", strategy_name=name),
                       cwd=art, allowed_tools=["Read", "Write"])
        _log_llm(trial_ledger, run_dir, "S4", out)
        f = art / f"{name}.py"
        if not f.exists():
            return StageResult("killed", f"{f.name} missing")
        problems = check_strategy_source(f.read_text(), name)
        if problems:
            return StageResult("killed", "static checks failed: " + "; ".join(problems))
        # smoke backtest on a short SPENT window: does it load and run?
        # (the engine records the trial and checks the holdout ledger)
        try:
            r = engine.backtest(name, card["timeframe"], smoke_timerange,
                                fee=WORKING.fee_per_side, run_id=run_dir.name,
                                why="S4 smoke", strategy_path=art)
        except Exception as e:
            return StageResult("killed", f"smoke backtest failed: {e}")
        report = f"smoke backtest ran: {r.trade_count} trades on {smoke_timerange}"
        if r.trade_count == 0:
            report += " — WARNING: zero trades; entry logic may be dead"
        return StageResult("passed", report, {"strategy_file": f.name})

    return stage


# --- S5 validate (wired) ----------------------------------------------------

def validate_stage(engine, trial_ledger: Path, costs=WORKING):
    def stage(run_dir, manifest) -> StageResult:
        # read at run time, not build time: `factory run --to S2` must not
        # require the lab checkout
        wf = json.loads((ROOT / "lab" / "user_data" / "notebooks" /
                         "walkforward.json").read_text())
        card = card_mod.load(run_dir)
        purge = max(30, 2 * int(card["holding_period_days"]))
        folds = splitter.purge_existing(wf, purge_days=purge)
        spec = ValidateSpec(
            strategy=card["name"], timeframe=card["timeframe"], costs=costs,
            folds=folds, full_timerange="20210101-20260101",
            turnover_per_trade=card_mod.turnover(card),
            strategy_path=mf.artifacts_dir(run_dir),
            notes={"purge_days": purge, "why": "S5 pre-registered run"},
        )
        return run_validation(engine, spec, run_dir, trial_ledger)

    return stage


# --- registry ---------------------------------------------------------------

def build_stages(engine, trial_ledger: Path, agent_fn=None, today: str = "",
                 holdout_ledger: Path | None = None):
    if not isinstance(engine, RecordedEngine):
        engine = RecordedEngine(engine, trial_ledger, holdout_ledger)
    return {
        "S0": intake_stage(agent_fn, trial_ledger),
        "S1": research_stage(agent_fn, trial_ledger),
        "S2": screen_stage(engine.data_dir, trial_ledger),
        "S3": prereg_stage(agent_fn, trial_ledger, today),
        "S4": implement_stage(engine, trial_ledger, agent_fn),
        "S5": validate_stage(engine, trial_ledger),
    }
