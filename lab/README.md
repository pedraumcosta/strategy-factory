# freqtrade-lab

A freqtrade 2026.8 research workspace, built 2026-09-28/29 to restart a crypto trading practice that
had been dormant since 2020. **Absorbed into the `strategy-factory` repo as `lab/` on 2026-09-29** —
it is the factory's engine room: the factory invokes the docker images and `wf/` harness described
here, and materializes generated strategies via `--strategy-path` without writing into this tree.

> **No money has ever been at risk from this workspace.** Every config is `dry_run: true`, and nothing
> has passed the research gate. `./ft trade` has never been run. Do not run it — see **Hard rules**.

**Companion documents,** in the `TechTrading/` knowledge folder three levels up (not in this repo):
`Autotrader Plan.md` is the canonical record of the strategy, the full results and every decision —
the section numbers below (§0, §12–§18) point into it — and `Strategy Factory Plan.md` is the
steering doc for the factory around this lab. This README covers *how the lab works*; the plans cover
*what was found and why*.

---

## 1. Quick start

```bash
./ft --version                     # freqtrade 2026.8 in docker, running as your uid
./ft list-strategies
./ft backtesting --config user_data/config.json --strategy XSMomentum \
     --timeframe 1d --timerange 20210101-20260101 --fee 0.001 --cache none
```

`ft` is a one-file docker wrapper. There is nothing to install beyond Docker — no Python env, no
TA-Lib build. It runs `freqtrade-lab:2026.8`, built from `Dockerfile` (the official image plus
`statsmodels`, which `Strategy005` needs and the official image omits).

If the image is missing: `docker build -t freqtrade-lab:2026.8 .`

## 2. Where files live, and why it looks odd

Two locations, deliberately:

| Location | Holds | In Dropbox? |
|---|---|---|
| `./` (this folder) | wrapper, Dockerfile, configs, strategies, research harness, backtest exports | **yes** — worth backing up |
| `~/freqtrade-data/` | OHLCV price data (~75 MB of feather files) | **no** |

`ft` bind-mounts them together so that *inside the container* everything is at the normal
`user_data/data` path:

```
-v "$LAB/user_data:/freqtrade/user_data"
-v "$HOME/freqtrade-data:/freqtrade/user_data/data"
```

Price data is bulk, regenerable in ~60 s (`./ft download-data`), and grows fast, so it is kept out of
file sync. **Moving this folder to another machine therefore needs a re-download**, not a copy.

⚠️ `user_data/hyperopt_results/` currently holds ~1.5 GB of `.fthypt` per-epoch dumps. `.gitignore`
excludes them from git but **Dropbox does not read `.gitignore`**, so they sync. They are regenerable
byproduct; the results are in the plan and the chosen parameters in `wf/*-params.json`.

## 3. The configs

Seven, because different commands need different settings. `config.json` is the one you want.

| File | Purpose |
|---|---|
| **`config.json`** | The working config. 17 USDT pairs, `dry_run: true`, `StaticPairList`. Start here. |
| `config-2020repro.json` | Reproduces the Sep 2020 backtest exactly: BTC-quoted, 23 pairs, `allow_inactive` (13 are delisted), `max_open_trades: 15`. Verified to still give 1,098 trades / 14:22:00 avg hold. Do not edit. |
| `config-dryrun.json` | Paper trading. `dry_run: true`, local FreqUI on 127.0.0.1:8080. No credentials block. |
| `config-lookahead.json` | `lookahead-analysis` only — it forces market orders, which require `price_side: "other"`. |
| `config-pairlist.json` | Regenerates the universe: `VolumePairList` + Age/Precision/Price/Spread filters. |
| `config-barrier.json` | Scratch, from the symmetric-barrier experiment (§14). Disposable. |
| `config-private.example.json` | Template for credentials. **The real one is gitignored and does not exist** — no API key has ever been stored here. Alternatively use `FREQTRADE__EXCHANGE__KEY` / `__SECRET` env vars. |

## 4. The strategies

**Tested and rejected** — all five, each for a different diagnosed reason (plan §13, §15, §17):

| File | What it is | Verdict |
|---|---|---|
| `Strategy005.py` | The bot that traded live in Sep 2020. Mean reversion. | **No edge** — negative at *zero* fees, at every exit geometry |
| `Strategy005v0.py` | Its pre-`slope` version, recovered from git commit `15feee8`. This is the one that reproduces the 2020 backtest. | Used as the fixed-rule control |
| `BBRSIStrategy.py` | Bollinger mean reversion. Rewritten 2026-09-28 from a legacy `IHyperOpt` file into hyperoptable parameters. | **Overfit** — lost to a zero-parameter control |
| `TrendVolTarget.py` | 4h Donchian breakout, ATR trailing stop, vol-targeted sizing. | **No gross edge** at defaults (−0.04× cost coverage) |
| `XSMomentum.py` | Daily cross-sectional momentum. The best result the project produced. | **Passed 5 of 6 criteria, failed on return concentration** |

