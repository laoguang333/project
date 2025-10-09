from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

import numpy as np
import pandas as pd
from bokeh.embed import file_html
from bokeh.models import CDSView, ColumnDataSource, HoverTool, IndexFilter
from bokeh.resources import INLINE
from bokeh.plotting import figure
from IPython.display import HTML, display
from unittest.mock import patch

import backtesting._plotting as plotting
from backtesting import Backtest, Strategy
from backtesting.test import GOOG, SMA

SILVER_BULL = plotting.RGB(192, 192, 192)
SILVER_BEAR = plotting.RGB(158, 158, 158)
LINE_COLOR = "#8C8C8C"
BACKGROUND_COLOR = "#FFF7E0"
VOLUME_BAR_COLOR = "#B3B3B3"
VOLUME_BACKGROUND_COLOR = "#F0F0F0"
DOTTED_DASH_PATTERN: Sequence[int] = (1, 20)
DOTTED_MARKER_STEP = 7

class PassiveStrategy(Strategy):
    """占位策略：不做交易，只用于生成基准图表。"""

    def init(self) -> None:  # pragma: no cover
        self.ma1 = self.I(SMA, self.data.Close, 1)

    def next(self) -> None:  # pragma: no cover
        pass


def prepare_backtest(sample_size: int = 220) -> Backtest:
    df = GOOG.copy()
    if sample_size:
        df = df.tail(sample_size)
    bt = Backtest(df, PassiveStrategy, cash=100_000, commission=0.0)
    bt.run()
    return bt


def display_bokeh(fig) -> None:
    html = file_html(fig, INLINE, "chart")
    display(HTML(html))


def _candlestick_renderers(ohlc_fig: Any):
    for renderer in ohlc_fig.renderers:
        glyph = getattr(renderer, "glyph", None)
        if glyph is None:
            continue
        if glyph.__class__.__name__ in {"Segment", "VBar"}:
            yield renderer, glyph


def _find_ohlc_figure(children: Iterable) -> Optional[Any]:
    for row in children:
        if row is None:
            continue
        cells = row if isinstance(row, (list, tuple)) else [row]
        for cell in cells:
            if cell is None or not hasattr(cell, "renderers"):
                continue
            for _renderer, _glyph in _candlestick_renderers(cell):
                return cell
    return None


def _find_volume_figure(children: Iterable, exclude: Optional[Any] = None) -> Optional[Any]:
    for row in children:
        if row is None:
            continue
        cells = row if isinstance(row, (list, tuple)) else [row]
        for cell in cells:
            if cell is None or cell is exclude or not hasattr(cell, "renderers"):
                continue
            yaxes = getattr(cell, 'yaxis', [])
            for axis in yaxes:
                axis_label = getattr(axis, 'axis_label', '')
                if isinstance(axis_label, str) and axis_label.strip().lower() == 'volume':
                    return cell
            for renderer in getattr(cell, 'renderers', []):
                glyph = getattr(renderer, 'glyph', None)
                if glyph is None or glyph.__class__.__name__ != 'VBar':
                    continue
                source = getattr(renderer, 'data_source', None)
                data = getattr(source, 'data', None)
                if isinstance(data, dict):
                    normalized = {str(key).lower() for key in data.keys()}
                    if 'volume' in normalized:
                        return cell
    return None


def _ensure_ma1(source: ColumnDataSource) -> None:
    data = dict(source.data)
    if "MA1" in data:
        return
    close = np.array(data.get("Close", []), dtype=float)
    data["MA1"] = close.tolist()
    source.data = data


def _hide_candles_and_get_source(ohlc_fig: Any) -> Optional[ColumnDataSource]:
    source = None
    for renderer, _glyph in _candlestick_renderers(ohlc_fig):
        renderer.visible = False
        if source is None:
            source = renderer.data_source
    return source


