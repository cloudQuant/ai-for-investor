# 迭代207：逐项修复 TODO 清单

> 对应方案：[README.md](README.md) | 详细证据：[AUDIT.md](AUDIT.md)
> 进度统计：**24 / 24 已完成**（P0: 4/4 | P1: 16/16 | P2: 3/3 | P3: 1/1）
> 执行约定：按 `P0 → P1 → P2 → P3` 推进；每项先补可在当前代码上失败的反例，再修复；PR 目标分支为 `dev`。
> 完成定义：代码、回归测试、命令退出码、源码 `文件:行`、回滚说明齐全；E3 项必须另附受控环境证据。

---

## P0 — 生产发布阻断（4 项）

### [x] REV207-01 — 停用/删除用户 JWT 立即失效

- **依赖**：无；REV207-02 复用本次认证语义。
- **文件所有权**：`src/backend/app/api/_dependencies.py`、`src/backend/app/api/data/deps.py`、认证相关测试；前端会话清理只改 `src/frontend/src/api/index.ts` 对应测试。
- **先红**：新增 `tests/test_iteration207_auth_authorization.py`，active/inactive/deleted 三臂；HTTP 与 WebSocket 各一组。当前 inactive/deleted 臂应失败。
- **修复**：每次请求加载账户状态或校验服务端 token version/revocation；统一会话失效错误。
- **验收**：
  ```bash
  cd src/backend
  pytest tests/test_iteration207_auth_authorization.py -q
  ```
  active 对照返回成功；inactive/deleted 返回 `401`；前端收到会话失效后清空 token。
- **回滚**：单独回退依赖接线；保留新增测试和角色/权限定义，不恢复“只信 JWT”的旧实现。

### [x] REV207-02 — 策略与回测 RBAC 接线

- **依赖**：REV207-01。
- **文件所有权**：`src/backend/app/api/strategy/base.py`、`src/backend/app/api/backtest_enhanced.py`、`src/backend/app/api/_dependencies.py`、RBAC 测试。
- **先红**：GUEST/USER/PREMIUM/ADMIN × 创建/更新/删除策略、运行/删除/导出回测矩阵；无权限臂当前会错误成功。
- **修复**：使用已有 `RequireCreateStrategy`、`RequireUpdateStrategy`、`RequireDeleteStrategy`、`RequireRunBacktest`、`RequireExportBacktest`；保留 owner 检查。
- **验收**：
  ```bash
  pytest tests/test_iteration206_security_rbac.py tests/test_iteration207_auth_authorization.py -q
  ```
  无权限 `403`，有权通过，跨 owner 独立拒绝。
- **回滚**：回退路由依赖替换；不删除底层权限定义和测试。

### [x] REV207-03 — sealed holdout 与 discovery 强制隔离

- **依赖**：无；REV207-04、08 在隔离契约稳定后实施。
- **文件所有权**：`src/backend/app/services/research/holdout_request.py`、`dataset_registry.py`、`holdout_claim.py`、相关 model/migration 与测试。
- **先红**：新增 `tests/test_iteration207_holdout_integrity.py`，覆盖时间重叠、标的重叠、对象相同、freeze 晚于 sealed 起点四类负例和完全隔离正例。
- **修复**：封存不可变 manifest（universe、日期范围、内容摘要、freeze、label horizon）；claim/finalize fail-closed；旧快照缺元数据时重新封存。
- **验收**：
  ```bash
  pytest tests/test_iteration207_holdout_integrity.py tests/test_ai_research_holdout_worker.py -q
  ```
  四类负例拒绝，正例通过，既有 worker 行为不回归。
- **回滚**：保留 manifest 读取兼容；回退新增强制校验前必须确认没有未重新封存的候选进入 promotion。

### [x] REV207-04 — 外部 receipt 样本充分性门禁

