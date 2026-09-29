"""
TrendBaseline - exploratory probe, NOT a gate candidate yet.

Deliberately the inverse of everything that failed in Plan sections 12-13:
  failed: mean reversion, buy weakness, ROI ladder caps winners at +2%, stop 5x further away,
          fixed stake, no regime filter  ->  win 68.9%, payoff 0.34, expectancy -0.45%/trade.
  here:   trend following, buy strength, NO roi cap (winners run), tight ATR-based trailing
          stop (losers cut), regime filter, and a volatility-scaled stake.
Expect a LOW win rate and a payoff ratio well above 1 - the opposite shape.
Only 2 numbers are tunable (entry/exit Donchian lengths); everything else is fixed by design.
"""
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


class TrendDaily(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False

    # No ROI ladder. This is the single most important line in the file: capping winners is
    # what made the 2020-era strategies mathematically unable to pay for their losers.
    minimal_roi = {"0": 100}

    stoploss = -0.25                 # disaster stop only; the trailing stop does the real work
    trailing_stop = True
    trailing_stop_positive = 0.08
    trailing_stop_positive_offset = 0.12
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    startup_candle_count: int = 150

    entry_len = IntParameter(15, 80, default=40, space="buy", optimize=True)   # breakout lookback
    exit_len = IntParameter(8, 40, default=20, space="sell", optimize=True)   # give-back lookback

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        for n in self.entry_len.range:
            dataframe[f"dc_hi_{n}"] = dataframe["high"].rolling(n).max().shift(1)
        for n in self.exit_len.range:
            dataframe[f"dc_lo_{n}"] = dataframe["low"].rolling(n).min().shift(1)
        # Regime filter: only hold risk while the pair is above its own long trend. Cheap proxy
        # for "is this a market where trend following is even the right tool".
        dataframe["smaF"] = ta.SMA(dataframe, timeperiod=50)
        dataframe["smaS"] = ta.SMA(dataframe, timeperiod=100)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = self.entry_len.value
        dataframe.loc[
            (dataframe["close"] > dataframe[f"dc_hi_{n}"])       # breakout to new high
            & (dataframe["smaF"] > dataframe["smaS"])        # long-trend regime is up
            & (dataframe["volume"] > 0),
            "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = self.exit_len.value
        dataframe.loc[dataframe["close"] < dataframe[f"dc_lo_{n}"], "exit_long"] = 1
        return dataframe