def _ma_line_renderers(ohlc_fig: Any):
    """Yield registered moving-average line renderers from the OHLC figure."""
    for renderer in getattr(ohlc_fig, "renderers", []):
        glyph = getattr(renderer, "glyph", None)
        if glyph is None or glyph.__class__.__name__ != "Line":
            continue
        source = getattr(renderer, "data_source", None)
        data = getattr(source, "data", None)
        if not isinstance(data, dict):
            continue
        columns = [str(key).upper() for key in data.keys()]
        if any("SMA" in column or column.startswith("MA(") for column in columns):
            yield renderer, glyph


def _style_volume_panel(volume_fig: Any) -> None:
    volume_fig.background_fill_color = VOLUME_BACKGROUND_COLOR
    volume_fig.border_fill_color = VOLUME_BACKGROUND_COLOR
    for axis in getattr(volume_fig, 'yaxis', []):
        axis.axis_label_text_color = LINE_COLOR
        axis.major_label_text_color = LINE_COLOR
    for axis in getattr(volume_fig, 'xaxis', []):
        axis.major_label_text_color = LINE_COLOR
    for renderer in getattr(volume_fig, 'renderers', []):
        glyph = getattr(renderer, 'glyph', None)
        if glyph is None or glyph.__class__.__name__ != 'VBar':
            continue
        if hasattr(glyph, 'fill_color'):
            glyph.fill_color = VOLUME_BAR_COLOR
        if hasattr(glyph, 'line_color'):
            glyph.line_color = VOLUME_BAR_COLOR
        if hasattr(glyph, 'line_alpha'):
            glyph.line_alpha = 0.85
        renderer.visible = True


def _style_price_axis(ohlc_fig: Any) -> None:
    ohlc_fig.background_fill_color = BACKGROUND_COLOR
    ohlc_fig.border_fill_color = BACKGROUND_COLOR
    if ohlc_fig.legend:
        ohlc_fig.legend.visible = False

def _draw_dotted_ma(ohlc_fig: Any, source: ColumnDataSource, dash_pattern: Sequence[int], marker_step: int) -> None:
    dash = list(dash_pattern)
    ohlc_fig.line(
        "index",
        "MA1",
        source=source,
        line_color=LINE_COLOR,
        line_width=2.6,
        line_dash=dash,
        line_cap="round",
        line_join="round",
        legend_label="MA(1)",
    )
    if marker_step and marker_step > 1:
        indices = list(range(0, len(source.data.get("index", [])), marker_step))
        if indices:
            view = CDSView(filter=IndexFilter(indices))
            ohlc_fig.scatter(
                "index",
                "MA1",
                source=source,
                view=view,
                size=5.0,
                color=LINE_COLOR,
            )


def render_silver_candles(bt: Backtest):
    original_colors = plotting.BULL_COLOR, plotting.BEAR_COLOR
    try:
        plotting.BULL_COLOR, plotting.BEAR_COLOR = SILVER_BULL, SILVER_BEAR
        fig = bt.plot(open_browser=False)
    finally:
        plotting.BULL_COLOR, plotting.BEAR_COLOR = original_colors
    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is not None:
        for _renderer, glyph in _candlestick_renderers(ohlc_fig):
            if glyph.__class__.__name__ == "VBar":
                glyph.line_alpha = 0.0
            elif glyph.__class__.__name__ == "Segment":
                glyph.line_color = LINE_COLOR
                glyph.line_alpha = 0.6
        _style_price_axis(ohlc_fig)
        return ohlc_fig
    return fig


def render_ma_line(bt: Backtest):
    fig = bt.plot(open_browser=False)
    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is not None:
        source = _hide_candles_and_get_source(ohlc_fig)
        if source is not None:
            _ensure_ma1(source)
            ohlc_fig.line(
                "index",
                "MA1",
                source=source,
                line_color=LINE_COLOR,
                line_width=2.8,
                line_cap="round",
                line_join="round",
                legend_label="MA(1)",
            )
            _style_price_axis(ohlc_fig)
            return ohlc_fig
    return fig