- **依赖**：REV207-03（同一研究契约）；可与 REV207-08 并行设计状态。
- **文件所有权**：`holdout_execution_contract.py`、`holdout_finalize.py`、`promotion.py`、策略版本配置与测试。
- **先红**：达标聚合指标 + 极小样本必须拒绝；同指标 + 满足策略族最低充分性必须通过；字段缺失拒绝。
- **修复**：新增版本化最低独立样本、有效收益数、trial/fold、时间跨度、label maturity 策略；receipt 绑定策略版本和证据摘要。
- **验收**：
  ```bash
  pytest tests/test_iteration207_holdout_integrity.py tests/test_ai_research_holdout_worker.py -q
  ```
  小样本、零收益、跨度不足、字段缺失、合法充分性五类结果精确。
- **回滚**：只回退新策略版本的启用，不删除审计字段；不得回退到“无样本证明也可通过”。

---

## P1 — 高优先级（16 项）

### A. 安全、RBAC 与隔离（3 项）

#### [x] REV207-05 — AI 研究配置档案 owner/管理员隔离

- **依赖**：无。
- **文件所有权**：`src/backend/app/api/strategy/base.py`、`ai_strategy_research_config_profiles.py`、配置 model/migration 与测试。
- **先红**：用户 B 修改/导入/删除用户 A 或全局 profile 当前成功；修复后 `403` 或只能操作自己的 profile。
- **修复**：个人 profile 绑定 `owner_id`；全局写操作仅 ADMIN；读与写权限分离。
- **验收**：A/B 隔离 + ADMIN 正例；`pytest tests/test_iteration207_auth_authorization.py -q`。
- **回滚**：保留 owner 字段读取兼容；回退路由写权限前不得重新开放全局覆盖。

#### [x] REV207-06 — data topic 强制刷新使用写 ACL

- **依赖**：无。
- **文件所有权**：`src/backend/app/api/data/topics.py`、`data_topic_hub.py` 对应权限测试。
- **先红**：只读 USER 对公共 topic `force=True` 当前成功；修复后 HTTP/WS 均 `403`。
- **修复**：强制刷新统一 `write=True`；若产品允许用户触发，则必须有限流配额和 actor 审计。
- **验收**：匿名、只读、写用户 HTTP/WS 六臂；`pytest tests/test_iteration206_security_rbac.py -q`。
- **回滚**：回退权限接线；不恢复无配额的公共强制刷新。

#### [x] REV207-07 — 模拟分析读取实例隔离日志

- **依赖**：无；不要重复改动迭代 206 已完成的写隔离路径。
- **文件所有权**：`src/backend/app/api/simulation_analytics.py`、`simulation.py` 的 runtime helper、`tests/test_iteration206_security_rbac.py`。
- **先红**：A/B 用户复用同一 strategy template、runtime 日志不同；detail/monthly-returns 当前读取共享目录。
- **修复**：所有分析接口统一通过实例 runtime 解析日志；共享模板仅用于创建。
- **验收**：扩展现有测试，A/B 日志互不串；K-line 现有隔离路径不回归。
- **回滚**：回退到 helper 读取，但保留 runtime 目录创建和写隔离。

### B. 研究终态与行情持久化（4 项）

#### [x] REV207-08 — finalize 终态与 evidence package 解耦

- **依赖**：REV207-03、04。
- **文件所有权**：`src/backend/app/services/research/holdout_worker.py`、`holdout_finalize.py`、`tests/test_ai_research_holdout_worker.py`。
- **先红**：注入 package builder 失败；当前 worker 返回 `FAILED`，与数据库终态不一致。
- **修复**：增加 `PACKAGE_PENDING`/`PACKAGE_FAILED` 子状态；恢复后只打包，不重跑研究。
- **验收**：
  ```bash
  pytest tests/test_ai_research_holdout_worker.py -q
  ```
  终态保持不变，错误码精确，二次执行不重复 finalize。
- **回滚**：保留新状态映射兼容；不得恢复通用 `FAILED` 覆盖已提交终态。

#### [x] REV207-09 — 在线持久化取消安全与 fenced receipt 恢复

