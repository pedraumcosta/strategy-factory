# Kinship spike results

| backend | model | acc | brier | ECE | mean lat | total cost |
|---|---|---|---|---|---|---|
| haiku | claude-haiku-5-5 | 88% | 0.132 | 0.130 | 5.9s | $1.326 |
| opus | claude-opus-5-5 | 92% | 0.088 | 0.104 | 5.3s | $1.401 |

Misses per backend:
- haiku: nv_weekend -> chose breadth_regime_gate (true novel, conf 0.5)
- haiku: nv_btc_leadlag -> chose breadth_regime_gate (true novel, conf 0.444)
- haiku: nv_stable_flow -> chose volume_shock (true novel, conf 0.8)
- opus: nv_btc_leadlag -> chose breadth_regime_gate (true novel, conf 0.444)
- opus: nv_stable_flow -> chose volume_shock (true novel, conf 0.556)
