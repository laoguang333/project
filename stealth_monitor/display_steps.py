# -*- coding: utf-8 -*-
"""Utilities to build Bokeh figures step by step for debugging display issues."""
from __future__ import annotations

from typing import Tuple

import pandas as pd
from bokeh.models import ColumnDataSource
from bokeh.plotting import figure

from .config import INSTRUMENTS, TIMEFRAMES
from .data_sources import fetch_data


def load_sample_data(limit: int = 200) -> pd.DataFrame:
    instrument = INSTRUMENTS[0]
    timeframe = TIMEFRAMES[0]
    df = fetch_data(instrument, timeframe, limit=limit)
    return df


def build_basic_line(df: pd.DataFrame):
    fig = figure(x_axis_type="datetime", height=300, sizing_mode="stretch_width")
    fig.line(df["datetime"], df["close"], line_color="#336699", line_width=2)
    return fig


def build_columnsourced_line(df: pd.DataFrame) -> Tuple[figure, ColumnDataSource]:
    source = ColumnDataSource(df[["datetime", "close"]])
    fig = figure(x_axis_type="datetime", height=300, sizing_mode="stretch_width")
    fig.line("datetime", "close", source=source, line_color="#336699", line_width=2)
    fig.circle("datetime", "close", source=source, size=4, color="#6699cc")
    return fig, source


def build_candles(df: pd.DataFrame) -> Tuple[figure, ColumnDataSource]:
    source = ColumnDataSource(df[["datetime", "open", "high", "low", "close"]])
    fig = figure(x_axis_type="datetime", height=320, sizing_mode="stretch_width")
    fig.segment("datetime", "high", "datetime", "low", source=source, color="#666666")
    width = 30 * 1000  # 30 seconds in milliseconds
    fig.vbar("datetime", width, "open", "close", source=source,
             fill_color="#C0C0C0", line_color="#8C8C8C", alpha=0.9)
    return fig, source


def build_dashboard_style(df: pd.DataFrame) -> Tuple[figure, ColumnDataSource]:
    from .styles import CHART_STYLE_INDEX

    timeframe = TIMEFRAMES[0]
    style = CHART_STYLE_INDEX["candles"]
    fig, source = style.builder(timeframe)
    payload = style.payload(df)
    source.data = payload
    return fig, source
