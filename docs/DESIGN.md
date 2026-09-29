# strategy-factory — design

Self-contained buildable spec. The *decision record* (why each choice was made, with the
measured numbers behind every gate) lives in the private TechTrading knowledge folder
(`Strategy Factory Plan.md`, `Autotrader Plan.md`); section references like "Plan §21"
point there. This file is what you build from.

## 1. Principles

1. **Deterministic core, LLM edges.** The orchestrator is a plain state machine over
   manifests. Claude Agent SDK sessions run *inside* the Intake / Research / Pre-register /
   Implement stages with stage-scoped prompts and tool allowlists. Everything the Screen and
   Validate stages compute is a library function with a unit test. LLM output never
   self-certifies; deterministic gates decide every transition.
2. **A strategy factory is, by default, a multiple-comparisons machine.** The structural
   answers: an append-only **trial ledger** (makes deflated Sharpe computable), a
   **holdout lockout** (holdout data is not mounted without a signed approval), and
   **pre-registration as a blocking human gate** before any fold runs.
3. **The graveyard is the test suite.** Six hypotheses were manually tested and killed in
   Sep 2026, each for a measured, diagnosed reason. Their recorded numbers are fixtures:
   the factory must re-kill each at the right stage for the right reason.
4. **The engine is freqtrade, across a process boundary.** The factory shells out to the
   in-repo lab's (`lab/`) docker images (`freqtrade-lab:2026.8` for backtests,
   `:2026.8-research` for screens/tear sheets — never mixed: the research image downgrades
   pandas). Strategies are materialized into the run directory and passed via
   `--strategy-path`; the lab's own tree is never written to.

## 2. Pipeline

```
prompt ─► S0 Intake ─► S1 Research ─► S2 Screen ─► S3 Pre-register ─► S4 Implement ─► S5 Validate ─► S6 Deploy ─► S7 Observe
                                        │auto-kill      ▲ HG1                             ▲ HG2 (+HG2b)   ▲ HG3
```

Stage contract: read `manifest.json` + prior artifacts → write artifacts + a short report →
append to the trial ledger if anything ran on data → end `passed | killed | needs_human`.

| Stage | Kind | Output |
|---|---|---|
| S0 Intake | LLM | Hypothesis card (`hypothesis.md/.json`): premise, edge source, universe, timeframe, holding period, a-priori parameter priors, provenance |
| S1 Research | LLM | `research.md` with citations — local materials first, then web; must name each source's cost model (usually absent) and check known anti-patterns |
| S2 Screen | Deterministic | `screen_report.md` — cheap kills in order: noise floor, 3× cost rule, factor screen (cross-sectional only, with ORACLE + NOISE arms), spread screen + random-entry controls (spread designs only). In-sample data only. Most hypotheses should die here |
| S3 Pre-register | LLM draft → **HG1** | `prereg.md`: fixed parameters, pass criteria, protocol, trial budget, committed consequences. Signed by the human before anything downstream runs |
| S4 Implement | LLM + checks | `strategy.py` + `config.json` in the run dir; static checks; smoke backtest on a small in-sample window; freqtrade `lookahead-analysis` (single-strategy mode only; invalid for cross-sectional designs); a generated causal test (truncated-vs-full dataframe equality) |
| S5 Validate | Deterministic | Dossier: purged+embargoed walk-forward, control arms (untuned defaults AND exposure-scaled passive), cost sweep, robustness grid, tear sheet (mark-to-market, 365-day annualization), deflated Sharpe from the ledger, cross-provider data-integrity audit; papermill review notebook → **HG2**. Holdout spend is a separate signature (**HG2b**) |
| S6 Deploy | Deterministic + **HG3** | Docker compose to a VM: freqtrade `dry_run: true` + FreqUI (localhost-bound) + observer. Secrets env-only. Target: a 30-day dry run |
| S7 Observe | Service | REST-API poller → append-only parquet snapshots; daily dry-run-vs-backtest parity check; Telegram alerts on errors/drift/silence; observation notebook |

**Approvals are signatures over hashes.** `factory approve <run> <gate>` records
who/when/artifact-hash. The orchestrator refuses to advance when upstream artifacts changed
after signing (hash mismatch ⇒ re-approve).

## 3. Gates (S2/S5 validators)

