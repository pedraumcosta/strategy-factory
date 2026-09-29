# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
"""
BBRSIStrategy — Bollinger-band mean reversion with an optional RSI guard.

Rewritten 2026-09-28. The 2020 version came as a pair: a plain strategy plus a separate
`user_data/hyperopts/bbrsi_opt.py` in the legacy `IHyperOpt` file format (buy_strategy_generator /
sell_strategy_generator / indicator_space). That format was removed from freqtrade in 2021, so the
file could not load at all. Its search space is ported here as hyperoptable parameters on the
strategy itself, which is the V3 idiom: one file, and the optimiser and the live strategy can no
longer drift apart — which is precisely the failure mode documented in Autotrader Plan §12.

Parameter defaults are chosen to reproduce the 2020 strategy's behaviour exactly:
entry `close < bb_lowerband3` with the RSI guard off, exit `rsi > 75 and close > bb_middleband`.
So a backtest with no parameter file gives the same signals as before the rewrite.
"""
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import CategoricalParameter, IntParameter, IStrategy


class BBRSIStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"

    # Baked-in values are the 2020 hyperopt OUTPUT, kept so the strategy runs as it did then.
    # Treat them as suspect, not as settings: the -0.36828 stoploss is a 37 % stop, which is an
    # artifact of a single-split hyperopt over a deliberately widened stoploss space (the legacy
    # file searched Real(-0.5, -0.02), wider than freqtrade's own default). `hyperopt` will
    # overwrite both via user_data/strategies/BBRSIStrategy.json once re-optimised properly.
    minimal_roi = {"0": 0.09638, "19": 0.03643, "69": 0.01923, "120": 0}
    stoploss = -0.36828

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # 20-period bands, so 20 candles of warm-up before any signal is valid.
    startup_candle_count: int = 20

    # --- entry space (was bbrsi_opt.indicator_space) ---
    buy_rsi = IntParameter(5, 50, default=30, space="buy", optimize=True)
    buy_rsi_enabled = CategoricalParameter([True, False], default=False, space="buy", optimize=True)
    buy_trigger = CategoricalParameter(
        ["bb_lower1", "bb_lower2", "bb_lower3", "bb_lower4"],
        default="bb_lower3", space="buy", optimize=True,
    )

    # --- exit space (was bbrsi_opt.sell_indicator_space) ---
    # The legacy file computed a separate `sell-rsi` column with identical parameters to `rsi`;
    # there is no reason for two copies, so both sides read `rsi`.
    sell_rsi = IntParameter(30, 100, default=75, space="sell", optimize=True)
    sell_rsi_enabled = CategoricalParameter([True, False], default=True, space="sell", optimize=True)
    sell_trigger = CategoricalParameter(
        ["bb_lower1", "bb_middle1", "bb_upper1"],
        default="bb_middle1", space="sell", optimize=True,
    )

    # roi_space() / stoploss_space() are deliberately NOT overridden. The legacy file re-declared
    # them, and its stoploss range of -0.5..-0.02 is how the -0.36828 stop was produced. Freqtrade's
    # defaults are tighter and saner; if a custom range is ever wanted, justify it in writing first.

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe)

        # All four band widths, because the entry trigger selects among them. Computing every
        # width unconditionally is what the legacy hyperopt did, and keeps the indicator set
        # identical whether hyperopt is running or not (a mismatch there is a classic source of
        # optimiser-vs-live divergence).
        typical = qtpylib.typical_price(dataframe)
        for stds in (1, 2, 3, 4):
            bb = qtpylib.bollinger_bands(typical, window=20, stds=stds)
            dataframe[f"bb_lowerband{stds}"] = bb["lower"]
            dataframe[f"bb_middleband{stds}"] = bb["mid"]
            dataframe[f"bb_upperband{stds}"] = bb["upper"]

        # Back-compat aliases: the 2020 file exposed unsuffixed names built at stds=4.
        # The middle band is the SMA of typical price and so is identical at every width.
        dataframe["bb_lowerband"] = dataframe["bb_lowerband4"]
        dataframe["bb_middleband"] = dataframe["bb_middleband4"]
        dataframe["bb_upperband"] = dataframe["bb_upperband4"]
        return dataframe

    # Explicit trigger -> column maps. The parameter values are the names the legacy hyperopt
    # used; keeping them verbatim means an old parameter file still resolves.
    ENTRY_TRIGGERS = {
        "bb_lower1": "bb_lowerband1",
        "bb_lower2": "bb_lowerband2",
        "bb_lower3": "bb_lowerband3",
        "bb_lower4": "bb_lowerband4",
    }
    EXIT_TRIGGERS = {
        "bb_lower1": "bb_lowerband1",
        "bb_middle1": "bb_middleband1",
        "bb_upper1": "bb_upperband1",
    }

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [dataframe["close"] < dataframe[self.ENTRY_TRIGGERS[self.buy_trigger.value]]]
        if self.buy_rsi_enabled.value:
            conditions.append(dataframe["rsi"] > self.buy_rsi.value)
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[self._all(conditions), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [dataframe["close"] > dataframe[self.EXIT_TRIGGERS[self.sell_trigger.value]]]
        if self.sell_rsi_enabled.value:
            conditions.append(dataframe["rsi"] > self.sell_rsi.value)
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[self._all(conditions), "exit_long"] = 1
        return dataframe

    @staticmethod
    def _all(conditions):
        out = conditions[0]
        for c in conditions[1:]:
            out = out & c
        return out
