"""Control for the lookahead-analysis flag on XSMomentum: identical momentum maths, but
computed ONLY from the pair's own dataframe - no DataProvider, no cross-pair access."""
import numpy as np
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter

class XSControl(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    minimal_roi = {"0": 100}
    stoploss = -0.35
    startup_candle_count: int = 120
    lookback = IntParameter(10, 90, default=40, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        lb = self.lookback.value
        ret = dataframe["close"].pct_change(lb)
        vol = dataframe["close"].pct_change().rolling(lb).std()
        dataframe["mom"] = (ret / vol.replace(0, np.nan)).shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["mom"] > 1.0, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["mom"] < 0.0, "exit_long"] = 1
        return dataframe