- **依赖**：无；REV207-10 复用同一幂等/恢复测试夹具。
- **文件所有权**：`query_service.py`、`store_persistence.py`、`publication.py`、`tests/test_iteration207_market_persistence.py`。
- **先红**：store 提交后、publication 提交前逐 `await` 点取消；当前恢复后仍不可见。
- **修复**：受管任务 + `asyncio.shield` + 强引用；recovery 支持 fenced pending publication 或提供可重放入口。
- **验收**：逐点取消后数据可见；正常路径不变；受控 DB E3 复验。
- **回滚**：保留恢复入口和测试；不删除不可变 receipt 历史。

#### [x] REV207-10 — 批处理重试幂等与重叠 lease 互斥

- **依赖**：REV207-09 的测试夹具。
- **文件所有权**：`stock_valuation_collector.py`、`cffex_settlement_collector.py`、`store_persistence.py`、`fetch_lease.py` 与测试。
- **先红**：第 K 个目标失败后重试全部；当前已成功前缀 revision 数增加。
- **修复**：稳定业务键 + receipt + fields digest 幂等；相同内容返回既有 revision，变更才追加；重叠目标集合并发受控。
- **验收**：全量重试、部分重试、重叠集合、内容变更四类；revision 计数精确。
- **回滚**：保留去重读取逻辑；不删除历史重复 revision，需另行审计标注。

#### [x] REV207-11 — CFFEX lease 释放错误传播

- **依赖**：无。
- **文件所有权**：`src/backend/app/services/market_data/cffex_settlement_collector.py`、`fetch_lease.py` 与测试。
- **先红**：同时注入部分发布失败和 release 失败；当前只保留主错误。
- **修复**：结果/异常链同时记录 primary 与 cleanup failure。
- **验收**：单主错误、单 release 错误、双错误三臂；双错误必须包含 `CFFEX_SETTLEMENT_FETCH_LEASE_RELEASE_FAILED`。
- **回滚**：可回退展示层，但不得再次丢弃 cleanup error。

### C. 纸交易（1 项，E3 必做）

#### [x] REV207-12 — SQLite 多进程账户串行化

- **依赖**：无。
- **文件所有权**：`src/backend/app/services/paper_trading_execution.py`、`tests/test_iteration207_paper_sqlite_multiprocess.py`。
- **先红**：两个独立进程/事件循环对同账户下不同订单，初始资金仅允许一笔；当前可同时通过检查。
- **修复**：SQLite 在读取账户快照前获取事务级写串行化（`BEGIN IMMEDIATE` 或等价机制）；事件循环锁仅作优化。
- **验收**：
  ```bash
  pytest tests/test_iteration207_paper_sqlite_multiprocess.py -q
  ```
  只能一笔成交，现金/持仓精确；MySQL/PG `FOR UPDATE` 回归通过。
- **回滚**：保留 managed-paper 路径；回退锁策略前必须确认 SQLite 多进程反例仍为红，不得标记完成。

### D. 前端认证与竞态（6 项）

#### [x] REV207-13 — 消息抑制不再绕过 401 刷新

- **依赖**：无。
- **文件所有权**：`src/frontend/src/api/index.ts`、`src/frontend/src/api/marketData.ts`、`src/frontend/src/__tests__/api/`。
- **先红**：`suppressErrorMessage=true` + 401 当前不刷新、不登出。
- **修复**：先完成认证/重试/会话处理，再决定是否展示 toast。
- **验收**：Vitest 覆盖 401→刷新→重放、刷新失败→登出、并发单飞；`npm run typecheck && npm run lint`。
- **回滚**：只回退 toast 展示逻辑，不恢复认证提前返回。

#### [x] REV207-14 — 回测提交/轮询 generation 栅栏

- **依赖**：无。
- **文件所有权**：`BacktestPage.vue`、`useBacktestRuntime.ts`、对应 Vitest。
- **先红**：卸载后解析提交、A/B 提交乱序、迟到状态/结果。
- **修复**：提交 generation + task identity + unmounted 守卫；轮询携带 AbortSignal。
- **验收**：四类乱序均不回写、不创建 socket/timer。
- **回滚**：保留 unmount 基础清理；不恢复离页后启动 runtime。

