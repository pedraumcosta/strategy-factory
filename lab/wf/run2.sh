#!/usr/bin/env bash
# Pre-registered protocol (Plan section 14) for the two candidates.
# Control = the SAME strategy at default parameters with no hyperopt, which measures directly
# whether optimisation added anything beyond in-sample fit.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
EPOCHS=100; FEE=0.001; CFG=user_data/config.json
log(){ printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

run_strategy () {
  local S=$1 TF=$2
  local PARAM="user_data/strategies/${S}.json"
  log "########## $S ($TF) ##########"
  while read -r N IS OOS; do
    rm -f "$PARAM"
    log "$S fold $N: control (defaults, no hyperopt) on OOS"
    ./ft backtesting --config $CFG --strategy "$S" --timeframe "$TF" --timerange "$OOS" \
        --fee $FEE --cache none --export trades > "wf/${S}-f${N}-ctl.log" 2>&1

    log "$S fold $N: hyperopt on IS"
    ./ft hyperopt --config $CFG --strategy "$S" --hyperopt-loss SharpeHyperOptLoss \
        --spaces buy sell --epochs $EPOCHS --timeframe "$TF" --timerange "$IS" --fee $FEE \
        --random-state $((2000+N)) > "wf/${S}-f${N}-hyperopt.log" 2>&1
    [ -f "$PARAM" ] && cp "$PARAM" "wf/${S}-f${N}-params.json" || log "$S fold $N: no params produced"

    log "$S fold $N: IS with optimised params"
    ./ft backtesting --config $CFG --strategy "$S" --timeframe "$TF" --timerange "$IS" \
        --fee $FEE --cache none --export trades > "wf/${S}-f${N}-is.log" 2>&1
    log "$S fold $N: OOS with optimised params"
    ./ft backtesting --config $CFG --strategy "$S" --timeframe "$TF" --timerange "$OOS" \
        --fee $FEE --cache none --export trades > "wf/${S}-f${N}-oos.log" 2>&1
    rm -f "$PARAM"
  done < wf/folds.txt
}

run_strategy XSMomentum 1d
run_strategy TrendVolTarget 4h
log "########## pre-registered protocol complete ##########"
