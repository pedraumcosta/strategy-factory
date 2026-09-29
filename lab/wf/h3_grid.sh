#!/usr/bin/env bash
# H3-G6 robustness grid. For each (lookback, top_k), evaluate the SEVEN OOS folds and take the
# mean. Criterion: >=70% of grid points must have positive mean OOS. Run entirely on already-spent
# fold data - the 2026 holdout is NOT touched here.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PARAM=user_data/strategies/XSMomentum.json
OUT=wf/h3_grid.csv
echo "lookback,top_k,mean_oos,folds_positive,total_trades" > "$OUT"
for LB in 20 30 40 50 60; do
  for K in 2 3 4 5; do
    cat > "$PARAM" <<JSON
{"strategy_name":"XSMomentum","params":{"buy":{"lookback":$LB,"top_k":$K}}}
JSON
    SUM=0; POS=0; N=0; TR=0
    while read -r FOLD IS OOS; do
      ./ft backtesting --config user_data/config.json --strategy XSMomentum --timeframe 1d \
        --timerange "$OOS" --fee 0.001 --cache none --export trades >/dev/null 2>&1
      read P T < <(python3 - <<'PY'
import glob,json,os,zipfile
z=max(glob.glob("user_data/backtest_results/*.zip"),key=os.path.getmtime)
with zipfile.ZipFile(z) as zf:
    n=[x for x in zf.namelist() if x.endswith(".json") and "_config" not in x and not x.endswith("_XSMomentum.json")][0]
    r=json.loads(zf.read(n))["strategy"]["XSMomentum"]
print(r["profit_total"]*100, r["total_trades"])
PY
)
      SUM=$(python3 -c "print($SUM+$P)"); TR=$((TR+T)); N=$((N+1))
      python3 -c "import sys; sys.exit(0 if $P>0 else 1)" && POS=$((POS+1))
    done < wf/folds.txt
    MEAN=$(python3 -c "print(round($SUM/$N,3))")
    echo "$LB,$K,$MEAN,$POS,$TR" >> "$OUT"
    printf '  lookback=%-3s top_k=%-2s  mean OOS %8s%%  folds+ %s/7  trades %s\n' "$LB" "$K" "$MEAN" "$POS" "$TR"
  done
done
rm -f "$PARAM"
echo "grid complete"
