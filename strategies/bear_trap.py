import pandas as pd
import numpy as np
from indicators.ta import sma, ema, macd, kline_overlap


class TrapStrategy:
    def __init__(self, df_1m: pd.DataFrame):
        """
        df_1m: 1分钟行情数据，必须包含 [open, high, low, close]
        index: DatetimeIndex
        """
        self.df_1m = df_1m.copy()
        self.df_1m = self.df_1m.sort_index()
        self._prepare_multi_timeframes()

    def _prepare_multi_timeframes(self):
        # === 5分钟周期 ===
        self.df_5m = self.df_1m.resample("5min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        # === 30分钟周期 ===
        self.df_30m = self.df_1m.resample("30min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        # 大周期 overlap
        self.df_30m["overlap3"] = kline_overlap(self.df_30m, 3)

        # 中周期 MA 波动范围 + X
        self.df_5m["sma5"] = sma(self.df_5m["close"], 5)
        self.df_5m["ma_range20"] = (
            self.df_5m["sma5"].rolling(20).max() - self.df_5m["sma5"].rolling(20).min()
        )
        self.df_5m["X"] = (self.df_5m["high"] - self.df_5m["low"]).rolling(20).mean()

        # 中周期 MACD (只用 DIF)
        macd_df = macd(self.df_5m["close"])
        self.df_5m["dif"] = macd_df["macd"]

        # 小周期 overlap
        self.df_1m["overlap3"] = kline_overlap(self.df_1m, 3)

        # 将 5m/30m 对齐到 1m 索引
        self.df5_for_1m = self.df_5m.reindex(self.df_1m.index, method="ffill")
        self.df30_for_1m = self.df_30m.reindex(self.df_1m.index, method="ffill")

    def run(self, multiplier=300):
        """
        执行策略，返回交易明细和权益曲线
        """
        trades = []
        equity_curve = []
        cash = 1_000_000
        pos = None
        cooldown = 0  # 冷却计数 (单位: 1分钟bar)

        idx = self.df_1m.index
        for i in range(len(idx) - 1):  # 最后一根不能开仓，因为没有下一根成交
            ts = idx[i]
            row1 = self.df_1m.loc[ts]
            row5 = self.df5_for_1m.loc[ts]
            row30 = self.df30_for_1m.loc[ts]

            # === 持仓处理 ===
            if pos is not None:
                pos["bars_held"] += 1
                if pos["bars_held"] >= 20:  # 持仓满20根bar强平
                    exit_time = ts
                    exit_price = row1["close"]  # 当前收盘价平仓
                    pnl = (exit_price - pos["entry_price"]) * multiplier
                    cash += pnl
                    trades.append({
                        "open_time": pos["entry_time"],
                        "open_price": pos["entry_price"],
                        "close_time": exit_time,
                        "close_price": exit_price,
                        "pnl": pnl
                    })
                    pos = None
                    cooldown = 5  # 冷却5根bar
                continue

            # === 空仓，处理冷却 ===
            if cooldown > 0:
                cooldown -= 1
                continue

            # === 开仓条件 ===
            cond1 = self.df30_for_1m.loc[:ts].tail(6)["overlap3"].sum() >= 3
            cond2 = (row5["ma_range20"] >= 1.5 * row5["X"]) if pd.notna(row5["X"]) else False
            dif10 = self.df5_for_1m.loc[:ts].tail(10)["dif"].min()
            dif40 = self.df5_for_1m.loc[:ts].tail(40)["dif"].min()
            cond4 = (dif10 >= 1.2 * dif40) if pd.notna(dif10) and pd.notna(dif40) else False
            high20_prev = self.df_1m.loc[:ts].iloc[:-1].tail(20)["high"].max()
            cond5 = (high20_prev - row1["close"]) >= row5["X"] if pd.notna(row5["X"]) else False
            cond6 = self.df_1m.loc[:ts].tail(20)["overlap3"].sum() >= 7

            if cond1 and cond2 and cond4 and cond5 and cond6:
                # === 用当前收盘判定，下一根开盘成交 ===
                entry_time = idx[i + 1]
                entry_price = self.df_1m.loc[entry_time, "open"]
                pos = {
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "bars_held": 0
                }

            # 记录权益
            equity_curve.append((ts, cash))

        equity_df = pd.DataFrame(equity_curve, columns=["datetime", "equity"]).set_index("datetime")
        trades_df = pd.DataFrame(trades)
        return trades_df, equity_df
