# 源码尺寸棘轮处置单

日期：2026-09-22。本文是 `scripts/ci/large_file_ratchet.py` 的受审查处置记录，不是对历史巨型模块结构债务的关闭声明。

## 事实与决定

迭代 200 的类型收紧、失败关闭和市场数据功能接入使 24 个已有大型生产文件超过迭代 183 基线；前端 lint 收口又带来 7 个纯模板排版增量。独立复审逐项检查了共 31 项增长及其调用边界：撤销这些行会撤销已经验证的安全/类型行为或 lint 要求；而将七个多职责编排器强行压回旧行数，需要跨越数据持久化、路由、工作空间和前端状态的高风险重构。

因此：

1. 本轮只在完成门禁与定向验证后，将下面列出的 31 项**增长**（24 项业务/后端增量与 7 项前端 lint 格式增量）写入新的非回退基线。`large_file_ratchet.py --update` 会确定性地重算全部受跟踪源文件，因此它还会保留本轮已发生的缩小（这会收紧而非放宽门禁）；该动作仍由 `ALLOW_BASELINE_UPDATE=1` guard 显式保护，并且不会新增超过 1,000 行的生产文件。
2. 基线刷新不关闭七个长期结构债务；它们已转入 [迭代 201](../迭代201-核心编排器职责拆分/README.md)，并要求目标模块实际缩小才可关闭。
3. 后续新增行仍会立即被棘轮阻断。小型可共享提取候选也保留到迭代 201，而不是以无测试的压行数操作处理。

## 当前超基线清单

| 类别 | 文件 | 旧基线 | 当前行数 | 差值 | 处置与理由 |
| --- | --- | ---: | ---: | ---: | --- |
| 结构拆分 | `src/backend/app/api/portfolio/api.py` | 3352 | 3393 | +41 | 路由、实例解析和仓位归并耦合；转入迭代 201 工作包 2。 |
| 必要增量 | `src/backend/app/config.py` | 1307 | 1332 | +25 | THS fail-closed 设置与调度开关。 |
| 必要增量 | `src/backend/app/models/market_data_platform.py` | 1507 | 1569 | +62 | SQLAlchemy 2 显式映射与 JSON 类型边界。 |
| 结构拆分 | `src/backend/app/services/ai_strategy_research_task_manager.py` | 2138 | 2152 | +14 | 研究任务生命周期与编排混合；转入迭代 201 工作包 6。 |
| 必要增量 | `src/backend/app/services/akshare/script.py` | 1820 | 1823 | +3 | 运行时类型/失败关闭收窄。 |
| 必要增量 | `src/backend/app/services/backtest/service.py` | 1274 | 1293 | +19 | 已验证的请求/运行时边界收窄。 |
| 必要增量 | `src/backend/app/services/gateway/manual.py` | 2708 | 2721 | +13 | 网关持久化与类型边界修复。 |
| 必要增量 | `src/backend/app/services/live_trading/manager.py` | 1802 | 1803 | +1 | 异步运行时边界修复。 |
| 必要增量 | `src/backend/app/services/market_data/akshare_provider.py` | 2415 | 2416 | +1 | AkShare 字段/协议兼容边界。 |
| 可共享提取 | `src/backend/app/services/market_data/cffex_settlement_collector.py` | 1355 | 1366 | +11 | 与估值 collector 的 persisted-receipt 守卫可在迭代 201 抽共享边界。 |
| 可共享提取 | `src/backend/app/services/market_data/publication.py` | 1124 | 1134 | +10 | 与 holdout finalize 的 cursor-rowcount 可抽共享 DB 结果工具。 |
| 必要增量 | `src/backend/app/services/market_data/research_binding.py` | 2330 | 2337 | +7 | 研究授权/绑定失败关闭。 |
| 可共享提取 | `src/backend/app/services/market_data/stock_valuation_collector.py` | 1121 | 1142 | +21 | 与 CFFEX collector 的 receipt 守卫可共享。 |
| 结构拆分 | `src/backend/app/services/market_data/store.py` | 4535 | 4556 | +21 | 持久化、证据、授权、日历查询多职责；转入迭代 201 工作包 1。 |
| 必要增量 | `src/backend/app/services/market_data_coverage_service.py` | 1000 | 1003 | +3 | 覆盖率数据的类型边界。 |
| 结构拆分 | `src/backend/app/services/market_instrument.py` | 2500 | 2514 | +14 | 资产适配与动态清洗混合；转入迭代 201 工作包 4。 |
| 结构拆分 | `src/backend/app/services/position_valuation.py` | 2369 | 2379 | +10 | 数值清洗和估值投影混合；转入迭代 201 工作包 5。 |
| 可共享提取 | `src/backend/app/services/research/holdout_finalize.py` | 2190 | 2197 | +7 | 与 publication 同构的 cursor-rowcount 工具。 |
| 必要增量 | `src/backend/app/services/research/independent_evaluator.py` | 1113 | 1114 | +1 | 研究结果类型收窄。 |
| 必要增量 | `src/backend/app/services/research/run_records.py` | 1815 | 1819 | +4 | 运行记录类型收窄。 |
| 结构拆分 | `src/backend/app/services/trading_workspace_service.py` | 3080 | 3089 | +9 | 运行时快照、仓位与启动编排混合；转入迭代 201 工作包 3。 |
| 必要增量 | `src/backend/app/services/workspace/run_ops.py` | 1666 | 1669 | +3 | 工作空间运行时边界。 |
| 必要增量 | `src/backend/app/services/workspace/units.py` | 1299 | 1301 | +2 | 工作空间 unit 类型收窄。 |
| 结构拆分 | `src/frontend/src/views/strategy/useStrategyPage.ts` | 8201 | 8204 | +3 | AI 研究、CRUD、表单和运行时操作共存；转入迭代 201 工作包 7。 |

