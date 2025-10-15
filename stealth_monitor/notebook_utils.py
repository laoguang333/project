# -*- coding: utf-8 -*-
"""Helper utilities shared by notebooks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

# 修改相对导入为绝对导入
import sys
import os
# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))

from config import INSTRUMENT_INDEX, TIMEFRAME_INDEX, Instrument, Timeframe
from data_source_factory import (
    fetch_data as _factory_fetch_data,
    use_hybrid_cache,
    use_original_data_source,
)


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
    return df.reset_index(drop=True)
