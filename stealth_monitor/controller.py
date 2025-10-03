# -*- coding: utf-8 -*-
"""Dashboard controller coordinating instruments, timeframes, and styles."""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

import nest_asyncio
from bokeh.embed import components
from IPython.display import HTML, display

from .config import INSTRUMENT_INDEX, TIMEFRAME_INDEX, Instrument, Timeframe
from .data_source_factory import fetch_data
from .styles import CHART_STYLE_INDEX, ChartStyle


class StealthDashboard:
    def __init__(
        self,
        *,
        update_interval: int = 10,
        limit: int = 200,
        adjust: str = "",
    ) -> None:
        nest_asyncio.apply()
        self.update_interval = update_interval
        self.limit = limit
        self.adjust = adjust

        self._instrument: Optional[Instrument] = None
        self._timeframe: Optional[Timeframe] = None
        self._style: Optional[ChartStyle] = None

        self._display_handle = None

        self._task: Optional[asyncio.Task] = None
        self._loop = asyncio.get_event_loop()
        self._lock = threading.Lock()

    def bind_output(self, _output_widget) -> None:  # pragma: no cover - compatibility shim
        """Kept for backwards compatibility; rendering uses IPython display handles."""
        return

    def update_selection(self, instrument_key: str, timeframe_key: str, style_key: str) -> None:
        instrument = INSTRUMENT_INDEX[instrument_key]
        timeframe = TIMEFRAME_INDEX[timeframe_key]
        style = CHART_STYLE_INDEX[style_key]

        self._instrument = instrument
        self._timeframe = timeframe
        self._style = style

        self.refresh_once()
        self._ensure_background_task()

    def refresh_once(self) -> None:
        if not (self._instrument and self._timeframe and self._style):
            return
        try:
            df = fetch_data(self._instrument, self._timeframe, limit=self.limit, adjust=self.adjust)
            payload = self._style.payload(df)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            print(f"[StealthDashboard] 数据刷新失败: {exc}")
            return

        with self._lock:
            fig, source = self._style.builder(self._timeframe)
            source.data = payload
            script, div = components(fig)
            html = script + "\n" + div
            if self._display_handle is None:
                self._display_handle = display(HTML(html), display_id=True)
            else:
                self._display_handle.update(HTML(html))

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def _ensure_background_task(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = self._loop.create_task(self._runner())

    async def _runner(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.update_interval)
                self.refresh_once()
        except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
            pass