def render_dotted_ma(bt: Backtest, dash_pattern: Sequence[int], marker_step: int):
    fig = bt.plot(open_browser=False)
    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is not None:
        source = _hide_candles_and_get_source(ohlc_fig)
        if source is not None:
            _ensure_ma1(source)
            _draw_dotted_ma(
                ohlc_fig,
                source,
                dash_pattern,
                marker_step,
            )
            _style_price_axis(ohlc_fig)
            return ohlc_fig
    return fig


def render_native_silver_ma(bt: Backtest):
    """
    Modify the Backtest-native plot: hide default candles and overlay a silver MA line.
    Returns the original layout so auxiliary Backtest panels remain intact.
    """
    fig = bt.plot(open_browser=False)
    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is None:
        return fig
    volume_fig = _find_volume_figure(fig.children, exclude=ohlc_fig)
    source = _hide_candles_and_get_source(ohlc_fig)
    if source is None:
        return fig
    _ensure_ma1(source)
    ohlc_fig.line(
        "index",
        "MA1",
        source=source,
        line_color=LINE_COLOR,
        line_width=2.8,
        line_cap="round",
        line_join="round",
        legend_label="MA(1)",
    )
    _style_price_axis(ohlc_fig)
    if volume_fig is not None:
        _style_volume_panel(volume_fig)
    return fig


