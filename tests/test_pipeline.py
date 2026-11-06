"""M5 acceptance (offline half): the full pipeline S0→S4 with fake agents —
valid artifacts advance, invalid ones kill, HG1 blocks until signed, and
the implement stage's static checks catch lookahead."""

import json
from pathlib import Path

import pytest

from factory.engine.lab import BacktestResult
from factory.engine.recorded import RecordedEngine
from factory.orchestrator import approvals, manifest as mf
from factory.orchestrator.runner import GateRefusal, Runner, acknowledge
from factory.stages import pipeline

CARD = {
    "name": "ToySmaCross",
    "premise": "trend persistence on daily bars",
    "edge_source": "momentum",
    "cross_sectional": False,
    "universe": ["BTC/USDT", "ETH/USDT"],
    "timeframe": "1d",
    "holding_period_days": 10,
    "estimates": {"gross_edge_per_trade": 0.008, "per_trade_sd": 0.05,
                  "trades_available": 400},
    "estimates_basis": "toy numbers chosen to clear the screens",
    "parameters": {"fast": 20, "slow": 50},
    "provenance": "M5 acceptance test",
}

STRATEGY_OK = '''
from freqtrade.strategy import IStrategy

class ToySmaCross(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    stoploss = -0.10
    minimal_roi = {"0": 10}
    startup_candle_count = 60
    can_short = False
    FAST, SLOW = 20, 50

    def populate_indicators(self, dataframe, metadata):
        dataframe["fast"] = dataframe["close"].rolling(self.FAST).mean()
        dataframe["slow"] = dataframe["close"].rolling(self.SLOW).mean()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[dataframe["fast"] > dataframe["slow"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[dataframe["fast"] < dataframe["slow"], "exit_long"] = 1
        return dataframe
'''

RESEARCH_MD = "\n\n".join(
    [f"{s}\n\n" + "filler text " * 40 for s in pipeline.RESEARCH_SECTIONS])
PREREG_MD = "\n\n".join(f"{s}\n\ncontent" for s in pipeline.PREREG_SECTIONS)


def fake_agent_writing(files: dict):
    """An agent_fn that just writes canned artifacts."""
    def agent(prompt, cwd, allowed_tools, **kw):
        for name, content in files.items():
            (Path(cwd) / name).write_text(content)
        return {"result": "done", "cost_usd": 0.0, "num_turns": 1}
    return agent


class SmokeEngine:
    def backtest(self, strategy, timeframe, timerange, fee, strategy_path=None):
        assert strategy_path is not None  # never runs from the lab tree
        return BacktestResult(strategy, 12, 10.0, 0.005, [], None, 0.004)


def stages_for(tmp_path, card=CARD, strategy_src=STRATEGY_OK):
    ledger = tmp_path / "trials.jsonl"
    return {
        "S0": pipeline.intake_stage(fake_agent_writing({
            "hypothesis.json": json.dumps(card), "hypothesis.md": "# card"}), ledger),
        "S1": pipeline.research_stage(fake_agent_writing({
            "research.md": RESEARCH_MD}), ledger),
        "S2": pipeline.screen_stage(),
        "S3": pipeline.prereg_stage(fake_agent_writing({
            "prereg.md": PREREG_MD}), ledger),
        "S4": pipeline.implement_stage(
            RecordedEngine(SmokeEngine(), ledger), ledger,
            fake_agent_writing({f"{card['name']}.py": strategy_src})),
    }, ledger


def test_full_flow_blocks_at_hg1_then_reaches_s4(tmp_path):
    stages, ledger = stages_for(tmp_path)
    run_dir = mf.new_run("toy sma cross", tmp_path / "runs")
    runner = Runner(run_dir, stages)

    with pytest.raises(GateRefusal, match="hg1"):
        runner.run_to("S4")
    m = mf.load(run_dir)
    assert m.stages["S3"]["status"] == "needs_human"
    assert m.stages["S3"]["completed"] is True

    # a second run_to must refuse again, not re-run S3 (the 24-CPU-minute bug)
    with pytest.raises(GateRefusal, match="acknowledgement"):
        runner.run_to("S4")

    art = run_dir / "artifacts"
    approvals.sign(run_dir, "hg1",
                   [art / "prereg.md", art / "hypothesis.json"], notes="toy")
    acknowledge(run_dir, "S3")
    runner.run_to("S4")
    m = mf.load(run_dir)
    assert m.stages["S4"]["status"] == "passed"
    assert "smoke backtest ran: 12 trades" in m.stages["S4"]["report"]
    # every agent call (S0, S1, S3, S4) and the smoke backtest hit the ledger
    kinds = [json.loads(l)["kind"] for l in open(ledger)]
    assert kinds.count("llm") == 4 and kinds.count("backtest") == 1


def test_bad_card_kills_intake(tmp_path):
    bad = dict(CARD, name="not a class name", timeframe="7m")
    stages, _ = stages_for(tmp_path, card=bad)
    run_dir = mf.new_run("bad card", tmp_path / "runs")
    Runner(run_dir, stages).advance()
    st = mf.load(run_dir).stages["S0"]
    assert st["status"] == "killed"
    assert "not a valid class name" in st["report"]
    assert "timeframe" in st["report"]