| Gate | Test | Kills fixture |
|---|---|---|
| Noise floor | per-trade sd at intended holding period vs the edge gate; trades needed (≈ (sd/edge)²·k) vs trades the history supplies. Gate inside error bars ⇒ untestable ⇒ kill | H4 (Kalman hedge-ratio spread): sd ≈ 15 pp vs 0.6 % gate |
| Cost rule | gross edge per trade ≥ 3× round-trip cost at the intended timeframe | H2 trend-following: −0.04× coverage |
| Zero-fee sanity | negative at zero cost ⇒ no signal | Strategy005: −49.55 % at zero fees |
| Factor screen | IC per horizon with t-stats, quintile forward returns, turnover; always beside an ORACLE (look-ahead) arm and a NOISE arm for scale | H1/H3 factor: IC negative at 9/9 horizons |
| Control arm | candidate must beat its own untuned defaults out-of-sample | H1 tuned: lost 6 of 7 folds |
| G-passive | equal-weight buy-and-hold of the same universe, scaled to realized exposure, compared on Sharpe, split by rising/falling windows | H3 five-year: Sharpe 0.81 vs 1.64 |
| Concentration | tear-sheet level only (provably not screenable in-sample): share of profit in best month/trade cluster | H3 holdout: one month = 78 % of profit |
| Deflated Sharpe | Bailey/López de Prado DSR using the trial count from the ledger, never a guess | calibrated at M4 |
| Data integrity | gaps, duplicate/missing candles, zero-volume stretches, cross-provider deviation bands (bands, not equality — venues differ) | synthetic corruption fixtures |

## 4. Layout

```
factory/
  orchestrator/   # state machine, manifest schema, approvals, resume/replay
  stages/         # S0–S7 (LLM stages via Claude Agent SDK; prompts in prompts/)
  gates/          # §3 as pure functions
  engine/         # freqtrade adapter over the lab's docker images + harness
  datafeed/       # providers, integrity audit, partitioned store (research/ vs holdout/)
  ledgers/        # trials.jsonl, holdout.json (both append-only)
  observer/       # S7 poller + parity + alerts
notebooks/        # papermill templates per human gate
runs/<id>/        # manifest.json + approvals/ tracked; artifacts/ gitignored
lab/              # the engine room: freqtrade docker workspace + wf/ research harness
fixtures/         # the graveyard: recorded numbers for the six dead hypotheses
deploy/           # compose + VM runbook
```

State is **manifest-first**: the run directory is authoritative; any SQLite index is derived.
Resume restarts an interrupted stage; replay from an earlier stage with changed inputs is a
new trial and the ledger records it.

Tech: Python 3.12, uv, Claude Agent SDK, papermill, pytest, docker. CLI:
`factory new | run | approve | status | replay`.

## 5. Data

- Primary OHLCV: Binance via `freqtrade download-data`; bulk data lives outside the repo
  and outside file sync (`~/freqtrade-data/` convention), regenerable.
- Secondary provider (ccxt, second exchange): integrity cross-check only, never backtested.
- Store partitioned `research/` vs `holdout/` by date range; the holdout ledger seeds from
  the predecessor project (2021–2025 folds spent; 2026 spent; 2019–2020 the last clean
  window; calendar accrues new windows). Research runs mount `research/` only.

## 6. Roadmap

| M | Delivers | Done when |
|---|---|---|
| M0 | Scaffold (this) | pushed |
| M1 | Engine adapter + golden test: rerun a fixed reference backtest through the lab image, match a recorded result exactly (trade count, timestamps, P&L) | `pytest -k golden` green given docker + data |
| M2 | `gates/` + graveyard fixtures | every dead hypothesis re-killed by the right gate |
| M3 | Orchestrator, manifests, approvals, both ledgers | a scripted run advances S2→S5 on fixtures; refuses failed gates and unsigned holdout |
| M4 | Purged+embargoed splitter, DSR, full S5 + review notebook | prior best result re-judged under the new splitter; delta documented |
| M5 | LLM stages S0/S1/S3/S4 + HG1 flow | toy prompt → signed pre-reg → strategy passing S4 checks |
| M6 | Full-pipeline rehearsal on a deliberately mediocre idea | a correct, cheap, legible kill |
| M7 | Deploy + observer on a VM (dry-run) | daily parity report generating |
| M8 | Observation notebooks, 30-day review flow, calendar-holdout accrual | first 30-day review through the factory |
