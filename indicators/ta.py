import pandas as pd

def sma(series: pd.Series, n: int) -> pd.Series:
    """简单移动平均"""
    return series.rolling(window=n, min_periods=1).mean()

def ema(series: pd.Series, n: int) -> pd.Series:
    """指数移动平均"""
    return series.ewm(span=n, adjust=False).mean()