**Exploratory probes** — kept as evidence, not candidates: `TrendBaseline.py` (1h), `Trend4h.py`,
`TrendDaily.py`, `XSControl.py` (the no-cross-pair control that proved the lookahead flag was a false
positive). `Strategy001/002`, `sample_strategy` are stock freqtrade, untested.

`user_data/strategies_orig_updater/` holds the **untouched 2020 V2 originals** from `strategy-updater`.

## 5. The research harness (`wf/`)

| Script | Does |
|---|---|
| `run.sh` | 7-fold walk-forward: hyperopt in-sample → evaluate out-of-sample → fixed-rule control |
| `run2.sh` / `run3.sh` | Same for the §14 candidates (`run3` re-ran XSMomentum with the correct `--spaces buy`) |
| `h3_grid.sh` | Parameter-robustness grid — 20 combinations × 7 folds |
| `cost_sweep.sh` | Fee sensitivity 0 → 0.3 %/side. **Separates "bad signal" from "good signal eaten by costs"** |
| `summarise.py` / `summarise2.py` | Map exports onto folds, print the IS-vs-OOS table |
| `parity.py` | Compares a dry-run sqlite against a backtest export — the Phase 3 gate (d) method. **Written, never used** |
| `spread_screen.py` | **Pre-backtest screen** for a mean-reversion hypothesis on BTC-quoted crosses: causal Kalman residual, per-fold ADF + Engle-Granger, gross % per round trip against the 3× cost gate. In-sample folds only. Run: `docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/user_data:/freqtrade/user_data" -v "$HOME/freqtrade-data:/freqtrade/user_data/data" -v "$PWD/wf:/wf" --entrypoint python3 freqtrade-lab:2026.8 /wf/spread_screen.py` |
| `spread_control.py` | The controls that decide whether a screen result is real: matched-horizon drift, **matched-count random-entry band**, per-fold concentration. Same invocation. **Use it on any positive screen result** — it is what killed H4 |
| `factor_screen.py` | **Pre-fold factor screen** for any ranking signal: IC per horizon with t-stats, quintile forward returns, turnover — always run alongside an ORACLE (look-ahead) and NOISE arm so the numbers have a scale. Needs the **research** image |
| `factor_verify.py` | The three checks a screen verdict must survive: demeaned-vs-absolute, lag sensitivity, a 9-point horizon scan. Research image |
| `factor_portfolio.py` | Top-*k* equal-weight portfolio vs **equal-weight-all-17 passive control**. Research image. Note it is a FULLY-INVESTED comparison — for the implemented strategies use `tearsheet.py --gpassive` instead |
| `tearsheet.py` | **Per-candidate tear sheet from any backtest export** — mark-to-market equity vs benchmark, underwater plot, monthly bars, return concentration, plus pyfolio's stats. `--list` finds an export tag; **`--gpassive` re-judges every export ever written against the passive benchmark, exposure-scaled.** Reporting only, no gates. Research image |

Outputs land in `user_data/spread_screen.csv`, `spread_screen_beta.csv`, `spread_control.csv`,
`factor_screen.csv`, `factor_portfolio.csv`. The `--entrypoint python3` override is needed because the
image's entrypoint is `freqtrade`; `./ft` cannot run a plain script.

**Two images, and do not mix them up.** `freqtrade-lab:2026.8` runs backtests. `freqtrade-lab:2026.8-research`
(built from `Dockerfile.research`) adds `alphalens-reloaded` + `pyfolio-reloaded` for the four scripts above —
and **installing them downgrades pandas 3.0.5 → 2.3.3, so never run a backtest with the research image.**
The `factor_*` scripts import each other, so pass `-e PYTHONPATH=/wf`:

```
docker run --rm --user "$(id -u):$(id -g)" -e PYTHONPATH=/wf \
  -v "$PWD/user_data:/freqtrade/user_data" -v "$HOME/freqtrade-data:/freqtrade/user_data/data" \
  -v "$PWD/wf:/wf" --entrypoint python3 freqtrade-lab:2026.8-research /wf/factor_screen.py
```

