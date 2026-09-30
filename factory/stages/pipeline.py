"""The staged pipeline: S0 intake, S1 research, S2 screen, S3 pre-register,
S4 implement, S5 validate — wired for the Runner.

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

from factory.gates import core
from factory.ledgers import trials
from factory.orchestrator.runner import StageResult
from factory.stages import llm
from factory.stages.validate import ValidateSpec, run_validation
from factory.validation import splitter

ROOT = Path(__file__).resolve().parents[2]
TIMEFRAMES = {"1d", "4h", "1h"}
ROUNDTRIP = 0.002  # 0.1%/side, the working fee basis
REQUIRED_CARD_FIELDS = [
    "name", "premise", "edge_source", "cross_sectional", "universe",
    "timeframe", "holding_period_days", "estimates", "estimates_basis",
    "parameters", "provenance",
]
# Source patterns that killed real strategies via lookahead; S4 refuses them.
FORBIDDEN = [
    (r"shift\(\s*-", "negative shift reads the future"),
    (r"center\s*=\s*True", "centered window reads the future"),
    (r"iloc\[\s*-1\s*\]", "whole-frame iloc[-1] inside populate_* is a lookahead"),
    (r"\.hyper_opt|IntParameter|DecimalParameter|CategoricalParameter",
     "strategy must not be tunable (Plan §15)"),
]


def _art(run_dir: Path) -> Path:
    a = run_dir / "artifacts"
    a.mkdir(exist_ok=True)
    return a


def _log_llm(ledger: Path, run_dir: Path, stage: str, out: dict) -> None:
    trials.append(ledger, "llm", run_dir.name,
                  {"stage": stage, "cost_usd": out.get("cost_usd"),
                   "num_turns": out.get("num_turns")})


def load_card(run_dir: Path) -> dict:
    return json.loads((_art(run_dir) / "hypothesis.json").read_text())


# --- S0 intake --------------------------------------------------------------

def validate_card(card: dict) -> list[str]:
    problems = [f"missing field {k!r}" for k in REQUIRED_CARD_FIELDS if k not in card]
    if problems:
        return problems
    if not str(card["name"]).isidentifier():
        problems.append(f"name {card['name']!r} is not a valid class name")
    if card["timeframe"] not in TIMEFRAMES:
        problems.append(f"timeframe {card['timeframe']!r} not in {sorted(TIMEFRAMES)}")
    if not (isinstance(card["universe"], list) and 0 < len(card["universe"]) <= 17):
        problems.append("universe must be a list of 1-17 pairs")
    est = card.get("estimates", {})
    for k in ("gross_edge_per_trade", "per_trade_sd", "trades_available"):
        if not isinstance(est.get(k), (int, float)):
            problems.append(f"estimates.{k} must be a number")
    if not (isinstance(card["parameters"], dict) and card["parameters"]):
        problems.append("parameters must be a non-empty dict of a-priori values")
    return problems


def intake_stage(agent_fn=None, ledger: Path | None = None):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = _art(run_dir)
        out = agent_fn(prompt=llm.load_prompt("intake", idea=manifest.prompt),
                       cwd=art, allowed_tools=["Write", "Read"])
        if ledger:
            _log_llm(ledger, run_dir, "S0", out)
        try:
            card = load_card(run_dir)
        except Exception as e:
            return StageResult("killed", f"intake produced no readable card: {e}")
        problems = validate_card(card)
        if problems:
            return StageResult("killed", "invalid hypothesis card: " + "; ".join(problems))
        if not (art / "hypothesis.md").exists():
            return StageResult("killed", "hypothesis.md missing")
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
        art = _art(run_dir)
        out = agent_fn(
            prompt=llm.load_prompt("research", library_dir=lib),
            cwd=art,
            allowed_tools=["Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
        )
        if ledger:
            _log_llm(ledger, run_dir, "S1", out)
        f = art / "research.md"
        if not f.exists():
            return StageResult("killed", "research.md missing")
        text = f.read_text()
        missing = [s for s in RESEARCH_SECTIONS if s not in text]
        if missing:
            return StageResult("killed", f"research.md missing sections: {missing}")
        if len(text) < 1500:
            return StageResult("killed", "research.md too thin to be a research memo")
        return StageResult("passed", "research memo written")

    return stage


# --- S2 screen (deterministic) ----------------------------------------------

def screen_stage():
    def stage(run_dir, manifest) -> StageResult:
        card = load_card(run_dir)
        est = card["estimates"]
        edge_gate = 3 * ROUNDTRIP  # what the 3x rule will demand per trade
        verdicts = [
            core.noise_floor(est["per_trade_sd"], edge_gate,
                             int(est["trades_available"])),
            core.cost_coverage(est["gross_edge_per_trade"], ROUNDTRIP),
        ]
        lines = [f"# Screen report — {card['name']}", "",
                 "Screens run on the card's declared estimates (see "
                 "estimates_basis); measured screens follow in S5.", ""]
        for v in verdicts:
            lines.append(f"- {'PASS' if v.passed else '**FAIL**'} `{v.gate}` — {v.reason}")
        if card.get("cross_sectional"):
            lines += ["", "**Cross-sectional card: a measured factor screen "
                          "(ORACLE + NOISE arms) is REQUIRED before S5** (Plan §22)."]
        (_art(run_dir) / "screen_report.md").write_text("\n".join(lines) + "\n")
        failed = [v for v in verdicts if not v.passed]
        if failed:
            return StageResult("killed",
                               "; ".join(f"{v.gate}: {v.reason}" for v in failed))
        return StageResult("passed", "estimate screens clear; measured screens due in S5")

    return stage


# --- S3 pre-register --------------------------------------------------------

PREREG_SECTIONS = ["## Hypothesis", "## Fixed parameters", "## Protocol",
                   "## Pass criteria", "## Trial budget", "## Committed consequences"]


def prereg_stage(agent_fn=None, ledger: Path | None = None, today: str = ""):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = _art(run_dir)
        out = agent_fn(prompt=llm.load_prompt("preregister", today=today),
                       cwd=art, allowed_tools=["Read", "Write"])
        if ledger:
            _log_llm(ledger, run_dir, "S3", out)
        f = art / "prereg.md"
        if not f.exists():
            return StageResult("killed", "prereg.md missing")
        missing = [s for s in PREREG_SECTIONS if s not in f.read_text()]
        if missing:
            return StageResult("killed", f"prereg.md missing sections: {missing}")
        return StageResult(
            "needs_human",
            "pre-registration drafted — review artifacts/prereg.md and sign: "
            f"factory approve {run_dir.name} hg1",
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
    return problems


def implement_stage(engine, trial_ledger: Path, agent_fn=None,
                    smoke_timerange: str = "20210101-20210901"):
    agent_fn = agent_fn or llm.run_agent

    def stage(run_dir, manifest) -> StageResult:
        art = _art(run_dir)
        card = load_card(run_dir)
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
        try:
            r = engine.backtest(name, card["timeframe"], smoke_timerange,
                                fee=0.001, strategy_path=art)
        except Exception as e:
            return StageResult("killed", f"smoke backtest failed: {e}")
        trials.append(trial_ledger, "backtest", run_dir.name,
                      {"strategy": name, "timerange": smoke_timerange,
                       "fee": 0.001, "why": "S4 smoke",
                       "trades": r.trade_count, "profit_total": r.profit_total})
        report = f"smoke backtest ran: {r.trade_count} trades on {smoke_timerange}"
        if r.trade_count == 0:
            report += " — WARNING: zero trades; entry logic may be dead"
        return StageResult("passed", report, {"strategy_file": f.name})

    return stage


# --- S5 validate (wired) ----------------------------------------------------

def validate_stage(engine, trial_ledger: Path):
    wf = json.loads((ROOT / "lab" / "user_data" / "notebooks" /
                     "walkforward.json").read_text())

    def stage(run_dir, manifest) -> StageResult:
        card = load_card(run_dir)
        purge = max(30, 2 * int(card["holding_period_days"]))
        folds = splitter.purge_existing(wf, purge_days=purge)
        spec = ValidateSpec(
            strategy=card["name"], timeframe=card["timeframe"], fee=0.001,
            folds=folds, full_timerange="20210101-20260101",
            strategy_path=_art(run_dir),
            notes={"purge_days": purge, "why": "S5 pre-registered run"},
        )
        return run_validation(engine, spec, run_dir, trial_ledger)

    return stage


# --- registry ---------------------------------------------------------------

def build_stages(engine, trial_ledger: Path, agent_fn=None, today: str = ""):
    return {
        "S0": intake_stage(agent_fn, trial_ledger),
        "S1": research_stage(agent_fn, trial_ledger),
        "S2": screen_stage(),
        "S3": prereg_stage(agent_fn, trial_ledger, today),
        "S4": implement_stage(engine, trial_ledger, agent_fn),
        "S5": validate_stage(engine, trial_ledger),
    }
