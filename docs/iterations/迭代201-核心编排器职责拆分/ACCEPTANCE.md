# 迭代 201：开发与验收记录

> 状态：**PASS / ACCEPTED_LOCAL**。九个工作包已完成主审验收。当前证据见[统一汇总](../迭代202-项目综合审查与可靠性优化/FINAL_ACCEPTANCE.md)；该结论不表示生产发布或真实交易验收。

起始 HEAD 为 `50b6a54baa6a7d9424bc3b3664c399c297908852`。实现未提交，当前源码由[最终清单与版本映射](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/full-v3-final-source-delta-parent.json)绑定。

## 九个工作包最终结果

| 工作包 | 完成的职责边界 | 主审独立回归 |
| --- | --- | --- |
| WP-01 | 持久化、证据回执、日历网格、查询投影；保留 facade 与失败关闭 | 133 passed |
| WP-02 | 实例解析、仓位归并、资产规格、估值/PnL 与概览计算 | 138 passed |
| WP-03 | 快照、规格、仓位归一化、启动编排；实例方法回调与 live-handoff 保持 | 178 passed |
| WP-04 | 资产适配、目录、动态数据收窄、指标投影 | 36 passed |
| WP-05 | 数值清洗、价格/仓位估值、结果投影 | 173 passed |
| WP-06 | 任务生命周期、研究绑定、快照投影 | 222 passed |
| WP-07 | 市场数据、研究运行/任务生命周期、运行时操作、对话框与视图状态；498 个公开返回键保持 | Node 20/24 各 1,726 passed，typecheck/lint/build/bundle 通过 |
| WP-08 | PersistedProviderFetch 回执及取消/时间校验共享边界 | 67 passed，含共享边界 6 项 |
| WP-09 | cursor rowcount 共享边界；调用方保留事务与异常归一 | 71 passed，含同一共享边界 6 项 |

逐文件结果和收据来源见[工作包映射](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/iteration201-final-workpackages-parent-review.json)。计数存在重叠，不能相加为唯一用例数。完整后端批次原有 25 项失败均已由完整受影响文件复验关闭，原始 FAIL 不改写，见[组合复核](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/backend-final-composite-parent-review.json)。

主审检查了迁出主体、兼容 facade、错误码和写入顺序；修正 workspace 实例回调及前端 continue 运行态两处遗漏，并增加失败/重复提交边界断言。当前 canonical dev lock 下 Mypy 1.20.2 为 **667 文件零错误**，ratchet 0/0；Ruff 0.16.2 check/format、依赖同步/审计、源码尺寸棘轮全部通过。

| 入口 | 最终行数 | 计划上限 |
| --- | ---: | ---: |
| market_data/store.py | 1,703 | 3,900 |
| portfolio/api.py | 1,912 | 2,900 |
| trading_workspace_service.py | 2,034 | 2,650 |
| market_instrument.py | 1,246 | 2,150 |
| position_valuation.py | 1,128 | 2,000 |
| ai_strategy_research_task_manager.py | 504 | 1,800 |
| useStrategyPage.ts | 5,272 | 6,500 |
| cffex_settlement_collector.py | 1,334 | 1,335 |
| stock_valuation_collector.py | 1,113 | 1,115 |
| publication.py | 1,109 | 1,115 |
| holdout_finalize.py | 2,176 | 2,178 |

[独立尺寸与保护文件收据](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/final-source-sizes-and-protected-files-parent.json)确认 49 个新增生产模块全部小于 1,000 行，6 个用户原有根文件哈希保持不变。真实供应商、交易及发布未执行。

## 历史过程记录（保留当时状态）

下面的 FAIL、INCOMPLETE、待完成和中间行数只描述当时快照；最终状态以上述工作包矩阵为准。原始失败不被最终通过覆盖。

## 主审独立检查

1. 对核心后端影响面执行 canonical 依赖下的 494 项回归，使用两个 xdist worker。运行后段出现三次 worker 异常退出，主审中止反复重启；退出码为 130。该批结果为 **INCOMPLETE**，不能写为 494 项通过。
2. 三个退出时的案例分别是 `test_market_instrument_options_fall_back_without_warehouse[stock]`、`test_market_instrument_lookup_rejects_legacy_online_refresh[fx-USDCNH]`、`test_history_gap_merge_reads_provider_from_compatibility_facade`。使用仅显式加载 asyncio/timeout 插件的小范围命令另行诊断，保留默认 30 秒用例门槛，结果 **3 passed in 34.74s，退出码 0**。这个结果不改写原批次的未完成状态。
3. 同期宿主 load average 超过 70，且存在本任务以外的测试进程。这是已观察到的环境事实，尚不足以单独证明上述退出全部由环境造成。
4. 已直接核对隔离 Ruff 二进制版本为 0.16.2。全后端 lint 一轮通过；随后格式检查只剩正在修改的优化工作包文件未收敛，最终仍须在冻结代码上重新检查。

临时原始日志：`/tmp/ai-investor-iter200-202-20261012.afLb99/iter201-core-parent.txt`、`core-crash-diagnostic.txt`、`ruff-backend-0162.txt`、`format-backend-0162.txt`。最终验收须把脱敏结果摘要及哈希留在仓库证据目录，临时文件不能成为唯一长期收据。

### 16:50 当前代码复核