Folds are defined in `user_data/notebooks/walkforward.json`.

## 6. Holdout status — read before any new backtest

A holdout is data that has never influenced a decision. **Its value is destroyed by looking at it.**
Plan §18 explains this in full.

| Window | Status |
|---|---|
| 2021-01-01 → 2025-12-31 | **Spent** — the seven walk-forward folds. The **in-sample halves** were re-used on 2026-09-29 for the H4 spread screen, which is legitimate: a screen on IS data spends nothing that was not already spent |
| 2026-01-01 → 2026-09-28 | **Spent** — H3's holdout, 2026-09-29 |
| **2019-01-01 → 2020-12-31** | **UNTOUCHED — the last clean window.** ~11–13 of the 17 pairs have data. Do not spend it without a written pre-registration |
| A 30-day dry-run | The best holdout available; adds real execution frictions |

## 7. Hard rules and gotchas

Each of these cost real debugging time. Several are silent failures.

1. **Never `./ft trade`.** Nothing has passed the gate. Read plan §6 Phase 0 first.
2. **`user_data/strategies/<Strategy>.json` silently overrides class defaults** on every backtest, and
   the summary does not mention it. The same command gave +4.34 % with a leftover file present and
   −28.62 % without. Treat it as part of the strategy; never leave one from an exploratory run.
3. **Config overrides strategy attributes.** `config.json` sets `stoploss: -0.10`, which beats the
   `-0.35` declared in `XSMomentum.py`. All recorded results used −0.10.
4. **`config.json` has `timeframe: 1h`**, a leftover — XSMomentum is 1d and TrendVolTarget is 4h. Always
   pass `--timeframe` explicitly.
5. **`--export-filename` is deprecated and ignored.** Exports land in `user_data/backtest_results/` as
   timestamped zips — which bundle the result, the config, the strategy source *and* the parameter file.
   Map them via `.meta.json`, never by filename order.
6. **`lookahead-analysis --strategy-list` cross-contaminates.** It attributed one strategy's biased
   indicator to two others that had no reference to it. Run one strategy at a time.
7. **`lookahead-analysis` cannot validate cross-sectional strategies.** It rebuilds the cross-section
   from untruncated data and reports a false positive. Proven by `XSControl` and by
   `user_data/notebooks/test_xs_causal.py` (0 differing cells in 39,848). Plan §14 Amendment 1.
8. **Hyperopt errors on an empty space but the surrounding loop carries on.** `--spaces buy sell` on a
   strategy with no sell parameters failed 7 folds silently and every "optimised" run used defaults.
   **Assert on artifacts, never on exit status.**
9. **13 of the 23 2020-era pairs are delisted.** Backtesting them needs
   `pairlists: [{"method": "StaticPairList", "allow_inactive": true}]`, or they vanish silently.
10. **`strategy-updater` migrates the freqtrade API, not the scientific stack.** statsmodels changed
    `results.params[-1]` from positional to label lookup; it now needs `.iloc[-1]`.

## 8. State as of 2026-09-29, and what is next

The research phase is **paused** (plan §18) — five strategies tested, five rejected, the 2026 holdout
spent, and cross-sectional momentum closed by prior commitment. **Paused because the ideas ran out, not
the method.** The harness works and will put a new hypothesis through the full gauntlet in ~15 minutes.

**A sixth strategy was tested and rejected on 2026-09-29: H4**, a Kalman/DLM hedge-ratio spread on
BTC-quoted crosses (plan §20.3, result §21). It died at a pre-backtest screen — no cointegration in 0–2 of
7 in-sample folds, ETH/BTC at −0.55 % gross per round trip against a 0.600 % gate, and every pair's result
inside its own random-entry band. **No holdout was spent and no fold was re-used.** The 14 BTC-quoted
crosses (1d and 1h, 2020–2025) are now in `~/freqtrade-data/`.

**The factor screen was then built (plan §20.7 step 1, result §22) and it retired cross-sectional
momentum on evidence.** Pointed at H1/H3's factor (`ret40/std40`) over the in-sample halves, calibrated
against a look-ahead ORACLE arm and a random NOISE arm: **IC negative at 9 of 9 horizons** (t up to −6.1),
top quintile the **worst of five** in absolute terms (+4.48 % / 21d vs +5.37 % for equal-weight-17), and the
one horizon where the top bucket leads (3 days, +0.128 %) delivers **0.8× cost coverage where 3× is required**.
Had this existed on 2026-09-28, H3 would never have been pre-registered and **the 2026 holdout would still
be clean.** Two things it does NOT do: it only fits ranking factors, and **return concentration is not
screenable** — the §17 G5 failure could not be detected in-sample at either the forward-return or the
portfolio level (tried both; the factor looked *less* concentrated than noise).

