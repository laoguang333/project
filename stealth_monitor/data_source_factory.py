"""Data source factory for selecting between different data loading strategies."""
from __future__ import annotations
from typing import Callable, Dict, Optional
import pandas as pd

from .config import Instrument, Timeframe
from .data_sources import fetch_data as original_fetch_data

# 可选的数据源策略
DataSourceStrategy = Callable[[Instrument, Timeframe, Optional[int], str], pd.DataFrame]

# 默认使用原始数据源
_current_strategy: str = "original"

# 数据源策略映射
_strategies: Dict[str, DataSourceStrategy] = {
    "original": original_fetch_data
}

def register_strategy(name: str, strategy: DataSourceStrategy) -> None:
    """注册新的数据源策略"""
    _strategies[name] = strategy


def set_strategy(name: str) -> None:
    """设置当前使用的数据源策略"""
    global _current_strategy
    if name not in _strategies:
        available = ", ".join(_strategies.keys())
        raise ValueError(f"未知的数据源策略: {name}。可用策略: {available}")
    _current_strategy = name


def get_current_strategy() -> str:
    """获取当前使用的数据源策略"""
    return _current_strategy


def get_available_strategies() -> list:
    """获取所有可用的数据源策略"""
    return list(_strategies.keys())


def fetch_data(
    instrument: Instrument,
    timeframe: Timeframe,
    *, 
    limit: Optional[int] = 200,
    adjust: str = "",
) -> pd.DataFrame:
    """使用当前选择的策略获取数据"""
    strategy = _strategies[_current_strategy]
    return strategy(instrument, timeframe, limit=limit, adjust=adjust)

# 尝试导入并注册缓存数据源策略
try:
    from .cached_data_sources import fetch_data_with_cache, configure_cache, clear_cache, get_cache_info
    register_strategy("hybrid_cache", fetch_data_with_cache)
    # 提供访问缓存相关功能的方法
    cache_functions = {
        "configure": configure_cache,
        "clear": clear_cache,
        "info": get_cache_info
    }

except ImportError as e:
    # 如果无法导入缓存模块，不影响原有功能
    print(f"无法导入缓存数据源模块: {e}")
    cache_functions = None


# 提供便捷的配置接口
def use_original_data_source() -> None:
    """使用原始的无缓存数据源"""
    set_strategy("original")


def use_hybrid_cache() -> None:
    """使用混合缓存数据源（内存+SQLite）"""
    if "hybrid_cache" in _strategies:
        set_strategy("hybrid_cache")
    else:
        raise ValueError("混合缓存策略不可用。请确保cached_data_sources模块能够正确导入。")


def configure_hybrid_cache(**kwargs) -> None:
    """配置混合缓存参数"""
    if cache_functions and "configure" in cache_functions:
        cache_functions["configure"](**kwargs)
    else:
        raise ValueError("缓存配置功能不可用。请确保cached_data_sources模块能够正确导入。")


def clear_hybrid_cache(clear_memory: bool = True, clear_sqlite: bool = False) -> None:
    """清除混合缓存数据"""
    if cache_functions and "clear" in cache_functions:
        cache_functions["clear"](clear_memory, clear_sqlite)
    else:
        raise ValueError("缓存清理功能不可用。请确保cached_data_sources模块能够正确导入。")


def get_hybrid_cache_info() -> Dict:
    """获取混合缓存状态信息"""
    if cache_functions and "info" in cache_functions:
        return cache_functions["info"]()
    else:
        raise ValueError("缓存信息功能不可用。请确保cached_data_sources模块能够正确导入。")