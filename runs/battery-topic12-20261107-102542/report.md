# §17 topic 12 battery — user-sourced candidates

## EthBtcSectorCascade: **KILL**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": false,
 "reason": "best horizon 1d needs IC>0 with t\u22652.0; h1: IC +0.0401 (t +1.7), h5: IC +0.0187 (t +0.8), h21: IC +0.0014 (t +0.1)",
 "ic_by_horizon": {
  "1": {
   "mean": 0.0401,
   "t": 1.6814
  },
  "5": {
   "mean": 0.0187,
   "t": 0.7843
  },
  "21": {
   "mean": 0.0014,
   "t": 0.0578
  }
 }
}
```

## UsMarketOpenDrift: **KILL**
```json
{
 "design": "conditional",
 "calibration_valid": true,
 "passed": false,
 "pooled_t": 1.61,
 "diff_bp_per_day": 19.87,
 "per_fold_t": [
  2.7,
  1.48,
  1.06,
  -0.31,
  0.49,
  0.51,
  -0.14
 ],
 "oracle_t": 37.7,
 "placebo_t": -0.78
}
```

## Regression arm (topic 11 re-run): **IDENTICAL** — every number matches the committed results.json
