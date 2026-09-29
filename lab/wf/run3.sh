#!/usr/bin/env bash
# Fix-up run: XSMomentum only, --spaces buy (both its parameters live in the buy space).
# The earlier default-parameter OOS runs remain valid and serve as the control.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
S=XSMomentum; TF=1d; EPOCHS=100; FEE=0.001; CFG=user_data/config.json
PARAM="user_data/strategies/${S}.json"
log(){ printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
while read -r N IS OOS; do
  rm -f "$PARAM"
  log "$S fold $N: hyperopt on IS (spaces=buy)"
  ./ft hyperopt --config $CFG --strategy "$S" --hyperopt-loss SharpeHyperOptLoss \
      --spaces buy --epochs $EPOCHS --timeframe "$TF" --timerange "$IS" --fee $FEE \
      --random-state $((2000+N)) > "wf/${S}-f${N}-hyperopt.log" 2>&1
  if [ -f "$PARAM" ]; then cp "$PARAM" "wf/${S}-f${N}-params.json"; else log "$S fold $N: STILL no params"; fi
  log "$S fold $N: IS with optimised params"
  ./ft backtesting --config $CFG --strategy "$S" --timeframe "$TF" --timerange "$IS" \
      --fee $FEE --cache none --export trades > "wf/${S}-f${N}-is.log" 2>&1
  log "$S fold $N: OOS with optimised params"
  ./ft backtesting --config $CFG --strategy "$S" --timeframe "$TF" --timerange "$OOS" \
      --fee $FEE --cache none --export trades > "wf/${S}-f${N}-oos2.log" 2>&1
  rm -f "$PARAM"
done < wf/folds.txt
log "XSMomentum fix-up complete"
