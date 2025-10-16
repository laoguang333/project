"""
Minimal Qt application that uses finplot to display a single MA(1) line.

The module keeps the existing data infrastructure intact and replaces only the
view layer. It relies on finplot for both plotting and moving-average helpers,
falling back to pandas rolling windows if finplot does not expose the helper.
"""
from __future__ import annotations

import sys
import os
# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple
import threading
import signal

import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets

import finplot as fplt
import pyqtgraph as pg
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

from config import INSTRUMENTS, Instrument
from notebook_utils import TimeframePlan, load_market_data
from .single_instance import release_single_instance
from .custom_combo import CircularComboBox

# VS Code inspired palette.
FOREGROUND_COLOR = "#CCCCCC"
BACKGROUND_COLOR = "#1E1E1E"
PANEL_BACKGROUND_COLOR = "#252526"
ACCENT_COLOR = "#0E639C"
MA_LINE_COLOR = "#696969"
CANDLE_MUTED_COLOR = "#3A3D41"
CANDLE_MUTED_ALPHA = 85
STATUS_BAR_COLOR = "#007ACC"
RESIZE_MARGIN = 6

APP_STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND_COLOR};
    color: {FOREGROUND_COLOR};
    font-family: "Cascadia Code", "Consolas", "Segoe UI", monospace;
    font-size: 12px;
}}

QWidget#TitleBar {{
    background-color: #2D2D2D;
    border-radius: 6px 6px 0 0;
}}

QFrame#ContentFrame {{
    background-color: {PANEL_BACKGROUND_COLOR};
    border: 1px solid #3C3C3C;
    border-radius: 6px;
}}

QLabel#StatusLabel {{
    background-color: #1B1D21;
    padding: 6px 10px;
    color: {STATUS_BAR_COLOR};
}}

QLabel.section-title {{
    color: #AEAFAD;
    font-size: 11px;
}}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background-color: #2D2D30;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 3px 8px;
}}

QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
    border-color: {ACCENT_COLOR};
}}

QComboBox::drop-down {{
    border: none;
}}

QPushButton {{
    background-color: #2D2D30;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 4px 12px;
    color: {FOREGROUND_COLOR};
}}

QPushButton:hover {{
    border-color: {ACCENT_COLOR};
}}

QPushButton:pressed {{
    background-color: #1F2327;
}}

QPushButton#TitleBarButton {{
    background-color: transparent;
    border: none;
    padding: 6px 10px;
    color: #BBBBBB;
}}

QPushButton#TitleBarButton:hover {{
    background-color: rgba(14, 99, 156, 0.25);
    color: {FOREGROUND_COLOR};
}}

QPushButton#CloseButton:hover {{
    background-color: #C75450;
    color: white;
}}

QLabel#StatusLabel[state="idle"] {{
    color: {STATUS_BAR_COLOR};
}}

QLabel#StatusLabel[state="loading"] {{
    color: #CCCCCC;
}}

QLabel#StatusLabel[state="success"] {{
    color: {STATUS_BAR_COLOR};
}}

