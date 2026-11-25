# 迭代207：OpenCodeReview 全仓复审详细报告（AUDIT）

> 基线：`dev` @ `4bdfab992fc4d0a0e169d2bba30d88bbe57509a8`
> 方法：OpenCodeReview `1.14.2` 本地 preview/rule + 当前会话模型源码审阅、调用链复核与定向测试。
> 口径：**E1 = 本机实测**；**E2 = 静态确认**；**E3 = 需受控环境动态复验**。
> 去重：不重复迭代 206 的 44 项已闭环修复；仅记录回归、兄弟路径和未覆盖契约。

---

## 一、P0 — 生产发布阻断（4 项）

### REV207-01 [P0 / 认证生命周期 / E2] 停用或删除用户在 access token 过期前仍可通过普通 API 与 WebSocket

- **位置**：
  - `src/backend/app/api/_dependencies.py:44-77`（`get_current_user`）
  - `src/backend/app/api/_dependencies.py:32-41`（WebSocket token 校验）
  - 对照：`src/backend/app/api/data/deps.py:24-61` 会加载数据库用户并检查停用状态。
- **当前行为**：普通依赖只解码 JWT、构造 `TokenPayload` 并写 `request.state.user_id`，不查询 `User`，也不检查 `is_active` 或账户是否已删除。
- **违反的不变量**：访问权限必须在每次请求时同时满足“token 有效”和“账户当前可用”；停用/删除应立即切断未过期访问令牌。
- **影响**：离职、封禁或误删账户在 token 自然过期前仍可调用普通业务 API 和 WebSocket，形成认证撤销缺口。
- **最小反例**：创建 active 用户并取得 token → 将用户置为 inactive 或删除 → 同一 token 调用任一普通受保护端点。当前返回业务成功；预期 `401`。active 对照臂必须仍返回成功。WebSocket 增加同一反例。
- **修复方向**：普通与 WebSocket 依赖统一读取账户状态，或引入服务端 token version/revocation 并在每次请求校验；失败统一返回会话失效语义，不缓存已撤销账户。
- **验收**：新增 `tests/test_iteration207_auth_authorization.py`，覆盖 active/inactive/deleted、HTTP/WebSocket；前端在 `401` 后清理会话。

---

### REV207-02 [P0 / RBAC / E2] 策略 CRUD、回测运行/删除/导出定义了权限依赖却未接线

- **位置**：
  - 权限定义：`src/backend/app/api/_dependencies.py:173-201` 附近，`RequireCreateStrategy`、`RequireUpdateStrategy`、`RequireDeleteStrategy`、`RequireRunBacktest`、`RequireExportBacktest`。
  - 策略：`src/backend/app/api/strategy/base.py:462-479, 1459-1477, 1505-1524`。
  - 回测：`src/backend/app/api/backtest_enhanced.py:169-197, 340-353, 413-445, 448-474, 482-507`。
- **当前行为**：路由只使用 `get_current_user`；对象归属检查保留，但角色能力未执行。GUEST 可创建/改/删自己的策略，USER 可运行/删除回测并导出 HTML/PDF/Excel。
- **违反的不变量**：认证解决“你是谁”，对象归属解决“是不是你的”，RBAC 还必须解决“你被允许做这类操作吗”。
- **影响**：已设计的角色权限形同虚设，付费/管理员专属能力被普通角色绕过。
- **最小反例**：参数化 GUEST/USER/PREMIUM/ADMIN 对创建、更新、删除策略、运行/删除/导出回测；无权限角色必须 `403`，有权角色通过。保留“对象属于其他用户”的独立拒绝臂。
- **修复方向**：在对应路由替换为已存在的 `Require*` 依赖；保持现有 owner 检查，不用角色校验替代对象归属；权限错误统一 `403`。
- **验收**：新增角色矩阵测试；`tests/test_iteration206_security_rbac.py` 与新增测试同时通过。

---

### REV207-03 [P0 / 研究数据泄漏 / E2] sealed holdout 快照未与 discovery 样本、标的集合和 freeze 时点隔离

- **位置**：
  - `src/backend/app/services/research/holdout_request.py:572-619, 764-799`（`_select_owner_sealed_snapshot`）
  - `src/backend/app/services/research/dataset_registry.py:562-599`（`_validate_snapshot_request`）
  - `src/backend/app/services/research/holdout_claim.py:874-958`。
