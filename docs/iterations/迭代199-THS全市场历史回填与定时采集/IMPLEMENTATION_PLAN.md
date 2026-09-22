# 迭代 199：实施计划

## 任务包

### T0：全市场 identity 前置（S0）
- `app/services/market_data/ths_dump_importer.py` 中的 `seed_market_identities`
- 从 `tickers/list?asset_type=a-share` 分页拉全市场清单 → `MarketDataIdentityWriter` 落库
- 验收：可解析的标的数据 > 0，重复运行幂等

### T1：Parquet 下载与解析（S1）
- `ThsDumpDownloader`：`market-dumps/<kind>/download-url` → 即时下载 → 解析 Parquet
- 依赖：`pyarrow`（环境已具备）
- 验收：真实 dump 解析出行数与 schema 一致；超限大小拒绝

### T2：Parquet importer 落库（S1）
- `ThsDumpImporter`：按 `thscode` 分组 → 构造 unbound context → collector 落库
- `date_ms` → UTC midnight 归一化（-1 天）
- 验收：fixture + 真实小规模落库

### T3：全量回填 CLI（S2）
- `scripts/backfill_ths_history.py`：`--dataset daily-k|adjustment-factors|financials|calendar|index`
- `--apply` 才写库；`--limit` 限制标的数；断点续跑
- 验收：真实回填计数

### T4：每日增量 CLI（S3）
- `scripts/collect_ths_daily.py`：`daily-k-10d` + 日历
- 幂等
- 验收：重复运行不产生重复

### T5：调度接入（S4）
- `app/services/market_data/ths_scheduler.py` + 启动挂载（`MARKET_DATA_THS_SCHEDULER_ENABLED`）
- 验收：任务注册可见、可解释

### T6：验收（S5）
- `tests/market_data_platform/test_ths_dump_importer.py`
- `scripts/acceptance/iteration199_ths_history.py`

## 顺序

T0 → T1 → T2 → T3 → T4 → T5 → T6

## 回滚单元

| PR | 内容 | 回滚 |
| --- | --- | --- |
| P1 | downloader + importer | 默认 dry-run，无写入 |
| P2 | 回填 CLI | 不加 --apply 不写 |
| P3 | 调度服务 | flag 关闭即停 |
