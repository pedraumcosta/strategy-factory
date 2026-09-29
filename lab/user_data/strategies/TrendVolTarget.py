"""
TrendVolTarget - H2 of Autotrader Plan section 14 (pre-registered 2026-09-28).

The 1h trend probe had a real gross edge (+5.95% at zero fee, payoff 1.50) that 0.2% round-trip
cost destroyed: 0.073% edge per trade against 0.157% cost. This keeps that structure and attacks
the cost gap directly - 4h bars, long breakout lookbacks and a wide ATR trailing stop, so there
are far fewer and far larger trades. A minimum-volatility filter refuses trades whose expected
move cannot pay the spread several times over.

Section 14 rules: no minimal_roi (R1), ATR trailing stop so losers are cut and winners run (R2),
volatility floor for cost (R3), vol-targeted sizing (R4), three optimised parameters (R5).
"""
import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy


class TrendVolTarget(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 100}          # R1: winners are never capped
    stoploss = -0.35                  # disaster stop; custom_stoploss does the real work
    trailing_stop = False
    use_custom_stoploss = True

    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True
    startup_candle_count: int = 300

    # R5: exactly three optimised parameters.
    entry_len = IntParameter(60, 240, default=120, space="buy", optimize=True)
    vol_floor = DecimalParameter(0.005, 0.030, default=0.012, decimals=3, space="buy", optimize=True)
    atr_stop = DecimalParameter(2.0, 6.0, default=3.5, decimals=1, space="sell", optimize=True)

    TARGET_VOL = 0.60
    MAX_STAKE_MULT = 2.0
    MIN_STAKE_MULT = 0.25

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # shift(1) so the breakout level is formed strictly before the candle being tested
        for n in self.entry_len.range:
            dataframe[f"dc_hi_{n}"] = dataframe["high"].rolling(n).max().shift(1)

        # regime: only trade the long side while the pair's own trend is up
        dataframe["sma_f"] = ta.SMA(dataframe, timeperiod=60)
        dataframe["sma_s"] = ta.SMA(dataframe, timeperiod=240)

        dataframe["rvol"] = dataframe["close"].pct_change().rolling(90).std() * np.sqrt(6 * 365)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = self.entry_len.value
        dataframe.loc[
            (dataframe["close"] > dataframe[f"dc_hi_{n}"])          # breakout
            & (dataframe["sma_f"] > dataframe["sma_s"])             # regime up
            & (dataframe["atr_pct"] > self.vol_floor.value)         # R3: move must pay the spread
            & (dataframe["volume"] > 0),
            "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit is the trailing stop only - a signal-based exit would cap winners (R1/R2).
        return dataframe

    def custom_stoploss(self, pair: str, trade, current_time, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        """ATR-multiple trailing stop measured from the trade's high-water mark.

        Returned as a ratio relative to current_rate, which is what freqtrade expects.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty or "atr" not in df:
            return None
        atr = df["atr"].iloc[-1]
        if not np.isfinite(atr) or atr <= 0:
            return None
        peak = max(trade.max_rate or current_rate, current_rate)
        stop_price = peak - self.atr_stop.value * atr
        if stop_price <= 0:
            return None
        ratio = stop_price / current_rate - 1.0
        return min(ratio, -0.005)   # always below current price

    def custom_stake_amount(self, pair: str, current_time, current_rate: float,
                            proposed_stake: float, min_stake, max_stake: float,
                            leverage: float, entry_tag, side: str, **kwargs) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty or "rvol" not in df:
            return proposed_stake
        rvol = df["rvol"].iloc[-1]
        if not np.isfinite(rvol) or rvol <= 0:
            return proposed_stake
        mult = float(np.clip(self.TARGET_VOL / rvol, self.MIN_STAKE_MULT, self.MAX_STAKE_MULT))
        stake = proposed_stake * mult
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake)
