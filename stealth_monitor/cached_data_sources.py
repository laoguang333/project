"""Data loaders with hybrid caching support (memory + SQLite)."""
from __future__ import annotations
import os
import sqlite3
import time
from datetime import timedelta

CACHE_TIMEZONE = 'Asia/Shanghai'
from typing import Dict, Optional, Tuple
import pandas as pd

from .config import Instrument, Timeframe

# 缓存配置
CACHE_CONFIG = {
    "enabled": True,
    "memory_cache_timeout_seconds": 30,
    "sqlite_cache_enabled": True,
    "sqlite_db_path": os.path.join(os.path.dirname(__file__), "data_cache.db")
}

# 内存缓存
_data_cache: Dict[Tuple[str, str, str], Tuple[float, pd.DataFrame]] = {}


def _get_sqlite_connection() -> sqlite3.Connection:
    """获取SQLite数据库连接"""
    conn = sqlite3.connect(CACHE_CONFIG["sqlite_db_path"])
    # 初始化表结构
    with conn: 
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS instrument_data (
            instrument_key TEXT,
            timeframe_key TEXT,
            adjust TEXT,
            datetime TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (instrument_key, timeframe_key, adjust, datetime)
        )
        ''')
    return conn


def _normalize_dataframe(df: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """数据标准化（从原data_sources.py复制，确保一致性）"""
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


def fetch_data_with_cache(
    instrument: Instrument,
    timeframe: Timeframe,
    *, 
    limit: Optional[int] = 200, 
    adjust: str = "",
    # 导入原函数以避免代码复制
) -> pd.DataFrame:
    """Return OHLCV dataframe with hybrid caching support."""
    from .data_sources import fetch_data as original_fetch_data
    
    cache_key = (instrument.key, timeframe.key, adjust)
    current_time = time.time()
    
    # 1. 优先检查内存缓存
    if CACHE_CONFIG["enabled"] and cache_key in _data_cache:
        cache_time, cached_df = _data_cache[cache_key]
        if (
            current_time - cache_time < CACHE_CONFIG["memory_cache_timeout_seconds"]
            and not _is_stale(cached_df, timeframe)
        ):
            if limit and len(cached_df) > limit:
                return cached_df.tail(limit).copy()
            return cached_df.copy()
    
    # 2. 检查SQLite缓存
    if CACHE_CONFIG["sqlite_cache_enabled"]:
        try:
            conn = _get_sqlite_connection()
            query = '''
            SELECT datetime, open, high, low, close, volume 
            FROM instrument_data 
            WHERE instrument_key = ? AND timeframe_key = ? AND adjust = ?
            ORDER BY datetime DESC
            '''
            params = (instrument.key, timeframe.key, adjust)
            df_sqlite = pd.read_sql_query(query, conn, params=params)
            conn.close()
            
            if not df_sqlite.empty:
                # 转换datetime列
                df_sqlite['datetime'] = pd.to_datetime(df_sqlite['datetime'])
                # 排序
                df_sqlite = df_sqlite.sort_values('datetime')
                # 存入内存缓存
                if CACHE_CONFIG["enabled"]:
                    _data_cache[cache_key] = (current_time, df_sqlite.copy())
                # 返回数据
                if limit and len(df_sqlite) > limit:
                    return df_sqlite.tail(limit).copy()
                return df_sqlite.copy()
        except Exception as e:
            print(f"SQLite缓存读取失败: {e}")
    
    # 3. 调用原函数获取新数据
    df = original_fetch_data(instrument, timeframe, limit=None, adjust=adjust)
    
    # 4. 更新SQLite缓存
    if CACHE_CONFIG["sqlite_cache_enabled"] and not df.empty:
        try:
            conn = _get_sqlite_connection()
            # 准备写入SQLite的数据
            df_sql = df.copy()
            df_sql['instrument_key'] = instrument.key
            df_sql['timeframe_key'] = timeframe.key
            df_sql['adjust'] = adjust
            df_sql['datetime'] = df_sql['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 使用upsert方式插入或更新数据
            with conn:
                for _, row in df_sql.iterrows():
                    conn.execute(
                        '''
                        INSERT OR REPLACE INTO instrument_data 
                        (instrument_key, timeframe_key, adjust, datetime, open, high, low, close, volume) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (row['instrument_key'], row['timeframe_key'], row['adjust'], 
                         row['datetime'], row['open'], row['high'], row['low'], 
                         row['close'], row['volume'])
                    )
            conn.close()
        except Exception as e:
            print(f"SQLite缓存更新失败: {e}")
    
    # 5. 更新内存缓存
    if CACHE_CONFIG["enabled"]:
        _data_cache[cache_key] = (current_time, df.copy())
    
    # 6. 返回限制数量的数据
    if limit and len(df) > limit:
        df = df.tail(limit)
    
    return df



def _is_stale(df: pd.DataFrame, timeframe: Timeframe) -> bool:
    if df.empty:
        return True
    last_bar = pd.to_datetime(df['datetime'].iloc[-1]).tz_localize(None)
    now = pd.Timestamp.now(tz=CACHE_TIMEZONE).tz_localize(None)
    interval_ms = getattr(timeframe, 'duration_ms', 60_000) or 60_000
    tolerance = timedelta(milliseconds=interval_ms)
    return now - last_bar > tolerance


def clear_cache(clear_memory: bool = True, clear_sqlite: bool = False) -> None:
    """清除缓存数据"""
    global _data_cache
    if clear_memory and CACHE_CONFIG["enabled"]:
        _data_cache.clear()
    
    if CACHE_CONFIG["sqlite_cache_enabled"] and clear_sqlite:
        try:
            conn = _get_sqlite_connection()
            with conn:
                conn.execute("DELETE FROM instrument_data")
            conn.close()
        except Exception as e:
            print(f"SQLite缓存清理失败: {e}")


def configure_cache(**kwargs) -> None:
    """配置缓存参数"""
    for key, value in kwargs.items():
        if key in CACHE_CONFIG:
            CACHE_CONFIG[key] = value


def get_cache_info() -> Dict:
    """获取缓存状态信息"""
    current_time = time.time()
    
    # 获取SQLite缓存信息
    sqlite_info = {
        "enabled": CACHE_CONFIG["sqlite_cache_enabled"],
        "db_path": CACHE_CONFIG["sqlite_db_path"],
        "record_count": 0
    }
    
    if CACHE_CONFIG["sqlite_cache_enabled"]:
        try:
            conn = _get_sqlite_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM instrument_data")
            sqlite_info["record_count"] = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass
    
    return {
        "enabled": CACHE_CONFIG["enabled"],
        "memory_cache_timeout_seconds": CACHE_CONFIG["memory_cache_timeout_seconds"],
        "memory_cache_size": len(_data_cache),
        "sqlite": sqlite_info
    }
