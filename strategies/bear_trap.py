"""
空头陷阱买入策略（TrapStrategy）

周期：
- 小周期：1分钟
- 中周期：5分钟
- 大周期：30分钟
输入数据：仅有1分钟K线（open, high, low, close, volume），内部生成多周期数据。

开仓条件（全部满足才买入）：
1. 大周期过去6根K线中，至少有3根存在重叠区间（使用3K重叠判断）。
2. 中周期过去20根K线的5均线波动范围 >= 1.5 × 过去20根K线的平均振幅X，
   其中 X = mean(high - low)。
3. （条件编号3为空）
4. 中周期DIF（MACD快慢线差值）：
   过去10根的最低值 >= 过去40根的最低值 × 1.2。
5. 小周期过去20根最高点 - 当前收盘价 >= X（即收盘价“跌破”X，制造空头陷阱）。
6. 小周期过去20根K线中，至少7根满足3K重叠。

执行逻辑：
- 信号由当前K线收盘判定，下一根K线开盘价执行开仓。
- 每次开仓持有20根1分钟K线，到期后在当根收盘价平仓。
- 平仓后进入冷却期5根1分钟K线，期间禁止再次开仓。

输出：
- trades：开平仓明细（open_time, open_price, close_time, close_price, pnl）
- equity：权益曲线（按1分钟粒度记录现金账户变化）

注意事项：
- 多周期数据通过resample从1分钟数据生成。
- 条件计算均避免“未来函数”，使用收盘判定、下一根执行。
- 策略为示例用途，可扩展止损/加仓/资金管理等功能。
"""

import pandas as pd
from backtest_framework import Strategy, Order, Position
from indicators.ta import sma, ema, macd, kline_overlap


class TrapStrategy(Strategy):
    def __init__(self, params=None):
        params = params or {}
        super().__init__(params)
        self.params = params
        self.direction = self.params.get("direction", "long").lower()
        if self.direction not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")
        self.hold_bars = int(self.params.get("hold_bars", 20))
        self.cooldown_bars = int(self.params.get("cooldown_bars", 5))
        self.cooldown = 0  # 冷却计数 (单位: 1分钟bar)
        self.position_bars_held = 0  # 记录持仓bar数
    def init(self, data: pd.DataFrame):
        # 准备多周期数据
        self.cooldown = 0
        self.position_bars_held = 0
        self.df_1m = data.copy()
        self.df_1m = self.df_1m.sort_index()
        self._prepare_multi_timeframes()
    def _prepare_multi_timeframes(self):
        # === 5分钟周期 ===
        self.df_5m = self.df_1m.resample("5min", label="right", closed="right").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        # === 30分钟周期 ===
        self.df_30m = self.df_1m.resample("30min", label="right", closed="right").agg({
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

    def on_bar(self, i: int, row: pd.Series, pos: Position) -> list:
        orders = []

        # 确保有足够的数据进行计算
        if i < 40 or i >= len(self.df_1m) - 1:
            return orders

        # 持仓处理（多空通用）
        if pos.contracts != 0:
            self.position_bars_held += 1
            if self.position_bars_held >= self.hold_bars:
                exit_side = "SELL" if pos.contracts > 0 else "BUY"
                orders.append(Order(side=exit_side, size=abs(pos.contracts), reason=f"hold_{self.hold_bars}_bars_exit"))
                self.position_bars_held = 0
                self.cooldown = self.cooldown_bars
            return orders

        # 空仓，处理冷却
        if self.cooldown > 0:
            self.cooldown -= 1
            return orders

        # 开仓条件检查
        ts = self.df_1m.index[i]
        row1 = self.df_1m.iloc[i]
        row5 = self.df5_for_1m.iloc[i]

        # 条件1
        recent_30m = self.df_30m.loc[:ts].tail(4)
        cond1 = len(recent_30m) == 4 and recent_30m["overlap3"].fillna(0).sum() >= 3

        # 条件2
        cond2 = (row5["ma_range20"] >= 1.5 * row5["X"]) if pd.notna(row5["X"]) else False

        # 条件4
        dif10 = self.df5_for_1m.iloc[max(0, i-9):i+1]["dif"].min()
        dif40 = self.df5_for_1m.iloc[max(0, i-39):i+1]["dif"].min()
        cond4 = (dif10 >= 1.2 * dif40) if pd.notna(dif10) and pd.notna(dif40) else False

        # 条件5
        high20_prev = self.df_1m.iloc[max(0, i-20):i]["high"].max()
        cond5 = (high20_prev - row1["close"]) >= row5["X"] if pd.notna(row5["X"]) else False

        # 条件6
        cond6 = self.df_1m.iloc[max(0, i-19):i+1]["overlap3"].sum() >= 7

        # 所有条件满足时开仓
        if cond1 and cond2 and cond4 and cond5 and cond6:
            contracts = int(self.params.get("contracts", 1))
            side = "BUY" if self.direction == "long" else "SELL"
            reason = "bear_trap_long_entry" if self.direction == "long" else "bear_trap_short_entry"
            orders.append(Order(side=side, size=contracts, reason=reason))
            self.position_bars_held = 0

        return orders


class TrapStrategyShort(TrapStrategy):
    def __init__(self, params=None):
        params = dict(params or {})
        params.setdefault("direction", "short")
        super().__init__(params)
