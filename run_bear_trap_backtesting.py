# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from indicators.ta import sma, macd, kline_overlap
from backtesting import Backtest, Strategy

DATA_PATH = 'data/IF9999.CCFX.csv'


def load_if_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').set_index('date')
    df = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return df


def prepare_bear_trap_features(df: pd.DataFrame) -> pd.DataFrame:
    base = df.copy()
    lower = base.rename(columns={c: c.lower() for c in base.columns})
    # 1分钟 overlap
    overlap1m = kline_overlap(lower[['high', 'low']], lookback=3).fillna(0).astype(int)
    base['overlap3_1m'] = overlap1m

    # 5分钟数据
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    df_5m = lower.resample('5min', label='right', closed='right').agg(agg).dropna()
    df_5m['sma5'] = sma(df_5m['close'], 5)
    df_5m['ma_range20'] = df_5m['sma5'].rolling(20, min_periods=20).max() - df_5m['sma5'].rolling(20, min_periods=20).min()
    df_5m['X'] = (df_5m['high'] - df_5m['low']).rolling(20, min_periods=20).mean()
    macd_df = macd(df_5m['close'])
    df_5m['dif'] = macd_df['macd']
    df_5m['dif_min10'] = df_5m['dif'].rolling(10, min_periods=10).min()
    df_5m['dif_min40_prev'] = df_5m['dif'].shift(10).rolling(40, min_periods=40).min()

    feats_5m = df_5m[['ma_range20', 'X', 'dif', 'dif_min10', 'dif_min40_prev']].reindex(base.index, method='ffill')
    base[['ma_range20', 'X', 'dif', 'dif_min10', 'dif_min40_prev']] = feats_5m

    # 30分钟数据
    df_30m = lower.resample('30min', label='right', closed='right').agg(agg).dropna()
    df_30m['overlap3'] = kline_overlap(df_30m[['high', 'low']], lookback=3).fillna(0)
    df_30m['overlap3_sum4'] = df_30m['overlap3'].rolling(4, min_periods=4).sum()
    feats_30m = df_30m[['overlap3', 'overlap3_sum4']].reindex(base.index, method='ffill')
    base[['overlap3_30m', 'overlap3_sum4']] = feats_30m

    # Additional rolling metrics
    base['overlap3_sum20'] = base['overlap3_1m'].rolling(20, min_periods=20).sum()
    base['high20_prev'] = base['High'].shift(1).rolling(20, min_periods=20).max()

    # Conditions stored for quick lookup
    base['cond1'] = base['overlap3_sum4'] >= 3
    base['cond2'] = base['ma_range20'] >= 1.5 * base['X']
    base['cond4'] = base['dif_min10'] >= 1.2 * base['dif_min40_prev']
    base['cond5'] = (base['high20_prev'] - base['Close']) >= base['X']
    base['cond6'] = base['overlap3_sum20'] >= 7

    # Overlap-based smoothness score for current bar (C) versus previous two bars (A, B)
    high_c = base['High']
    low_c = base['Low']
    range_c = (high_c - low_c).clip(lower=0)

    high_a = high_c.shift(2)
    low_a = low_c.shift(2)
    high_b = high_c.shift(1)
    low_b = low_c.shift(1)

    def pair_overlap(h1, l1, h2, l2):
        return (pd.concat([h1, h2], axis=1).min(axis=1) - pd.concat([l1, l2], axis=1).max(axis=1)).clip(lower=0)

    overlap_ac = pair_overlap(high_a, low_a, high_c, low_c)
    overlap_bc = pair_overlap(high_b, low_b, high_c, low_c)
    overlap_abc = (pd.concat([high_a, high_b, high_c], axis=1).min(axis=1) -
                   pd.concat([low_a, low_b, low_c], axis=1).max(axis=1)).clip(lower=0)

    s = (range_c - overlap_abc).clip(lower=0)
    denom = range_c.replace(0, np.nan)

    x_norm = (overlap_ac / denom).fillna(0)
    y_norm = (overlap_bc / denom).fillna(0)
    z_norm = (overlap_abc / denom).fillna(0)
    s_norm = (s / denom).fillna(0)

    alpha = 0.2
    beta = 0.4
    score_norm = s_norm - alpha * (x_norm + y_norm) - beta * z_norm
    base['overlap_score'] = score_norm * range_c

    return base


class BearTrapStrategy(Strategy):
    direction = 'long'
    hold_bars = 20
    cooldown_bars = 5
    size = 1

    def init(self):
        self.df = self.data.df
        self.overlap_score_indicator = self.I(lambda: self.df['overlap_score'].fillna(0).to_numpy(), name='overlap_score')
        self.macd_dif_indicator = self.I(lambda: self.df['dif'].fillna(0).to_numpy(), name='macd_dif')
        self.ma_range_indicator = self.I(lambda: self.df['ma_range20'].fillna(0).to_numpy(), name='ma_range20')
        self.high20_diff_indicator = self.I(lambda: (self.df['high20_prev'] - self.df['Close']).fillna(0).to_numpy(), name='high20_diff')
        self.cooldown = 0
        self.hold_counter = 0
        self.direction = self.direction.lower()
        if self.direction not in ('long', 'short'):
            raise ValueError("direction must be 'long' or 'short'")

    def next(self):
        i = len(self.data) - 1
        if i < 40:
            return

        if self.position:
            self.hold_counter += 1
            if self.hold_counter >= self.hold_bars:
                self.position.close()
                self.cooldown = self.cooldown_bars
                self.hold_counter = 0
            return

        if self.cooldown > 0:
            self.cooldown -= 1
            return

        ts = self.data.index[-1]
        row = self.df.loc[ts]
        if not (row['cond1'] and row['cond2'] and row['cond4'] and row['cond5'] and row['cond6']):
            return

        if pd.isna(row[['ma_range20', 'X', 'dif_min10', 'dif_min40_prev', 'high20_prev']]).any():
            return

        if self.direction == 'long':
            self.buy(size=self.size)
        else:
            self.sell(size=self.size)
        self.hold_counter = 0


def main():
    df = load_if_data(DATA_PATH)
    df = prepare_bear_trap_features(df)
    bt = Backtest(df, BearTrapStrategy, cash=1_000_000, commission=0.0)
    stats = bt.run()
    print(stats)


if __name__ == '__main__':
    main()
