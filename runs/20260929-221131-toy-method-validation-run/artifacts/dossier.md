# Validation dossier — DonchianBreakout17

Timeframe 1d, fee 0.001, full range 20210101-20260101.

## Purged walk-forward (OOS)

| fold | test window | trades | return |
|---|---|---|---|
| 1 | 20220702-20221231 | 48 | -12.40% |
| 2 | 20221231-20230701 | 35 | +5.75% |
| 3 | 20230702-20231231 | 35 | +12.65% |
| 4 | 20231231-20240630 | 36 | +3.81% |
| 5 | 20240701-20241230 | 42 | +22.82% |
| 6 | 20241230-20250630 | 42 | -9.07% |
| 7 | 20250701-20251230 | 44 | +12.68% |
| **mean** | | | **+5.18%** (5/7 positive) |

## Cost sweep

| fee/side | trades | total return | mean/trade |
|---|---|---|---|
| 0.0000 | 416 | +99.82% | +4.7971% |
| 0.0005 | 416 | +97.69% | +4.6923% |
| 0.0010 | 416 | +95.56% | +4.5877% |
| 0.0020 | 416 | +91.31% | +4.3787% |
| 0.0030 | 416 | +87.05% | +4.1702% |

## Trade shape (full range)

- max realized hold: **107.0 days** (check against the pre-registered purge)
- best month 2021-03 holds **48%** of total profit (G-conc)

## Deflated Sharpe

- annualized SR **1.02** over 1825 daily obs (skew +3.70, kurt 71.9)
- deflation family 24 trials (ledger total 337) → expected max per-period SR 0.0824
- **DSR = 0.091** — deflated within the comparable-basis family (24 trials, 1d, >=300d); the full ledger holds 337 trials and hyperopt epochs are uncounted, so the true search was wider — treat DSR as an upper bound

## Gates

- PASS `zero_fee_sanity` — total return at zero fees: +99.82%
- PASS `cost_coverage` — coverage 23.99× vs required 3.0×