最终代码的 Ruff 0.16.2 lint/format、全仓尺寸棘轮及前端 Node 20 typecheck/lint 已通过。主审重新计数全部入口，并检查本轮 44 个新增生产模块均小于 1,000 行；六个用户原有根目录文件哈希保持一致。证据与逐文件计数保存在[当前主审检查点](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/current-parent-checkpoint.json)。

| 入口 | 当前行数 | 计划上限 |
| --- | ---: | ---: |
| market_data/store.py | 1,703 | 3,900 |
| portfolio/api.py | 2,130 | 2,900 |
| trading_workspace_service.py | 2,041 | 2,650 |
| market_instrument.py | 1,246 | 2,150 |
| position_valuation.py | 1,128 | 2,000 |
| ai_strategy_research_task_manager.py | 504 | 1,800 |
| useStrategyPage.ts | 5,854 | 6,500 |
| cffex_settlement_collector.py | 1,334 | 1,335 |
| stock_valuation_collector.py | 1,113 | 1,115 |
| publication.py | 1,109 | 1,115 |
| holdout_finalize.py | 2,176 | 2,178 |

这些结果关闭尺寸和上述静态检查，不关闭行为回归。17:20 主审完整 Mypy 已确认 666 个源文件零错误、棘轮 0/0，详见[类型检查收据](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/type-and-collection-parent-receipt.json)。完整前端回归在 StrategyPage 文件中报告 18 项失败，之后以 143 退出，未形成全套结果；后端收集错误已定位为临时验收容器缺 `ps`，补装测试工具后仍需复验。组合回归和构建门禁尚未完成。

## 未关闭门槛

最终补齐回归已更新：八文件差异的完整相关文件 **451 passed / 0 skipped / 0 failed**；最终 Node 20.20.2 / 24.19.0 各 **1,726 项通过**，类型、零 warning lint、build、原 bundle gate 均通过。两套产物逐字节一致，会话/工作区 7 项和三浏览器样式 9 项也在最终产物上通过。证据见[后端差异复验](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/backend-final-delta-parent-review.json)、[前端矩阵](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/frontend-final-v15-matrix-parent-review.json)、[浏览器复验](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/frontend-final-v15-browser-parent-review.json)。下面保留前次检查的过程记录；当前剩余门槛为后端完整批次收尾、开发锁新增报告依赖后的同步/审计，以及最终生产镜像复验。

最终补齐复核：WP-02/WP-03/WP-07 的剩余职责已迁出，主审已保存 [portfolio 对照](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/portfolio-completion-parent-review.json)、[workspace 对照](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/workspace-completion-parent-review.json)和[策略页面对照](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/strategy-task-completion-parent-review.json)。复审修正了两项迁移遗漏：workspace 别名读取须保留实例方法回调；研究任务继续提交前须设 `aiResearchRunning=true`。分别增加实例替换及 deferred 重复提交/错误收尾断言，已有通过测试没有替代这次缺口检查。最终主审 canonical Mypy **667 文件零错误**、0/0 ratchet、全后端 Ruff/format、全局尺寸检查通过，见[静态收据](../迭代202-项目综合审查与可靠性优化/evidence/2026-10-12/backend-final-static-v4-parent-receipt.json)。指定受影响完整文件和前端 Node 20/24 矩阵仍待结束。

完成审计更新：此前 v10 前端全量 **1,721 项通过**，v12 构建与原预算通过；v12 dist 与会话/工作区 7 项、三浏览器样式 9 项所测产物一致。上述结果是后续补齐职责前的基线，不代表九个工作包已经完成。

- WP-02：路由文件仍含仓位估值/PnL 与资产概览聚合，正在迁入具名计算协作者；保留原 facade 和 monkeypatch 接缝。
- WP-03：仅响应行方向、open-size 与 long/short 别名转换仍属仓位归一化残留，正在归入现有协作者；响应投影及日汇总无需扩大迁移。
- WP-07：研究任务 submit/poll/restore/cancel/continue/retry 生命周期仍在主 composable，正在迁出。策略 CUD 已在 dialogs 协作者内，不因文件命名或页面发起 fetch 再增加拆分要求；公开 498 键必须保持。

补齐后由主审核对差异，刷新对应完整测试文件、最终类型/格式/尺寸门槛及前端受支持 Node 门禁。后端 full-v3 固定快照继续作为全局问题清单；其原失败与后续修订回归分别保留，通过版本映射说明最终覆盖范围。

20:14 补充：前端 v8 正式构建和原 bundle gate 已通过，主审会话/工作区 preview 7 项通过；全量 Vitest 与后端 v3 完整回归仍运行。Tailwind 三浏览器移动 viewport 的 5 项断言失败另行诊断。后端 runner 的一次失败定位到测试启动竞态，测试修订后须独立完成真实进程组回归，不覆盖原完整运行中的失败记录。

- 九个工作包指定回归及新增失败路径全部通过，并完成主审独立核对。
- 原入口符合实施计划上限，新生产模块小于 1,000 行，全局尺寸棘轮不放宽。
- 最终 canonical-lock Mypy 1.20.2 及 0-error ratchet、Ruff 0.16.2、依赖同步/审计通过。
- Node 20 的类型、全量前端测试、构建及 bundle 门禁；本轮追加 Tailwind 4 样式/浏览器回归另有证据。
- 所有版本变化和残余项明确记录，不用历史通过覆盖当前未完成项。