- **当前行为**：快照选择只检查 owner、`partition_kind="SEALED_HOLDOUT"`、policy version 和 `integrity_status="VERIFIED"`；不比较 discovery/sealed 日期窗口、标的口径、底层对象身份或 `candidate.frozen_at`。只有 `FORWARD_OBSERVATION` 部分路径强制 cutoff 晚于 freeze。
- **违反的不变量**：sealed holdout 必须与 discovery/iteration validation 在样本、标的和时间上不相交，并且必须晚于候选冻结及所需 label horizon 成熟点。
- **影响**：模型已见过的样本可进入最终评估，导致数据泄漏和偏乐观 promotion；这是研究可信度的发布阻断问题。
- **最小反例**：构造时间重叠、标的重叠、底层对象相同、freeze 晚于 sealed 起点四类快照；每类当前应被错误接受，修复后必须拒绝。构造完全隔离的快照作为通过对照。
- **修复方向**：封存不可变 manifest，记录 universe、日期范围、内容摘要、freeze 时间和 label horizon；claim/finalize 强制验证无交集及时间顺序。缺少元数据的历史快照要求重新封存，不默认通过。
- **验收**：新增 `tests/test_iteration207_holdout_integrity.py`，四类负例 + 一类正例；现有 `tests/test_ai_research_holdout_worker.py` 不回归。

---

### REV207-04 [P0 / 研究充分性 / E2] 外部 evaluator receipt 只有聚合指标，没有最小样本/收益/时间跨度证明

- **位置**：
  - `src/backend/app/services/research/holdout_execution_contract.py:109-137, 453-473`（`_SAFE_METRIC_KEYS`）
  - `src/backend/app/services/research/holdout_finalize.py:931-954`
  - `src/backend/app/services/research/promotion.py:442-552, 931-976`（`_recomputed_safe_receipt_outcomes`）。
- **当前行为**：安全指标白名单只有 11 个聚合值，明确排除 `samples`、`returns`、`rows`、`measurements` 等键；重算结果直接将 `CANDIDATE_FROZEN`、`SEALED_HOLDOUT`、`EVIDENCE_BINDING` 设为 `True`，只检查聚合阈值。
- **违反的不变量**：有限且好看的聚合指标不能替代样本充分性；通过 promotion 必须证明有足够的独立观测、非零收益、trial/fold 和时间跨度。
- **影响**：外部 evaluator 可用 1～2 个样本给出“满足阈值”的 receipt，绕过持有期研究证据要求。
- **最小反例**：同一组达标聚合指标分别配“极少样本”和“满足策略族最低充分性”的证据；前者必须拒绝，后者必须通过。样本字段缺失也必须 fail-closed。
- **修复方向**：新增版本化充分性策略，按策略族/horizon 定义最低独立样本、有效收益数、trial/fold、时间跨度和 label maturity；receipt 必须绑定策略版本和证据摘要。禁止只放宽阈值。
- **验收**：新增小样本、零收益、时间跨度不足、字段缺失、合法充分性五类测试；promotion 和 finalize 使用同一策略版本。

---

## 二、P1 — 高优先级业务（14 项；另 2 项门禁见第四节）

### A. 安全、RBAC 与隔离（REV207-05～07）

#### REV207-05 [P1 / 全局配置越权 / E2] 任意登录用户可修改、导入或删除仓库级 AI 研究配置档案

- **位置**：
  - `src/backend/app/api/strategy/base.py:711-845`
  - `src/backend/app/services/ai_strategy_research_config_profiles.py:22-143`。
- **当前行为**：路由主动 `del current_user`，服务读写仓库级 `config/ai_research_profiles.yaml`；没有 owner 或管理员限制。
- **影响**：任一登录用户可覆盖/删除所有用户共享的研究表单配置，造成配置破坏和越权。
- **最小反例**：用户 A 创建共享 profile，用户 B 更新/导入/删除；预期 `403` 或仅能操作自己的 profile。
- **修复方向**：优先将个人 profile 绑定 `owner_id`；确需全局共享的写操作收口至管理员。读取与写入权限分离。
- **验收**：A/B 用户隔离测试 + ADMIN 全局管理正例。

#### REV207-06 [P1 / 配额与写权限 / E2] 公共 data topic 强制刷新只校验读 ACL

