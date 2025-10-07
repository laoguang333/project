# 缓存策略使用指南

本文件说明 `stealth_monitor.cached_data_sources` 中的混合缓存能力（内存 + SQLite），并总结当前局限。

## 1. 功能概览
- **内存缓存**：默认开启，保存最近一次请求的 DataFrame，并在设定超时时间内直接返回，适合频繁刷新同一标的。
- **SQLite 缓存**：默认开启，在 `stealth_monitor/data_cache.db` 中持久化 OHLCV 数据，避免重复向 akshare 拉取历史。
- **策略注册**：`data_source_factory.py` 将缓存策略注册为 `hybrid_cache`，可在运行时切换。
- **辅助函数**：提供配置、清理与状态查询接口，便于在 Notebook 内快速管理缓存。

## 2. 快速使用
```python
from stealth_monitor.data_source_factory import (
    use_hybrid_cache,
    configure_hybrid_cache,
    get_hybrid_cache_info,
)

use_hybrid_cache()  # 改用混合缓存策略
info = get_hybrid_cache_info()
print(info)
```

如需恢复实时拉取，可调用 `use_original_data_source()`。

## 3. 常用配置项
- `enabled`：是否启用内存缓存，默认 `True`。
- `memory_cache_timeout_seconds`：内存缓存超时时间（秒），默认 `30`。
- `sqlite_cache_enabled`：是否启用 SQLite 缓存，默认 `True`。
- `sqlite_db_path`：SQLite 文件路径，默认位于包目录下。

示例：
```python
configure_hybrid_cache(
    memory_cache_timeout_seconds=120,
    sqlite_db_path='/tmp/stealth_cache.db',
)
```

## 4. 清理与诊断
- `clear_hybrid_cache(clear_memory=True, clear_sqlite=False)`：分别清空内存或持久化缓存。
- `get_hybrid_cache_info()`：返回内存缓存条目数量与 SQLite 表记录数，便于确认命中情况。
- SQLite 读写异常会打印警告但不会中断数据拉取，必要时检查磁盘写权限。

## 5. 当前限制
- Notebook 中尚未提供 UI 控件切换缓存策略或配置参数，需要在代码单元里手动调用上述函数。
- 缓存格式固定为标准化 OHLCV，若后续扩展指标数据需同步调整 `_normalize_dataframe`。
- 缓存文件未实现自动归档与清理策略，长时间运行后需要手动删除或迁移。
- `cache_strategy_example.ipynb` 仍为空白，可补充完整操作流程与命中演示。
