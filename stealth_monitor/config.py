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
    Instrument(key="PVC", label="PVC)", kind="futures", symbol="v0"),
    Instrument(key="FU", label="ry", kind="futures", symbol="fu0"),
    Instrument(key="B", label="de", kind="futures", symbol="b0"),
    Instrument(key="SR", label="bt", kind="futures", symbol="sr0"),
    Instrument(key="BU", label="lq", kind="futures", symbol="bu0"),
    Instrument(key="L", label="L", kind="futures", symbol="l0"),
    Instrument(key="MOUTAI", label="mt", kind="stock", symbol="sh600519"),
]


TIMEFRAMES: List[Timeframe] = [
    Timeframe(key="1m", label="o", category="minute", value="1", duration_ms=60_000),
    Timeframe(key="5m", label="f", category="minute", value="5", duration_ms=5 * 60_000),
    Timeframe(key="15m", label="ff", category="minute", value="15", duration_ms=15 * 60_000),
    Timeframe(key="30m", label="t", category="minute", value="30", duration_ms=30 * 60_000),
    Timeframe(key="60m", label="s", category="minute", value="60", duration_ms=60 * 60_000),
    Timeframe(key="1d", label="d", category="daily", value="daily", duration_ms=24 * 60 * 60_000),
]


INSTRUMENT_INDEX: Dict[str, Instrument] = {item.key: item for item in INSTRUMENTS}
TIMEFRAME_INDEX: Dict[str, Timeframe] = {item.key: item for item in TIMEFRAMES}