- **位置**：
  - `src/backend/app/api/data/topics.py:72-78`（HTTP）
  - `src/backend/app/api/data/topics.py:148-150`（WebSocket）
  - `src/backend/app/services/data_topic_hub.py:127-147`。
- **当前行为**：`refresh` 使用 `_require_topic_access(..., write=False)`，随后 `hub.request(..., force=True)` 触发生产者；同类 WebSocket 分支同样如此。`push` 已正确要求写权限。
- **影响**：只有公共 topic 读权限的用户可反复触发上游抓取，消耗配额、放大负载，形成读操作触发写副作用。
- **最小反例**：USER 读取公共 topic 成功；同一 USER 普通 refresh 非强制路径可按设计成功，`force=True` 必须 `403`；有写权限角色通过。
- **修复方向**：HTTP 与 WebSocket 的强制刷新统一使用写 ACL；若产品希望允许用户触发，则改为显式限流配额并记录 actor。
- **验收**：HTTP/WS 双向权限测试，覆盖匿名、只读用户、写用户。

#### REV207-07 [P1 / 模拟实例数据隔离 / E2] 详情和月收益分析仍读取共享策略模板日志

- **位置**：
  - `src/backend/app/api/simulation_analytics.py:37-56, 222-241`
  - 对照：`src/backend/app/api/simulation.py:61-77, 384-393` 已使用实例隔离 runtime/log。
- **当前行为**：接口先按 `user_id` 校验实例归属，随后调用 `get_strategy_dir(inst["strategy_id"])` 和 `parse_all_logs(strategy_dir)`，仍指向共享模板目录。
- **影响**：两个实例复用同一策略模板时，详情/月收益可能展示其他实例或其他用户的日志，属于迭代 206 写隔离修复的遗漏读取路径。
- **最小反例**：A/B 两用户、同一 strategy template、不同 runtime 日志；请求各自 detail/monthly-returns 必须只返回本实例日志。
- **修复方向**：统一通过实例 runtime 解析日志目录，所有分析接口复用同一 helper；共享模板只用于创建，不用于运行态读取。
- **验收**：扩展 `tests/test_iteration206_security_rbac.py`，覆盖 detail 与 monthly-returns，不仅覆盖配置/日志写隔离。

### B. 研究终态一致性（REV207-08）

#### REV207-08 [P1 / 状态机 / E2] finalize 已提交终态后打包失败，worker 对外却返回 `FAILED`

- **位置**：
  - `src/backend/app/services/research/holdout_worker.py:84-110, 336-412`
  - `src/backend/app/services/research/holdout_finalize.py:2075-2105`
  - 现有反向固化测试：`src/backend/tests/test_ai_research_holdout_worker.py:551-583`。
- **当前行为**：数据库已写入 `SUCCEEDED/PASSED` 或 `REJECTED` 后，evidence package 构建异常被 `run_once` 捕获为 `HOLDOUT_WORKER_FAILED`，worker 结果与数据库终态不一致。
- **影响**：调用方可能误判研究失败并重试/告警，破坏幂等和审计；现有测试还把这一行为固化为预期。
- **最小反例**：注入 package builder 失败；断言数据库终态保持不变，worker 返回“终态 + package pending/error”，而不是通用 `FAILED`；恢复打包后不重新执行研究。
- **修复方向**：将研究终态与证据打包拆为两个可恢复阶段；明确 `PACKAGE_PENDING`/`PACKAGE_FAILED` 子状态和错误码。
- **验收**：重写上述现有测试，增加“打包失败→恢复→只打包不重跑”的正反例。

### C. 行情持久化与重试（REV207-09～11）

#### REV207-09 [P1 / 取消恢复 / E2，需 E3 强化] 在线持久化取消可遗留永久不可见的 fenced receipt

- **位置**：
  - `src/backend/app/services/market_data/query_service.py:1014-1022`
  - `src/backend/app/services/market_data/store_persistence.py:203-269`
  - `src/backend/app/services/market_data/publication.py:419-475`。
