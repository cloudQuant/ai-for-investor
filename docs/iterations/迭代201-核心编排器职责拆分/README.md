# 迭代 201：核心编排器职责拆分

## 背景

迭代 200 建立了类型、依赖、前端 bundle 和可复现性门禁。在其源码尺寸复审中，以下模块虽然继续受尺寸棘轮保护，但本身已承载过多职责；仅调整行数基线不能替代结构性治理。本迭代是这些结构债务的唯一关闭载体，迭代 200 的基线更新不构成关闭。

- `app/services/market_data/store.py`
- `app/api/portfolio/api.py`
- `app/services/trading_workspace_service.py`
- `app/services/market_instrument.py`
- `app/services/position_valuation.py`
- `app/services/ai_strategy_research_task_manager.py`
- `src/frontend/src/views/strategy/useStrategyPage.ts`

本迭代将这些历史巨型编排器拆成具名、可单测的边界，同时保持已有对外 API、数据模型、错误码和交易风控语义。

## 明确移交范围

除七个主工作包外，下列四个共享提取候选也从迭代 200 的尺寸处置单移交到本迭代；它们不能因未列入原七项而失去责任人。

| 候选 | 当前职责 | 计划工作包 |
| --- | --- | --- |
| `market_data/cffex_settlement_collector.py` 与 `market_data/stock_valuation_collector.py` | persisted receipt 边界校验重复 | WP-08 |
| `market_data/publication.py` 与 `research/holdout_finalize.py` | 数据库 cursor `rowcount` 读取重复 | WP-09 |

所有九个工作包在 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) 中都有基线、量化目标、抽取边界和指定回归命令。任何一个未完成时，相关结构债务保持 `OPEN / Iteration 201`。

## 成功标准

1. 每个目标模块按职责抽取到受控子模块/composable，原入口保留稳定兼容接口。
2. 每次抽取都有覆盖原行为的定向回归、静态检查和格式检查；不以 `Any`、`cast`、`type: ignore` 或放宽 lint/type 规则换取通过。
3. 每个目标入口达到计划中的量化行数上限；仅更新 `large_file_ratchet.py` 基线不算收敛。任何新生产源文件不得超过 1,000 行。
4. 前端策略页拆分后，Node 20 的 typecheck、Vitest、build 和 manifest bundle gate 持续通过。
5. 后端拆分后，Mypy 1.20.2 0-error ratchet、Ruff、相关 pytest 与依赖同步门禁持续通过。

真实数据库、行情供应商、券商/交易网关和生产交易验收不属于本次局部重构的自动化证明范围，除非另有明确授权和环境证据。

## 约束

- 先抽取纯函数、DTO/协议、查询适配器和渲染状态；不要在同一批中改变业务规则或数据库 schema。
- 对持久化、授权、风控、仓位和研究绑定路径采用失败关闭；保持错误码和调用顺序。
- 逐模块小批次验收，避免将七个模块合并成不可审阅的大型重构。
- 不重置、覆盖或清理用户已有工作区变更。

详见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。
