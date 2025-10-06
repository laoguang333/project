"""Generate stealthy OHLC previews using backtesting.py visuals."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
from bokeh.io import output_file, save
from bokeh.models import CDSView, ColumnDataSource, IndexFilter

import backtesting._plotting as plotting
from backtesting import Backtest

from run_bear_trap_backtesting import (
    DATA_PATH,
    BearTrapStrategy,
    load_if_data,
    prepare_bear_trap_features,
)

OUTPUT_DIR = Path("outputs") / "stealth_views"
SILVER_BULL = plotting.RGB(192, 192, 192)
SILVER_BEAR = plotting.RGB(158, 158, 158)
LINE_COLOR = "#B0B0B0"
BACKGROUND_COLOR = "#FBFBFB"
DOTTED_DASH_PATTERN: Sequence[int] = (1, 14)
DOTTED_MARKER_STEP = 6


def prepare_backtest(sample_size: int = 400) -> Backtest:
    """Load data, compute features, and initialise a Backtest instance."""
    df = load_if_data(DATA_PATH)
    if sample_size:
        df = df.tail(sample_size * 2)
    df = prepare_bear_trap_features(df)
    if sample_size:
        df = df.tail(sample_size)
    bt = Backtest(df, BearTrapStrategy, cash=1_000_000, commission=0.0)
    bt.run()
    return bt


def render_silver_candles(bt: Backtest, filename: str) -> Path:
    """Render muted silver candlesticks without visible outlines."""
    original_colors = plotting.BULL_COLOR, plotting.BEAR_COLOR
    target = OUTPUT_DIR / filename

    try:
        plotting.BULL_COLOR, plotting.BEAR_COLOR = SILVER_BULL, SILVER_BEAR
        fig = bt.plot(open_browser=False)
    finally:
        plotting.BULL_COLOR, plotting.BEAR_COLOR = original_colors

    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is not None:
        for renderer, glyph in _candlestick_renderers(ohlc_fig):
            if glyph.__class__.__name__ == "VBar":
                glyph.line_alpha = 0.0
            elif glyph.__class__.__name__ == "Segment":
                glyph.line_color = LINE_COLOR
                glyph.line_alpha = 0.85

    _finalise_and_save(fig, target)
    return target


def render_ma_line(bt: Backtest, filename: str) -> Path:
    """Hide candlesticks and draw a silver MA(1) line instead."""
    target = OUTPUT_DIR / filename
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
                line_width=2.5,
                legend_label="MA(1)",
            )
            _style_price_axis(ohlc_fig)

    _finalise_and_save(fig, target)
    return target


def render_dotted_ma_line(
    bt: Backtest,
    filename: str,
    dash_pattern: Sequence[int] | None = None,
    marker_step: int | None = None,
) -> Path:
    """Draw the MA(1) line as a custom dotted path with adjustable spacing."""
    target = OUTPUT_DIR / filename
    fig = bt.plot(open_browser=False)

    ohlc_fig = _find_ohlc_figure(fig.children)
    if ohlc_fig is not None:
        source = _hide_candles_and_get_source(ohlc_fig)
        if source is not None:
            _ensure_ma1(source)
            _draw_dotted_ma(
                ohlc_fig,
                source,
                dash_pattern or DOTTED_DASH_PATTERN,
                marker_step or DOTTED_MARKER_STEP,
            )
            _style_price_axis(ohlc_fig)

    _finalise_and_save(fig, target)
    return target


def _hide_candles_and_get_source(ohlc_fig: Any) -> Optional[ColumnDataSource]:
    """Hide candlestick renderers and return their shared data source."""
    source = None
    for renderer, _ in _candlestick_renderers(ohlc_fig):
        renderer.visible = False
        if source is None:
            source = renderer.data_source
    return source


def _ensure_ma1(source: ColumnDataSource) -> None:
    """Ensure the ColumnDataSource holds an MA(1) column for plotting."""
    data = dict(source.data)
    if "MA1" in data:
        return
    close = np.array(data.get("Close", []), dtype=float)
    data["MA1"] = close.tolist()
    source.data = data


def _draw_dotted_ma(ohlc_fig: Any, source: ColumnDataSource, dash_pattern: Sequence[int], marker_step: int) -> None:
    """Draw a dotted MA(1) line with optional marker spacing control."""
    dash = list(dash_pattern)
    ohlc_fig.line(
        "index",
        "MA1",
        source=source,
        line_color=LINE_COLOR,
        line_width=2.5,
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
                size=5,
                fill_color=LINE_COLOR,
                line_color=LINE_COLOR,
            )


def _style_price_axis(ohlc_fig: Any) -> None:
    """Apply a light background and hide duplicate legends."""
    ohlc_fig.background_fill_color = BACKGROUND_COLOR
    ohlc_fig.border_fill_color = BACKGROUND_COLOR
    if ohlc_fig.legend:
        ohlc_fig.legend.visible = False


def _candlestick_renderers(ohlc_fig: Any):
    """Yield renderers paired with their glyphs for candlestick elements."""
    for renderer in ohlc_fig.renderers:
        glyph = getattr(renderer, "glyph", None)
        if glyph is None:
            continue
        if glyph.__class__.__name__ in {"Segment", "VBar"}:
            yield renderer, glyph


def _find_ohlc_figure(children: Iterable) -> Optional[object]:
    """Locate the primary OHLC figure inside the returned layout."""
    for row in children:
        if row is None:
            continue
        cells = row if isinstance(row, (list, tuple)) else [row]
        for cell in cells:
            if cell is None or not hasattr(cell, "renderers"):
                continue
            for renderer, _ in _candlestick_renderers(cell):
                return cell
    return None


def _finalise_and_save(fig, target: Path) -> None:
    """Persist the composed Bokeh figure to disk."""
    output_file(str(target))
    save(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bt = prepare_backtest()

    silver_path = render_silver_candles(bt, "silver_candles.html")
    print(f"Silver candlesticks saved to: {silver_path}")

    line_path = render_ma_line(bt, "silver_ma_line.html")
    print(f"Silver MA(1) line saved to: {line_path}")

    dotted_path = render_dotted_ma_line(bt, "silver_ma_dotted.html")
    print(f"Dotted MA(1) line saved to: {dotted_path}")


if __name__ == "__main__":
    main()
