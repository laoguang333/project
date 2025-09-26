import pandas as pd

def sma(series: pd.Series, n: int) -> pd.Series:
    """简单移动平均"""
    return series.rolling(window=n, min_periods=1).mean()

def ema(series: pd.Series, n: int) -> pd.Series:
    """指数移动平均"""
    return series.ewm(span=n, adjust=False).mean()

def macd(series: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> pd.DataFrame:
    """MACD指标
    计算MACD线、信号线和柱状图
    返回DataFrame包含['macd', 'signal', 'histogram']三个列
    """
    # 计算快线和慢线
    fast_ema = ema(series, fast_period)
    slow_ema = ema(series, slow_period)
    
    # 计算MACD线
    macd_line = fast_ema - slow_ema
    
    # 计算信号线
    signal_line = ema(macd_line, signal_period)
    
    # 计算柱状图
    histogram = macd_line - signal_line
    
    # 返回DataFrame
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    })

def kline_overlap(df: pd.DataFrame, lookback: int = 3) -> pd.Series:
    """K线重叠指标
    如果过去lookback根K线有重叠的部分，就表示为1，否则表示为0
    需要DataFrame包含high和low列
    """
    # 计算过去lookback根K线的最高价最小值和最低价最大值
    rolling_high_min = df['high'].rolling(window=lookback).min()
    rolling_low_max = df['low'].rolling(window=lookback).max()
    
    # 如果最高价最小值大于最低价最大值，则表示有重叠
    overlap = (rolling_high_min > rolling_low_max).astype(int)
    
    return overlap

def ma_crossover(series1: pd.Series, series2: pd.Series) -> pd.Series:
    """均线交叉指标
    接受两根均线，输出交叉点：
    1表示series1上穿series2
    -1表示series1下穿series2
    0表示无交叉
    """
    # 确保两个Series长度相同
    if len(series1) != len(series2):
        raise ValueError("两个Series长度必须相同")
    
    # 计算前一天的值
    prev_series1 = series1.shift(1)
    prev_series2 = series2.shift(1)
    
    # 检测交叉点
    # 上穿: 当前series1 > series2 且 前一天series1 <= series2
    cross_up = (series1 > series2) & (prev_series1 <= prev_series2)
    
    # 下穿: 当前series1 < series2 且 前一天series1 >= series2
    cross_down = (series1 < series2) & (prev_series1 >= prev_series2)
    
    # 创建结果Series
    result = pd.Series(0, index=series1.index)
    result[cross_up] = 1
    result[cross_down] = -1
    
    return result

def ma_volatility(series: pd.Series, base_period: int = 1, ma_period: int = 5, lookback: int = 20, volatility_type: str = 'range') -> pd.Series:
    """均线波动幅度指标
    计算5倍周期下，5均线在过去20根K线的波动幅度
    
    参数:
        series: 原始价格序列
        base_period: 基础周期（默认1分钟）
        ma_period: 均线周期（默认5）
        lookback: 回溯K线数量（默认20）
        volatility_type: 波动幅度类型，'range'表示绝对范围，'percent'表示百分比
    
    返回:
        均线波动幅度的Series
    """
    # 将原始数据重采样到5倍周期
    # 假设输入序列的索引是时间，我们使用resample进行重采样
    # 注意：这里假设基础周期单位为分钟，如果是其他单位需要调整
    if hasattr(series.index, 'freq') and series.index.freq is not None:
        # 如果索引已经有频率信息
        freq_str = f'{base_period * 5}min'
        resampled_series = series.resample(freq_str).last()
    else:
        # 对于没有频率信息的索引，我们每隔5个数据点采样一次
        resampled_series = series.iloc[::5].copy()
    
    # 计算5倍周期下的5日均线
    ma_line = sma(resampled_series, ma_period)
    
    # 计算过去20根K线的波动幅度
    rolling_max = ma_line.rolling(window=lookback).max()
    rolling_min = ma_line.rolling(window=lookback).min()
    
    if volatility_type.lower() == 'percent':
        # 计算百分比波动幅度
        volatility = (rolling_max - rolling_min) / rolling_min * 100
    else:
        # 计算绝对波动范围
        volatility = rolling_max - rolling_min
    
    # 将结果重新索引回原始数据的索引，使用前向填充
    volatility = volatility.reindex(series.index, method='ffill')
    
    return volatility