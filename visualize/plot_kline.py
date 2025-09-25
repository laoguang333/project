import os
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime
from indicators import ta  # 若未做包，可改为手动 sys.path 方式

# 频率规范化：支持 "1T"/"5T"/"15T" 兼容，但统一转为 "1min" 等新写法
def _normalize_freq(freq: str) -> str:
    freq = freq.strip().lower()
    if freq.endswith("t"):
        # 兼容老写法：1t/5t/15t -> 1min/5min/15min
        return freq[:-1] + "min"
    return freq

def plot_kline(
    data_csv="data/IF9999.CCFX.csv",
    round_trips_csv="outputs/round_trips.csv",
    indicators=None,
    out_path="outputs/kline.png",
    start=None,
    end=None,
    freq="1min",        # "1min" / "5min" / "15min"
    limit=200           # 默认只显示最后200根
):
    # === 1) 加载行情 ===
    if not os.path.exists(data_csv):
        raise FileNotFoundError(f"行情数据文件不存在: {data_csv}")

    df = pd.read_csv(data_csv)
    if "date" not in df.columns:
        raise ValueError("数据缺少 'date' 列")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # === 2) 重采样到指定周期 ===
    freq = _normalize_freq(freq)
    if freq != "1min":
        df = df.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            # open_interest 常用 last
            "open_interest": "last"
        }).dropna(how="any")  # 避免产生全NaN的bar

    # === 3) 时间范围过滤 ===
    if start:
        start = pd.to_datetime(start)
        df = df.loc[df.index >= start]
    if end:
        end = pd.to_datetime(end)
        df = df.loc[df.index <= end]

    # === 4) 默认只显示最后 limit 根（仅当未指定时间范围） ===
    if start is None and end is None and limit:
        df = df.tail(limit)

    if df.empty:
        raise ValueError("当前筛选/重采样后没有可用于绘图的K线数据（检查 start/end/freq/limit 是否过于严格）。")

    # === 5) 处理指标：对齐索引，若在可见窗口无有效点则跳过 ===
    addplots = []
    if indicators:
        for name, series in indicators.items():
            # 先转成 Series，按当前 df.index 对齐
            s = pd.Series(series).copy()
            s.index = pd.to_datetime(s.index)
            s = s.reindex(df.index)

            # 清理全NaN或无有效数据的情况，避免 mplfinance 报错
            if s.dropna().empty:
                # 当前可见区间内没有任何有效数据，跳过此指标
                continue

            df[name] = s
            addplots.append(mpf.make_addplot(df[name], width=1.0))
            # 不手动指定颜色，避免与全局风格冲突；需要时可自行传入

    # === 6) 绘制K线 ===
    fig, axlist = mpf.plot(
        df,
        type="candle",
        style="yahoo",
        addplot=addplots if addplots else None,
        volume=True,
        returnfig=True,
        figratio=(16, 9),
        figscale=1.2
    )
    ax = axlist[0]

    # 当前显示范围（用于过滤交易线）
    xmin, xmax = df.index.min(), df.index.max()

    # === 7) 交易轨迹（可选）：范围内才画，盈利绿/亏损红 ===
    if os.path.exists(round_trips_csv):
        trades = pd.read_csv(round_trips_csv, parse_dates=["open_time", "close_time"])
        for _, t in trades.iterrows():
            ot, ct = pd.to_datetime(t["open_time"]), pd.to_datetime(t["close_time"])
            # 只要两端有任意一点落在显示范围内，就画（不强制与索引对齐）
            if (ot < xmin and ct < xmin) or (ot > xmax and ct > xmax):
                continue
            color = "green" if float(t.get("pnl", 0)) > 0 else "red"
            ax.plot([ot, ct], [t["open_price"], t["close_price"]], linewidth=1.5, color=color, alpha=0.9)

    # === 8) 保存 ===
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    print(f"✅ 已保存图表: {out_path}")


if __name__ == "__main__":
    # demo：如果存在默认数据，就给两条均线作为示例
    data_csv = "data/IF9999.CCFX.csv"
    round_trips_csv = "outputs/round_trips.csv"

    if os.path.exists(data_csv):
        raw = pd.read_csv(data_csv)
        raw["date"] = pd.to_datetime(raw["date"])
        raw = raw.set_index("date").sort_index()
        s_close = raw["close"]
        indicators = {
            "SMA5": ta.sma(s_close, 20),
            "EMA10": ta.ema(s_close, 60)
        }
    else:
        indicators = None

    plot_kline(
        data_csv=data_csv,
        round_trips_csv=round_trips_csv,
        indicators=indicators,
        out_path="outputs/charts/demo.png",
        freq="5min",      # 可改 "1min"/"15min"
        limit=200
    )
