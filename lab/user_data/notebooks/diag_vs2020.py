import json
import pandas as pd, numpy as np
from freqtrade.configuration import Configuration
from freqtrade.data.history import load_pair_history
from freqtrade.resolvers import StrategyResolver

OLD = "/freqtrade/user_data/notebooks/backtest-2020.json"
old = json.load(open(OLD))["strategy"]["Strategy005"]["trades"]
cfg = Configuration.from_files(["/freqtrade/user_data/config.json"])
cfg["strategy"] = "Strategy005"; cfg["timeframe"] = "1h"
strat = StrategyResolver.load_strategy(cfg)

pair = "KMD/BTC"
tr = [t for t in old if t["pair"] == pair]
print(f"2020 trades on {pair}: {len(tr)}")
df = load_pair_history(datadir=cfg["datadir"], timeframe="1h", pair=pair, data_format="feather")
d = strat.advise_indicators(df.copy(), {"pair": pair}).set_index("date")

terms = lambda r: {
  "close>2e-06":       r["close"] > 0.00000200,
  "vol>4xMA200":       r["volume"] > r["_volma"],
  "close<sma":         r["close"] < r["sma"],
  "fastd>fastk":       r["fastd"] > r["fastk"],
  "fisher_norma<38.9": r["fisher_rsi_norma"] < 38.900000000000006,
  "slope>-16":         r["slope"] > -16,
}
d["_volma"] = d["volume"].rolling(200).mean()*4
print(f"\nEvaluating the 2020 entry candles of the first 12 {pair} trades:")
hdr=None; fails={}
for t in tr[:12]:
    ts = pd.Timestamp(t["open_date"])
    if ts not in d.index:
        print(f"  {ts}  <- candle not in data!"); continue
    r = d.loc[ts]; tv = terms(r)
    if hdr is None:
        hdr=list(tv.keys()); print("   " + "open_date".ljust(26) + "".join(f"{h:>19}" for h in hdr))
    print("   " + str(ts).ljust(26) + "".join(f"{str(bool(tv[h])):>19}" for h in hdr))
    for k,v in tv.items():
        if not bool(v): fails[k]=fails.get(k,0)+1
print("\n=== which term blocks the 2020 entries? (fail counts over those candles) ===")
for k,v in sorted(fails.items(), key=lambda x:-x[1]): print(f"  {k:<20} failed {v} times")
if not fails: print("  none - all 2020 entries still pass")
