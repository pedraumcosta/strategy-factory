#!/bin/bash
# Daily Phase-3 parity: backtest the elapsed dry-run window with the SAME
# strategy and compare against the dry-run DB. ONESHOT=1 runs once (rehearsal).
set -u
STRAT="${STRATEGY:?}"; START="${DRYRUN_START:?}"
# Fee mirrors factory/costs.py WORKING.fee_per_side (bash cannot import it);
# override via the environment if the working fee changes.
FEE="${FEE:-0.001}"
RESULTS=/freqtrade/user_data/backtest_results
MARKER=/tmp/parity.marker
while true; do
  echo "[parity] $(date -u +%FT%TZ) downloading data and backtesting ${START}- ..."
  freqtrade download-data --config /freqtrade/user_data/config.json \
      --timeframe 1d --days 60 2>/dev/null
  touch "$MARKER"
  freqtrade backtesting --config /freqtrade/user_data/config.json \
      --strategy "$STRAT" --strategy-path /factory/strategy \
      --timeframe 1d --timerange "${START}-" --fee "$FEE" --cache none \
      > /data/parity_backtest.log 2>&1
  # Only an export NEWER than this run's marker counts: after a failed
  # backtest, comparing against yesterday's stale zip would report parity
  # that was never measured.
  ZIP=$(find "$RESULTS" -name '*.zip' -newer "$MARKER" 2>/dev/null | head -1)
  if [ -n "$ZIP" ] && [ -f /freqtrade/user_data/dryrun.sqlite ]; then
    python3 /obs/parity.py --db /freqtrade/user_data/dryrun.sqlite \
        --export "$ZIP" --strategy "$STRAT" --out /data/parity_report.md \
      && echo "[parity] report written to /data/parity_report.md"
  else
    # day 0: a window starting today has nothing left after startup candles;
    # the report still gets written, honestly, so silence never looks like success
    printf '# Parity report — %s (%s)\n\n- no NEW backtest export this run (day-0 window or backtest failure — see parity_backtest.log)\n- dry-run DB present: %s\n' \
        "$STRAT" "$(date -u +%F)" "$([ -f /freqtrade/user_data/dryrun.sqlite ] && echo yes || echo no)" \
        > /data/parity_report.md
    echo "[parity] day-0/no-export report written"
  fi
  [ "$ONESHOT" = "1" ] && exit 0
  sleep 86400
done
