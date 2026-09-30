#!/bin/bash
# Daily Phase-3 parity: backtest the elapsed dry-run window with the SAME
# strategy and compare against the dry-run DB. ONESHOT=1 runs once (rehearsal).
set -u
STRAT="${STRATEGY:?}"; START="${DRYRUN_START:?}"
while true; do
  echo "[parity] $(date -u +%FT%TZ) downloading data and backtesting ${START}- ..."
  freqtrade download-data --config /freqtrade/user_data/config.json \
      --timeframe 1d --days 60 2>/dev/null
  freqtrade backtesting --config /freqtrade/user_data/config.json \
      --strategy "$STRAT" --strategy-path /factory/strategy \
      --timeframe 1d --timerange "${START}-" --fee 0.001 --cache none \
      > /data/parity_backtest.log 2>&1
  ZIP=$(ls -t /freqtrade/user_data/backtest_results/*.zip 2>/dev/null | head -1)
  if [ -n "$ZIP" ] && [ -f /freqtrade/user_data/dryrun.sqlite ]; then
    python3 /obs/parity.py --db /freqtrade/user_data/dryrun.sqlite \
        --export "$ZIP" --strategy "$STRAT" --out /data/parity_report.md \
      && echo "[parity] report written to /data/parity_report.md"
  else
    # day 0: a window starting today has nothing left after startup candles;
    # the report still gets written, honestly, so silence never looks like success
    printf '# Parity report — %s (%s)\n\n- no backtest export yet (day-0 window or backtest failure — see parity_backtest.log)\n- dry-run DB present: %s\n' \
        "$STRAT" "$(date -u +%F)" "$([ -f /freqtrade/user_data/dryrun.sqlite ] && echo yes || echo no)" \
        > /data/parity_report.md
    echo "[parity] day-0/no-export report written"
  fi
  [ "$ONESHOT" = "1" ] && exit 0
  sleep 86400
done