**A second new criterion — G-passive — adopted in plan §22 and AMENDED the same day in §23. Use the §23
form.** The pre-registered control was always *the same strategy at default parameters*, never buy-and-hold,
so nothing ever measured opportunity cost. The benchmark turned out to be in every export already
(`market_change.feather` → `rel_mean`), so all 62 past runs were re-judged for free. The catch §23 found:
**median realised exposure across those runs is 8.9 %** and β to the universe is ≈ 0 (`XSMomentum` +0.139,
the rest lower) — so comparing these books to a *fully-invested* benchmark is not like-for-like and mostly
measures which way the market went (12 of 14 down-universe windows "passed", 1 of 48 up-universe windows did).

**G-passive, current form:** compare against equal-weight buy-and-hold of the same universe **(a) scaled to
the candidate's realised exposure, (b) on Sharpe as well as total return, (c) split by rising and falling
windows.** The raw fully-invested comparison is context, not pass/fail. On this basis H3's holdout is
**+1.04 pp** vs an exposure-matched universe at Sharpe **1.13 vs 0.98**, and the 5-year run is **+27.65 pp**
at Sharpe **0.81 vs 1.64**. `tearsheet.py --gpassive` computes all of it. **Limit:** at ~9 % exposure the
scaled benchmark is a median 5.1 pp, so the scaled test is weak on its own — the Sharpe comparison is the
load-bearing one.

**Tear sheet gotchas** (plan §23): the tear sheet's drawdown is **daily mark-to-market including open
positions**, so it is deeper than freqtrade's trade-close figure (−6.80 % vs 5.65 % on H3) and is the
stricter number; and **pyfolio annualises on a 252-day year** while crypto trades 365, so its Sharpe reads
low — use the script's own 365-day figures.

**The transferable finding, and the new rule:** a 21-day hold on a crypto cross has a per-trade standard
deviation of **≈ 15 pp** against a **0.6 %** gate — the noise is ~25× the signal, and resolving that mean
needs **≈ 2,400 trades** where five years of daily data supply **≈ 90** per pair. So **every new hypothesis
now gets a noise-floor check before it gets a pre-registration**: per-trade sd at the intended holding
period, trades the history supplies, sample needed to resolve the gate. If the gate is inside the error
bars, it is not testable. Plan §21.

**Before writing a sixth strategy, run the thirteen-question audit checklist in plan §24.2.** Every question
is anchored to a number this project measured, and four of them (cost model, 3x cost rule, noise floor, factor
screen) are cheap enough to kill a candidate in minutes. Three of the thirteen are preconditions on a
pre-registration now: the **noise-floor check** (§21), **G-passive** in §23's form, and a **factor screen**
for anything with a cross-section (§22).

Next work is **reading, not backtesting**: plan §8's studies spine is the designated source of the next
hypothesis, and the specific gap is **U1's purged, embargoed walk-forward splitter plus a trials-adjusted
Sharpe** (Lopez de Prado ch. 7 and 11-12). `wf/run.sh` neither purges nor embargoes, so **every rejection in
plan §13-§17 was measured on a splitter that leaks across the fold boundary.** U3 (the cost model) and U4
(Monte Carlo drawdown bands) are the other two outstanding deliverables. Plan §20.7 is closed.

**Credentials:** none are stored here. The Telegram token and Binance key from 2020 are revoked and
verified dead. One item is outstanding — a Polygon.io key in the sibling `execution-trade` repo is
still live and belongs to a former collaborator's account. Plan §0.

## 9. If this folder moves machines

It is part of the `strategy-factory` git repo since 2026-09-29 (this folder's `.gitignore` keeps the
byproducts out). What does not travel with a clone:

1. Price data — re-download with `./ft download-data`; `~/freqtrade-data/` is outside the repo by design.
2. The docker images — rebuild both: `docker build -t freqtrade-lab:2026.8 .` and
   `docker build -f Dockerfile.research -t freqtrade-lab:2026.8-research .`
3. `user_data/hyperopt_results/` (~1.5 GB) and `user_data/backtest_results/` are gitignored regenerable
   byproduct; the numbers that matter live in `Autotrader Plan.md` and `wf/*-params.json`.

**Nothing secret is in the tree** — the 2020 repo's committed API keys are the reason this workspace
was built clean, and the factory keeps the rule: credentials via `FREQTRADE__*` env vars only.
