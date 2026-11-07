# §17 topic 13 battery — the five registered constructions at expanded breadth

52 names (52 perp-funded); calibration measurements only — no family reopens, nothing enters S0.

## short_term_reversal: **PASS**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": true,
 "reason": "best horizon 1d needs IC>0 with t\u22652.0; h1: IC +0.0378 (t +2.1), h5: IC +0.0197 (t +1.2), h21: IC -0.0119 (t -0.7)",
 "ic_by_horizon": {
  "1": {
   "mean": 0.0378,
   "t": 2.0946
  },
  "5": {
   "mean": 0.0197,
   "t": 1.1774
  },
  "21": {
   "mean": -0.0119,
   "t": -0.7299
  }
 }
}
```

## low_volatility: **PASS**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": true,
 "reason": "best horizon 21d needs IC>0 with t\u22652.0; h1: IC +0.0630 (t +2.7), h5: IC +0.0704 (t +3.2), h21: IC +0.0988 (t +4.4)",
 "ic_by_horizon": {
  "1": {
   "mean": 0.063,
   "t": 2.7439
  },
  "5": {
   "mean": 0.0704,
   "t": 3.1509
  },
  "21": {
   "mean": 0.0988,
   "t": 4.3614
  }
 }
}
```

## volume_shock: **FAIL**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": false,
 "reason": "best horizon 21d needs IC>0 with t\u22652.0; h1: IC -0.0253 (t -1.7), h5: IC -0.0115 (t -0.8), h21: IC -0.0081 (t -0.6)",
 "ic_by_horizon": {
  "1": {
   "mean": -0.0253,
   "t": -1.7372
  },
  "5": {
   "mean": -0.0115,
   "t": -0.7777
  },
  "21": {
   "mean": -0.0081,
   "t": -0.5801
  }
 }
}
```

## distance_from_highs: **PASS**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": true,
 "reason": "best horizon 21d needs IC>0 with t\u22652.0; h1: IC +0.0083 (t +0.4), h5: IC +0.0326 (t +1.7), h21: IC +0.0596 (t +3.1)",
 "ic_by_horizon": {
  "1": {
   "mean": 0.0083,
   "t": 0.4223
  },
  "5": {
   "mean": 0.0326,
   "t": 1.6652
  },
  "21": {
   "mean": 0.0596,
   "t": 3.0519
  }
 }
}
```

## FundingCarryTilt: **PASS**
```json
{
 "design": "cross_sectional_ic",
 "calibration_valid": true,
 "passed": true,
 "reason": "best horizon 21d needs IC>0 with t\u22652.0; h1: IC +0.0213 (t +1.6), h5: IC +0.0410 (t +3.0), h21: IC +0.0454 (t +3.4)",
 "ic_by_horizon": {
  "1": {
   "mean": 0.0213,
   "t": 1.5834
  },
  "5": {
   "mean": 0.041,
   "t": 2.9835
  },
  "21": {
   "mean": 0.0454,
   "t": 3.3776
  }
 }
}
```

## Regression arm (topic 11 re-run): **IDENTICAL** — every number matches the committed results.json
