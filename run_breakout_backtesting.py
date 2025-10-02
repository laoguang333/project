# -*- coding: utf-8 -*-
import pandas as pd
from backtesting import Backtest

from strategies.breakout import BreakoutStrategy, prepare_breakout_features

DATA_PATH = "data/IF9999.CCFX.csv"


def load_if_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').set_index('date')
    df = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return df


def main():
    df = load_if_data(DATA_PATH)
    df = prepare_breakout_features(df)
    bt = Backtest(df, BreakoutStrategy, cash=1_000_000, commission=0.0)
    stats = bt.run()
    print(stats)
    # bt.plot(resample=False, open_browser=False)


if __name__ == "__main__":
    main()
