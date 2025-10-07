# -*- coding: utf-8 -*-
"""Data loaders unified across instruments and timeframes."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

try:
    import akshare as ak
except ImportError:  # pragma: no cover - optional dependency
    ak = None

from .config import Instrument, Timeframe


def fetch_data(
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    limit: Optional[int] = 200,
    adjust: str = "",
) -> pd.DataFrame:
    """Return OHLCV dataframe normalized to common schema."""
    if ak is None:
        return _generate_placeholder_data(instrument, timeframe, limit=limit)

    if instrument.kind == "futures":
        if timeframe.category == "minute":
            df = ak.futures_zh_minute_sina(symbol=instrument.symbol, period=timeframe.value)
        else:
            df = ak.futures_zh_daily_sina(symbol=instrument.symbol)
    elif instrument.kind == "stock":
        if timeframe.category == "minute":
            df = ak.stock_zh_a_minute(symbol=instrument.symbol, period=timeframe.value, adjust=adjust)
        else:
            df = ak.stock_zh_a_daily(symbol=instrument.symbol, start_date="19900101", end_date="21001231", adjust=adjust)
    else:  # pragma: no cover - defensive branch
        raise ValueError(f"Unsupported instrument kind: {instrument.kind}")

    df = _normalize_dataframe(df, timeframe)
    if limit:
        df = df.tail(limit)
    return df


def _normalize_dataframe(df: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    df = df.copy()

    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
    elif "day" in df.columns:
        df["datetime"] = pd.to_datetime(df["day"])
    elif "date" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"])
    else:
        raise ValueError("Dataframe missing datetime column")

    rename_map = {col: col.lower() for col in ["Open", "High", "Low", "Close", "Volume"] if col in df.columns}
    if rename_map:
        df = df.rename(columns=rename_map)

    lower_map = {col: col.lower() for col in ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"] if col in df.columns}
    if lower_map:
        df = df.rename(columns=lower_map)

    df.columns = [c.lower() for c in df.columns]

    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"Column '{col}' missing from data")

    if "volume" not in df.columns:
        df["volume"] = df.get("vol", df.get("volume", 0))

    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("datetime")
    return df.reset_index(drop=True)


def _generate_placeholder_data(
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    limit: Optional[int],
) -> pd.DataFrame:
    """Fallback dataset when akshare is unavailable."""
    size = limit or 200
    freq = _infer_freq(timeframe)
    index = pd.date_range(end=pd.Timestamp.utcnow(), periods=size, freq=freq)
    seed = abs(hash((instrument.key, timeframe.key))) % (2**32)
    rng = np.random.default_rng(seed)

    base = np.linspace(0, 4 * np.pi, size)
    center = 100 + rng.normal(scale=0.5)
    close = center + np.sin(base) * 2 + rng.normal(scale=0.4, size=size)
    open_ = close + rng.normal(scale=0.2, size=size)
    high = np.maximum(open_, close) + rng.random(size) * 0.6
    low = np.minimum(open_, close) - rng.random(size) * 0.6
    volume = rng.integers(500, 2500, size=size)

    df = pd.DataFrame(
        {
            "datetime": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return df.reset_index(drop=True)


def _infer_freq(timeframe: Timeframe) -> str:
    if timeframe.category == "minute":
        try:
            minutes = int(timeframe.value)
        except ValueError:
            minutes = 1
        return f"{minutes}T"
    return "1D"
