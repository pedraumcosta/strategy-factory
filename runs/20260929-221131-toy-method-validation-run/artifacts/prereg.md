# Pre-registration — DonchianBreakout17 (S3, gate HG1)

Run `20260929-221131-toy-method-validation-run` · drafted 2026-09-29 · toy
method-validation run #2 (M5 acceptance). Once signed at HG1, every choice in
this document is frozen; nothing downstream runs without the signature.

## Hypothesis

Crypto markets exhibit medium-term trend persistence: once price closes above
its prior 10-day high, herding, momentum-chasing flow, and slow diffusion of
narrative-driven capital tend to push it further before the move exhausts. A
long-only, fixed-parameter Donchian channel breakout — enter on a close above
the 10-day high, exit on a close below the 5-day low or a -10% stop — captures
this drift net of realistic fees on a 17-pair liquid USDT daily universe.

**Strategy name:** `DonchianBreakout17`

## Fixed parameters

All parameters below were **chosen a priori on 2026-09-29, before any fold was
run; there is no parameter search in this protocol.** Values are taken verbatim
from the hypothesis card.

| Parameter | Value |
|---|---|
| `entry_channel_days` | 10 (enter long when close > prior 10-day high) |
| `exit_channel_days` | 5 (exit when close < prior 5-day low) |
| `stoploss` | -0.10 |
| `timeframe` | 1d |
| `long_only` | true (no shorts) |
| `shift_periods` | 1 (channels computed on prior completed bars only) |

There are no other tunable inputs. No hyperopt, no grid, no re-parameterized
re-run of this card is permitted under this pre-registration. (Run #1 of this
idea died at the noise-floor screen on a 5-pair universe; this resubmission
enlarged the universe for statistical power only, before any backtest of either
run, and is logged as a resubmission.)

## Protocol

- **Validation scheme:** purged walk-forward on the seven recorded in-sample
  folds (`lab/user_data/notebooks/walkforward.json`, ledgered as the spent
  2021–2025 window):

  | Fold | IS window | OOS window |
  |---|---|---|
  | 1 | 20210101–20220702 | 20220702–20221231 |
  | 2 | 20210702–20221231 | 20221231–20230701 |
  | 3 | 20220101–20230702 | 20230702–20231231 |
  | 4 | 20220702–20231231 | 20231231–20240630 |
  | 5 | 20230101–20240701 | 20240701–20241230 |
  | 6 | 20230702–20241230 | 20241230–20250630 |
  | 7 | 20240101–20250701 | 20250701–20251230 |

- **Purge: 30 days**, applied by the factory splitter (`purge_existing`) by
  trimming each fold's IS end back from its OOS start; embargo 30 days. The
  strategy's typical hold is ~7 days; its exits (trailing 5-day low, -10%
  stop) are condition-based, so 30 days is pre-registered as the maximum
  holding period the purge covers — more than 4× the typical hold. The dossier
  must report the maximum realized holding period; **if any trade's hold
  exceeds 30 days, the purge is undersized and the run fails on protocol** —
  it may not be re-run with a larger purge under this signature.
- **Timeframe:** 1d. **Fee: 0.001 per side** (0.2% round trip). **Universe:**
  the 17 USDT pairs from the card, verbatim from `lab/user_data/config.json`:
  BTC, ETH, BNB, XRP, ADA, SOL, DOGE, LTC, LINK, XLM, TRX, AVAX, ALGO, UNI,
  NEAR, HBAR, ZEC (all /USDT). Pairs listing after a window's start simply
  contribute shorter histories; no substitutions.
- **Execution semantics (pre-registered, per the research memo's lookahead
  audit):** signals on completed daily bars, fills at the **next bar's open**;
  the -10% stop fills pessimistically — a gap through the stop fills at the
  open, not at -10%; no full-series normalization anywhere.
- **Full range:** one run over 20210101–20251231 at fee 0.001, used for the
  tear sheet, concentration, and DSR. **Cost sweep:** the same full range at
  fees 0, 0.0005, and 0.002 per side (the zero-fee leg feeds G-cost and
  G-zero).
- **Passive control:** equal-weight buy-and-hold of the same 17 pairs over the
  same full range, scaled to the strategy's realized exposure (average
  fraction of capital deployed), for G-passive.
