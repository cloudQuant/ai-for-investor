# 迭代 201 实施计划

## 关闭规则

每个工作包都必须同时满足以下条件，才能把相应的 `OPEN / Iteration 201` 标为关闭：

1. 原入口保留兼容 facade、公开导出、错误码和数据写入顺序。
2. 原入口达到表中的最大行数；新模块必须小于 1,000 行。不得以注释删除、压缩格式或更新 baseline 代替职责拆分。
3. 指定回归、目标 Mypy、Ruff/format 和 `scripts/ci/large_file_ratchet.py` 均通过；后端使用 canonical dev lock 的 Mypy 1.20.2。
4. 涉及持久化、授权、风控、仓位或研究绑定的抽取必须保留失败关闭、事务边界和已有错误码。

## 工作包与量化验收

| ID | 原入口基线 → 最大行数 | 必须抽取的边界（建议具名模块） | 最低回归命令 |
| --- | --- | --- | --- |
| WP-01 | `market_data/store.py` 4,556 → <= 3,900 | 持久化写入（`store_persistence.py`）、证据/来源授权（`store_evidence.py`）、日历读取（`store_calendar.py`）、查询投影（`store_projection.py`） | `pytest -q tests/market_data_platform/test_store.py tests/market_data_platform/test_query_service.py tests/market_data_platform/test_query_resolution.py` |
| WP-02 | `api/portfolio/api.py` 3,393 → <= 2,900 | 实例解析（`instance_resolution.py`）、仓位归并（`position_aggregation.py`）、资产规格适配（`asset_spec_adapter.py`）；路由只保留请求/响应适配 | `pytest -q tests/test_portfolio_api.py tests/test_portfolio_ledger.py tests/test_portfolio_ledger_analytics.py` |
| WP-03 | `trading_workspace_service.py` 3,089 → <= 2,650 | 运行时快照、合约规格、仓位归一化、启动编排；入口只协调这些可测试协作者 | `pytest -q tests/test_trading_workspace_service.py tests/test_paper_runtime_service.py` |
| WP-04 | `market_instrument.py` 2,514 → <= 2,150 | 资产类别适配、动态数据收窄、指标投影 | `pytest -q tests/test_market_instrument_api.py tests/test_market_instrument_freshness.py tests/test_market_instrument_type_boundaries.py` |
| WP-05 | `position_valuation.py` 2,379 → <= 2,000 | 数值清洗、价格/持仓估值、结果投影 | `pytest -q tests/test_position_valuation.py tests/test_trading_workspace_service.py` |
| WP-06 | `ai_strategy_research_task_manager.py` 2,152 → <= 1,800 | 任务生命周期、状态投影、研究绑定编排 | `pytest -q tests/test_ai_strategy_research_service.py` 加上被抽取边界的新增失败路径测试 |
| WP-07 | `src/frontend/src/views/strategy/useStrategyPage.ts` 8,204 → <= 6,500 | AI 研究、策略 CRUD、表单/对话框、运行时操作、视图状态 composable；页面 API 不变 | `npm run typecheck && npm run test -- --run src/__tests__/views/StrategyPage.test.ts && npm run build && bash ../../scripts/ci/check_bundle_size.sh dist` |
| WP-08 | `cffex_settlement_collector.py` 1,366 → <= 1,335；`stock_valuation_collector.py` 1,142 → <= 1,115 | 一个只接受 `PersistedProviderFetch` 的共享 receipt-boundary helper；各调用方保留自己的错误码映射 | `pytest -q tests/market_data_platform/test_cffex_settlement_collector.py tests/market_data_platform/test_stock_valuation_collector.py` |
| WP-09 | `market_data/publication.py` 1,134 → <= 1,115；`research/holdout_finalize.py` 2,197 → <= 2,178 | 一个共享的数据库 cursor `rowcount` helper，调用方保留原事务与异常归一 | `pytest -q tests/market_data_platform/test_publication_recovery.py tests/market_data_platform/test_deferred_publication.py tests/test_ai_research_holdout_finalize.py` |

表中的数字以迭代 200 的 `SOURCE_SIZE_DISPOSITION.md` 记录的 2026-09-22 行数为基线。若实现前文件因独立、已验收工作发生变化，先在工作包中记录新基线和原因；不得静默放宽目标。

## 每个工作包的固定流程

1. 记录当前公共导出、调用图、错误码、持久化副作用、基线行数和本表指定测试的失败/通过状态。
2. 先抽取纯函数、DTO、协议、查询适配器或渲染状态；原入口保留兼容 facade，不改变请求/响应或数据库 schema。
3. 添加覆盖抽取边界、异常路径、兼容导入和失败关闭的测试；已有测试通过不能代替这些新边界断言。
4. 运行指定 pytest/Vitest、目标 Mypy、Ruff/format；前端另运行 typecheck、build 和 manifest bundle gate。
5. 运行 `scripts/ci/large_file_ratchet.py`，记录原入口的实际行数与抽取模块行数；只有真实达到量化目标才关闭工作包。
6. 对高风险持久化和交易路径执行根代理复审，检查失败关闭、事务边界、错误码稳定性和未覆盖的外部系统边界。

## 退出条件

九个工作包全部关闭、全局源码尺寸棘轮通过，且迭代 200 建立的 canonical-lock Mypy、依赖安全、前端 lint/bundle 和本地测试门禁没有回归。真实外部系统验证仍须按其环境和证据单独报告，不得由本地 fixture 代替。
