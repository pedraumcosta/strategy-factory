# strategy-factory

An agent pipeline that **researches, implements, tests, validates, deploys and observes**
crypto trading strategies for [freqtrade](https://github.com/freqtrade/freqtrade), with a
human signature gate between the stages that matter.

```
prompt ─► Intake ─► Research ─► Screen ─► Pre-register ─► Implement ─► Validate ─► Deploy ─► Observe
                                 │auto-kill    ▲ HG1                       ▲ HG2/HG2b  ▲ HG3
                                 ▼             user signs                  user judges user approves
                              graveyard       the pre-reg                 the dossier  the deploy
```

**Status: M0 — scaffold.** Design in [`docs/DESIGN.md`](docs/DESIGN.md); roadmap M0–M8 at its end.

## What this is, in one paragraph

Between 2026-09-26 and 2026-09-29 a manual research process put six strategy hypotheses
through a gauntlet of measured gates — cost coverage, noise floor, factor screens, control
arms, exposure-scaled passive benchmarks, return concentration — and killed all six, each
for a diagnosed reason. This factory is that method, mechanized: the gates become stage
validators, pre-registration becomes a blocking human gate, holdout data becomes physically
unmountable without a signed spend approval, and every run appends to a trial ledger so the
deflated Sharpe is computable instead of aspirational. The six corpses are the regression
suite: **the factory must re-kill every one of them, at the right stage, for the right reason.**

## Hard rules

1. **No live trading.** Deploy means `dry_run: true`. Going live is outside this repo's scope.
2. **No secrets in the tree, ever.** Env vars only (`FREQTRADE__EXCHANGE__KEY/__SECRET`).
3. **Holdout data is spent by looking at it.** The store partitions it; only a signed
   HG2b approval mounts it, and the spend is recorded permanently.
4. **Every backtest/screen/re-run appends to the trial ledger.** The count only goes up.

## Provenance

- Engine room: a freqtrade 2026.8 docker workspace (`freqtrade-lab`, sibling folder, not in
  this repo) with a 7-fold walk-forward harness, screens and a tear sheet.
- Decision record: `Autotrader Plan.md` and `Strategy Factory Plan.md` in the private
  TechTrading knowledge folder (not in this repo).
- Design: established practice for staged multi-agent build pipelines (role-scoped
  workers, manifests, per-stage validators, resume/replay), adapted to strategy
  production — with the common LLM meta-agent orchestrator deliberately replaced by a
  deterministic state machine. LLM judgment lives *inside* stages, never between them.

## License

MIT. freqtrade (GPL-3.0) is driven strictly across a process boundary (docker CLI); no
freqtrade code is copied here.
