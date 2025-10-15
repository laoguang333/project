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
from datetime import datetime
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets

import finplot as fplt
import pyqtgraph as pg
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

from config import INSTRUMENTS, Instrument
from notebook_utils import TimeframePlan, load_market_data

# VS Code inspired palette.
FOREGROUND_COLOR = "#CCCCCC"
BACKGROUND_COLOR = "#1E1E1E"
PANEL_BACKGROUND_COLOR = "#252526"
ACCENT_COLOR = "#0E639C"
MA_LINE_COLOR = "#C0C0C0"
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
"""


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

        # Resize handling state
        self._resize_edge = QtCore.Qt.Edge(0)
        self._is_resizing = False
        self._resize_start_rect: QtCore.QRect | None = None
        self._resize_start_pos: QtCore.QPoint | None = None

        # Enable mouse tracking for resizing detection
        self.setMouseTracking(True)
        for widget in (central, content_frame, self.title_bar, self):
            widget.setMouseTracking(True)
        for widget in (central, content_frame, self.title_bar, self.chart.widget):
            widget.installEventFilter(self)

        # 系统托盘功能
        self.tray_icon = None
        self._setup_tray_icon()
        
        # 鼠标静止检测功能
        self.mouse_idle_timer = QtCore.QTimer(self)
        self.mouse_idle_timer.setInterval(20000)  # 20秒
        self.mouse_idle_timer.timeout.connect(self._on_mouse_idle)
        self.mouse_idle_enabled = False  # 默认关闭自动托盘功能
        self.last_mouse_pos = None
        
        # 添加自动托盘功能开关按钮到控制行
        self.auto_tray_button = QtWidgets.QPushButton("启用自动托盘", self)
        self.auto_tray_button.setCheckable(True)
        self.auto_tray_button.toggled.connect(self._toggle_auto_tray)
        
        # 获取已创建的控制行并添加自动托盘按钮
        control_row = content_layout.itemAt(0).layout()  # 获取已存在的控制行
        control_row.addWidget(self.auto_tray_button)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.refresh_interval_ms)
        self._timer.timeout.connect(self.refresh_chart)
        self._timer.start()

        QtCore.QTimer.singleShot(0, self.refresh_chart)

    def _build_control_row(self) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

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
            
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        
        # 设置托盘图标（这里使用应用程序图标，如果有的话）
        # 如果没有特定图标，可以使用默认图标
        self.tray_icon.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon))
        
        # 创建托盘菜单
        tray_menu = QMenu(self)
        
        # 添加显示/隐藏选项
        show_action = tray_menu.addAction("显示")
        show_action.triggered.connect(self.showNormal)
        
        # 添加退出选项
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self._quit_application)
        
        self.tray_icon.setContextMenu(tray_menu)
        
        # 连接托盘图标激活信号
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        
        # 显示托盘图标
        self.tray_icon.show()

    def _on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """处理托盘图标被点击的事件"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 单击托盘图标时切换窗口显示状态
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()

    def _quit_application(self) -> None:
        """退出应用程序"""
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
        if self.mouse_idle_enabled and isinstance(event, QtGui.QMouseEvent):
            # 有任何鼠标活动都重置计时器
            self.mouse_idle_timer.start()
            self.last_mouse_pos = QtGui.QCursor.pos()
            
        # 调用父类的事件过滤器
        return super().eventFilter(obj, event)


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