QLabel#StatusLabel[state="error"] {{
    color: #F48771;
}}
"""

@dataclass(frozen=True)
class CacheProbe:
    dataframe: pd.DataFrame
    timestamp: datetime
    age: timedelta
    is_fresh: bool


@dataclass(frozen=True)
class FetchResult:
    selection: "MarketSelection"
    dataframe: pd.DataFrame
    request_id: int
    fetched_at: datetime
    source: str  # "cache" or "network"


@dataclass(frozen=True)
class FetchError:
    selection: "MarketSelection"
    request_id: int
    message: str


class DataSignals(QtCore.QObject):
    data_ready = QtCore.pyqtSignal(object)
    data_failed = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)


def _build_timeframe_config() -> Dict[str, Tuple[str, TimeframePlan]]:
    """Create the timeframe menu metadata."""
    return {
        "1d": ("日", TimeframePlan(base_key="1d")),
        "1m": ("1", TimeframePlan(base_key="1m")),
        "5m": ("5", TimeframePlan(base_key="5m")),
        "15m": ("15", TimeframePlan(base_key="15m")),
        "30m": ("30", TimeframePlan(base_key="30m")),
        "1h": ("60", TimeframePlan(base_key="60m")),
        "4h": ("240", TimeframePlan(base_key="60m", resample_rule="4H", limit_multiplier=4)),
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
        self._ttl = timedelta(minutes=3)
        self._cache: Dict[Tuple[str, str], Tuple[datetime, pd.DataFrame]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["datetime"] = pd.to_datetime(df["datetime"], utc=False)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def _cache_key(self, selection: MarketSelection) -> Tuple[str, str]:
        return (selection.instrument_key, selection.timeframe_key)

    def peek_cache(self, selection: MarketSelection) -> CacheProbe | None:
        key = self._cache_key(selection)
        with self._lock:
            entry = self._cache.get(key)
        if entry is None:
            return None
        timestamp, dataframe = entry
        age = datetime.now() - timestamp
        is_fresh = age <= self._ttl
        return CacheProbe(
            dataframe=dataframe.copy(deep=True),
            timestamp=timestamp,
            age=age,
            is_fresh=is_fresh,
        )

    def fetch(self, selection: MarketSelection, *, force_refresh: bool = False) -> Tuple[pd.DataFrame, str]:
        plan = TIMEFRAME_CONFIG[selection.timeframe_key][1]
        prefer_cache = not force_refresh
        df = load_market_data(
            selection.instrument_key,
            plan,
            limit=self.history_limit,
            prefer_cache=prefer_cache,
        )
        cleaned = self._ensure_datetime(df)
        key = self._cache_key(selection)
        with self._lock:
            self._cache[key] = (datetime.now(), cleaned.copy(deep=True))
        source = "cache" if prefer_cache else "network"
        return cleaned, source


class DataFetchTask(QtCore.QRunnable):
    """Background task for loading market data without blocking the UI thread."""

    def __init__(
        self,
        adaptor: DataAdaptor,
        selection: MarketSelection,
        request_id: int,
        *,
        force_refresh: bool,
        signals: DataSignals,
    ) -> None:
        super().__init__()
        self._adaptor = adaptor
        self._selection = selection
        self._request_id = request_id
        self._force_refresh = force_refresh
        self._signals = signals

    def run(self) -> None:  # type: ignore[override]
        try:
            dataframe, source = self._adaptor.fetch(
                self._selection,
                force_refresh=self._force_refresh,
            )
            result = FetchResult(
                selection=self._selection,
                dataframe=dataframe,
                request_id=self._request_id,
                fetched_at=datetime.now(),
                source=source,
            )
            self._signals.data_ready.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            error = FetchError(
                selection=self._selection,
                request_id=self._request_id,
                message=str(exc),
            )
            self._signals.data_failed.emit(error)

class TitleBar(QtWidgets.QWidget):
    """Custom frameless title bar styled like VS Code."""

    HEIGHT = 34

    def __init__(self, window: QtWidgets.QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._drag_pos: QtCore.QPoint | None = None

        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(6)

        title_label = QtWidgets.QLabel("Stealth Monitor MA1", self)
        title_label.setProperty("class", "section-title")
        layout.addWidget(title_label)
        layout.addStretch(1)

        self.min_button = self._create_button("—", "最小化")
        self.max_button = self._create_button("□", "最大化")
        self.close_button = self._create_button("✕", "关闭")
        self.close_button.setObjectName("CloseButton")

        for btn in (self.min_button, self.max_button, self.close_button):
            layout.addWidget(btn)

        self.min_button.clicked.connect(self._window.showMinimized)
        self.max_button.clicked.connect(self._toggle_max_restore)
        self.close_button.clicked.connect(self._window.close)

    def _create_button(self, text: str, tooltip: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text, self)
        btn.setObjectName("TitleBarButton")
        btn.setFixedSize(32, 24)
        btn.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        btn.setToolTip(tooltip)
        return btn

    def _toggle_max_restore(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            self.max_button.setText("□")
            self.max_button.setToolTip("最大化")
        else:
            self._window.showMaximized()
            self.max_button.setText("❐")
            self.max_button.setToolTip("还原")

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._toggle_max_restore()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

class ChartPane:
    """Wrapper around a single finplot axis embedded in a Qt widget."""

    def __init__(self, master: QtWidgets.QWidget, *, history_limit: int, ma_period: int) -> None:
        fplt.foreground = FOREGROUND_COLOR
        fplt.background = PANEL_BACKGROUND_COLOR
        fplt.odd_plot_background = PANEL_BACKGROUND_COLOR

        self.widget = pg.GraphicsLayoutWidget(master)
        self.widget.setContentsMargins(0, 0, 0, 0)
        if hasattr(self.widget, "setBackground"):
            self.widget.setBackground(PANEL_BACKGROUND_COLOR)

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
        self.ax.vb.setBackgroundColor(PANEL_BACKGROUND_COLOR)
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
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowSystemMenuHint
            | QtCore.Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setStyleSheet(APP_STYLESHEET)
        self.setMinimumSize(720, 420)

        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        outer_layout = QtWidgets.QVBoxLayout(central)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(8)

        self.title_bar = TitleBar(self)
        outer_layout.addWidget(self.title_bar)

        content_frame = QtWidgets.QFrame(self)
        content_frame.setObjectName("ContentFrame")
        content_layout = QtWidgets.QVBoxLayout(content_frame)
        content_layout.setContentsMargins(18, 18, 18, 14)
        content_layout.setSpacing(14)
        outer_layout.addWidget(content_frame, 1)

        content_layout.addLayout(self._build_control_row())

        self.chart = ChartPane(
            self,
            history_limit=self.adaptor.history_limit,
            ma_period=self.adaptor.ma_period,
        )
        content_layout.addWidget(self.chart.widget, 1)

        status_bar = QtWidgets.QHBoxLayout()
        status_bar.setContentsMargins(0, 0, 0, 0)
        status_bar.setSpacing(0)
        self.status_label = QtWidgets.QLabel("等待刷新...", self)
        self.status_label.setObjectName("StatusLabel")
        self._update_status("等待刷新…", state="idle")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch(1)
        content_layout.addLayout(status_bar)

        grip_layout = QtWidgets.QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 0, 0)
        grip_layout.addStretch(1)
        self.size_grip = QtWidgets.QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.setStyleSheet("background-color: transparent;")
        grip_layout.addWidget(self.size_grip)
        content_layout.addLayout(grip_layout)

        self.thread_pool = QtCore.QThreadPool.globalInstance()
        if self.thread_pool.maxThreadCount() < 2:
            self.thread_pool.setMaxThreadCount(2)
        self._request_counter = 0
        self._latest_request_id = 0
        self._active_request_ids: set[int] = set()
        self._request_signals: Dict[int, DataSignals] = {}
        self._request_context: Dict[int, Dict[str, str]] = {}

        # Resize handling state
        self._resize_edge = QtCore.Qt.Edge(0)
        self._is_resizing = False
        self._resize_start_rect: QtCore.QRect | None = None
        self._resize_start_pos: QtCore.QPoint | None = None

        # 鼠标静止检测状态
        self.mouse_idle_enabled = False  # 默认关闭自动托盘功能
        self.mouse_idle_timer = QtCore.QTimer(self)
        self.mouse_idle_timer.setInterval(20000)  # 20秒
        self.mouse_idle_timer.timeout.connect(self._on_mouse_idle)
        self.last_mouse_pos = None

        # Enable mouse tracking for resizing detection
        self.setMouseTracking(True)
        for widget in (central, content_frame, self.title_bar, self):
            widget.setMouseTracking(True)
        for widget in (central, content_frame, self.title_bar, self.chart.widget):
            widget.installEventFilter(self)

        # 系统托盘功能
        self.tray_icon = None
        self._tray_icon_icon: QtGui.QIcon | None = None
        self._tray_icon_source = "unknown"
        self._setup_tray_icon()
        # 添加自动托盘功能开关按钮到控制行
        self.auto_tray_button = QtWidgets.QPushButton("启用自动托盘", self)
        self.auto_tray_button.setCheckable(True)
        self.auto_tray_button.toggled.connect(self._toggle_auto_tray)
        
        # 获取已创建的控制行并添加自动托盘按钮
        control_row = content_layout.itemAt(0).layout()  # 获取已存在的控制行
        control_row.addWidget(self.auto_tray_button)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.refresh_interval_ms)
        self._timer.timeout.connect(self._refresh_timer)
        self._timer.start()

        QtCore.QTimer.singleShot(0, lambda: self._schedule_refresh(reason="startup"))

    def _build_control_row(self) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.instrument_combo = CircularComboBox(self)
        for instrument in INSTRUMENTS:
            self.instrument_combo.addItem(instrument.label, instrument.key)
        self.instrument_combo.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self.instrument_combo)

        self.timeframe_combo = CircularComboBox(self)
        for key, (label, _plan) in TIMEFRAME_CONFIG.items():
            self.timeframe_combo.addItem(label, key)
        self.timeframe_combo.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self.timeframe_combo)

        self.refresh_button = QtWidgets.QPushButton("立即刷新", self)
        self.refresh_button.clicked.connect(self._refresh_manual)
        row.addWidget(self.refresh_button)

        self.toggle_timer_button = QtWidgets.QPushButton("暂停自动刷新", self)
        self.toggle_timer_button.setCheckable(True)
        self.toggle_timer_button.toggled.connect(self._toggle_timer)
        row.addWidget(self.toggle_timer_button)

        # 添加窗口置顶按钮
        self.toggle_stay_on_top_button = QtWidgets.QPushButton("置顶", self)
        self.toggle_stay_on_top_button.setCheckable(True)
        self.toggle_stay_on_top_button.toggled.connect(self._toggle_stay_on_top)
        row.addWidget(self.toggle_stay_on_top_button)

        # 添加透明度控制
        opacity_container = QtWidgets.QWidget(self)
        opacity_layout = QtWidgets.QHBoxLayout(opacity_container)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(4)
        
        opacity_label = QtWidgets.QLabel("透明度", opacity_container)
        opacity_label.setProperty("class", "section-title")
        opacity_layout.addWidget(opacity_label)
        
        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self.opacity_slider.setRange(20, 100)  # 20%到100%的透明度范围
        self.opacity_slider.setValue(100)  # 默认不透明
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        
        row.addWidget(opacity_container)

        row.addStretch(1)
        return row

    def _wrap_with_label(self, text: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QtWidgets.QLabel(text, container)
        label.setProperty("class", "section-title")
        layout.addWidget(label)
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
        self._schedule_refresh(reason="selection")

    def _toggle_timer(self, checked: bool) -> None:
        if checked:
            self._timer.stop()
            self.toggle_timer_button.setText("恢复自动刷新")
        else:
            if not self._timer.isActive():
                self._timer.start()
            self.toggle_timer_button.setText("暂停自动刷新")
            self._schedule_refresh(reason="timer")

    def _toggle_stay_on_top(self, checked: bool) -> None:
        """切换窗口置顶状态"""
        if checked:
            self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
            self.toggle_stay_on_top_button.setText("取消置顶")
        else:
            self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, False)
            self.toggle_stay_on_top_button.setText("置顶")
        self.show()  # 重新显示窗口以应用更改

    def _on_opacity_changed(self, value: int) -> None:
        """处理透明度变化"""
        # 将0-100的值转换为0.0-1.0的透明度值
        opacity = value / 100.0
        self.setWindowOpacity(opacity)

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

    def _refresh_manual(self) -> None:
        self._schedule_refresh(reason="manual")

    def _refresh_timer(self) -> None:
        if self._timer.isActive():
            self._schedule_refresh(reason="timer")

    def _schedule_refresh(self, *, reason: str) -> None:
        selection = self.selection
        cache_probe = self.adaptor.peek_cache(selection)

        if cache_probe is None:
            self.chart.clear()
            self._update_status(f"{self._reason_label(reason)}中…", state="loading")
            force_refresh = True
        else:
            self.chart.draw_chart(cache_probe.dataframe)
            timestamp_str = cache_probe.timestamp.strftime("%H:%M:%S")
            if cache_probe.is_fresh and reason != "manual":
                self._update_status(
                    f"{self._format_selection()} 使用缓存 ({timestamp_str})",
                    state="success",
                )
                force_refresh = False
            else:
                if cache_probe.is_fresh and reason == "manual":
                    self._update_status(
                        f"{self._reason_label(reason)}中…",
                        state="loading",
                    )
                else:
                    self._update_status("缓存已显示，后台刷新最新数据…", state="loading")
                force_refresh = True

        if not force_refresh:
            return

        self._start_fetch(selection, force_refresh=force_refresh, reason=reason)

    def _start_fetch(self, selection: MarketSelection, *, force_refresh: bool, reason: str) -> None:
        self._request_counter += 1
        request_id = self._request_counter
        signals = DataSignals(self)
        signals.data_ready.connect(self._on_data_ready)
        signals.data_failed.connect(self._on_data_failed)

        task = DataFetchTask(
            self.adaptor,
            selection,
            request_id=request_id,
            force_refresh=force_refresh,
            signals=signals,
        )

        self._active_request_ids.add(request_id)
        self._request_signals[request_id] = signals
        self._request_context[request_id] = {
            "reason": reason,
            "selection": selection,
        }
        self._latest_request_id = request_id
        self._update_loading_state()
        self.thread_pool.start(task)

    def _on_data_ready(self, payload: object) -> None:
        if not isinstance(payload, FetchResult):
            return

        self._active_request_ids.discard(payload.request_id)
        self._request_signals.pop(payload.request_id, None)
        context = self._request_context.pop(payload.request_id, {})
        self._update_loading_state()

        if payload.request_id < self._latest_request_id:
            return  # stale result

        reason_label = self._reason_label(context.get("reason", ""))
        if payload.selection != self.selection:
            return

        self.chart.draw_chart(payload.dataframe)
        source_label = "缓存" if payload.source == "cache" else "实时"
        self._update_status(
            f"{reason_label}完成 ({payload.fetched_at:%H:%M:%S}, {source_label})",
            state="success",
        )

    def _on_data_failed(self, payload: object) -> None:
        if not isinstance(payload, FetchError):
            return

        self._active_request_ids.discard(payload.request_id)
        self._request_signals.pop(payload.request_id, None)
        context = self._request_context.pop(payload.request_id, {})
        self._update_loading_state()

        if payload.request_id < self._latest_request_id:
            return
        if payload.selection != self.selection:
            return

        self.chart.clear()
        reason_label = self._reason_label(context.get("reason", ""))
        self._update_status(f"{reason_label}失败: {payload.message}", state="error")

    def _update_loading_state(self) -> None:
        self.refresh_button.setEnabled(not self._active_request_ids)

    def _update_status(self, text: str, *, state: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.update()

    @staticmethod
    def _reason_label(reason: str) -> str:
        mapping = {
            "manual": "手动刷新",
            "timer": "自动刷新",
            "selection": "切换刷新",
            "startup": "启动刷新",
        }
        return mapping.get(reason, "刷新")

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isMaximized():
            self.title_bar.max_button.setText("❐")
            self.title_bar.max_button.setToolTip("还原")
        else:
            self.title_bar.max_button.setText("□")
            self.title_bar.max_button.setToolTip("最大化")

    # --- Resize helpers -------------------------------------------------

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if isinstance(event, QtGui.QMouseEvent):
            if event.type() == QtCore.QEvent.Type.MouseMove:
                return self._handle_mouse_move(event, obj)
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                return self._handle_mouse_press(event, obj)
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                return self._handle_mouse_release(event, obj)
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._handle_mouse_press(event, self):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._handle_mouse_move(event, self):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if not self._handle_mouse_release(event, self):
            super().mouseReleaseEvent(event)

    def _handle_mouse_press(self, event: QtGui.QMouseEvent, widget: QtCore.QObject) -> bool:
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self.isMaximized():
            return False
        window_pos = self._map_to_window(widget, event.position())
        edge = self._detect_resize_edge(window_pos)
        if edge == QtCore.Qt.Edge(0):
            return False
        self._is_resizing = True
        self._resize_edge = edge
        self._resize_start_pos = event.globalPosition().toPoint()
        self._resize_start_rect = self.geometry()
        event.accept()
        return True

    def _handle_mouse_move(self, event: QtGui.QMouseEvent, widget: QtCore.QObject) -> bool:
        window_pos = self._map_to_window(widget, event.position())
        if self._is_resizing and self._resize_start_rect and self._resize_start_pos:
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return True
        if self.isMaximized():
            self.unsetCursor()
            return False
        edge = self._detect_resize_edge(window_pos)
        self._apply_resize_cursor(edge)
        return False

    def _handle_mouse_release(self, event: QtGui.QMouseEvent, widget: QtCore.QObject) -> bool:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        if self._is_resizing:
            self._is_resizing = False
            self._resize_edge = QtCore.Qt.Edge(0)
            self._resize_start_rect = None
            self._resize_start_pos = None
            self.unsetCursor()
            event.accept()
            return True
        return False

    def _map_to_window(self, widget: QtCore.QObject, pos: QtCore.QPointF) -> QtCore.QPoint:
        if widget is self:
            return QtCore.QPoint(round(pos.x()), round(pos.y()))
        if isinstance(widget, QtWidgets.QWidget):
            return widget.mapTo(self, QtCore.QPoint(round(pos.x()), round(pos.y())))
        return QtCore.QPoint(round(pos.x()), round(pos.y()))

    def _detect_resize_edge(self, pos: QtCore.QPoint) -> QtCore.Qt.Edge:
        rect = self.rect()
        edges = QtCore.Qt.Edge(0)
        if pos.x() <= RESIZE_MARGIN:
            edges |= QtCore.Qt.Edge.LeftEdge
        if pos.x() >= rect.width() - RESIZE_MARGIN:
            edges |= QtCore.Qt.Edge.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= QtCore.Qt.Edge.TopEdge
        if pos.y() >= rect.height() - RESIZE_MARGIN:
            edges |= QtCore.Qt.Edge.BottomEdge
        return edges

    def _apply_resize_cursor(self, edges: QtCore.Qt.Edge) -> None:
        if edges == QtCore.Qt.Edge(0):
            self.unsetCursor()
            return
        if edges in (
            QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.TopEdge,
            QtCore.Qt.Edge.RightEdge | QtCore.Qt.Edge.BottomEdge,
        ):
            self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor)
        elif edges in (
            QtCore.Qt.Edge.RightEdge | QtCore.Qt.Edge.TopEdge,
            QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.BottomEdge,
        ):
            self.setCursor(QtCore.Qt.CursorShape.SizeBDiagCursor)
        elif edges & (QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.RightEdge):
            self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        elif edges & (QtCore.Qt.Edge.TopEdge | QtCore.Qt.Edge.BottomEdge):
            self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)

    def _perform_resize(self, global_pos: QtCore.QPoint) -> None:
        if not self._resize_start_rect or not self._resize_start_pos:
            return
        rect = QtCore.QRect(self._resize_start_rect)
        delta = global_pos - self._resize_start_pos

        if self._resize_edge & QtCore.Qt.Edge.LeftEdge:
            rect.setLeft(rect.left() + delta.x())
        if self._resize_edge & QtCore.Qt.Edge.RightEdge:
            rect.setRight(rect.right() + delta.x())
        if self._resize_edge & QtCore.Qt.Edge.TopEdge:
            rect.setTop(rect.top() + delta.y())
        if self._resize_edge & QtCore.Qt.Edge.BottomEdge:
            rect.setBottom(rect.bottom() + delta.y())

        min_w = self.minimumWidth()
        min_h = self.minimumHeight()
        if rect.width() < min_w:
            if self._resize_edge & QtCore.Qt.Edge.LeftEdge:
                rect.setLeft(rect.right() - min_w)
            else:
                rect.setRight(rect.left() + min_w)
        if rect.height() < min_h:
            if self._resize_edge & QtCore.Qt.Edge.TopEdge:
                rect.setTop(rect.bottom() - min_h)
            else:
                rect.setBottom(rect.top() + min_h)

        self.setGeometry(rect.normalized())

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """重写关闭事件，将窗口隐藏而不是关闭"""
        if self.tray_icon and self.tray_icon.isVisible():
            self.hide()  # 隐藏窗口而不是关闭
            event.ignore()  # 忽略关闭事件
        else:
            super().closeEvent(event)

    def _setup_tray_icon(self) -> None:
        """设置系统托盘图标"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        if self.tray_icon is None:
            self.tray_icon = QSystemTrayIcon(self)

        tray_icon = self._resolve_tray_icon()
        self._tray_icon_icon = tray_icon
        self.tray_icon.setIcon(tray_icon)
        if self.windowIcon().isNull():
            self.setWindowIcon(tray_icon)
        app_instance = QtWidgets.QApplication.instance()
        if app_instance and app_instance.windowIcon().isNull():
            app_instance.setWindowIcon(tray_icon)
        self.tray_icon.setToolTip(self.windowTitle() or "Stealth Monitor MA1")
        if __debug__ and tray_icon is not None:
            sizes = [f"{size.width()}x{size.height()}" for size in tray_icon.availableSizes()] or ["<empty>"]
            print("[tray] 图标来源: %s, 可用尺寸: %s" % (self._tray_icon_source, ", ".join(sizes)))

        tray_menu = QMenu(self)

        show_action = tray_menu.addAction("显示")
        show_action.triggered.connect(self.showNormal)

        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_application)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.setVisible(True)
        self.tray_icon.show()

    def _resolve_tray_icon(self) -> QtGui.QIcon:
        """????? Windows 11 ?????????"""
        app_instance = QtWidgets.QApplication.instance()
        sources = [
            ("window", self.windowIcon()),
            ("application", app_instance.windowIcon() if app_instance else None),
            ("theme", QtGui.QIcon.fromTheme("applications-system")),
            ("style", self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)),
        ]
        for source, icon in sources:
            if self._is_icon_usable(icon):
                self._tray_icon_source = source
                return icon
        self._tray_icon_source = "fallback"
        return self._create_fallback_tray_icon()

    def _is_icon_usable(self, icon: QtGui.QIcon | None) -> bool:
        """检查图标是否包含可用的位图"""
        if not icon or icon.isNull():
            return False
        for size in (16, 20, 24, 32, 48, 64):
            pixmap = icon.pixmap(size, size)
            if not pixmap.isNull():
                return True
        return False

    def _create_fallback_tray_icon(self) -> QtGui.QIcon:
        """生成兜底托盘图标，避免空图标被系统忽略"""
        base_size = 128
        base_pixmap = QtGui.QPixmap(base_size, base_size)
        base_pixmap.fill(QtGui.QColor(ACCENT_COLOR))

        painter = QtGui.QPainter(base_pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtGui.QColor(BACKGROUND_COLOR))
        painter.setPen(QtGui.QPen(QtGui.QColor(BACKGROUND_COLOR)))
        painter.drawEllipse(12, 12, base_size - 24, base_size - 24)

        painter.setPen(QtGui.QPen(QtGui.QColor(FOREGROUND_COLOR)))
        font = QtGui.QFont("Segoe UI", 52, QtGui.QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(base_pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "S")
        painter.end()

        icon = QtGui.QIcon()
        icon.addPixmap(base_pixmap)
        for size in (16, 20, 24, 32, 48, 64):
            scaled = base_pixmap.scaled(size, size, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                      QtCore.Qt.TransformationMode.SmoothTransformation)
            icon.addPixmap(scaled)
        return icon
    def _on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """处理托盘图标被点击的事件"""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def _quit_application(self) -> None:
        """退出应用程序"""
        # 释放单实例检查器资源
        release_single_instance()
        # 先隐藏托盘图标再退出应用
        if self.tray_icon:
            self.tray_icon.hide()
        QtWidgets.QApplication.quit()

    def _toggle_auto_tray(self, checked: bool) -> None:
        """切换自动托盘功能"""
        self.mouse_idle_enabled = checked
        if checked:
            self.auto_tray_button.setText("禁用自动托盘")
            # 启动鼠标监控
            self.installEventFilter(self)
            self.mouse_idle_timer.start()
            # 初始化鼠标位置
            self.last_mouse_pos = QtGui.QCursor.pos()
        else:
            self.auto_tray_button.setText("启用自动托盘")
            # 停止鼠标监控
            self.removeEventFilter(self)
            self.mouse_idle_timer.stop()

    def _on_mouse_idle(self) -> None:
        """鼠标静止超时处理"""
        if self.mouse_idle_enabled and self.isVisible():
            # 检查鼠标位置是否变化
            cursor_pos = QtGui.QCursor.pos()
            if self.last_mouse_pos is None or self.last_mouse_pos != cursor_pos:
                self.last_mouse_pos = cursor_pos
                # 重启计时器
                self.mouse_idle_timer.start()
            else:
                # 鼠标静止超过20秒，隐藏窗口到托盘
                self.hide()
                # 重置位置以避免立即触发
                self.last_mouse_pos = cursor_pos

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """事件过滤器，用于监控鼠标活动"""
        if getattr(self, "mouse_idle_enabled", False) and isinstance(event, QtGui.QMouseEvent):
            # 有任何鼠标活动都重置计时器
            self.mouse_idle_timer.start()
            self.last_mouse_pos = QtGui.QCursor.pos()
            
        # 调用父类的事件过滤器
        return super().eventFilter(obj, event)



def _install_sigint_handler(app: QtWidgets.QApplication) -> None:
    """在控制台环境下让 Ctrl+C 中断 Qt 事件循环"""
    try:
        signal.signal(signal.SIGINT, lambda *_: QtWidgets.QApplication.quit())
    except ValueError:
        # 信号注册失败时直接返回（常见于非主线程环境）
        return

    timer = QtCore.QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    def _stop_timer() -> None:
        timer.stop()
        timer.deleteLater()

    app.aboutToQuit.connect(_stop_timer)
    app._sigint_helper_timer = timer

def run() -> None:
    """
    Launch the Qt client. Creates a QApplication if needed.
    """
    app = QtWidgets.QApplication.instance()
    own_app = app is None
    if own_app:
        app = QtWidgets.QApplication(sys.argv)
        _install_sigint_handler(app)
    app.setQuitOnLastWindowClosed(False)
    adaptor = DataAdaptor()
    window = StealthMainWindow(adaptor)
    window.show()
    fplt.refresh()
    if own_app:
        app.exec()


__all__ = ["run", "StealthMainWindow", "DataAdaptor", "ChartPane"]
