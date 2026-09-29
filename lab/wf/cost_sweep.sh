#!/usr/bin/env bash
# Cost sensitivity: same fixed-rule strategy, same window, fee swept. Separates "the signal is
# bad" from "the signal is fine but costs eat it". Results read from the JSON export, not the
# pretty table (whose column widths shift with the numbers).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
STRAT=${1:-Strategy005v0}
RANGE=${2:-20210101-20260101}
for FEE in 0 0.00025 0.0005 0.00075 0.001 0.002 0.003; do
  ./ft backtesting --config user_data/config.json --strategy "$STRAT" --timeframe 1h \
    --timerange "$RANGE" --fee "$FEE" --cache none --export trades >/dev/null 2>&1
  python3 - "$FEE" "$STRAT" <<'PY'
import glob, json, os, sys, zipfile
fee, strat = sys.argv[1], sys.argv[2]
z = max(glob.glob("user_data/backtest_results/*.zip"), key=os.path.getmtime)
with zipfile.ZipFile(z) as zf:
    n = [x for x in zf.namelist() if x.endswith(".json") and "_config" not in x
         and not x.endswith(f"_{strat}.json")][0]
    r = json.loads(zf.read(n))["strategy"][strat]
print(f"  {fee:<10}{r['total_trades']:>8}{r['profit_total']*100:>11.2f}"
      f"{(r['wins']/r['total_trades']*100 if r['total_trades'] else 0):>8.1f}"
      f"{r.get('max_drawdown_account',0)*100:>9.2f}"
      f"{r['profit_total_abs']:>12.2f}")
PY
done