- **当前行为**：store 事务提交 snapshot/revision/pending publication 后，另一事务负责发布可见性；query service 缺少 collector 使用的独立任务 + `asyncio.shield`。取消可中断第二事务，留下 `published_at=NULL`；`recover_pending` 排除 fenced source receipt，释放 lease 后通用恢复也不会发布。
- **影响**：上游已成功抓取并持久化的数据永久不可见，形成静默数据缺口。
- **最小反例**：在 store 提交后、publication 提交前每个 `await` 点注入取消；随后运行恢复。当前会留下不可见 receipt，修复后必须能恢复或返回明确未持久化状态。
- **修复方向**：将 store+publication 作为取消安全的受管任务，使用 `asyncio.shield` 并保存强引用；同时让 recovery 能识别并修复 fenced pending publication，或提供可重放入口。
- **验收**：新增 `tests/test_iteration207_market_persistence.py`，逐 await 点取消 + 恢复正例；受控 DB 环境重复验证。

#### REV207-10 [P1 / 幂等与 PIT 历史 / E2] 批处理部分成功后重试会制造重复 revision

- **位置**：
  - `src/backend/app/services/market_data/stock_valuation_collector.py:294-345`
  - `src/backend/app/services/market_data/cffex_settlement_collector.py:454-511, 595-650`
  - `src/backend/app/services/market_data/store_persistence.py:586-649`。
- **当前行为**：每个目标逐次 append-only 写入，`_next_revision_numbers` 对已存在 coordinate 直接 `max+1`；部分发布后重试全部目标，会为已成功前缀生成相同 `fields_sha256` 的新 revision。CFFEX lease key 包含完整目标集合，不同但重叠的集合不能互斥。
- **影响**：普通读取只显示最新 revision，问题隐蔽；PIT 修订历史被污染，审计和回放重复。
- **最小反例**：N 个目标发布到第 K 个失败 → 重试全部目标；已成功 K-1 个目标的 revision 数必须不增加，未完成目标恰好增加一次。重叠目标集合并发也需验证。
- **修复方向**：以稳定业务键 + receipt + fields digest 做幂等判断；相同内容返回既有 revision，不同内容才追加。重叠目标集合的 lease 必须可互斥或使用数据库幂等约束。
- **验收**：全量重试、部分重试、重叠集合、内容变更四类测试；历史 revision 计数精确。

#### REV207-11 [P1 / 错误传播 / E2] CFFEX 部分发布后的 lease 释放失败被主异常掩盖

- **位置**：
  - `src/backend/app/services/market_data/cffex_settlement_collector.py:508-569`
  - `src/backend/app/services/market_data/fetch_lease.py:388-417`。
- **当前行为**：已有主异常时，release 失败只设置 `release_error`，仅在 `primary_failure is None` 时抛出；调用方看不到 `CFFEX_SETTLEMENT_FETCH_LEASE_RELEASE_FAILED`。
- **影响**：主异常掩盖租约清理失败，排障人员不知道 lease 会占用至超时。
- **最小反例**：同时注入部分发布失败和 lease release 失败；结果必须同时携带主错误码与 release 错误码，日志不得只保留一个。
- **修复方向**：结构化异常链/结果对象同时记录 primary 与 cleanup failure；release 错误不得因主错误存在而消失。
- **验收**：单错、双错、仅 release 错三种测试；错误码精确匹配。

### D. 纸交易账务（REV207-12）

#### REV207-12 [P1 / SQLite 多进程账务 / E2 + E3] 账户锁按事件循环保存，SQLite 不提供跨进程行锁

- **位置**：`src/backend/app/services/paper_trading_execution.py:34-53, 176-185`。
- **当前行为**：`WeakKeyDictionary[event_loop, account_locks]` 只能串行化同一事件循环；SQLite 路径 `use_row_lock=False`，不执行 `SELECT ... FOR UPDATE`。同订单 CAS 不能保护不同订单对同一账户的并发修改。
- **边界说明**：当前 HTTP managed-paper 路径不直接走 legacy `submit_order`；legacy producer、测试迁移和任何直接调用 `_process_order` 的路径仍受影响。MySQL/PostgreSQL 有账户行锁，不受这一特定缺口影响。
- **影响**：SQLite 多进程/多事件循环同时处理同一账户不同订单时，可能基于相同现金/持仓快照通过检查，造成重复入账或丢更新。
- **最小反例**：两个独立进程/事件循环同时提交同账户不同订单，初始资金只允许一笔成交；最终只能一笔成功，现金与持仓精确。单进程正例保持通过。
- **修复方向**：SQLite 在读取账户快照前获取事务级写串行化（如 `BEGIN IMMEDIATE` 或等价数据库机制）；`asyncio.Lock` 只作为性能优化，不能作为唯一正确性边界。
- **验收**：新增 `tests/test_iteration207_paper_sqlite_multiprocess.py` 并在 E3 多进程环境运行；MySQL/PG 回归保持 `FOR UPDATE`。

