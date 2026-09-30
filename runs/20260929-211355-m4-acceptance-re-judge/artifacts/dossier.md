# Validation dossier — XSMomentum

Timeframe 1d, fee 0.001, full range 20210101-20260101.

## Purged walk-forward (OOS)

| fold | test window | trades | return |
|---|---|---|---|
| 1 | 20220702-20221231 | 87 | -2.24% |
| 2 | 20221231-20230701 | 90 | +4.72% |
| 3 | 20230702-20231231 | 91 | +15.62% |
| 4 | 20231231-20240630 | 120 | +1.38% |
| 5 | 20240701-20241230 | 97 | +10.25% |
| 6 | 20241230-20250630 | 106 | -3.08% |
| 7 | 20250701-20251230 | 85 | +25.12% |
| **mean** | | | **+7.40%** (5/7 positive) |

## Cost sweep

| fee/side | trades | total return | mean/trade |
|---|---|---|---|
| 0.0000 | 1028 | +57.81% | +1.2271% |
| 0.0005 | 1028 | +54.01% | +1.1259% |
| 0.0010 | 1028 | +50.21% | +1.0248% |
| 0.0020 | 1028 | +42.61% | +0.8230% |
| 0.0030 | 1028 | +35.01% | +0.6215% |

## Deflated Sharpe

- annualized SR **0.77** over 1825 daily obs (skew +0.55, kurt 17.9)
- deflation family 24 trials (ledger total 309) → expected max per-period SR 0.0824
- **DSR = 0.036** — deflated within the comparable-basis family (24 trials, 1d, >=300d); the full ledger holds 309 trials and hyperopt epochs are uncounted, so the true search was wider — treat DSR as an upper bound

## Gates

- PASS `zero_fee_sanity` — total return at zero fees: +57.81%
- PASS `cost_coverage` — coverage 6.14× vs required 3.0×
