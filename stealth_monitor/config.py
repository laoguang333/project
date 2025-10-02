# -*- coding: utf-8 -*-
"""Configuration for supported instruments and timeframes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    kind: str  # 'futures' | 'stock'
    symbol: str


@dataclass(frozen=True)
class Timeframe:
    key: str
    label: str
    category: str  # 'minute' | 'daily'
    value: str
    duration_ms: int


INSTRUMENTS: List[Instrument] = [
    Instrument(key="PVC", label="PVC 主力 (v0)", kind="futures", symbol="v0"),
    Instrument(key="L", label="塑料 L 主力 (l0)", kind="futures", symbol="l0"),
    Instrument(key="MOUTAI", label="贵州茅台 (sh600519)", kind="stock", symbol="sh600519"),
]


TIMEFRAMES: List[Timeframe] = [
    Timeframe(key="1m", label="1 分钟", category="minute", value="1", duration_ms=60_000),
    Timeframe(key="5m", label="5 分钟", category="minute", value="5", duration_ms=5 * 60_000),
    Timeframe(key="15m", label="15 分钟", category="minute", value="15", duration_ms=15 * 60_000),
    Timeframe(key="30m", label="30 分钟", category="minute", value="30", duration_ms=30 * 60_000),
    Timeframe(key="60m", label="60 分钟", category="minute", value="60", duration_ms=60 * 60_000),
    Timeframe(key="1d", label="日线", category="daily", value="daily", duration_ms=24 * 60 * 60_000),
]


INSTRUMENT_INDEX: Dict[str, Instrument] = {item.key: item for item in INSTRUMENTS}
TIMEFRAME_INDEX: Dict[str, Timeframe] = {item.key: item for item in TIMEFRAMES}

