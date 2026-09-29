"""
XSMomentum - H1 of Autotrader Plan section 14 (pre-registered 2026-09-28).

Cross-sectional momentum: rank the whole universe by volatility-adjusted trailing return and
hold only the top k. The point is structural, not statistical - by holding relative winners and
nothing else, the book is far less of a pure long-beta bet than every strategy tested so far,
and directional beta is what lost money in 2021-22 and 2024-25 (Plan section 13).

Obeys the section 14 design rules: no minimal_roi cap (R1), volatility-targeted sizing (R4),
two optimised parameters (R5), concurrency capped at top_k (R6). Cost is handled by construction
(R3) - daily bars and slow turnover mean very few trades.
"""
import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IntParameter, IStrategy


class XSMomentum(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = False

    # R1: never cap a winner. Exits come from leaving the top-k, not from a profit target.
    minimal_roi = {"0": 100}
    # Disaster stop only. A daily cross-sectional book should not be stopped out on noise.
    stoploss = -0.35
    trailing_stop = False

    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True
    startup_candle_count: int = 120

    # R5: exactly two optimised parameters.
    lookback = IntParameter(10, 90, default=40, space="buy", optimize=True)
    top_k = IntParameter(2, 5, default=3, space="buy", optimize=True)

    # R4: volatility targeting. Annualised target risk per position; size is scaled so each
    # position contributes roughly the same risk regardless of how volatile the pair is.
    TARGET_VOL = 0.60          # 60% annualised per position - crypto-appropriate, deliberately fixed
    MAX_STAKE_MULT = 2.0       # never size above 2x the nominal stake
    MIN_STAKE_MULT = 0.25

    # ---- cross-sectional ranking -------------------------------------------------------
    def _ranks(self, lookback: int, max_date=None) -> pd.DataFrame:
        """Rank table: index = date, columns = pair, value = rank (1 = strongest).

        Built once per lookback and cached. Every input is causal - pct_change and rolling std
        look backwards only, and the rank at date t uses only values observed at t. Verified by
        lookahead-analysis rather than trusted.
        """
        series = {}
        for pair in self.dp.current_whitelist():
            df = self.dp.get_pair_dataframe(pair, self.timeframe)
            if df is None or df.empty or "close" not in df:
                continue
            d = df.set_index("date")["close"].astype(float)
            if max_date is not None:
                d = d.loc[d.index <= max_date]
            ret = d.pct_change(lookback)
            vol = d.pct_change().rolling(lookback).std()
            series[pair] = (ret / vol.replace(0, np.nan)).rename(pair)

        if not series:
            return pd.DataFrame()
        panel = pd.concat(series.values(), axis=1).sort_index()
        # rank across pairs at each date; 1 = highest risk-adjusted momentum
        ranks = panel.rank(axis=1, ascending=False, method="first")
        # shift(1): the decision on bar t uses the ranking formed at t-1, i.e. strictly
        # information that existed before the bar being traded. Costs one bar of latency and
        # removes any argument about same-bar leakage.
        return ranks.shift(1)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        lb = self.lookback.value
        ranks = self._ranks(lb, max_date=dataframe['date'].max())
        # never let the cross-section see past the end of the window being analysed
        if not ranks.empty:
            ranks = ranks.loc[ranks.index <= dataframe["date"].max()]

        dataframe["xs_rank"] = np.nan
        if not ranks.empty and pair in ranks.columns:
            r = ranks[pair].rename("xs_rank")
            dataframe = dataframe.merge(r, how="left", left_on="date", right_index=True,
                                        suffixes=("_drop", ""))
            if "xs_rank_drop" in dataframe:
                dataframe = dataframe.drop(columns=["xs_rank_drop"])

        # realised volatility, used for position sizing (R4)
        dataframe["ret"] = dataframe["close"].pct_change()
        dataframe["rvol"] = dataframe["ret"].rolling(30).std() * np.sqrt(365)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["xs_rank"] <= self.top_k.value)
            & (dataframe["xs_rank"].notna())
            & (dataframe["volume"] > 0),
            "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Leaving the top-k is the exit. Nothing else.
        dataframe.loc[
            (dataframe["xs_rank"] > self.top_k.value) & (dataframe["xs_rank"].notna()),
            "exit_long"] = 1
        return dataframe

    # ---- R4: volatility-targeted sizing -------------------------------------------------
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