#### [x] REV207-15 — 过拟合任务单飞与身份复核

- **依赖**：无。
- **文件所有权**：`BacktestResultPage.vue`、`useOverfittingRuntime.ts`、对应 Vitest。
- **先红**：双击重复提交；A 完成响应停止 B runtime。
- **修复**：in-flight lock + generation + taskId 快照。
- **验收**：双击、A/B 乱序、卸载三臂。
- **回滚**：保留 runtime dispose；不恢复无身份复核的 stop。

#### [x] REV207-16 — 行情图表最新请求生效

- **依赖**：无。
- **文件所有权**：`src/frontend/src/stores/quote.ts`、`QuotePage.vue`、对应 Vitest。
- **先红**：日线→周线、A symbol→B symbol、source 切换、关闭抽屉后旧响应回写。
- **修复**：请求序号 + `(source,symbol,timeframe)` 快照 + AbortController。
- **验收**：仅最新请求可写 bars/loading/error。
- **回滚**：保留 closeChart 清理；不恢复共享 loading 被旧请求结束。

#### [x] REV207-17 — 新闻正文绑定 article identity

- **依赖**：无。
- **文件所有权**：`NewsIntelligencePage.vue`、对应 Vitest。
- **先红**：打开 A 后打开 B，先解析 A；当前标题 B、正文 A。
- **修复**：articleId/generation 校验，关闭弹窗递增 generation。
- **验收**：A/B 乱序、关闭后响应均不回写。
- **回滚**：保留安全外链逻辑；不恢复共享正文无身份写入。

#### [x] REV207-18 — 股票分析轮询 single-flight 与状态单调

- **依赖**：无；REV207-19 复用其 generation 约定。
- **文件所有权**：`useStockAnalysisTask.ts`、`StockAnalysisTaskCard.vue`、对应 Vitest。
- **先红**：慢请求超过 interval、旧 running 覆盖 completed、网络拒绝未处理。
- **修复**：single-flight + 序号/状态单调 + 终态停轮询 + 错误捕获。
- **验收**：无重叠请求、无状态回退、无 unhandled rejection。
- **回滚**：保留 stopPolling；不恢复无界重叠轮询。

### E. CI 门禁（2 项）

#### [x] REV207-22 — 恢复大文件棘轮并垂直切片

- **依赖**：先做最小切片恢复 CI；REV207-03、04、08～11、20 的业务修复随后在新模块落地，避免二次搬迁。
- **文件所有权**：AUDIT 列出的 9 个后端文件、`scripts/ci/large_file_baseline.json`（只读核对，不上调）、对应 characterization tests。
- **先红**：当前 `large_file_ratchet.py` 已退出码 1，9 个文件超基线。
- **修复**：抽取纯 helper/DTO/查询编排/状态机；每批保持行为不变。
- **验收**：
  ```bash
  python3 scripts/ci/large_file_ratchet.py
  python3 scripts/ci/check_complexity_budget.py
  ```
  均退出码 0；受影响模块测试通过；baseline 未上调。
- **回滚**：按切片独立回滚；不得通过提高 baseline 制造“绿灯”。

#### [x] REV207-23 — 锁定 mypy 工具链并恢复门禁

- **依赖**：无。
- **文件所有权**：`src/backend/pyproject.toml`、`config/requirements-dev.lock`、`scripts/ci/mypy_ratchet.py`、开发环境文档/脚本。
- **先红**：当前本机 `mypy 2.3.1`，baseline `1.20.2`，门禁退出码 1。
- **修复**：建立锁定 Python + `mypy==1.20.2` 验证环境；版本漂移继续 fail-closed；工具升级必须独立 PR。
- **验收**：
  ```bash
  python3 -m mypy --version
  python3 scripts/ci/mypy_ratchet.py
  ```
  版本精确为 `1.20.2`，门禁退出码 0；记录平台与解释器。
- **回滚**：回退环境脚本，不用新版本基线覆盖旧基线。

---

