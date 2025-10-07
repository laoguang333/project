# -*- coding: utf-8 -*-
"""Factory utilities for switching between different data loading strategies."""
from __future__ import annotations

from typing import Dict, Optional, Protocol

import pandas as pd

from .config import Instrument, Timeframe
from .data_sources import fetch_data as _original_fetch_data


class DataSourceStrategy(Protocol):
    """Callable signature for data loading strategies."""

    def __call__(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        limit: Optional[int] = 200,
        adjust: str = "",
    ) -> pd.DataFrame:
        ...


_strategies: Dict[str, DataSourceStrategy] = {"original": _original_fetch_data}
_current_strategy: str = "original"


def register_strategy(name: str, strategy: DataSourceStrategy) -> None:
    """Register a new data source strategy."""
    _strategies[name] = strategy


def set_strategy(name: str) -> None:
    """Switch to a registered strategy by name."""
    if name not in _strategies:
        available = ", ".join(sorted(_strategies))
        raise ValueError(f"Unknown data source strategy '{name}'. Available: {available}")
    global _current_strategy
    _current_strategy = name


def get_current_strategy() -> str:
    """Return the name of the active strategy."""
    return _current_strategy


def get_available_strategies() -> list[str]:
    """Return the names of registered strategies."""
    return sorted(_strategies)


def fetch_data(
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    limit: Optional[int] = 200,
    adjust: str = "",
) -> pd.DataFrame:
    """Fetch data using the active strategy."""
    strategy = _strategies[_current_strategy]
    return strategy(instrument, timeframe, limit=limit, adjust=adjust)


try:
    from .cached_data_sources import (
        configure_cache,
        clear_cache,
        fetch_data_with_cache,
        get_cache_info,
    )

    register_strategy("hybrid_cache", fetch_data_with_cache)
    _cache_helpers = {
        "configure": configure_cache,
        "clear": clear_cache,
        "info": get_cache_info,
    }
except Exception:  # pragma: no cover - keep original behaviour when cache import fails
    _cache_helpers = None


def use_original_data_source() -> None:
    """Switch back to the original non-cached data source."""
    set_strategy("original")


def use_hybrid_cache() -> None:
    """Enable the hybrid cache data source if it is available."""
    if "hybrid_cache" not in _strategies:
        raise ValueError("Hybrid cache strategy is unavailable.")
    set_strategy("hybrid_cache")


def configure_hybrid_cache(**kwargs) -> None:
    """Configure cache parameters for the hybrid cache strategy."""
    if not _cache_helpers or "configure" not in _cache_helpers:
        raise ValueError("Cache configuration is unavailable.")
    _cache_helpers["configure"](**kwargs)


def clear_hybrid_cache(clear_memory: bool = True, clear_sqlite: bool = False) -> None:
    """Clear cached data."""
    if not _cache_helpers or "clear" not in _cache_helpers:
        raise ValueError("Cache clearing is unavailable.")
    _cache_helpers["clear"](clear_memory, clear_sqlite)


def get_hybrid_cache_info() -> Dict:
    """Return diagnostic information for the hybrid cache."""
    if not _cache_helpers or "info" not in _cache_helpers:
        raise ValueError("Cache diagnostics are unavailable.")
    return _cache_helpers["info"]()