### E. 前端认证与异步竞态（REV207-13～19）

#### REV207-13 [P1 / 前端认证 / E2] `suppressErrorMessage` 提前返回，绕过 401 刷新和会话失效

- **位置**：
  - `src/frontend/src/api/index.ts:362-388`
  - 调用方：`src/frontend/src/api/marketData.ts:1155-1161, 1206-1231`。
- **当前行为**：响应拦截器在状态码处理前直接 `return Promise.reject(error)`；这些行情请求收到过期 token 的 `401` 时不会刷新，也不会触发 `expireSession`。
- **影响**：用户停留在看似正常的页面，但数据持续失败；与普通 401 单飞刷新行为不一致。
- **最小反例**：`suppressErrorMessage=true` 的请求收到 401，应先单飞刷新并重放一次；刷新失败才清理会话。静默只控制 toast，不控制认证生命周期。
- **修复方向**：把消息抑制移到认证/重试处理之后，仅跳过用户提示。
- **验收**：Vitest 覆盖 401→刷新→重放、刷新失败→登出、并发请求只刷新一次。

#### REV207-14 [P1 / 回测前端生命周期 / E2] 提交与轮询缺少卸载/generation 栅栏

- **位置**：
  - `src/frontend/src/views/BacktestPage.vue:432-444, 487-489`
  - `src/frontend/src/composables/useBacktestRuntime.ts:92-103, 208-218, 276-291`。
- **当前行为**：离页后迟到的提交响应仍可调用 `startRuntime`，重新创建 WebSocket/心跳；轮询 AbortController 未传给 `getStatus`，迟到响应仍可写回结果。
- **最小反例**：提交 A 后立即卸载，再解析 A；不得创建 socket/timer。提交 B 后解析 A，不得启动 A runtime 或覆盖 B 状态。
- **修复方向**：提交 generation + task identity + unmounted 守卫；轮询请求携带 signal，并在应用响应前复核 generation/taskId。
- **验收**：Vitest 覆盖卸载、快速二次提交、迟到状态、迟到结果。

#### REV207-15 [P1 / 过拟合任务 / E2] 可重复提交，旧完成请求可关闭新任务

- **位置**：
  - `src/frontend/src/views/BacktestResultPage.vue:575-590, 924-944`
  - `src/frontend/src/composables/useOverfittingRuntime.ts:141-173`。
- **当前行为**：创建请求无 loading/generation 控制；`await getOverfittingTask(taskId)` 后未复核 socket/task 身份。
- **最小反例**：双击创建只允许一个在途请求；A 的完成响应晚于 B 时不得停止 B socket 或清空 B 任务。
- **修复方向**：in-flight lock + generation + taskId 快照；停止/应用响应前验证当前任务身份。
- **验收**：Vitest 覆盖双击、A/B 乱序、卸载。

#### REV207-16 [P1 / 行情图表 / E2] 图表请求可乱序覆盖新周期

- **位置**：
  - `src/frontend/src/stores/quote.ts:543-580`
  - `src/frontend/src/views/QuotePage.vue:860-925`。
- **当前行为**：`fetchChartData` 无请求序号、AbortController 或参数快照校验；旧周期响应可覆盖新周期数据和 loading。
- **最小反例**：先请求日线、再请求周线，先解析日线；周线数据和 loading 必须保持。关闭抽屉/切换 symbol 同样不得回写。
- **修复方向**：每次请求捕获 `(source, symbol, timeframe)` 与序号；仅最新请求可应用结果和结束 loading，取消旧请求。
- **验收**：Vitest 覆盖周期、symbol、source、卸载四类乱序。

#### REV207-17 [P1 / 新闻正文 / E2] 文章 A 迟到响应可写入文章 B 的标题/正文状态

- **位置**：`src/frontend/src/views/NewsIntelligencePage.vue:210-228, 786-798`。
- **当前行为**：弹窗使用共享 `articleContent*`，请求完成后不复核当前 article id。
- **最小反例**：打开 A 后打开 B，先解析 A；标题必须是 B，正文必须是 B，loading 只由当前请求结束。
- **修复方向**：保存请求 articleId/generation；应用响应前校验当前选择，关闭弹窗递增 generation。
- **验收**：Vitest 覆盖 A/B 乱序与关闭弹窗后响应。