## P2 — 中优先级（3 项）

### [x] REV207-19 — 股票分析页统一请求 generation

- **依赖**：REV207-18。
- **文件所有权**：`src/frontend/src/views/investment/StockAnalysisPage.vue`、对应 Vitest。
- **先红**：A 的报告/历史/证据未完成时切换 B，旧响应覆盖 B。
- **修复**：页面级 generation + task/symbol/unmounted 上下文快照。
- **验收**：三类请求、切换 symbol、路由卸载均不回写。
- **回滚**：保留单任务轮询修复；不恢复跨任务共享响应写入。

### [x] REV207-20 — 后台任务统一所有权、关停与恢复

- **依赖**：与 REV207-22 协调同文件拆分。
- **文件所有权**：`src/backend/app/utils/async_tasks.py`、`api/stock_analysis.py`、`services/overfitting/service.py`、startup/shutdown hooks 与测试。
- **先红**：shutdown 后 tracked task 未取消；durable in-flight 重启后无明确恢复/中断状态。
- **修复**：所有 fire-and-forget 使用 `spawn_tracked_task`；统一 shutdown；启动 reconcile durable 任务。
- **验收**：注册、取消、异常回收、重启恢复四类测试；不声称尚无运行证据的任务丢失已发生。
- **回滚**：保留任务注册表；不恢复裸 `asyncio.create_task`。

### [x] REV207-21 — gitleaks 扫描口径与 allowlist 校准

- **依赖**：无。
- **文件所有权**：`.gitleaks.toml`、CI secret-scan 步骤、`scripts/ci/tests/` 新增策略测试。
- **先红**：临时 tracked 受控假 token 必须命中；现有 allowlist 不得屏蔽新的真实形态。
- **修复**：统一本地/CI tracked 范围与命令；allowlist 精确到规则/路径/值语义；报告脱敏。
- **验收**：planted positive 命中、negative 不误报、CI 命令与文档一致；67 个旧候选重新分类但不宣称全是泄漏。
- **回滚**：保留 planted control 测试；不得通过全局忽略真实密钥规则制造绿灯。

---

## P3 — 文档治理（1 项）

### [x] REV207-24 — 修正迭代索引与状态

- **依赖**：所有业务项完成后做最终状态更新；可在计划阶段先补入口。
- **文件所有权**：`docs/iterations/README.md`、迭代 206/207 的 README/TODO。
- **先红**：索引把迭代 206 标为 PLANNED，与其 44/44 COMPLETED 不一致。
- **修复**：迭代 206 改为 COMPLETED；新增迭代 207 PLANNED 入口；最终统计为 24 项。
- **验收**：
  ```bash
  python3 scripts/ci/check_doc_links.py
  ```
  退出码 0；索引、README、TODO 状态一致。
- **回滚**：文档独立提交，可直接回滚，不影响业务代码。

---

## 实施与验收证据索引

