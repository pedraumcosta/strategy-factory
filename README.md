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

**Status: operational.** The M0–M8 roadmap closed 2026-09-30; the pipeline has since run
real candidates and killed them at the right stages, a dry-run observes on the VM, and the
holdout matures 2027-03-28. Design in [`docs/DESIGN.md`](docs/DESIGN.md); the decision
record (status, gate changes, every battery's registration and results) is
[`docs/PLAN.md`](docs/PLAN.md).

## What this is, in one paragraph

Between 2026-09-26 and 2026-09-29 a manual research process put six strategy hypotheses
through a gauntlet of measured gates — cost coverage, noise floor, factor screens, control
arms, exposure-scaled passive benchmarks, return concentration — and killed all six, each
for a diagnosed reason. This factory is that method, mechanized: the gates become stage
validators, pre-registration becomes a blocking human gate, holdout data becomes physically
unmountable without a signed spend approval, and every run appends to a trial ledger so the
deflated Sharpe is computable instead of aspirational. The graveyard — now eight corpses
spanning the 2020 live bot, that manual gauntlet and the factory's own runs — is the
regression suite: **the factory must re-kill every corpse, at the right stage, for the right
reason**, and each corpse carries a full dossier (data, universe, timeframe, construction,
performance, why it was killed).

## The CLI

```
factory new "hypothesis idea..."      create a run (S0 intake writes the card)
factory run <run-id> [--to S5]        advance the pipeline
factory approve <run-id> <gate>       sign a human gate (hg1|hg2|hg2b|hg3)
factory reject <run-id>               record a human kill
factory replay <run-id>               re-issue a run killed by infrastructure, not verdict
factory status [<run-id>]             show runs / one run's stages
factory ledger                        trial counts + LLM spend
factory record [--out f.md]           render the tested register (below)
factory dryrun-review <data-dir>      judge a deployed dry-run's week
```

`factory record` renders **the tested register**: every strategy ever tried — the 2020
live-bot era, the manual 2026-09 gauntlet, the factory era — each with its data, universe,
timeframe, construction, performance, result and kill reason. It is a query over the
machine record (graveyard, kinship scopes, run manifests, battery results, trial ledger),
never a hand-maintained document: when it looks wrong, fix the record, not the report.

## Candidate sources beyond the pipeline

- **Pre-registered factor batteries** ([`tools/run_battery.py`](tools/run_battery.py),
  [`tools/run_battery12.py`](tools/run_battery12.py)): deterministic screens, zero LLM
  spend, each battery's premises and pass bars committed to `docs/PLAN.md` §17 *before*
  any run. Topic 12 added a regression arm that re-runs topic 11 and demands bit-for-bit
  equality with its committed results (recorded IDENTICAL, twice).
- **Data families**, fetched outside the repo beside the price data: 8h perp funding
  ([`tools/fetch_funding.py`](tools/fetch_funding.py)) — also a causal `funding` panel in
  the screen DSL — and daily open interest ([`tools/fetch_oi.py`](tools/fetch_oi.py),
  Binance Vision, published from 2021-12-01).
- **Graveyard kinship at S0**: an advisory flag judging every new card against the closed
  idea-space families before any fold is spent — verdict and confidence land in the run's
  `kinship.json` and on the ledger; it informs HG1, it never kills.

## Hard rules

1. **No live trading.** Deploy means `dry_run: true`. Going live is outside this repo's scope.
2. **No secrets in the tree, ever.** Env vars only (`FREQTRADE__EXCHANGE__KEY/__SECRET`).
3. **Holdout data is spent by looking at it.** The store partitions it; only a signed
   HG2b approval mounts it, and the spend is recorded permanently.
4. **Every backtest/screen/re-run appends to the trial ledger.** The count only goes up.

## Provenance

- Engine room: [`lab/`](lab/) — a freqtrade 2026.8 docker workspace (formerly the standalone
  `freqtrade-lab`, absorbed 2026-09-29) with a 7-fold walk-forward harness, screens and a tear
  sheet. Its own README documents the harness, holdout status and ten hard-won gotchas.
- Decision record: [`docs/PLAN.md`](docs/PLAN.md) — the steering document (status, decisions,
  M0–M8 execution findings, next steps in its §17). Its `Autotrader Plan §n` references point
  to the private trading-practice record, which stays out of this repo.
- Design: established practice for staged multi-agent build pipelines (role-scoped
  workers, manifests, per-stage validators, resume/replay), adapted to strategy
  production — with the common LLM meta-agent orchestrator deliberately replaced by a
  deterministic state machine. LLM judgment lives *inside* stages, never between them.

## License

MIT. freqtrade (GPL-3.0) is driven strictly across a process boundary (docker CLI); no
freqtrade code is copied here.