def build_dotted_ma_figure_from_dataframe(
    df: pd.DataFrame,
    *,
    dash_pattern: Sequence[int] = DOTTED_DASH_PATTERN,
    marker_step: int = DOTTED_MARKER_STEP,
) -> Any:
    """Create a dotted MA style figure directly from a dataframe."""
    cleaned = _prepare_dataframe(df)

    source = ColumnDataSource(
        data=dict(
            datetime=cleaned["datetime"].dt.to_pydatetime().tolist(),
            value=cleaned["close"].tolist(),
        )
    )

    fig = _base_dataframe_figure()

    fig.line(
        "datetime",
        "value",
        source=source,
        line_color=LINE_COLOR,
        line_width=2.6,
        line_dash=list(dash_pattern),
        line_cap="round",
        line_join="round",
    )

    if marker_step and marker_step > 1:
        indices = list(range(0, len(source.data["datetime"]), marker_step))
        if indices:
            view = CDSView(filter=IndexFilter(indices))
            fig.scatter(
                "datetime",
                "value",
                source=source,
                view=view,
                size=5.0,
                color=LINE_COLOR,
            )

    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("价格", "@value{0.00}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig


def build_silver_candles_figure_from_dataframe(df: pd.DataFrame) -> Any:
    """Create a silver-themed candlestick figure from a dataframe."""
    cleaned = _prepare_dataframe(df)
    width = _infer_bar_width(cleaned["datetime"])

    inc = cleaned["close"] >= cleaned["open"]
    body_color = np.where(inc, "#C0C0C0", "#8C8C8C")
    wick_color = np.where(inc, "#A0A0A0", "#7A7A7A")

    source = ColumnDataSource(
        data=dict(
            datetime=cleaned["datetime"].dt.to_pydatetime().tolist(),
            open=cleaned["open"].tolist(),
            high=cleaned["high"].tolist(),
            low=cleaned["low"].tolist(),
            close=cleaned["close"].tolist(),
            body_color=body_color.tolist(),
            wick_color=wick_color.tolist(),
        )
    )

    fig = _base_dataframe_figure()
    fig.segment(
        x0="datetime",
        y0="high",
        x1="datetime",
        y1="low",
        source=source,
        line_color="wick_color",
        line_alpha=0.7,
    )
    fig.vbar(
        x="datetime",
        width=width,
        top="open",
        bottom="close",
        source=source,
        line_color="body_color",
        fill_color="body_color",
        line_alpha=0.9,
        fill_alpha=0.9,
    )

    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("开盘", "@open{0.00}"),
                ("最高", "@high{0.00}"),
                ("最低", "@low{0.00}"),
                ("收盘", "@close{0.00}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig


def build_silver_ma_line_from_dataframe(df: pd.DataFrame) -> Any:
    """Create a silver-themed MA line figure from a dataframe."""
    cleaned = _prepare_dataframe(df)

    source = ColumnDataSource(
        data=dict(
            datetime=cleaned["datetime"].dt.to_pydatetime().tolist(),
            value=cleaned["close"].tolist(),
        )
    )

    fig = _base_dataframe_figure()
    fig.line(
        "datetime",
        "value",
        source=source,
        line_color=LINE_COLOR,
        line_width=2.8,
        line_cap="round",
        line_join="round",
    )

    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("价格", "@value{0.00}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig


def build_backtest_from_dataframe(
    df: pd.DataFrame,
    *,
    cash: float = 100_000.0,
    commission: float = 0.0,
) -> Backtest:
    """Convert a dataframe into a Backtest using the passive strategy."""
    cleaned = _prepare_dataframe(df)
    rename_map = {
        "datetime": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    bt_df = cleaned.rename(columns=rename_map)
    if "Volume" not in bt_df.columns:
        bt_df["Volume"] = cleaned.get("volume", 0)
    bt_df = bt_df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    bt_df = bt_df.set_index("Date")
    bt = Backtest(bt_df, PassiveStrategy, cash=cash, commission=commission)
    bt.run()
    return bt


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned["datetime"] = pd.to_datetime(cleaned["datetime"])
    cleaned = cleaned.sort_values("datetime").reset_index(drop=True)
    required = {"open", "high", "low", "close"}
    missing = required.difference(cleaned.columns)
    if missing:
        raise ValueError(f"Missing columns for chart: {', '.join(sorted(missing))}")
    return cleaned


def _base_dataframe_figure() -> Any:
    fig = figure(
        x_axis_type="datetime",
        height=360,
        sizing_mode="stretch_width",
        toolbar_location="right",
    )
    fig.background_fill_color = BACKGROUND_COLOR
    fig.border_fill_color = BACKGROUND_COLOR
    fig.yaxis.axis_label = "Price"
    fig.xaxis.axis_label = "Time"
    return fig


def _infer_bar_width(datetimes: pd.Series) -> float:
    if len(datetimes) < 2:
        return 60_000.0
    diffs = datetimes.diff().dropna().dt.total_seconds().to_numpy()
    if len(diffs) == 0:
        return 60_000.0
    median_ms = np.median(diffs) * 1000.0
    return max(median_ms * 0.6, 1.0)


def render_native_silver_ma2(bt: Backtest):
    """Capture the native Backtest SMA renderer, restyle it, and retain auxiliary panels."""
    captured = {}

    def _capture(obj, *args, **kwargs):
        captured['layout'] = obj
        return obj

    with patch('bokeh.io.show', _capture):
        layout = bt.plot(open_browser=False)

    fig = captured.get('layout', layout)
    children = getattr(fig, 'children', None)
    if children is None:
        children = [fig]

    ohlc_fig = _find_ohlc_figure(children)
    if ohlc_fig is None:
        return fig

    volume_fig = _find_volume_figure(children, exclude=ohlc_fig)

    ma_renderers = list(_ma_line_renderers(ohlc_fig))
    if not ma_renderers:
        return fig

    for renderer, _glyph in _candlestick_renderers(ohlc_fig):
        renderer.visible = False

    for renderer, glyph in ma_renderers:
        glyph.line_color = SILVER_BULL
        glyph.line_width = 2.8
        if hasattr(glyph, 'line_cap'):
            glyph.line_cap = 'round'
        if hasattr(glyph, 'line_join'):
            glyph.line_join = 'round'
        if hasattr(glyph, 'line_dash'):
            glyph.line_dash = 'solid'
        if hasattr(glyph, 'line_alpha'):
            glyph.line_alpha = 1.0
        renderer.visible = True

    _style_price_axis(ohlc_fig)
    if volume_fig is not None:
        _style_volume_panel(volume_fig)
    return fig