#### REV207-18 [P1 / 股票分析轮询 / E2] 定时轮询可重叠、状态回退并产生未处理拒绝

- **位置**：
  - `src/frontend/src/composables/useStockAnalysisTask.ts:23-62`
  - `src/frontend/src/components/aichat/StockAnalysisTaskCard.vue:88-93, 186-192`。
- **当前行为**：`setInterval` 不等待前次请求，`void refreshTask()` 未捕获拒绝；旧 running 响应可覆盖新 completed。
- **最小反例**：人为延迟第一次请求超过 interval；不得出现第二次在途请求。旧 running 后到不得覆盖 completed。网络拒绝必须进入 error 而非 unhandled rejection。
- **修复方向**：single-flight + 序号/状态单调保护；终态停止轮询；所有异步调用捕获错误。
- **验收**：Vitest 覆盖慢请求、状态回退、拒绝、卸载。

---

## 三、P2 — 中优先级（3 项）

### REV207-19 [P2 / 股票分析页 / E2] polling generation 未覆盖报告、历史报告和证据请求

- **位置**：`src/frontend/src/views/investment/StockAnalysisPage.vue:657-665, 714-828`。
- **当前行为**：`loadResult`、`loadLatestCompletedResult`、`loadSignalEvidence` 未统一复核 polling generation、task id、symbol 和卸载状态。
- **影响**：切换股票/任务后，旧报告或证据可写入新页面，形成难以复现的错配。
- **最小反例**：A 请求未完成时切换 B；A 的报告、历史、证据均不得覆盖 B。
- **修复方向**：建立页面级 generation 和请求上下文快照；所有相关请求在应用响应前校验。
- **验收**：Vitest 覆盖三类请求、切换 symbol、路由卸载。

### REV207-20 [P2 / 后台任务生命周期 / E2] 后台任务所有权、关停和恢复策略不统一

- **位置**：
  - `src/backend/app/utils/async_tasks.py:15-58`
  - `src/backend/app/api/stock_analysis.py:186, 232`
  - `src/backend/app/services/overfitting/service.py:68-101`。
- **当前行为**：仓库已有 `spawn_tracked_task`/`cancel_tracked_tasks`，但股票分析仍直接 `asyncio.create_task`；shutdown hooks 未统一调用 `cancel_tracked_tasks`；overfitting 任务表没有统一恢复策略。
- **边界**：`run_pending_task` 自身捕获业务异常，monitoring 和 paper scheduler 有各自 shutdown；因此不声称已发生大规模任务丢失。
- **影响**：不同模块对强引用、异常回收、关停和重启恢复的口径不同，长期运行容易出现孤儿任务或状态滞留。
- **最小反例**：启动任务后执行 shutdown，任务必须取消并等待；重启后 in-flight durable task 必须恢复或明确标记 interrupted。
- **修复方向**：建立任务登记规范；所有 fire-and-forget 使用 tracked helper；shutdown 统一取消；启动 reconcile 处理 durable in-flight。
- **验收**：任务注册表、取消、异常回收、重启恢复四类测试。

### REV207-21 [P2 / gitleaks 治理 / E1] 扫描候选噪声较高，tracked/ignored 口径需与 CI 对齐

- **位置**：`.gitleaks.toml`、`.github/workflows/ci.yml`、`scripts/ci/tests/test_gitleaks_install_step.py`。
- **证据**：`--no-git` 得到 67 个候选，其中 tracked 45、ignored 22；主要为 fixture、`.env`、示例和第三方数据。当前未确认真实已跟踪凭据泄漏。
- **风险**：直接把候选数当泄漏数会制造误报；过度 allowlist 又可能屏蔽真实密钥。扫描模式与 Git 跟踪模式不同还会让本地与 CI 结论不可比。
- **最小反例**：在临时 tracked fixture 中植入受控假 token，扫描必须命中；同一内容放入 ignored 文件是否命中应符合明确策略；现有 allowlist 不得屏蔽新的真实形态。
- **修复方向**：明确本地/CI 扫描命令与 tracked 范围；allowlist 精确到规则、路径和值语义；增加正负控制测试，保持报告脱敏。
- **验收**：planted positive 命中、negative 不误报、CI 命令与文档一致。