## 前端 lint 格式化增量复核（2026-09-22）

前端将 `eslint . --max-warnings 0` 收口为 warning-free 后，按路径重新计算
棘轮差异。当前基线之外只出现下面 7 个路径，且没有新的超过 1,000 行文件：

| 文件 | 前端 lint 前的 T67 后基线 | 当前行数 | 增量 | 归因 |
| --- | ---: | ---: | ---: | --- |
| `src/frontend/src/components/workspace/WorkspaceReportTab.vue` | 1160 | 1182 | +22 | `vue/singleline-html-element-content-newline` 要求的图标内容换行 |
| `src/frontend/src/views/BacktestResultPage.vue` | 1741 | 1753 | +12 | Vue 元素内容、属性和 closing bracket 的 lint 格式化 |
| `src/frontend/src/views/NewsIntelligencePage.vue` | 1477 | 1522 | +45 | Vue 图标内容与多属性 `el-option` 的 lint 格式化 |
| `src/frontend/src/views/PortfolioPage.vue` | 1870 | 1885 | +15 | Vue 属性/子元素换行；同文件类型标注调整不增加物理行数 |
| `src/frontend/src/views/QuotePage.vue` | 2293 | 2304 | +11 | Vue 图标内容与多属性 closing bracket 的 lint 格式化 |
| `src/frontend/src/views/investment/AssetAnalysisPage.vue` | 1494 | 1512 | +18 | Vue 文本内容换行及 `v-html` 作用域 lint 注释稳定化 |
| `src/frontend/src/views/investment/StockAnalysisPage.vue` | 1611 | 1617 | +6 | `v-html` 作用域 lint 注释稳定化 |

逐项 diff 复核确认这些行数增量均来自本轮 lint 要求的模板可读性换行或
对应的 `v-html` 安全抑制范围标注；未增加组件、状态、请求、业务分支或数据
结构。这里的基线是前端 lint 修改前、已经过 T67 受保护刷新的实际 gate 值：
`QuotePage.vue` 与 `StockAnalysisPage.vue` 当时已分别从 HEAD 的 2294/1613
收紧到 2293/1611。因此，本次前端核对仅精确更新上述 7 个 baseline 键，未使用
第二次全量 baseline 重写；相对 HEAD 的完整 baseline diff 仍包含此前已记录的
24 项增长、9 项收紧、1 项移除及本表 7 项，共 41 个键变化。

## 写入结果

上表 24 项业务/后端增长在此前已通过显式
`ALLOW_BASELINE_UPDATE=1` guard 的受审查刷新写入。随后前端 lint 收口才产生
7 项额外的格式化行数；由于当前工作树包含无关用户改动，第二次没有执行会重写
全部条目的 `large_file_ratchet.py --update`。经逐路径 diff 复核后，只精确更新了
前端 lint 表中列出的 7 个 baseline 键，再以普通模式复验
`large_file_ratchet: passed`。

此前受保护刷新还自动下调了已缩小的
`api/strategy/base.py`、`direct_order_service.py`、`bootstrap.py`、
`query_service.py`、`paper_trading_service.py`、`quote_service.py`、
`promotion.py`、`workspace_unit_runtime.py` 与 `WorkspaceDetailPage.vue` 的上限；
`provider_contracts.py` 已低于 1,000 行，因而退出 baseline。上述变化都是
更严格的棘轮，不是对额外增长的豁免。`QuotePage.vue` 与
`StockAnalysisPage.vue` 不属于上述缩小项，而是分别以 +11 与 +6 计入前端 lint
格式化复核表。P1 异步边界抽取后的
`WorkspaceDetailPage.vue` 为 1,175 行，低于其原有 1,181 行上限，未被作为
增长写入。

## 本轮验证前提

- Mypy 1.20.2 全量 630 个源文件 0-error ratchet、Ruff 与格式检查均已通过。
- 受影响的市场数据、工作空间、组合和前端回归测试在最终验收中重新执行；完整后端 pytest 仍单独记录其实际结果。
- 基线刷新后，`large_file_ratchet.py` 已通过；若清单出现额外路径或当前行数变化，必须重新审查本文件，不能静默覆盖。

## 不在本处声称的结论

- 不声明任何目标模块已经完成职责拆分。
- 不以本地测试证明真实数据库、外部行情、券商或交易通道。
- 不将基线刷新作为放宽未来增长的授权。
