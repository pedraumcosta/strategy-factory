# =========================================================================
# REHEARSAL DEPLOYMENT — this strategy was KILLED at HG2 (2026-09-30):
# protocol failure (107d hold vs 30d purge tripwire), G-conc 48%, DSR 0.091.
# It runs here DRY-RUN ONLY to exercise the deploy/observe loop (M7).
# It must never be pointed at real money. See Strategy Factory Plan §14.
# =========================================================================
# DonchianBreakout17 — S4 implementation of the signed prereg
# (run 20260929-221131-toy-method-validation-run, gate HG1).
# Long-only fixed-parameter Donchian channel breakout, frozen a priori:
# enter on close > prior 10-day high, exit on close < prior 5-day low
# or the -10% stoploss. No tunable inputs; no hyperopt.

from pandas import DataFrame

from freqtrade.strategy import IStrategy


class DonchianBreakout17(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False

    # Exits are rule-based (5-day-low channel + stoploss); the ROI ladder
    # must never trigger, per prereg.
    minimal_roi = {"0": 10}
    stoploss = -0.10

    # Frozen parameters — plain constants, per prereg (no Parameter objects).
    ENTRY_CHANNEL_DAYS = 10
    EXIT_CHANNEL_DAYS = 5
    SHIFT_PERIODS = 1  # channels use prior completed bars only

    # Longest lookback: 10-day channel + 1-bar shift.
    startup_candle_count = ENTRY_CHANNEL_DAYS + SHIFT_PERIODS

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # shift(1) excludes the current bar: the channel is the high/low of
        # the N *prior completed* daily bars (shift_periods = 1). Positive
        # shift only — no future data enters any row.
        dataframe["donchian_upper"] = (
            dataframe["high"]
            .rolling(self.ENTRY_CHANNEL_DAYS)
            .max()
            .shift(self.SHIFT_PERIODS)
        )
        dataframe["donchian_lower"] = (
            dataframe["low"]
            .rolling(self.EXIT_CHANNEL_DAYS)
            .min()
            .shift(self.SHIFT_PERIODS)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] > dataframe["donchian_upper"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] < dataframe["donchian_lower"])
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1
        return dataframe