---

## 四、P1 门禁与 P3 文档（REV207-22～24）

### REV207-22 [P1 / CI 门禁与可维护性 / E1 + E2] 9 个巨型文件重新超过棘轮基线

- **位置与当前超限**：
  - `src/backend/app/api/portfolio/api.py`：1863 > 1861
  - `src/backend/app/services/asset_research/orchestrator.py`：3051 > 3044
  - `src/backend/app/services/market_instrument_asset_adapter.py`：1235 > 1233
  - `src/backend/app/services/monitoring_control.py`：1560 > 1558
  - `src/backend/app/services/research/holdout_claim.py`：1480 > 1478
  - `src/backend/app/services/research/holdout_finalize.py`：2180 > 2172
  - `src/backend/app/services/stock_analysis/data_collector.py`：1264 > 1249
  - `src/backend/app/services/sync_service.py`：2527 > 2525
  - `src/backend/app/services/workspace/run_ops.py`：1671 > 1667
- **证据**：[check-large-files.txt](evidence/check-large-files.txt)，命令退出码 1。
- **风险**：CI 当前为红灯；这些文件同时承载认证、研究、行情和任务生命周期等高影响逻辑，继续膨胀会提高回归概率。
- **修复方向**：按“纯 helper / DTO / 查询编排 / 状态机”垂直切片，先 characterization tests，再搬迁；禁止上调 baseline。REV207-20 修复涉及的文件优先合并拆分，避免二次搬迁。
- **验收**：`large_file_ratchet.py` 退出码 0；受影响模块测试、复杂度和 Ruff 全绿。

### REV207-23 [P1 / 工具链可复现性 / E1] mypy 本机版本与仓库锁定版本不一致，门禁 fail-closed

- **位置**：
  - `src/backend/pyproject.toml`
  - `config/requirements-dev.lock`
  - `scripts/ci/mypy_ratchet.py`。
- **证据**：baseline 为 `mypy 1.20.2 (compiled: yes)`，本机为 `mypy 2.3.1 (compiled: yes)`；[check-mypy-app.txt](evidence/check-mypy-app.txt) 退出码 1。
- **风险**：直接用 2.3.1 重生成基线会混入工具链变化，无法区分代码类型债务；CI 与本地结论不可复现。
- **修复方向**：建立仓库级、锁定解释器与 `mypy==1.20.2` 的验证环境；mypy_ratchet 在版本漂移时继续 fail-closed，并输出修复命令。只有在意向明确的工具升级 PR 中才重生成基线。
- **验收**：锁定环境运行 `python3 scripts/ci/mypy_ratchet.py` 退出码 0；记录版本、Python、平台和 baseline 差异。

### REV207-24 [P3 / 文档治理 / E1] 迭代索引仍把已完成的迭代 206 标为 PLANNED

- **位置**：`docs/iterations/README.md:13`；迭代 206 `README.md:5` 与 `TODO.md:4` 已为 44/44 COMPLETED。
- **影响**：维护者无法从索引判断当前有效计划，容易重复安排已闭环工作。
- **修复方向**：将迭代 206 改为 COMPLETED，新增迭代 207 入口并注明 PLANNED、24 项最终统计。
- **验收**：`python3 scripts/ci/check_doc_links.py` 通过，索引与各 README/TODO 状态一致。

---

## 五、未确认项与审计边界

以下内容不应被误写为已确认缺陷：

- **真实凭据泄漏**：gitleaks 的 67 个候选经分类和抽查未确认真实已跟踪密钥。
- **常规跨用户 IDOR**：已检查的回测任务、股票分析、投资组合、知识库、RAG、比较、纸交易和 WebSocket 多数有 owner 校验；本轮仅立案上述明确缺口。
- **纸交易所有路径双花**：MySQL/PostgreSQL 有账户行锁，当前 HTTP managed-paper 也不直接走 legacy 路径；缺口限定在 SQLite 多进程/多事件循环。
- **大规模任务丢失**：后台任务问题是所有权/恢复口径不统一，尚无运行证据证明已发生大规模丢失。
- **NaN 行情事实、重复最终化、claim/finalize 并发穿透**：已检查路径有相应约束，本轮不重复立项。
- **v-html/token 存储**：未发现未净化 `v-html`；token 使用 `sessionStorage`，WebSocket 使用子协议而非 URL 明文 token。
