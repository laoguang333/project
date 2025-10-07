# Stealth Monitor 需求说明

## 核心目标
- 在办公环境中隐蔽地查看行情：界面低调、配色柔和、避免引人注意。
- 支持精选品种的快速切换：期货（PVC、塑料等）与 A 股（贵州茅台等）。
- 多周期展示：分钟线（1/5/15/30/60）与日线。
- 图表样式灵活：银灰蜡烛、线图、点状图等一键切换。
- 自动刷新与轻量提示：默认 10 秒更新，可随时停止。

## 当前进展
- `config.py` 已固化 3 个标的与 6 个周期，并提供索引查询。
- `data_sources.py` 已接入 akshare，统一整理为标准化 OHLCV 结构。
- `data_source_factory.py` 支持注册/切换数据源策略，默认走实时拉取，可选混合缓存。
- `cached_data_sources.py` 实现内存 + SQLite 双层缓存，并暴露配置、清理、状态查询接口。
- `styles.py` 提供 3 套低调主题的 Bokeh 图表样式，已在 `StealthDashboard` 中接入。
- `controller.py` 完成仪表盘调度，在 `notebooks/stealth_dashboard.ipynb` 中与 ipywidgets 组合实现选项联动与自动刷新。
- `view.py` 与 `notebooks/testview.ipynb` 展示了 backtesting 库输出的银灰主题定制。
- `display_steps.py` 及对应 notebook 用于逐步调试 Bokeh 渲染流程。

## 待完善事项
- `cache_strategy_example.ipynb` 仍为空白，缺少使用缓存策略的实际演示。
- Notebook 端缺少切换缓存策略/配置参数的控件，`StealthDashboard` 也尚未暴露该入口。
- `testview.ipynb` 中注释掉 `render_silver_candles` 的创建但仍调用 `display_bokeh(silver_fig)`，示例需修正。
- `stealth_dashboard.ipynb` 尾部单元调用 `controller.stop()` 会触发内核崩溃，应排查事件循环兼容问题。
- 缺少自动化测试以及 nbconvert 批处理验证，未覆盖异常分支。
- 标的、周期、样式均为硬编码，可考虑外部配置或热更新以便扩展。

## 技术要求
- 使用 akshare 作为行情数据来源。
- 使用 Bokeh + ipywidgets 构建前端展示与交互。
- 核心逻辑封装在 Python 包 `stealth_monitor` 内，便于复用与维护。
- Jupyter Notebook 负责配置、控件绑定与展示。
- 兼容 nbconvert 批处理执行，确保 notebook 可一键跑通。