| 事项 | 主要实现位置 | 回归与证据 |
|---|---|---|
| REV207-01 | `src/backend/app/api/_dependencies.py:43,60`；`src/frontend/src/api/index.ts:385` | [WP01](evidence/WP01/) + [WP05](evidence/WP05/) |
| REV207-02 | `src/backend/app/api/strategy/base.py`；`src/backend/app/api/backtest_enhanced.py` | [WP01](evidence/WP01/) |
| REV207-03 | `src/backend/app/services/research/holdout_isolation.py:57`；`holdout_request.py` / `holdout_claim.py` | [WP02](evidence/WP02/) |
| REV207-04 | `src/backend/app/services/research/holdout_sufficiency.py:54`；`holdout_execution_contract.py:422`；`promotion.py:505` | [WP02](evidence/WP02/) |
| REV207-05 | `src/backend/app/api/strategy/ai_research_config_profiles.py:48,84` | [WP01](evidence/WP01/) |
| REV207-06 | `src/backend/app/api/data/topics.py:63` | [WP01](evidence/WP01/) |
| REV207-07 | `src/backend/app/api/simulation_analytics.py:58,161,246` | [WP01](evidence/WP01/) |
| REV207-08 | `src/backend/app/services/research/holdout_worker.py:388,437` | [WP02](evidence/WP02/) |
| REV207-09 | `src/backend/app/services/market_data/query_persistence.py:35`；`publication_recovery.py:16` | [WP03](evidence/WP03/) |
| REV207-10 | `src/backend/app/services/market_data/store_persistence.py:607`；`cffex_settlement_collector.py:607` | [WP03](evidence/WP03/) |
| REV207-11 | `src/backend/app/services/market_data/cffex_settlement_collector.py:579` | [WP03](evidence/WP03/) |
| REV207-12 | `src/backend/app/services/paper_trading_execution.py:182` | [WP04](evidence/WP04/)：双进程 SQLite E3 |
| REV207-13 | `src/frontend/src/api/index.ts:385` | [WP05](evidence/WP05/) |
| REV207-14 | `src/frontend/src/composables/useBacktestRuntime.ts:37,224` | [WP05](evidence/WP05/) |
| REV207-15 | `src/frontend/src/composables/useOverfittingRuntime.ts:41,226`；`useOverfittingSubmission.ts:21` | [WP05](evidence/WP05/) |
| REV207-16 | `src/frontend/src/stores/quote.ts:564` | [WP05](evidence/WP05/) |
| REV207-17 | `src/frontend/src/composables/useNewsArticleContent.ts:19` | [WP05](evidence/WP05/) |
| REV207-18 | `src/frontend/src/composables/useStockAnalysisTask.ts:33` | [WP05](evidence/WP05/) |
| REV207-19 | `src/frontend/src/views/investment/StockAnalysisPage.vue:515,739,782` | [WP05](evidence/WP05/) |
| REV207-20 | `src/backend/app/startup/reconcile.py:23-25,56`；`app/utils/async_tasks.py` | [WP03](evidence/WP03/) |
| REV207-21 | `scripts/ci/scan_tracked_secrets.py:40`；`.gitleaks-tracked.toml`；CI PR scan | [WP06](evidence/WP06/) |
| REV207-22 | 各垂直切片模块与 `scripts/ci/large_file_baseline.json`（未上调） | [WP06](evidence/WP06/)：336 项行为回归 |
| REV207-23 | `src/backend/pyproject.toml` / `config/requirements-dev.lock` 固定 `mypy==1.20.2` | [WP06](evidence/WP06/)：Python 3.11.8 隔离环境 |
| REV207-24 | `docs/iterations/README.md`；本 README/TODO | [WP07](evidence/WP07/) |

E3 边界：SQLite 多进程纸交易、受控 SQLite 取消/恢复、外部 evaluator fixture 与浏览器 smoke 已实际执行；MySQL/PostgreSQL 保留 `FOR UPDATE` 编译与现有契约回归，但未冒充已连接的真实 MySQL/PostgreSQL 环境。

---

## 全局验收清单

- [x] 24 项全部完成；P0/P1 无未关闭项，E3 项有受控环境证据。
- [x] `large_file_ratchet.py`、`check_complexity_budget.py`、`mypy_ratchet.py` 退出码 0。
- [x] Alembic、依赖同步、敏感文件、文档链接、ORM drift、A11y、生产锁门禁退出码 0。
- [x] 后端新增回归与现有定向 283 项基线不回归；新增 40 项、受影响文件 69 项通过；全量后端结果单独记录失败集合变化，最终 18 个失败节点与基线集合完全一致。
- [x] 前端 `npm run typecheck`、`npm run lint`、`npm run test -- --run` 通过，测试数不低于当前 2,209。
- [x] 每个 P0/P1 有“修复前失败、修复后通过”的同名反例；不允许只断言实现存在。
- [x] 回滚方案逐项完成方案级审查：本轮无 schema migration、无历史数据删除，API 变更保持可选字段/依赖接线；实际部署回滚演练仍属发布前 E3，不在本地验收中冒充已执行。本地 evidence 不纳入提交，新增非证据文件严格扫描为 0 候选。
