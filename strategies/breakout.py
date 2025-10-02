# -*- coding: utf-8 -*-
"""Breakout strategy based on 30-minute SMA direction and 5-minute range expansion."""

from typing import Optional

import numpy as np
import pandas as pd
from backtesting import Strategy
from indicators.ta import macd


def prepare_breakout_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return copy of df with multi-timeframe features for the breakout strategy."""
    base = df.copy().sort_index()
    lower = base.rename(columns={c: c.lower() for c in base.columns})

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    # 30-minute SMA direction
    df_30m = (
        lower
        .resample("30min", label="right", closed="right")
        .agg(agg)
        .dropna()
    )
    df_30m["sma20"] = df_30m["close"].rolling(20, min_periods=20).mean()
    df_30m["sma20_prev"] = df_30m["sma20"].shift(1)
    df_30m["sma20_slope"] = df_30m["sma20"] - df_30m["sma20_prev"]
    feats_30m = df_30m[["sma20", "sma20_prev", "sma20_slope"]].reindex(base.index, method="ffill")
    base[["sma20_30m", "sma20_30m_prev", "sma20_slope"]] = feats_30m
    base["cond_sma_flat_up"] = feats_30m["sma20_slope"] >= 0

    # 5-minute features and breakout reference
    df_5m = (
        lower
        .resample("5min", label="right", closed="right")
        .agg(agg)
        .dropna()
    )
    df_5m["sma5"] = df_5m["close"].rolling(5, min_periods=5).mean()
    df_5m["ma_range20"] = df_5m["sma5"].rolling(20, min_periods=20).max() - df_5m["sma5"].rolling(20, min_periods=20).min()
    macd_df = macd(df_5m["close"])
    df_5m["dif"] = macd_df["macd"]
    df_5m["prev2_high"] = df_5m["high"].shift(1).rolling(2, min_periods=2).max()
    feats_5m = df_5m[["prev2_high", "ma_range20", "dif"]].reindex(base.index, method="ffill")
    base[["prev2_5m_high", "ma_range20", "dif"]] = feats_5m

    base["high20_prev"] = base["High"].shift(1).rolling(20, min_periods=20).max()

    block_id_series = pd.Series(base.index.floor("5min"), index=base.index, name="block_id")
    block_pos = ((base.index - block_id_series) / pd.Timedelta(minutes=1)).astype(int)
    base["block_id"] = block_id_series
    base["block_pos"] = block_pos

    close_gt_prev_high = base["Close"] > base["prev2_5m_high"]
    same_block_prev = block_id_series.eq(block_id_series.shift(1))
    last_two_minutes = (block_pos >= 3) & (block_pos.shift(1) >= 3)
    breakout_cond = (
        last_two_minutes
        & same_block_prev
        & close_gt_prev_high
        & close_gt_prev_high.shift(1)
        & base["prev2_5m_high"].notna()
    )
    base["cond_breakout"] = breakout_cond.fillna(False)

    return base


class BreakoutStrategy(Strategy):
    hold_bars = 20
    size = 1

    def init(self):
        self.df = self.data.df
        self.hold_counter = 0
        self.last_entry_block: Optional[pd.Timestamp] = None

        self.macd_dif_indicator = self.I(
            lambda: self.df["dif"].fillna(0).to_numpy(),
            name="macd_dif",
        )
        self.ma_range_indicator = self.I(
            lambda: self.df["ma_range20"].fillna(0).to_numpy(),
            name="ma_range20",
        )
        self.high20_diff_indicator = self.I(
            lambda: (self.df["high20_prev"] - self.df["Close"]).fillna(0).to_numpy(),
            name="high20_diff",
        )

    def next(self):
        i = len(self.data) - 1
        if i < 1:
            return

        if self.position:
            self.hold_counter += 1
            if self.hold_counter >= self.hold_bars:
                self.position.close()
                self.hold_counter = 0
            return

        row = self.df.iloc[i]
        curr_block = row.get("block_id")

        if not row.get("cond_sma_flat_up", False):
            return
        if not row.get("cond_breakout", False):
            return
        if pd.isna(curr_block):
            return
        if self.last_entry_block is not None and curr_block == self.last_entry_block:
            return

        self.buy(size=self.size)
        self.hold_counter = 0
        self.last_entry_block = curr_block
