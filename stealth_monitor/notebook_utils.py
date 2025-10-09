# -*- coding: utf-8 -*-
"""Helper utilities shared by notebooks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from .config import INSTRUMENT_INDEX, TIMEFRAME_INDEX, Instrument, Timeframe
from .data_source_factory import (
    fetch_data as _factory_fetch_data,
    use_hybrid_cache,
    use_original_data_source,
)

from .data_sources import DataFetchError


@dataclass(frozen=True)
class TimeframePlan:
    """Notebook-friendly timeframe descriptor."""

    base_key: str
    resample_rule: Optional[str] = None
    limit_multiplier: int = 1


def _apply_cache_strategy(prefer_cache: bool) -> None:
    if prefer_cache:
        try:
            use_hybrid_cache()
            return
        except ValueError:
            pass
    use_original_data_source()


_DEF_TZ = 'Asia/Shanghai'
_DEF_TOLERANCE_FACTOR = 3


def _compute_interval_ms(base_timeframe: Timeframe, plan: TimeframePlan) -> int:
    interval_ms = getattr(base_timeframe, 'duration_ms', 60_000) or 60_000
    multiplier = max(plan.limit_multiplier, 1)
    if plan.resample_rule:
        try:
            delta = pd.to_timedelta(plan.resample_rule)
            if pd.isna(delta):
                raise ValueError
            interval_ms = int(delta.total_seconds() * 1000)
        except Exception:  # pragma: no cover - fallback for unusual rules
            interval_ms *= multiplier
    return max(int(interval_ms * multiplier), interval_ms)


def _ensure_fresh_data(
    df: pd.DataFrame,
    instrument: Instrument,
    timeframe: Timeframe,
    plan: TimeframePlan,
) -> None:
    if df.empty:
        raise DataFetchError(f"{instrument.label} {timeframe.label} data frame is empty")
    interval_ms = _compute_interval_ms(timeframe, plan)
    tolerance = pd.to_timedelta(interval_ms * _DEF_TOLERANCE_FACTOR, unit='ms')
    last_ts = pd.to_datetime(df['datetime'].iloc[-1])
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(_DEF_TZ)
    else:
        last_ts = last_ts.tz_convert(_DEF_TZ)
    now_ts = pd.Timestamp.now(tz=_DEF_TZ)
    if now_ts - last_ts > tolerance:
        raise DataFetchError(
            f"{instrument.label} {timeframe.label} latest bar {last_ts} exceeds allowed delay {tolerance}"
        )


def load_market_data(
    instrument_key: str,
    plan: TimeframePlan,
    *,
    limit: int = 200,
    adjust: str = "",
    prefer_cache: bool = True,
) -> pd.DataFrame:
    """Load market data using a timeframe plan, optionally resampling."""
    _apply_cache_strategy(prefer_cache)

    instrument: Instrument = INSTRUMENT_INDEX[instrument_key]
    base_timeframe: Timeframe = TIMEFRAME_INDEX[plan.base_key]
    base_limit = limit * max(plan.limit_multiplier, 1)
    df = _factory_fetch_data(instrument, base_timeframe, limit=base_limit, adjust=adjust)

    if plan.resample_rule:
        df = (
            df.set_index("datetime")
            .resample(plan.resample_rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
            .reset_index()
        )

    if limit:
        df = df.tail(limit)
    _ensure_fresh_data(df, instrument, base_timeframe, plan)
    return df.reset_index(drop=True)
