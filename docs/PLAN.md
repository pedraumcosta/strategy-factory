# Strategy Factory Plan — mechanizing the method

Steering document for this repository — **moved into the repo as `docs/PLAN.md` on 2026-09-30** (it began life in the private TechTrading knowledge folder, which is why `Autotrader Plan.md §n` and `Inventory §n` references below point to private documents: they are the trading practice's decision record, not part of this repo). Companion to `Autotrader Plan.md` (the trading practice: strategy, results, decisions — pointed from its §25) and `TechTrading Inventory.md` (the shelf catalogue). Written 2026-09-29, the day Phase 2 research was paused (Plan §18), from a pivot idea: build **the factory** — an agent system that researches, implements, tests, validates, deploys and observes autotrader strategies, with a human gate between stages. The design applies established practice for staged multi-agent build pipelines — role-scoped workers, state-first orchestration, per-stage validation, resume/replay — adapted from software-build automation to strategy production (§2).

---

## §0 Status at a glance — 2026-09-29

| | State |
|---|---|
| Steering doc (this file) | Written 2026-09-29 |
| M0 — repo scaffold | **Done 2026-09-29.** `Projects/strategy-factory/` created, git initialized, pushed **private** to `github.com/pedraumcosta/strategy-factory` |
| Lab absorption | **Done 2026-09-29** (user decision, was §11e): `freqtrade-lab/` moved into the repo as `lab/`, committed (8 MB / 177 files; byproducts and data stay out). All knowledge-folder path references repointed |
| M1 — engine adapter + golden test | **Done 2026-09-29.** `LabEngine` drives the lab image with the ft mounts, guards the leftover-param-file and exit-status gotchas; golden reference = XSMomentum 1d 2021→2026 fee 0.001, **1,028 trades**, reproduced exactly (timestamps exact, P&L to 1e-8) in ~7 s |
| M2 — gates + graveyard | **Done 2026-09-29.** `factory.gates`: noise floor, cost coverage, zero-fee sanity, control arm, factor-screen judge. `fixtures/graveyard.json` holds the recorded kill numbers; tests re-kill every corpse by the right gate, and the ORACLE arm must pass / NOISE must fail so the judge itself is calibrated |
| M3 — orchestrator spine | **Done 2026-09-29.** Manifest-first runs, approvals as signatures over artifact hashes (tampering voids them), deterministic runner (killed = terminal, crashes resume), trial ledger, holdout ledger seeded from Plan §18.2 with HG2b-gated permanent spends. 19 fast tests + 1 golden |
| M4 — splitter (U1), DSR, full S5 | **Done 2026-09-29.** Splitter + deflated Sharpe built and tested (incl. a NOISE-calibration test); S5 assembled (purged walk-forward, cost sweep, gates, DSR, dossier, papermill review notebook); trial ledger seeded with the lab's **276 historic exports**; H3 re-judged for real — findings in **§12** |
| M5 — LLM stages + HG1 flow | **Done 2026-09-29.** S0/S1/S3/S4 on the Claude Agent SDK with deterministic validators (the agent never self-certifies), stage prompts, S2 wired to the card, the `factory` CLI, and replay-from-stage. Acceptance ran with real agents — findings in **§13** |
| M6 — full-pipeline rehearsal | **Done 2026-09-30.** The signed toy ran S5's full gauntlet and was **killed at HG2 on three legible counts** (its own 30-day-hold tripwire at 107d realized, G-conc 48 % vs 40 %, DSR 0.091 vs 0.5) — findings in **§14**. `factory reject` records human kills with reasons |
| M7 — deploy + observer | **Done 2026-09-30, VM included.** The S6/S7 stack ran end to end locally, then went live on GCP: **`factory-dryrun`, e2-small, `europe-west1-b`** (project chosen by the user). Bot running dry-run on 17 pairs, observer healthy, parity writing daily. Three ops lessons in §15.1 |
| M8 — review flow + holdout accrual | **Done 2026-09-30** (§16). `factory dryrun-review` conducts the Phase-3 review through the factory; the calendar holdout accrues on the ledger (day 1 of 180). **The roadmap M0–M8 is complete; one calendar item open: the 30-day review itself, ~2026-10-30** |
| Money at risk | **None, and the factory does not change that.** Deploy means `dry_run: true`. Live remains gated by Autotrader Plan §6 Phase 3, unchanged |
| Repo | **Public since 2026-09-30** with protected `main` (PRs need the code owner's review; externals get issues + PRs, never merge). History audited before the flip: no credential ever committed |
| This document | Moved into the repo (`docs/PLAN.md`) 2026-09-30, lightly redacted for the public record. **Next steps live in §17** |

**Decisions locked at creation:** home is `Projects/strategy-factory/` (§8); license MIT with freqtrade driven only across a process boundary (§8); repo starts private (§8); the deterministic spine is built before any LLM stage (§9). **§11's opens were answered by the user the same day** — see §11 for the record; the notable ones: the lab is absorbed, deploy targets **GCP**, the secondary data provider is **Kraken**, the starting budget is **US$100/month**, and **pushes are paused** — commits stay local, push only when the user says so.

---

## §1 Verdict first

1. **The factory is the Autotrader Plan's method, mechanized — not a new trading idea.** Five strategies went through the manual gauntlet in September 2026 and all five died at measurable gates. The factory's stages *are* that gauntlet: the §24.2 audit checklist as code, the screens as stage validators, pre-registration as a signed human gate. What it buys is cost-per-hypothesis: the manual loop takes about a day; the harness itself runs in ~15 minutes. The bottleneck it does **not** remove is idea quality (§10.1).
2. **A strategy factory is, by default, a multiple-comparisons machine.** Automating the search multiplies trials, and trials are exactly what inflate Sharpe and destroy holdouts (Plan §15, §17, §18.1). The design answer is structural, not aspirational: a **trial ledger** every run must write (making the trials-adjusted/deflated Sharpe computable, closing the gap §20 named), a **holdout lockout** where holdout data is physically not mounted without a signed spend approval (§6), and **pre-registration as a blocking human gate** before any fold runs (§3, HG1).
3. **The named risk is the family failure mode: this is the fifth plumbing project.** `CryptoAnalysis` → `trader` → `execution-trade`/`techanalysis` all died where plumbing met strategy (Plan §1). Countermeasures, all structural: freqtrade remains the engine, so the strategy/execution layers the previous four never finished **already exist**; M1 is a golden test against a recorded freqtrade-lab result, so the factory is verifiable from its first week (the Plan §5 coupling-artifact idea, reused); the regression fixtures are **the five dead strategies** — the factory must re-kill each one at the right stage for the right reason (§4); and M4 delivers **U1's purged, embargoed splitter**, which Plan §24 already designated as the next work. The factory path and the plan's path converge; this is not a fork.
4. **Deploy means dry-run.** Stage S6 puts freqtrade on a cloud box against Binance with `dry_run: true` and the observer watching. A live decision would still have to clear Phase 3's 30-day parity gate and is out of this document's scope, exactly as before.
5. **The orchestration design, distilled:** a staged pipeline of role-scoped agents, state-first orchestration (manifest-first here), deterministic per-stage validators, resume/replay from any stage — the patterns that make build pipelines auditable, applied to research. And one deliberate refusal: the orchestrator is a deterministic state machine, with LLMs only *inside* stages — an LLM meta-agent coordinator adds failure modes a personal system doesn't need (§2).

---

## §2 Design lineage — patterns adopted, patterns refused

Multi-agent build systems have converged on a recognizable shape: specialized worker agents arranged as a pipeline (research → design → implement → test → ship), durable per-run state, quality gates between stages, and the ability to resume or replay a run. The factory adopts that shape where it fits a one-user scientific workflow and refuses it where it does not:

| Established pattern | Factory adaptation |
|---|---|
| Pipeline of role-scoped worker agents, each with a restricted tool set | Same, but the roles are Research / Screen / Pre-register / Implement / Validate / Deploy / Observe (§3), and three of the transitions are human gates |
| DB-first: every stage reads/writes rows, the filesystem is a materialization | **Manifest-first:** every run is a directory `runs/<id>/` with `manifest.json` + artifacts; a SQLite index is derived, never authoritative. Right weight for one user, and it diffs in git |
| Per-stage validators (quality gates before the next stage starts) | The deterministic gates of §4 — except ours are *scientific* gates with measured provenance, not lint |
| Build manifests + replay-from-stage + resume | Same, verbatim. A run interrupted at S5 resumes at S5; a re-run from S4 with a changed input is a **new trial** and the ledger records it |
| An LLM meta-agent as orchestrator, coordinating the stages through its own tool calls | **Refused in favor of a deterministic state machine.** LLM judgment lives inside stages; sequencing, retries and gate arithmetic are plain code |
| Live progress narration to a web UI | A run log + generated Jupyter notebooks per gate (§3). No web UI in v1; FreqUI and the observer cover the deployed side |
| Multi-tenant service architecture (auth, k8s, a database server, a web IDE) | Not carried. One user, one machine, CLI first |

---

## §3 The pipeline — seven stages, three human gates

```
prompt ─► S0 Intake ─► S1 Research ─► S2 Screen ─► S3 Pre-register ─► S4 Implement ─► S5 Validate ─► S6 Deploy ─► S7 Observe
                                        │auto-kill      ▲ HG1                             ▲ HG2 (+HG2b)   ▲ HG3        │
                                        ▼               │ user signs                      │ user judges   │ user       ▼
                                     graveyard          │ the pre-reg                     │ the dossier   │ approves  feedback
```

Every stage has the same contract: it reads `manifest.json` and prior artifacts, writes its artifacts and a short report, appends to the trial ledger when it runs anything on data, and ends in `passed | killed | needs_human`. Deterministic gates decide transitions; LLM output never self-certifies.

| Stage | Kind | Does | Key artifact |
|---|---|---|---|
| **S0 Intake** | LLM | Prompt/description → structured **hypothesis card**: premise, edge source, universe, timeframe, intended holding period, parameter priors (a-priori, tuning is the enemy — Plan §15), provenance | `hypothesis.md` + `hypothesis.json` |
| **S1 Research** | LLM | Search **my materials first** — `Library/` (79 items, 8 shelves), Inventory §10 link shelf, the plan's own findings — then the web. Must check the card against the §20.4 anti-patterns and state what cost model the sources used (usually: none) | `research.md` with citations |
| **S2 Screen** | Deterministic | The cheap kills, in the order the plan learned them: **noise-floor check** (Plan §21), **3× cost rule** at the intended horizon (Plan §12/§14 R3), **factor screen with ORACLE/NOISE arms** if cross-sectional (Plan §22), **spread screen + random-entry controls** if spread-based (Plan §21). In-sample data only. *Most hypotheses should die here; that is the stage working* | `screen_report.md` |
| **S3 Pre-register** | LLM draft → **HG1** | Drafts a pre-registration in the §16 house format: fixed parameters, pass criteria (incl. G-passive in §23 form), protocol, trial budget, committed consequences. **The user signs it — nothing downstream runs without the signature** | `prereg.md` + `approvals/hg1.json` |
| **S4 Implement** | LLM + checks | freqtrade strategy class + config, materialized into the run dir and executed via `--strategy-path` — never copied into the lab's strategies folder (the leftover-`.json` gotcha, lab README §7.2). Static checks, a smoke backtest on a small IS window, `lookahead-analysis` where valid (it can't judge cross-sectional strategies — Plan §14 Am.1), plus a generated causal test in the style of `test_xs_causal.py` | `strategy.py`, `config.json`, `impl_report.md` |
| **S5 Validate** | Deterministic | The full gauntlet on IS folds: **purged, embargoed walk-forward** (U1 — built at M4), control arms (untuned defaults *and* exposure-scaled passive), cost sweep, robustness grid, tear sheet with G-passive (§23 form) and **deflated Sharpe from the trial ledger**. Cross-provider data-integrity audit (§6). Emits a **validation dossier** and a parameterized review notebook → **HG2**: the user judges. Holdout spend is a *separate* signature (**HG2b**) checked against the holdout ledger | `dossier/`, `review.ipynb` |
| **S6 Deploy** | Deterministic + **HG3** | Docker compose to a cloud VM: freqtrade `dry_run: true` on Binance, FreqUI bound locally, observer alongside, secrets only via env (`FREQTRADE__EXCHANGE__KEY` pattern — nothing in the tree, the 2020 lesson). Target: the 30-day dry-run, which is also the best holdout available (Plan §18.2) | `deploy/` compose + runbook |
| **S7 Observe** | Service | Poll the freqtrade REST API (state, open trades, orders, balance, whitelist) → append-only snapshots; daily `parity.py` dry-run-vs-backtest comparison; drift/error alerts to Telegram; an observation notebook over the same data. Its parity verdicts feed back into the run's manifest | snapshots + `parity_report.md` |

**Human gates are signatures, not vibes.** `factory approve <run> hg1` records who/when/what-hash into `approvals/`; the orchestrator refuses to advance a stage whose upstream artifacts changed after signing (hash mismatch = re-approve). Each gate has a generated notebook as its reviewing surface — the tear sheet made §17's G5 failure legible as a picture, and that is the standard for what a gate review should look like.

## §4 The gates are §24.2 in code — and the graveyard is the test suite

Every automated gate exists because this project measured something in September 2026. Each ships with a regression fixture: **the factory must re-kill every strategy the manual process killed, at the right stage, for the right reason.** That is the acceptance test for M2/M4 — five dead strategies as ground truth is the one asset a from-scratch factory would not have.

| Gate | Provenance | Fixture that must fail it |
|---|---|---|
| Noise floor: per-trade sd vs gate, trades available vs trades needed | Plan §21 (sd ≈ 15 pp vs 0.6 % gate; needs ~2,400 trades, history supplies ~90) | **H4** dies at S2 |
| 3× round-trip cost coverage at intended horizon | Plan §12 (2020: +0.0837 %/trade gross vs 0.1556 % cost), §14 R3 | **H2 `TrendVolTarget`** (−0.04× coverage) |
| Factor screen: IC per horizon w/ t-stats, quintiles, turnover, ORACLE + NOISE arms | Plan §22 (H1/H3 factor: IC negative 9 of 9 horizons) | **H1/H3 factor** flagged before any fold |
| Control arm: candidate must beat its own untuned defaults | Plan §15 (tuned H1 lost in 6 of 7 folds) | **H1 tuned** |
| G-passive, §23 form: exposure-scaled, Sharpe-reported, split by rising/falling windows | Plan §23 (books run ~9 % exposure, β ≈ 0) | **H3** 5-year: Sharpe 0.81 vs 1.64 |
| Concentration (G5) at tear-sheet level — *not screenable in-sample, so it lives at S5, never S2* | Plan §17/§22 (September = 78 % of H3's profit; the screen provably cannot see it) | **H3** holdout |
| Zero-fee sanity: negative at zero cost = no signal at all | Plan §12 | **`Strategy005`** (−49.55 % at zero fees) |
| Deflated / trials-adjusted Sharpe from the ledger | Plan §20/§24 named the gap; López de Prado ch. 11–12 | New — no fixture yet; calibrate at M4 |
| Data integrity: gaps, duplicates, cross-provider deviation bands | New (§6) | Synthetic corruption fixtures |

## §5 Architecture and components

**Deterministic core, LLM edges.** The orchestrator is a plain state machine over manifests; Claude Agent SDK sessions run inside S0/S1/S3-draft/S4 with stage-scoped prompts and tool allowlists (the role-scoped worker pattern of §2). Everything S2/S5 computes is a library function with a unit test.

```
strategy-factory/
├── factory/               # the package
│   ├── orchestrator/      # state machine, manifest schema, approvals, resume/replay
│   ├── stages/            # S0–S7; LLM stages via Claude Agent SDK, prompts in prompts/
│   ├── gates/             # §4 as pure functions: noise_floor, cost_rule, factor_screen wrap, gpassive, dsr
│   ├── engine/            # freqtrade adapter: wraps the lab's docker images + wf/ harness, --strategy-path
│   ├── datafeed/          # providers (binance via freqtrade, secondary via ccxt), integrity, partitioned store
│   ├── ledgers/           # holdout ledger, trial ledger (append-only)
│   └── observer/          # S7 service
├── notebooks/             # papermill templates: prereg_review, validation_review, deploy_review, observe
├── runs/                  # manifest-first state, one dir per run (gitignored artifacts, manifests tracked)
├── fixtures/              # the graveyard: recorded numbers for the five dead strategies + H4
├── deploy/                # compose files, VM runbook
└── docs/DESIGN.md         # the buildable spec (self-contained; this file holds the decisions)
```

Tech: **Python 3.12 + uv** (uv is not yet installed — M1 prerequisite), **Claude Agent SDK** for LLM stages, **papermill** for gate notebooks, **SQLite** as derived index only, docker throughout for the engine. CLI verbs, freqtrade-style: `factory new "<idea>"`, `factory run <id> [--to S5]`, `factory approve <id> <gate>`, `factory status`, `factory replay <id> --from S4`.

**The lab is the engine room, not a dependency to rebuild — and since 2026-09-29 it lives in-repo as `lab/`** (user decision, formerly §11e; the deferral argument fell because the Plan's §12–§24 references were simply repointed the same day). The factory invokes its docker images (`freqtrade-lab:2026.8` for backtests, `:2026.8-research` for the screen/tear-sheet scripts — never mixed, the pandas gotcha) and its `wf/` scripts, and materializes strategies into `runs/<id>/` mounted via `--strategy-path`, never writing into the lab's tree.

## §6 Data — providers, partitions, ledgers

- **Primary:** Binance OHLCV via `./ft download-data` (already ~75 MB in `~/freqtrade-data/`, outside Dropbox, regenerable in ~60 s). The factory's store keeps that convention: bulk data never in Dropbox, never in git.
- **Secondary provider for validation, not for backtesting:** **Kraken** via ccxt (user decision 2026-09-29, was §11d). Cross-provider checks are **bands, not equality** — prices legitimately differ across venues; what the audit catches is gaps, duplicate/missing candles, zero-volume stretches, and deviations beyond a tolerance that flag bad files. (Polygon.io is not a candidate: no key of our own.)
- **Holdout lockout, physical:** the store is partitioned into `research/` and `holdout/` date ranges per §18.2's ledger (2019–2020 untouched; 2021–2025 folds spent; 2026 spent). Research invocations mount only `research/`; mounting `holdout/` requires an HG2b approval token, and the spend is written to the holdout ledger permanently. Calendar accrual gets recorded too: e.g. Oct 2026 → Mar 2027 becomes a new holdout entry once it exists.
- **Trial ledger:** append-only `trials.jsonl` — every backtest, hyperopt, screen and re-run, with config hash and outcome. This is what makes the deflated Sharpe honest, and it is deliberately humiliating: the count only goes up.

## §7 Deployment and observation

- **Where:** **GCP** (user decision 2026-09-29, was §11c) — an e2-small-class VM. Docker compose: `freqtrade` (dry-run, Binance), `freqtrade-ui` (bound to localhost, reached over SSH tunnel or tailscale), `observer`.
- **Secrets:** env-only (`FREQTRADE__EXCHANGE__KEY/__SECRET`), no tracked file ever holds one; dry-run against public endpoints needs no key at all. This repo exists partly *because* a 2020 predecessor workspace committed live keys — the factory never gets the chance.
- **Observer (S7):** a small poller on freqtrade's REST API → append-only parquet snapshots of state, open trades, orders, balances; daily `parity.py` run comparing the dry-run sqlite against the reference backtest (the Phase 3 gate (d) method — written 2026-09-28, never yet used, finally earning its keep); Telegram alerts on error states, drift beyond bands, or silence. Observation notebook over the snapshots for the human. Grafana/Prometheus deferred until the poller proves insufficient.

## §8 Where it lives, license, GitHub

- **Home: `Projects/strategy-factory/`** — the Inventory's run-or-read rule puts runnable own-code in `Projects/` (its catalogue entry: Inventory §3.6). Sibling of `freqtrade-lab/`, same Dropbox caveats (data out of sync, `.gitignore`d byproducts still sync — keep artifacts lean).
- **License: MIT.** The factory drives freqtrade strictly across a process boundary (docker CLI), copying nothing — the Plan §4 licensing tactic. Generated strategies execute inside freqtrade's GPL process but are our original files; they stay in this repo.
- **GitHub: `pedraumcosta/strategy-factory`, private at creation** (2026-09-29). Private because trading configs and run artifacts will accumulate and because the 2020 lesson says history hygiene precedes visibility; flipping public later is one setting plus a history audit. Meaningful commits per milestone task — the roadmap below is written to be committable step by step. **Push policy since 2026-09-29: local commits only; push happens when the user asks, not per milestone.**

## §9 Roadmap — milestones sized to commits

Deterministic spine first, LLM stages after — the temptation is to start with the agents; the value is in the gates.

| M | Delivers | Done when |
|---|---|---|
| **M0** | Repo scaffold: README, DESIGN.md, license, gitignore; pushed private | **Done 2026-09-29** (M1–M3 also done same day — see §0; commits local, unpushed per §11a) |
| **M1** | Engine adapter + **golden test**: factory reruns the reference backtest (fixed strategy/window/fee, `--cache none`) through the lab image and matches a recorded result exactly — trade count, timestamps, P&L | **Done 2026-09-29** — 1,028-trade reference, exact, ~7 s |
| **M2** | `gates/` as library functions + **the graveyard fixtures**: noise floor, cost rule, zero-fee sanity, factor-screen wrapper; recorded numbers for Strategy005/H1/H2/H4 | **Done 2026-09-29** — every corpse re-killed; ORACLE passes / NOISE fails |
| **M3** | Orchestrator: manifest schema, state machine, resume/replay, approvals with artifact hashes, trial + holdout ledgers seeded from Plan §18.2 | **Done 2026-09-29** — all refusal paths tested |
| **M4** | **U1 delivered:** purged, embargoed walk-forward splitter + deflated Sharpe from the ledger; S5 assembled (controls, cost sweep, tear sheet, dossier, review notebook) | **Done 2026-09-29** — exact §15 reproduction; delta documented in **§12** |
| **M5** | LLM stages S0/S1/S3-draft/S4 via Claude Agent SDK; prompt library; HG1 flow end-to-end | **Done 2026-09-29** — toy run signed through S4; a sibling toy correctly killed at S2 (§13) |
| **M6** | **Full-pipeline rehearsal** on a deliberately mediocre idea; success = a correct, cheap kill with a legible report | **Done 2026-09-30** — two kills, one at S2 in seconds, one at HG2 with a three-count dossier (§14) |
| **M7** | S6 deploy: VM, compose, secrets runbook, dry-run up; S7 observer polling + parity + alerts | **Done 2026-09-30** — rehearsed locally, then live on GCP (§15, §15.1) |
| **M8** | Observation notebooks, 30-day dry-run review flow, calendar-holdout accrual; revisit §11 opens | **Done 2026-09-30** — flow built, tested, day-1 accrual live; the 30-day review itself is a calendar item (~2026-10-30, §16) |

## §10 Honest caveats

1. **The factory does not refill the idea well.** Phase 2 paused because ideas ran out, not because testing was slow. S1 industrializes the reading (the Library and §10-shelf digestion is real leverage), but Track 3 against primary sources remains the designated source of hypotheses. A faster gauntlet with weak inputs just fills a graveyard faster — acceptable, cheap, but not progress by itself.
2. **Concentration is not screenable** (Plan §22 proved it): G5-style failures surface only at the tear sheet. The factory inherits that limit; S2 cannot promise that S5 won't kill.
3. **LLM-written strategies are a lookahead risk.** `lookahead-analysis` is blind to cross-sectional designs and cross-contaminates in list mode (lab README §7.6–7.7). Mitigations: per-strategy runs, a generated causal test per implementation, and the human actually reading the code at HG1/HG2. The five fixtures also guard the *gates*; nothing yet guards a novel biased indicator except those tests and the reviewer.
4. **Cost discipline applies to the factory itself:** API tokens per run, a VM invoice, and the temptation to run S2 in bulk. The trial ledger doubles as the odometer.
5. **Dropbox + git dual-sync** — same caveats as the lab: artifacts under `runs/` must stay lean, bulk outputs go outside Dropbox, and `.gitignore` does not stop Dropbox syncing.

## §11 Decisions — all answered by the user, 2026-09-29

- **(a) Repo visibility / pushing** — stays private; **pushes are paused**: commits stay local, milestone pushes stop, push only when the user says "push". (A public flip would still trigger a history audit first.)
- **(b) Name** — `strategy-factory`, confirmed.
- **(c) Cloud provider** — **GCP**.
- **(d) Secondary data provider** — **Kraken** via ccxt.
- **(e) Absorb the lab** — **yes, done the same day**: `lab/` in-repo, references repointed (§5).
- **(f) Budget** — **US$100/month to start**; the trial-ledger odometer alarms against it.

## §12 M4 executed — the re-judge under the purged splitter (2026-09-29)

U1's deliverable exists: `factory/validation/splitter.py` (purge + embargo, both asserted) and `factory/validation/dsr.py` (PSR/DSR, stdlib-only, with a best-of-50-coin-flips calibration test that must NOT clear its own benchmark). S5 is assembled and was run for real against H3 — 20 backtests, all on spent windows, everything on the trial ledger. Evidence: `runs/20260929-211355-m4-acceptance-re-judge/artifacts/` (dossier + comparison force-committed).

1. **The factory reproduces the manual process exactly.** All seven §15 control-column OOS folds to the last digit; mean +7.40 %, 4/7 positive. The machinery is now validated against the recorded record, not against itself.
2. **H3's rejection survives U1 unchanged — by construction.** For a fixed-parameter candidate the purged splitter leaves the OOS windows identical, so nothing about H3's numbers moves. Its G5 failure was never a splitter artifact.
3. **The purge matters for tuned pipelines, and now there is a number.** With purge = 87 days (max observed hold 86 d in the 1,028-trade reference), 12–22 % of each fold's in-sample trades open inside the purge zone — labels formed at the boundary that a hyperopt objective was allowed to fit. In fold 4 the zone held **89 % of the fold's P&L** (+333.5 of +375.7). Every §13/§15 hyperopt result was fitted on that contaminated margin.
4. **A finding the embargo check surfaced: the recorded rolling folds violate any embargo ≥ 1 day.** Folds 5–7 begin training exactly one day after folds 1–3's test windows end. Post-hoc iteration on early-fold OOS results therefore leaked into later folds' training data. `wf/run.sh`'s splitter fails U1 on both axes, as §24 suspected.
5. **The deflated Sharpe is devastating and convergent.** H3's five-year SR is 0.77 annualized (365-day, from the wallet mark-to-market curve; §23's tear sheet recorded 0.81 on its own reconstruction — same conclusion, slightly different equity granularity). Deflated against the **24 comparable-basis trials** on the ledger (same timeframe, ≥ 300-day window, finite SR — out of 296 ledger entries; hyperopt epochs still uncounted), **DSR = 0.036**: a 3.6 % probability the true SR beats the best-of-noise benchmark. §23's G-passive reached the same verdict (0.81 vs the universe's 1.64) from an entirely independent argument. Two instruments, one reading.
6. **S5 correctly refuses to be the judge.** Deterministic gates passed (zero-fee +57.8 %; cost coverage 6.14× on the per-trade-on-stake basis — §15's 7.61× was a different edge basis, same conclusion) and the stage ended `needs_human`, because G5 concentration is tear-sheet-level and not gate-detectable, exactly as §10.2 warned. The review notebook executed and is the HG2 surface.

**Corrections recorded on the way** (each now a fixture or a comment in code): freqtrade's wallet export is per-currency long format — the equity curve is `total_quote` summed by date; the 3× cost rule's basis is per-trade return *on stake* (`profit_mean`), not profit over total capital, which understates coverage ~22×; and a DSR deflation family must exclude incomparable trials — the raw ledger's SR variance was 39.4 with a −100 sentinel inside, which would have made SR0 meaningless.

**What M4 bought beyond U1:** the §24.2 checklist questions on trials ("how many things were tried?") and on the splitter now have living machinery behind them, and any future S5 dossier carries a DSR with an auditable N. **Next: M5**, the LLM stages, per §9.

## §13 M5 executed — real agents, and the gates bit on day one (2026-09-29)

The four LLM stages run on the Claude Agent SDK (headless, `bypassPermissions`, per-stage tool allowlists with no Bash anywhere); every agent call lands on the trial ledger with its dollar cost, so `factory ledger` reads the odometer against §11f's US$100/month. The acceptance was run twice, for the best possible reason:

1. **Run 1 (Donchian breakout, 5 pairs) — correctly killed at S2.** Told to anchor on the lab's measured priors, the intake agent chose *more conservative* estimates than prompted (sd 8 %, 260 trades for the smaller universe) and the noise-floor gate killed the card: needs ≥ 683 trades, history supplies 260. The first real run through the factory died the way §21 says untestable designs should. Much of M6's rehearsal is therefore already demonstrated.
2. **Run 2 (same idea, honestly resized to the 17-pair universe) — the full path.** Card → 13 KB research memo → screens pass (noise floor 1,200 vs 267 needed; coverage 5×) → pre-registration drafted — including a tripwire the agent added itself: *any realized hold > 30 days fails the run on protocol and may not be re-run with a larger purge under this signature* → blocked at HG1 → signed (recorded as an operator-signed method-validation toy, not a research decision) → acknowledged → `DonchianBreakout17.py` implemented clean (positive shift only, frozen constants, ROI ladder disabled) → static causality checks → real smoke backtest, 55 trades. Evidence committed under `runs/`.
3. **Two factory defects were caught by the factory's own refusals, and fixed.** (a) A stage that ends `needs_human` used to stay runnable, so the runner re-ran it forever — caught as a 24-CPU-minute pytest spin; `needs_human` is now blocking, and the `factory approve` signature is the transition that clears it. (b) The first S4 implementation set market `order_types` and freqtrade refused under the lab config's `price_side` (lab README §3's gotcha) — execution pricing is now banned from strategies by prompt *and* static check, and the M3-promised **replay-from-stage** was built to rerun S4 (`factory replay --from S4`); the HG1 signature survived the replay precisely because its hashed artifacts were untouched.

**Cost of the whole acceptance: US$6.39** (7 agent calls, itemized). The toy run deliberately stops before S5 — spending seven fold backtests on a method toy would be noise on the ledger; the S5-included rehearsal is M6's remaining work, on a hypothesis chosen for the purpose.

## §14 M6 executed — the rehearsal, and the toy died the instructive way (2026-09-30)

The signed toy (`DonchianBreakout17`, §13 run 2) went through the assembled S5: seven purged OOS folds, the cost sweep, the full-range run with DSR, ~13 more backtests on the ledger, all on spent windows. The dossier gained two protocol-checkable facts on the way: **max realized hold** and **monthly concentration** — both existed only as prose criteria before.

**The deterministic gates passed and the human review killed it anyway — which is the design, not a contradiction.** The numbers looked genuinely tempting: zero-fee +99.8 %, cost coverage 24×, OOS mean +5.18 % with 5/7 folds positive, annualized SR 1.02. The dossier then handed HG2 three clean counts:

1. **Protocol, by its own signature:** max realized hold **107 days** against the prereg's self-imposed tripwire (*any hold > 30 days fails the run on protocol; no re-run with a larger purge under this signature*). One 2021 bull-run position that the 5-day-low channel never broke — and it means the 30-day purge was undersized, so even the OOS table above is tainted. The agent-drafted tripwire turned out to be the sharpest criterion in the document.
2. **G-conc:** best month (2021-03) carries **48 %** of total profit vs the 40 % ceiling — §17's failure mode, which the deterministic gates provably cannot see (§22); skew +3.7 and kurtosis 72 say the same thing.
3. **G-dsr:** deflated Sharpe **0.091** vs the pre-registered 0.5 floor, within the 24-trial comparable family.

The kill is recorded in the manifest by the new **`factory reject <run> S5 --notes …`** verb — the missing half of the human gate (approve/reject now pair). The full arc M6 asked for exists twice over: §13's run 1 died at S2 in seconds for ~$1; run 2 died at HG2 with a dossier that leaves no confusion about why. **A lesson worth keeping:** purge sizing from *typical* hold is dangerous — condition-based exits have unbounded tails; size purges from the realized **maximum**, which the dossier now always reports.

**Next: M7** — deploy (GCP, dry-run, observer), which needs a strategy that has *earned* S6 or an explicitly-labeled rehearsal deployment; and the §9 table's remaining rows.

## §15 M7 executed — the deploy/observe loop, proven on this machine first (2026-09-30)

`deploy/` holds the whole S6 stack as three compose services, and the rehearsal ran it live locally with the killed toy strategy (its file carries a banner saying exactly that; a real deployment replaces `strategy/` with a gate-passed artifact and needs a signed HG3):

- **freqtrade** — dry-run against Binance public data, no exchange keys anywhere in the stack; FreqUI/API on `127.0.0.1:8080` only. The rehearsal bot runs 17 pairs on a US$2,000 dry wallet.
- **observer** (S7) — `factory/observer/poller.py`, stdlib-only, snapshots state/trades/profit/balance to append-only JSONL every 5 minutes and alerts (Telegram, env-configured) when the API is unreachable or the bot is not running. **The alert path fired for real** during the rehearsal — the first poll landed while freqtrade was still booting. Failures are written as snapshots too: silence never looks like success.
- **parity** — the Plan §6 Phase-3 gate (d) as a daily loop: download recent candles, backtest the elapsed dry-run window with the same strategy, compare trade-for-trade against the dry-run DB (`factory/observer/parity.py`, sqlite+zip, entry-day matching ±1 day), write `parity_report.md`. Day-0 is degenerate by construction (nothing survives startup candles) and now writes an honest day-0 report; the full compare path was exercised against a data-bearing window — 17 backtest entries vs 0 dry-run trades, every mismatch listed.

**Deliberately not executed: the VM.** `deploy/gcp/provision.sh` is one command (e2-small ≈ US$13/month against the §11f budget, Debian + docker, no public ports, FreqUI via SSH tunnel, secrets generated on the box). The machine had two credentialed gcloud accounts and **which project pays for a personal trading VM is not the factory's decision.** When the user names the project: `PROJECT=<id> bash deploy/gcp/provision.sh`.

The local rehearsal stack was torn down once the VM took over. One ops note that survives it: the parity service's backtests disable the API server via env, or the shared config's placeholder JWT fails freqtrade's schema validation.

### §15.1 The VM, live — and three ops lessons (2026-09-30)

**`factory-dryrun`** — e2-small, `europe-west1-b`, ≈ US$13/month against §11f's budget. State at hand-off: bot `factory-rehearsal` running `DonchianBreakout17` dry-run on 17 pairs with a US$2,000 paper wallet, observer snapshotting healthy every 5 minutes, parity loop writing its (day-0) report daily. No public ports; no exchange keys on the box; secrets generated on the box into its own `.env`.

- **FreqUI:** `gcloud compute ssh factory-dryrun --project=$PROJECT --zone=europe-west1-b -- -N -L 8080:localhost:8080` → http://127.0.0.1:8080 (user `freqtrader`; password: `cat ~/factory-deploy/deploy/.env` on the box).
- **Watch:** same ssh with `--command='tail -f factory-deploy/deploy/observer_data/snapshots.jsonl'`; parity: `cat factory-deploy/deploy/observer_data/parity_report.md`.
- **Stop the meter:** `gcloud compute instances delete factory-dryrun --project=$PROJECT --zone=europe-west1-b`.

Three failures found live, each fixed and baked into `provision.sh`: (1) **Binance geo-blocks US IPs** — the first VM, in `us-central1`, died with HTTP 451 on `exchangeInfo`; deleted, recreated in Belgium, and the script's default zone now says why. (2) **`docker-compose-v2` is not a Debian 12 package** — the startup script silently lost docker entirely; it now installs `docker.io` plus the compose v2 plugin binary, and the setup step waits for docker before proceeding. (3) **A root-created `observer_data/` is unwritable for freqtrade's `ftuser` (uid 1000)** — the local rehearsal masked it because the host uid happened to be 1000; provision now pre-creates the directory chowned.

## §16 M8 executed — the roadmap closes; what remains is calendar time (2026-09-30)

The last milestone built the review half of the observe loop and mechanized §18.2's calendar rule:

- **`factory dryrun-review <dir>`** turns fetched VM artifacts (`tools/fetch_dryrun.sh`: snapshots, dry-run DB, parity report) into `review.md`: uptime and alert counts, bot states seen, trade statistics, the latest parity report — labeled **interim** until 30 observed days, then **HG3 evidence**. It says out loud what it cannot say: dry-run measures execution reality, never edge.
- **Calendar-holdout accrual** — every review ticks `holdout.accrue()`: the window since 2026-09-29 (the day after H3 spent 2026) accrues on the ledger, matures into a *clean* window at 180 days, stays HG2b-gated like any holdout, and a new accrual starts behind it. As of today: **day 1 of 180**.
- **§11 revisited, all closed but one habit:** name kept; GCP live (§15.1); Kraken still the S5 integrity provider (exercised when a real candidate reaches S5); budget odometer live (`factory ledger`: ≈ US$6.5 LLM + the VM's ≈ US$13/month); **pushes remain paused — 14 local commits await the user's "push"** (origin still holds only M0).

**The M0–M8 roadmap is complete, one day after the pivot was an idea in a prompt.** What the factory now is: a pipeline that researched, screened, pre-registered, implemented, validated, deployed and observes strategies; whose gates re-kill every corpse in the graveyard for its documented reason; whose human gates are signatures over artifact hashes, with approve and reject both on the record; whose holdouts are physically ledgered and now accrue with the calendar; and whose only live strategy is a loudly-bannered rehearsal toy on a dry-run box in Belgium.

**Open items, none of them code:** (a) ~~gcloud reauth~~ — **done the same day; the first live review ran: 97.6 % uptime over 42 snapshots, 0 trades yet, accrual day 1** (fetch+review commands: `PROJECT=$PROJECT ZONE=europe-west1-b bash tools/fetch_dryrun.sh` then `factory dryrun-review runs/dryrun-review-<date>`); (b) **the 30-day review, ~2026-10-30** — the first HG3-grade judgment conducted through the factory; (c) the push decision; (d) the next *real* hypothesis, which still comes from Track 3 reading (§10.1 has not moved: the factory lowers the cost per idea; it does not supply ideas).

## §17 Next steps (written 2026-09-30, the day the roadmap closed)

### Calendar

| When | What |
|---|---|
| **~2026-10-30** | **The 30-day dry-run review** — the first HG3-grade judgment conducted through the factory: `PROJECT=$PROJECT ZONE=europe-west1-b bash tools/fetch_dryrun.sh`, then `factory dryrun-review runs/dryrun-review-<date>`. Until then the daily parity reports accumulate on the box |
| **~2027-03-28** | The calendar-accrued holdout matures (180 days from 2026-09-29). It becomes *clean*, not *free*: spending it still takes a pre-registration and a signed HG2b |
| Continuous | The next real hypothesis. The factory did not change where ideas come from (§10.1): reading, then `factory new` |

### Research topics

1. **Claude Code skills that mimic the factory for an engineer.** The factory's discipline lives in its orchestrator; an engineer working in a plain Claude Code session has none of it. Package the conventions as skills — the gauntlet order, the pre-registration format, the gate library (`factory.gates`) invoked as slash-commands, the trial/holdout ledger discipline as guardrails — so a session *behaves like the factory* without running it. Acceptance test, in this repo's spirit: an engineer driving only the skills must reach the same verdicts on the graveyard fixtures, for the same reasons.
2. **Jev (TypeSafe AI's "System One" models).** Released 2026-09-15: models that return **typed values with probability and confidence scores** instead of text, built for classify / route / score / extract / branch decisions, claimed ~200× faster and cheaper than LLMs on those tasks. That contract matches the factory's non-generative decision points exactly — S0 card field extraction, S2 screen routing, report classification, observer anomaly triage — places where an LLM is currently overkill and a typed answer with a confidence is precisely what the manifest wants. Spike: put one decision point behind an interface, swap LLM→Jev, compare verdicts, latency and cost on the graveyard fixtures; validate the vendor claims rather than repeating them.
3. **Cache solutions for the factory — candidate: [Headroom](https://github.com/headroomlabs-ai/headroom).** Two distinct cache problems live here. (a) **LLM context**: S1 reads large materials, S5 reviews fat dossiers and JSON exports — Headroom (open-source, ~19k stars) compresses tool outputs/logs/RAG chunks 20–95 % before they reach the model, keeps originals retrievable (CCR), and avoids busting provider KV-cache prefixes (CacheAligner). The odometer makes the evaluation honest: measure `factory ledger` cost per stage before/after, since compression that breaks cache reuse can *raise* a bill. (b) **Engine results**: identical backtests (same strategy hash + config + timerange + fee + data version) are re-run today by design — a result cache keyed on that tuple could cut fold reruns, but it must not soften the `--cache none` correctness rule that the lab adopted for a reason; cache only on exact content hashes, never on "close enough".
4. **Carry-overs from the build**, in rough order of value: tear-sheet/G-passive integration into the S5 dossier (today it needs the lab's research image run by hand); a factor-screen wrapper for arbitrary ranking factors (M2 wired the judge, not the generator); the Kraken integrity audit exercised end-to-end when a real candidate reaches S5; and the `enforce_admins` question — whether the owner, too, should be forced through PRs.