def test_hopeless_estimates_die_at_screen(tmp_path):
    # H4-shaped numbers: sd 15pp, ~90 trades — the noise floor must kill it
    bad = dict(CARD, estimates={"gross_edge_per_trade": 0.008,
                                "per_trade_sd": 0.15, "trades_available": 90})
    stages, _ = stages_for(tmp_path, card=bad)
    run_dir = mf.new_run("noisy idea", tmp_path / "runs")
    Runner(run_dir, stages).run_to("S4")
    m = mf.load(run_dir)
    assert m.stages["S2"]["status"] == "killed"
    assert "noise_floor" in m.stages["S2"]["report"]
    assert (run_dir / "artifacts" / "screen_report.md").exists()


def test_lookahead_strategy_is_refused():
    src = STRATEGY_OK.replace('rolling(self.FAST).mean()',
                              'rolling(self.FAST, center=True).mean()')
    problems = pipeline.check_strategy_source(src, "ToySmaCross")
    assert any("future" in p for p in problems)


def test_tunable_strategy_is_refused():
    src = STRATEGY_OK.replace("FAST, SLOW = 20, 50",
                              'FAST = IntParameter(10, 30, default=20)')
    problems = pipeline.check_strategy_source(src, "ToySmaCross")
    assert any("must not be tunable" in p for p in problems)


def test_thin_research_is_killed(tmp_path):
    stages, _ = stages_for(tmp_path)
    stages["S1"] = pipeline.research_stage(fake_agent_writing({
        "research.md": "\n".join(pipeline.RESEARCH_SECTIONS)}))
    run_dir = mf.new_run("thin research", tmp_path / "runs")
    Runner(run_dir, stages).run_to("S2")
    st = mf.load(run_dir).stages["S1"]
    assert st["status"] == "killed"
    assert "too thin" in st["report"]


def test_iloc_last_in_populate_is_refused_but_runtime_callbacks_pass():
    """The iloc[-1] rule means what it says: inside populate_* the frame is
    full history (lookahead); in runtime callbacks the analyzed frame is
    truncated to the current candle — the standard freqtrade sizing pattern
    (what S4 generated for LowVolRankTilt17 and the whole-file grep
    wrongly killed twice)."""
    in_populate = STRATEGY_OK.replace(
        'rolling(self.FAST).mean()', 'rolling(self.FAST).mean() * d["c"].iloc[-1]')
    problems = pipeline.check_strategy_source(in_populate, "ToySmaCross")
    assert any("iloc[-1]" in p or "iloc" in p for p in problems)

    in_callback = STRATEGY_OK + (
        "\n\ndef custom_stake_amount(self, pair, **kwargs):\n"
        "    df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)\n"
        "    return df['weight'].iloc[-1]\n")
    problems = pipeline.check_strategy_source(in_callback, "ToySmaCross")
    assert not problems


def test_gamed_estimates_are_refused():
    """The sd is the quadratic lever on the noise floor; a card whose sd is
    below its own claimed edge (per-trade Sharpe > 1) is a number picked to
    clear the gate, and the prompt's prose rule is now a code rule."""
    from factory import card as card_mod
    gamed = dict(CARD, estimates={"gross_edge_per_trade": 0.02,
                                  "per_trade_sd": 0.01,
                                  "trades_available": 400})
    problems = card_mod.validate(gamed)
    assert any("picked to clear the noise floor" in p for p in problems)
    absurd = dict(CARD, estimates={"gross_edge_per_trade": 0.6,
                                   "per_trade_sd": 0.9,
                                   "trades_available": 0})
    problems = card_mod.validate(absurd)
    assert any("under 50%" in p for p in problems)
    assert any("at least 1" in p for p in problems)
    assert not card_mod.validate(dict(CARD))  # the honest fixture still passes


def test_fitted_objects_in_strategy_are_refused():
    """Implement.md's 'no fitting' rule had no regex backstop; the causal-fit
    rule (Plan §17 topic 6) is now refused at S4, not just in prose."""
    src = STRATEGY_OK.replace(
        'rolling(self.FAST).mean()',
        'rolling(self.FAST).mean()\n        scaler.fit(d["c"])')
    problems = pipeline.check_strategy_source(src, "ToySmaCross")
    assert any("causal-fit" in p for p in problems)
    assert not pipeline.check_strategy_source(STRATEGY_OK, "ToySmaCross")


def test_llm_log_carries_model_and_latency():
    """Topic 2's first lesson applied to ourselves: the ledger must say WHICH
    model answered and how long it took, or no calibration is comparable."""
    import json as _json
    from factory.stages.pipeline import _log_llm

    class FakeRunDir:
        name = "fake-run"

    def check(tmp, out):
        _log_llm(tmp, FakeRunDir(), "S0", out)
        rec = _json.loads(open(tmp).readlines()[-1])
        return rec

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "trials.jsonl"
        rec = check(ledger, {"cost_usd": 0.5, "num_turns": 3,
                             "model": "claude-opus-5-5", "duration_s": 12.3})
        assert rec["model"] == "claude-opus-5-5"
        assert rec["duration_s"] == 12.3
