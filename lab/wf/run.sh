#!/usr/bin/env bash
# Walk-forward protocol, Autotrader Plan Phase 2.
# Per fold: hyperopt on IN-SAMPLE only -> evaluate the resulting parameters on the untouched
# OUT-OF-SAMPLE window -> also run a fixed-rule control (Strategy005v0, no parameters, so it
# cannot be overfitted) on the same OOS window. The IS-vs-OOS gap is the whole point.
#
# The <Strategy>.json parameter file is handled explicitly at every step: hyperopt writes it,
# the OOS backtest must use it, and it is removed afterwards so nothing leaks between folds.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
LAB="$PWD"; EPOCHS=100; FEE=0.001; TF=1h
CFG=user_data/config.json
PARAM=user_data/strategies/BBRSIStrategy.json
log(){ printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

python3 - <<'PY' > wf/folds.txt
import json
d=json.load(open("user_data/notebooks/walkforward.json"))
for f in d["folds"]: print(f["fold"], f["is"], f["oos"])
PY

while read -r N IS OOS; do
  log "===== fold $N : IS $IS  OOS $OOS ====="
  rm -f "$PARAM"

  log "fold $N: hyperopt on IS ($EPOCHS epochs, buy/sell/roi/stoploss, Sharpe loss)"
  ./ft hyperopt --config $CFG --strategy BBRSIStrategy \
      --hyperopt-loss SharpeHyperOptLoss --spaces buy sell roi stoploss \
      --epochs $EPOCHS --timeframe $TF --timerange "$IS" --fee $FEE \
      --random-state $((1000+N)) > "wf/fold${N}-hyperopt.log" 2>&1
  if [ -f "$PARAM" ]; then cp "$PARAM" "wf/fold${N}-params.json"; log "fold $N: params saved";
  else log "fold $N: WARNING no parameter file produced"; fi

  log "fold $N: backtest IS (with optimised params)"
  ./ft backtesting --config $CFG --strategy BBRSIStrategy --timeframe $TF \
      --timerange "$IS" --fee $FEE --cache none \
      --export trades --export-filename "wf/fold${N}-is.json" > "wf/fold${N}-is.log" 2>&1

  log "fold $N: backtest OOS (same params, unseen window)"
  ./ft backtesting --config $CFG --strategy BBRSIStrategy --timeframe $TF \
      --timerange "$OOS" --fee $FEE --cache none \
      --export trades --export-filename "wf/fold${N}-oos.json" > "wf/fold${N}-oos.log" 2>&1

  rm -f "$PARAM"   # never let a fold's params leak into the next one

  log "fold $N: control Strategy005v0 on OOS (no parameters, cannot be overfitted)"
  ./ft backtesting --config $CFG --strategy Strategy005v0 --timeframe $TF \
      --timerange "$OOS" --fee $FEE --cache none \
      --export trades --export-filename "wf/fold${N}-ctl.json" > "wf/fold${N}-ctl.log" 2>&1
done < wf/folds.txt

log "===== walk-forward complete ====="
