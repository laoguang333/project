# 量化交易回测框架

这是一个用于期货交易策略回测的框架，支持策略开发、指标计算、回测执行和结果可视化。

## 项目结构

```
project/
├─ backtest_framework.py        # 回测引擎（只做撮合、持仓、PnL、绩效）
├─ strategies/
│  └─ sma_with_oi.py           # 策略实现（只做信号）
├─ indicators/
│  └─ ta.py                    # 指标库（MA、EMA、ATR、布林等）
├─ visualize/
│  └─ plot_kline.py            # 可视化（读取CSV，画K线/指标/成交点/权益/回撤）
├─ configs/
│  └─ if_intraday.yaml         # 配置（合约乘数、费率、tick、文件路径等）
├─ data/
│  └─ IF1005_2010.csv
├─ outputs/
│  ├─ equity.csv               # 回测产出：权益曲线
│  ├─ trades.csv               # 交易明细（时间、方向、价格、数量、手续费等）
│  ├─ positions.csv            # 持仓随时间
│  ├─ metrics.json             # 绩效指标（收益、波动、Sharpe、回撤等）
│  └─ charts/                  # 图片输出目录（可视化脚本生成）
└─ README.md
```

## 功能说明

### 1. 回测引擎 (backtest_framework.py)
- 负责数据加载、订单撮合、持仓管理、盈亏计算和绩效评估
- 提供了Backtester类，实现了完整的回测流程
- 支持基本的订单类型和执行逻辑
- 计算关键绩效指标如总收益率、波动率、夏普率和最大回撤

### 2. 策略模块 (strategies/)
- 策略基类Strategy，定义了策略的基本接口
- 示例策略SMAWithOIStrategy，基于SMA和持仓量变化生成交易信号
- 策略只负责生成交易信号，不涉及具体的执行逻辑

### 3. 指标库 (indicators/)
- 提供常用技术指标的计算函数
- 包括MA、EMA、ATR、布林带、RSI、MACD、KDJ等指标
- 所有指标计算均基于pandas实现，支持向量化运算

### 4. 可视化模块 (visualize/)
- 提供K线图、指标图、交易信号标记、权益曲线和回撤分析的可视化功能
- 支持图片保存和交互式显示
- 适配中文显示

### 5. 配置文件 (configs/)
- YAML格式的配置文件，集中管理回测参数
- 包括合约信息、交易参数、数据配置、策略参数等
- 支持灵活的参数调整，无需修改代码

### 6. 数据目录 (data/)
- 存放原始市场数据
- 支持CSV格式的OHLCV数据
- 数据列包括：date, open, high, low, close, volume, money, open_interest, symbol

### 7. 输出目录 (outputs/)
- 存放回测结果和可视化图表
- 包括权益曲线、交易明细、持仓记录、绩效指标和图表文件

## 安装依赖

```bash
pip install pandas numpy matplotlib PyYAML
```

## 使用方法

### 1. 准备数据
将CSV格式的市场数据放入`data/`目录下，确保数据包含所需的列。

### 2. 配置参数
编辑`configs/if_intraday.yaml`文件，设置合约参数、交易参数、策略参数等。

### 3. 运行回测

```bash
python backtest_framework.py --csv data/IF1005_2010.csv --symbol IF1005
```

### 4. 生成可视化图表

```bash
python -m visualize.plot_kline --data_file data/IF1005_2010.csv
```

## 策略开发

1. 在`strategies/`目录下创建新的策略文件
2. 继承`Strategy`基类，实现`init`和`on_bar`方法
3. 在`on_bar`方法中根据市场数据生成交易信号

```python
from ..backtest_framework import Strategy, Position, Order

class MyStrategy(Strategy):
    def __init__(self, params=None):
        super().__init__(params)
        # 初始化参数
        
    def init(self, data):
        # 预计算指标
        
    def on_bar(self, i, row, pos):
        # 生成交易信号
        orders = []
        # ... 策略逻辑 ...
        return orders
```

## 注意事项

1. 回测结果仅供参考，不代表未来收益
2. 请根据实际情况调整手续费率、滑点等参数
3. 对于高频策略，可能需要优化代码性能
4. 数据质量对回测结果影响重大，请确保数据的准确性

## 扩展建议

1. 添加更多策略类型（如趋势跟踪、均值回归、套利等）
2. 实现更复杂的订单类型（如限价单、止损单、止盈单等）
3. 增加多品种、多策略的回测支持
4. 添加参数优化功能
5. 实现实盘接口对接

## License
MIT