- **The full pre-registered run happens ONCE.** No fold, sweep leg, or
  full-range run is repeated after results are seen. **No holdout is
  touched:** all data lies inside the already-spent 20210101–20251231 window;
  the clean 20190101–20201231 window and the 2026 window stay unmounted. Any
  holdout spend would be a separate HG2b signature against the holdout ledger
  — this document does not authorize one.

## Pass criteria

All criteria below must hold simultaneously. Each is checkable from the
backtest exports (per-trade records, per-fold summaries) and the S5 dossier.

- **G-cost:** zero-fee mean per-trade return on stake **≥ 0.60%** (3× the
  0.2% round trip), measured on the zero-fee full-range run. (This equals the
  edge the noise-floor screen was sized to resolve; anything weaker would
  contradict the screen.)
- **G-zero:** total return at zero fees **> 0** on the full range.
- **G-wf:** mean OOS total return across the seven folds **> 0** AND at least
  **4 of 7** fold OOS windows have positive total return.
- **G-passive:** full-range Sharpe (365-day annualization, mark-to-market)
  **strictly greater** than the Sharpe of the exposure-scaled equal-weight
  buy-and-hold control. The comparison is additionally computed and reported
  separately for rising and falling windows — fold OOS windows classified a
  priori by the sign of the passive control's total return in that window
  (≥ 0 rising, < 0 falling) — and the strategy must also beat the control on
  Sharpe in the pooled **falling** windows (where a breakout system's value
  must live); the rising-window comparison is reported alongside.
- **G-conc:** total net profit at fee 0.001 **> 0**, and no single calendar
  month contributes **more than 40%** of that total profit (return
  concentration killed the best prior candidate at 78%).
- **G-dsr:** deflated Sharpe ratio, computed against the trial ledger's
  comparable-basis family (the ledger's count of comparable backtests at run
  time, never a guess), **above 0.5** on the full-range run.
- **G-n:** total completed trades across the seven OOS folds **≥ 267** — the
  measured trade count must clear the same noise-floor requirement the
  estimate screen cleared on paper (267 trades to resolve a 0.60% edge at
  5.00% per-trade sd).

Numbers, not adjectives: a criterion missing by any margin is a fail. There is
no "near miss" category and no discretionary override at HG2.

## Trial budget

This protocol consumes **12 backtests**, every one appended to
`ledgers/trials.jsonl` before HG2:

| # | Runs | What |
|---|---|---|
| 1–7 | 7 | candidate on each fold's OOS window, fee 0.001 |
| 8 | 1 | candidate, full range 20210101–20251231, fee 0.001 |
| 9–11 | 3 | cost sweep on the full range: fee 0, 0.0005, 0.002 |
| 12 | 1 | exposure-scaled equal-weight buy-and-hold control, full range |

No other backtest of this strategy is authorized. Any run beyond these twelve
is a protocol violation and voids the result at HG2. (LLM-stage costs continue
to land on the ledger as usual; they are not backtests.)

## Committed consequences

- **On any criterion failing:** `DonchianBreakout17` is dead, and with it the
  idea-space **"long-only, fixed-parameter Donchian/price-channel breakout on
  daily bars over this lab's USDT spot universe"** is closed — at any channel
  lengths, any stop, and any universe size. Run #1 (5 pairs) already died at
  the noise floor; this run was that idea's one resubmission, justified by
  statistical power alone. A failure here may not be retried with a tweak: no
  re-run with 20/10 or 55/20 channels, a different stop, a filtered universe,
  a different timeframe, or "just the liquid majors." Any future card touching
  post-breakout drift in this lab must use a materially different mechanism
  (e.g., regime-filtered or vol-scaled trend, cross-sectional construction),
  must cite this failure in its provenance, and starts at S0 with fresh
  screens. The failure is recorded on the trial ledger and in this run's
  manifest.
- **On all criteria passing:** this remains a toy method-validation run (M5
  acceptance of the factory, not of the strategy). A pass authorizes
  proceeding to S4/S5 under this protocol and nothing else — no capital, no
  holdout spend, no live incubation — each of which requires its own later
  signature (HG2b for holdout, HG3 beyond).
- In either outcome, the artifacts of this run (`hypothesis.json`,
  `research.md`, `screen_report.md`, this document, and the S5 dossier) are
  immutable once produced; corrections happen in a new run, never by editing.
