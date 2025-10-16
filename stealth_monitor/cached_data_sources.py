"""Data loaders with lightweight in-memory caching support."""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import pandas as pd

from .config import Instrument, Timeframe

# In-memory cache only, default expiry 3 minutes
CACHE_CONFIG = {
    "enabled": True,
    "memory_cache_timeout_seconds": 180,
}

_data_cache: Dict[Tuple[str, str, str], Tuple[float, pd.DataFrame]] = {}


def fetch_data_with_cache(
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    limit: Optional[int] = 200,
    adjust: str = "",
) -> pd.DataFrame:
    """Return OHLCV data using a short-lived in-memory cache."""
    from .data_sources import fetch_data as original_fetch_data, DataFetchError

    cache_key = (instrument.key, timeframe.key, adjust)
    current_time = time.time()

    cache_entry = _data_cache.get(cache_key) if CACHE_CONFIG["enabled"] else None

    # 1. Cache hit within expiry window -> return directly
    if cache_entry:
        cache_time, cached_frame = cache_entry
        if current_time - cache_time < CACHE_CONFIG["memory_cache_timeout_seconds"]:
            result_df = cached_frame.copy()
            if limit and len(result_df) > limit:
                result_df = result_df.tail(limit)
            return result_df.reset_index(drop=True)

    # 2. Cache miss or expired -> fetch live data
    try:
        live_df = original_fetch_data(instrument, timeframe, limit=limit, adjust=adjust)
    except DataFetchError:
        raise
    except Exception as exc:  # normalize unexpected errors
        raise DataFetchError(
            f"Fetch failed for {instrument.label} {timeframe.label}: {exc}"
        ) from exc

    if live_df.empty:
        raise DataFetchError(f"No data available for {instrument.label} {timeframe.label}")

    result_df = live_df.copy()
    if limit and len(result_df) > limit:
        result_df = result_df.tail(limit)
    if CACHE_CONFIG["enabled"]:
        _data_cache[cache_key] = (current_time, result_df.copy())
    return result_df.reset_index(drop=True)


def clear_cache(clear_memory: bool = True, clear_sqlite: bool = False) -> None:
    """Clear cached data (memory cache only)."""
    global _data_cache
    if clear_memory and CACHE_CONFIG["enabled"]:
        _data_cache.clear()


def configure_cache(**kwargs) -> None:
    """Configure cache parameters."""
    for key, value in kwargs.items():
        if key in CACHE_CONFIG:
            CACHE_CONFIG[key] = value


def get_cache_info() -> Dict:
    """Return cache diagnostics."""
    return {
        "enabled": CACHE_CONFIG["enabled"],
        "memory_cache_timeout_seconds": CACHE_CONFIG["memory_cache_timeout_seconds"],
        "memory_cache_size": len(_data_cache),
    }
