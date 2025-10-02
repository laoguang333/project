# -*- coding: utf-8 -*-
"""Bokeh chart styles for stealth dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Tuple

import pandas as pd
from bokeh.models import ColumnDataSource, HoverTool
from bokeh.plotting import figure

from .config import Timeframe


@dataclass(frozen=True)
class ChartStyle:
    key: str
    label: str
    builder: Callable[[Timeframe], Tuple[object, ColumnDataSource]]
    payload: Callable[[pd.DataFrame], Dict[str, Iterable]]


def _base_figure(timeframe: Timeframe):
    fig = figure(
        x_axis_type="datetime",
        height=380,
        sizing_mode="stretch_width",
        toolbar_location="right",
    )
    fig.background_fill_color = "#f7f7f7"
    fig.xgrid.grid_line_color = None
    fig.ygrid.grid_line_color = "#dedede"
    fig.ygrid.grid_line_dash = [6, 4]
    fig.yaxis.axis_label = "Price"
    fig.xaxis.axis_label = "Time"
    return fig


def _candles_builder(timeframe: Timeframe):
    source = ColumnDataSource(
        data=dict(
            datetime=[],
            open=[],
            high=[],
            low=[],
            close=[],
            volume=[],
            color=[],
            wick_color=[],
        )
    )
    fig = _base_figure(timeframe)
    width = timeframe.duration_ms * 0.6
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
        line_color="color",
        fill_color="color",
        line_alpha=0.9,
        fill_alpha=0.9,
    )
    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("开", "@open{0.00}"),
                ("高", "@high{0.00}"),
                ("低", "@low{0.00}"),
                ("收", "@close{0.00}"),
                ("成交量", "@volume{0,0}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig, source


def _candles_payload(df: pd.DataFrame) -> Dict[str, Iterable]:
    inc = df["close"] >= df["open"]
    colors = ["#C0C0C0" if flag else "#8C8C8C" for flag in inc]
    wick = ["#A0A0A0" if flag else "#7A7A7A" for flag in inc]
    return {
        "datetime": df["datetime"].dt.to_pydatetime().tolist(),
        "open": df["open"].tolist(),
        "high": df["high"].tolist(),
        "low": df["low"].tolist(),
        "close": df["close"].tolist(),
        "volume": df["volume"].tolist(),
        "color": colors,
        "wick_color": wick,
    }


def _line_builder(timeframe: Timeframe):
    source = ColumnDataSource(
        data=dict(
            datetime=[],
            close=[],
        )
    )
    fig = _base_figure(timeframe)
    fig.line("datetime", "close", source=source, line_color="#8A8A8A", line_width=2.0)
    fig.circle("datetime", "close", source=source, size=4, color="#B0B0B0", alpha=0.7)
    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("收", "@close{0.00}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig, source


def _line_payload(df: pd.DataFrame) -> Dict[str, Iterable]:
    return {
        "datetime": df["datetime"].dt.to_pydatetime().tolist(),
        "close": df["close"].tolist(),
    }


def _dots_builder(timeframe: Timeframe):
    source = ColumnDataSource(
        data=dict(
            datetime=[],
            close=[],
        )
    )
    fig = _base_figure(timeframe)
    fig.circle("datetime", "close", source=source, size=4, color="#9C9C9C", alpha=0.8)
    fig.add_tools(
        HoverTool(
            tooltips=[
                ("时间", "@datetime{%F %H:%M}"),
                ("收", "@close{0.00}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
    )
    return fig, source


def _dots_payload(df: pd.DataFrame) -> Dict[str, Iterable]:
    return {
        "datetime": df["datetime"].dt.to_pydatetime().tolist(),
        "close": df["close"].tolist(),
    }


CHART_STYLES = [
    ChartStyle(key="candles", label="银灰蜡烛", builder=_candles_builder, payload=_candles_payload),
    ChartStyle(key="line", label="细线+点", builder=_line_builder, payload=_line_payload),
    ChartStyle(key="dots", label="点状图", builder=_dots_builder, payload=_dots_payload),
]

CHART_STYLE_INDEX = {style.key: style for style in CHART_STYLES}

