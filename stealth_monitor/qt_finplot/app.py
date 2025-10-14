"""
Minimal Qt application that uses finplot to display a single MA(1) line.

The module keeps the existing data infrastructure intact and replaces only the
view layer. It relies on finplot for both plotting and moving-average helpers,
falling back to pandas rolling windows if finplot does not expose the helper.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets

import finplot as fplt
import pyqtgraph as pg

from ..config import INSTRUMENTS, Instrument
from ..notebook_utils import TimeframePlan, load_market_data

# Palette tuned for a low-key, silver themed appearance.
FOREGROUND_COLOR = "#c0c0c0"
BACKGROUND_COLOR = "#fff7e0"
MA_LINE_COLOR = "#c0c0c0"
CANDLE_MUTED_COLOR = "#909090"
CANDLE_MUTED_ALPHA = 25


def _build_timeframe_config() -> Dict[str, Tuple[str, TimeframePlan]]:
    """Create the timeframe menu metadata."""
    return {
        "1d": ("日线", TimeframePlan(base_key="1d")),
        "1m": ("1分钟", TimeframePlan(base_key="1m")),
        "5m": ("5分钟", TimeframePlan(base_key="5m")),
        "15m": ("15分钟", TimeframePlan(base_key="15m")),
        "30m": ("30分钟", TimeframePlan(base_key="30m")),
        "1h": ("1小时", TimeframePlan(base_key="60m")),
        "4h": ("4小时", TimeframePlan(base_key="60m", resample_rule="4H", limit_multiplier=4)),
    }


TIMEFRAME_CONFIG = _build_timeframe_config()


@dataclass(frozen=True)
class MarketSelection:
    """Currently selected instrument and timeframe."""

    instrument_key: str
    timeframe_key: str


class DataAdaptor:
    """
    Bridge between the existing data pipeline and the new finplot-based view.
    """

    def __init__(self, *, history_limit: int = 200, ma_period: int = 1) -> None:
        self.history_limit = history_limit
        self.ma_period = ma_period

    @staticmethod
    def _ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["datetime"] = pd.to_datetime(df["datetime"], utc=False)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def fetch(self, selection: MarketSelection, *, prefer_cache: bool = True) -> pd.DataFrame:
        plan = TIMEFRAME_CONFIG[selection.timeframe_key][1]
        df = load_market_data(
            selection.instrument_key,
            plan,
            limit=self.history_limit,
            prefer_cache=prefer_cache,
        )
        return self._ensure_datetime(df)

    def compute_ma(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        sma_func = getattr(fplt, "sma", None)
        if callable(sma_func):
            ma = sma_func(close, self.ma_period)
        else:
            ma = close.rolling(self.ma_period, min_periods=1).mean()
        ma.index = df["datetime"]
        return ma.dropna()


class ChartPane:
    """Wrapper around a single finplot axis embedded in a Qt widget."""

    def __init__(self, master: QtWidgets.QWidget, *, history_limit: int, ma_period: int) -> None:
        fplt.foreground = FOREGROUND_COLOR
        fplt.background = BACKGROUND_COLOR
        fplt.odd_plot_background = BACKGROUND_COLOR

        self.widget = pg.GraphicsLayoutWidget(master)
        self.widget.setContentsMargins(0, 0, 0, 0)
        if hasattr(self.widget, "setBackground"):
            self.widget.setBackground(BACKGROUND_COLOR)

        axes = fplt.create_plot_widget(
            master=self.widget,
            rows=1,
            init_zoom_periods=max(history_limit, 150),
        )
        if isinstance(axes, (list, tuple)):
            axes = list(axes)[0]
        self.ax = axes
        self.widget.axs = [self.ax]
        # Add the finplot axis into the graphics layout so it becomes visible.
        try:
            self.widget.addItem(self.ax, row=0, col=0)
        except TypeError:
            self.widget.addItem(self.ax)

        self.ax.showGrid(x=False, y=False)
        self.ax.vb.setBackgroundColor(BACKGROUND_COLOR)
        axis_pen = pg.mkPen(color=FOREGROUND_COLOR, width=1)
        for axis_key in ("bottom", "right"):
            axis = self.ax.getAxis(axis_key)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
        self.ax.hideAxis("left")
        self.ax.setMenuEnabled(False)

        self._ma_handle = None
        self._candle_handle = None
        self._ma_period = max(ma_period, 1)

    def clear(self) -> None:
        needs_refresh = False
        if self._ma_handle is not None:
            try:
                self.ax.removeItem(self._ma_handle)
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            self._ma_handle = None
            needs_refresh = True
        if self._candle_handle is not None:
            try:
                self.ax.removeItem(self._candle_handle)
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            self._candle_handle = None
            needs_refresh = True
        # reset datasrc so next draw can auto-rescale
        self.ax.vb.set_datasrc(None)
        self.ax.vb.v_autozoom = True
        self.ax.vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        if needs_refresh:
            fplt.refresh()

    def draw_chart(self, df: pd.DataFrame) -> None:
        self.clear()
        if df.empty:
            return

        candles = df[["open", "close", "high", "low"]].copy()
        candles = candles.reset_index(drop=True)
        candles.insert(0, "time", np.arange(len(candles), dtype=float))

        self._candle_handle = fplt.candlestick_ochl(
            candles,
            ax=self.ax,
            candle_width=0.6,
        )
        muted = QtGui.QColor(CANDLE_MUTED_COLOR)
        muted.setAlpha(CANDLE_MUTED_ALPHA)
        for key in list(self._candle_handle.colors.keys()):
            self._candle_handle.colors[key] = QtGui.QColor(muted)
        self._candle_handle.shadow_width = 1

        ma_series = candles["close"].rolling(self._ma_period, min_periods=1).mean()
        if ma_series.dropna().empty:
            fplt.refresh()
            return

        ma_series.index = candles["time"]

        self._ma_handle = fplt.plot(
            ma_series.astype(float),
            ax=self.ax,
            color=MA_LINE_COLOR,
            legend="MA(1)",
            width=3.2,
        )
        if self._ma_handle is not None:
            self._ma_handle.setPen(
                pg.mkPen(
                    color=MA_LINE_COLOR,
                    width=3.2,
                    cap=QtCore.Qt.PenCapStyle.RoundCap,
                    join=QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
        self.ax.vb.updateAutoRange()
        fplt.refresh()


class StealthMainWindow(QtWidgets.QMainWindow):
    """Main window hosting controls and the finplot chart."""

    def __init__(
        self,
        adaptor: DataAdaptor,
        *,
        refresh_interval_ms: int = 10_000,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.adaptor = adaptor
        self.refresh_interval_ms = refresh_interval_ms
        self.selection = MarketSelection(
            instrument_key=INSTRUMENTS[0].key,
            timeframe_key="1d",
        )

        self.setWindowTitle("Stealth Monitor MA1")
        self.resize(1000, 640)

        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addLayout(self._build_control_row())

        self.chart = ChartPane(
            self,
            history_limit=self.adaptor.history_limit,
            ma_period=self.adaptor.ma_period,
        )
        layout.addWidget(self.chart.widget)

        self.status_label = QtWidgets.QLabel("等待刷新...", self)
        layout.addWidget(self.status_label)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.refresh_interval_ms)
        self._timer.timeout.connect(self.refresh_chart)
        self._timer.start()

        QtCore.QTimer.singleShot(0, self.refresh_chart)

    def _build_control_row(self) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.instrument_combo = QtWidgets.QComboBox(self)
        for instrument in INSTRUMENTS:
            self.instrument_combo.addItem(instrument.label, instrument.key)
        self.instrument_combo.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self._wrap_with_label("品种", self.instrument_combo))

        self.timeframe_combo = QtWidgets.QComboBox(self)
        for key, (label, _plan) in TIMEFRAME_CONFIG.items():
            self.timeframe_combo.addItem(label, key)
        self.timeframe_combo.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self._wrap_with_label("周期", self.timeframe_combo))

        self.refresh_button = QtWidgets.QPushButton("立即刷新", self)
        self.refresh_button.clicked.connect(self.refresh_chart)
        row.addWidget(self.refresh_button)

        self.toggle_timer_button = QtWidgets.QPushButton("暂停自动刷新", self)
        self.toggle_timer_button.setCheckable(True)
        self.toggle_timer_button.toggled.connect(self._toggle_timer)
        row.addWidget(self.toggle_timer_button)

        row.addStretch(1)
        return row

    def _wrap_with_label(self, text: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QtWidgets.QLabel(text, container))
        layout.addWidget(widget)
        return container

    def _on_selection_changed(self) -> None:
        instrument_key = self.instrument_combo.currentData()
        timeframe_key = self.timeframe_combo.currentData()
        if not instrument_key or not timeframe_key:
            return
        self.selection = MarketSelection(
            instrument_key=instrument_key,
            timeframe_key=timeframe_key,
        )
        self.refresh_chart()

    def _toggle_timer(self, checked: bool) -> None:
        if checked:
            self._timer.stop()
            self.toggle_timer_button.setText("恢复自动刷新")
        else:
            if not self._timer.isActive():
                self._timer.start()
            self.toggle_timer_button.setText("暂停自动刷新")

    def _format_selection(self) -> str:
        instrument = self._instrument_by_key(self.selection.instrument_key)
        timeframe_label = TIMEFRAME_CONFIG[self.selection.timeframe_key][0]
        return f"{instrument.label} / {timeframe_label}"

    @staticmethod
    def _instrument_by_key(key: str) -> Instrument:
        for instrument in INSTRUMENTS:
            if instrument.key == key:
                return instrument
        raise KeyError(f"Unknown instrument key: {key}")

    def refresh_chart(self) -> None:
        try:
            df = self.adaptor.fetch(self.selection)
            self.chart.draw_chart(df)
            now_str = datetime.now().strftime("%H:%M:%S")
            self.status_label.setText(f"{self._format_selection()} 已更新 ({now_str})")
        except Exception as exc:  # pragma: no cover - defensive path
            self.chart.clear()
            self.status_label.setText(f"刷新失败: {exc}")


def run() -> None:
    """
    Launch the Qt client. Creates a QApplication if needed.
    """
    app = QtWidgets.QApplication.instance()
    own_app = app is None
    if own_app:
        app = QtWidgets.QApplication(sys.argv)
    adaptor = DataAdaptor()
    window = StealthMainWindow(adaptor)
    window.show()
    fplt.refresh()
    if own_app:
        app.exec()


__all__ = ["run", "StealthMainWindow", "DataAdaptor", "ChartPane"]
