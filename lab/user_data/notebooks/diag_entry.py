import json, sys
import pandas as pd, numpy as np
from freqtrade.configuration import Configuration
from freqtrade.data.history import load_pair_history
from freqtrade.resolvers import StrategyResolver

tf = sys.argv[1] if len(sys.argv) > 1 else "1h"
cfg = Configuration.from_files(["/freqtrade/user_data/config.json"])
cfg["strategy"] = "Strategy005"; cfg["timeframe"] = tf
strat = StrategyResolver.load_strategy(cfg)

rows = []
for pair in ["ETC/BTC", "KMD/BTC", "EOS/BTC", "XEM/BTC", "ETH/BTC"]:
    df = load_pair_history(datadir=cfg["datadir"], timeframe=tf, pair=pair,
                           data_format=cfg.get("dataformat_ohlcv", "feather"))
    if df.empty:
        print(f"{pair}: no {tf} data"); continue
    d = strat.advise_indicators(df.copy(), {"pair": pair})
    terms = {
        "close>2e-06":        d["close"] > 0.00000200,
        "vol>4x MA200":       d["volume"] > d["volume"].rolling(200).mean() * 4,
        "close<sma":          d["close"] < d["sma"],
        "fastd>fastk":        d["fastd"] > d["fastk"],
        "rsi>0":              d["rsi"] > 0,
        "fastd>0":            d["fastd"] > 0,
        "fisher_norma<38.9":  d["fisher_rsi_norma"] < 38.900000000000006,
        "slope>-16":          d["slope"] > -16,
    }
    all_ = np.logical_and.reduce([t.fillna(False).values for t in terms.values()])
    rows.append((pair, len(d), {k: int(v.fillna(False).sum()) for k, v in terms.items()}, int(all_.sum())))
    if pair == "ETC/BTC":
        print(f"\n--- ETC/BTC {tf} indicator ranges ---")
        for c in ["sma","rsi","fastd","fastk","fisher_rsi","fisher_rsi_norma","slope","macd","minus_di","sar"]:
            if c in d:
                s=d[c].describe()
                print(f"  {c:<18} min={s['min']:>12.4f} med={s['50%']:>12.4f} max={s['max']:>12.4f} nan={d[c].isna().sum()}")

print(f"\n=== entry-term pass counts ({tf}) ===")
hdr = list(rows[0][2].keys())
print(f"  {'pair':<10}{'candles':>8}" + "".join(f"{h:>19}" for h in hdr) + f"{'ALL':>7}")
for pair, n, t, a in rows:
    print(f"  {pair:<10}{n:>8}" + "".join(f"{t[h]:>19}" for h in hdr) + f"{a:>7}")
