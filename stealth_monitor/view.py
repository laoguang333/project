from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

import numpy as np
from bokeh.embed import file_html
from bokeh.models import CDSView, ColumnDataSource, IndexFilter
from bokeh.resources import INLINE
from IPython.display import HTML, display

import backtesting._plotting as plotting
from backtesting import Backtest, Strategy
from backtesting.test import GOOG

SILVER_BULL = plotting.RGB(192, 192, 192)
SILVER_BEAR = plotting.RGB(158, 158, 158)
LINE_COLOR = "#8C8C8C"
BACKGROUND_COLOR = "#FFF7E0"
DOTTED_DASH_PATTERN: Sequence[int] = (1, 20)
DOTTED_MARKER_STEP = 7

class PassiveStrategy(Strategy):
    """占位策略：不做交易，只用于生成基准图表。"""

    def init(self) -> None:  # pragma: no cover
        pass

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


