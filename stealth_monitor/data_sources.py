# -*- coding: utf-8 -*-
"""Data loaders unified across instruments and timeframes."""
from __future__ import annotations

from typing import Optional

import akshare as ak
import pandas as pd

from .config import Instrument, Timeframe


def fetch_data(
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    limit: Optional[int] = 200,
    adjust: str = "",
) -> pd.DataFrame:
    """Return OHLCV dataframe normalized to common schema."""
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
