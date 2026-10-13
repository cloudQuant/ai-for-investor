# 迭代 202：验收计划与状态

> 日期：2026-10-12。状态：**PASS / ACCEPTED_LOCAL**。12 项本轮缺陷已实现并由主审独立验收；最终源码、锁、命名案例和组合回归见[最终验收汇总](FINAL_ACCEPTANCE.md)。AC-D04/AC-D05 保持 **DEFERRED_TO_OPENDATA**，不作为 202 门槛。历史失败与中间快照保留在[执行台账](EXECUTION_STATUS.md)。

## 1. 逐项验收矩阵

| ID / 工作包 | 建议用例名 | 条件与必须断言 | 本轮状态 |
| --- | --- | --- | --- |
| AC-D01 / WP01 | `reject_refresh_token_for_http_and_websocket` | 正常 access 成功；refresh、已撤销 refresh、缺失/未知用途在必选认证资源上401/WS拒绝；optional auth 不认作用户；正常 refresh 接口继续轮换；确认下游业务未调用 | PASS：主审最终依赖下鉴权组合 27 passed，见下节当前收据 |
| AC-D02 / WP01 | `ownership_lookup_error_never_exposes_or_cancels_foreign_task` | A 的任务在内存；令任务授权仓储抛异常、认证依赖正常；B 的进度/结果/取消全部受控拒绝且不泄漏任务内容，A 状态不变；正常 owner/非 owner 行为也覆盖 | PASS：同一主审鉴权组合覆盖授权仓储异常及正常 owner/non-owner |
| AC-D03 / WP02 | `reject_invalid_or_oversized_grid_before_materialization` | step=0、负步长、非有限值、数值不再推进、反向范围、不合法整数参数、超单轴/总组合上限被4xx拒绝；在生成/建任务前失败；正常边界网格输出精确；事件循环仍响应 | PASS：非法网格/精度/组合上限和 API 无任务创建均通过；真实后台线程阻塞期间主事件循环 heartbeat 独立复验 1 passed / 4.29 秒 |
| AC-D04 / WP03 | `ths_dry_run_leaves_no_durable_changes`（原案例保留） | 后续OpenData接入参考：dry-run前后持久数据不变，显式提交才出现期望数据；按保留/替换后的链路重写用例。本轮不运行THS验收 | DEFERRED_TO_OPENDATA |
| AC-D05 / WP03 | `resume_fills_partial_window_and_remains_idempotent`（原案例保留） | 后续OpenData接入参考：部分覆盖能够补缺，中断可恢复，完整覆盖重跑不重复，来源版本正确绑定。本轮不运行THS验收 | DEFERRED_TO_OPENDATA |
| AC-D06 / WP04 | `queued_claims_do_not_expire_before_execution_capacity` | batch=2、并发=1，第一任务阻塞超过可控lease，第二runner恢复时第二任务仍可执行；第二任务执行前才持有效租约；过期/取消token零Provider调用；正常心跳、取消CAS继续通过 | PASS：主审真实 MySQL/PostgreSQL 跨连接、容量及取消租约检查通过；全局回归另列 |
| AC-D07 / WP02 | `cancel_stops_trials_and_preserves_terminal_winner` | 隔离无交易trial持续等待，取消后停止新投递、进程/子进程组在S0约定时限内退出，清理临时资源；取消先赢与完成先赢两种交错均不被后写覆盖；持久终态与实际执行一致 | PASS：主审生命周期文件 14 passed，含真实进程组/进程池取消、排队阻断、CAS 和资源清理；关联与全局回归另列 |
| AC-D08 / WP02 | `best_result_is_independent_of_completion_order` | 目标明确的两trial反转完成顺序，summary与API选择同一最优项；最大化/最小化/并列/无成功项/无目标兼容语义覆盖；下载ZIP中的摘要也校验 | PASS：主审 169 项关联回归、14 项生命周期及新专项中 ZIP 最大化/最小化、全失败/无有效分数摘要断言通过；同批 heartbeat fixture 失败已修正并单独复验通过 |
| AC-D09 / WP05 | `preserves_session_when_get_me_fails_transiently` | 有效token下getMe的503/网络/超时不清凭证，有可见可重试状态；重试成功后用户恢复；真正401退出；资料未确认时不提前启用敏感操作 | PASS：主审最终 v15 dist preview 会话组合 7 passed，覆盖临时503/网络故障恢复及真正startup 401；无全局运行时异常 |
| AC-D10 / WP05 | `ignores_401_from_superseded_session` | 旧会话A请求悬挂，登录B后A返回401；B凭证、用户和路由不变、无全局过期事件；A的旧成功响应/重试也不能覆盖B；B自己的401仍可触发过期 | PASS：同一主审 v15 组合覆盖晚到A的401、成功重试、退出清理及B自身401；产物哈希前后不变 |
| AC-D11 / WP05 | `late_workspace_and_unit_responses_do_not_replace_new_selection` | A→B，B响应先到，分别让A的详情/units晚到；标题、表格、selected IDs和所有操作参数都属于B；旧请求完成不清除B的loading；浏览器确认同路由组件复用场景 | PASS：主审两种响应先后顺序真实浏览器断言均通过，包含旧响应处理屏障及 B 运行请求参数；全套/产物回归另列 |
| AC-D12 / WP06 | `clean_dev_compose_boots_with_postgresql` | 干净构建默认dev镜像/Compose，驱动和DB探测匹配，真实SELECT 1且backend ready；缺驱动立即给明确原因，DB暂时未就绪受控重试；不借宿主已安装包通过 | PASS：D12 固定镜像/6b dev 锁、空 PostgreSQL 第三轮 up --wait 205.189 秒 exit 0；独立 HTTP/DB 健康。最终 a2 锁只增加 docx 开发依赖，未声称重新构建该 dev 镜像；宿主端口未验收，前两轮失败保留 |
| AC-D13 / WP07 | `upgrade_previous_schema_then_start_without_ddl` | 一次性MySQL/PostgreSQL上准备前序revision和旧数据，migration job一次升级并核对回填/head；失败时新版本不接流量；双worker启动和开关false时应用账户无DDL仍成功；演练备份恢复 | PASS：两库迁移及 MySQL 8.0.46 恢复通过；最终源码镜像 v5 在无 DDL 账户下双 worker 启停、HTTP 200、schema 指纹一致；exit 0/OOM=false，最终 1,777 源码哈希和 123 registry pin 一致 |
| AC-D14 / WP08 | `bootstrap_tls_from_empty_certificate_directory` | 空证书目录可先HTTP引导；自定义域经隔离ACME/staging签发后TLS配置验证、reload成功；域名与证书匹配；续期失败保留有效配置并可观测；IP-only行为明确 | PASS：主审真实 Pebble HTTP-01 及失败回滚；生产 DNS/CA 未运行 |

同一用例中不同数据库/部署组合分别出具结果，不能将 SQLite fixture PASS 填到 MySQL/PostgreSQL 行。认证/任务控制用替身和无副作用本地任务验证，不下真实订单。

## 2. 测试落点与回归入口

以下是**现有文件**，建议在其中扩充命名案例或按模块新增目标文件。实施时记录新文件的实际路径；当前文件存在不表示已包含本表案例。

| 工作包 | 现有测试/入口 |
| --- | --- |
| WP01 | `src/backend/tests/test_auth.py`、`test_optimization_service.py`、`test_optimization_helpers.py`、`test_optimization_api.py`；补HTTP/WS用途拒绝案例 |
| WP02 | `src/backend/tests/test_optimization_submission.py`、`test_optimization_helpers.py`、`test_optimization_task_state.py`、`test_optimization_service.py` |
| WP03（延后） | 原THS测试仅作迁移参考；不进入本轮回归命令，后续按OpenData链路确定落点 |
| WP04 | `src/backend/tests/asset_research/test_task_runner.py`、`test_task_lifecycle.py` |
| WP05 | `src/frontend/src/__tests__/stores/auth.test.ts`、`api/index.test.ts`、`stores/workspace.test.ts`、`views/workspace/WorkspaceDetailPage.test.ts` |
| WP06–WP08 | `src/backend/tests/test_main_startup.py`、`test_ci_migration_checks.py`、`test_ai_research_v2_migration.py`；另补真实容器启动、online迁移及TLS引导场景 |

后端命令必须用用户 Anaconda base 环境。执行前核对其 Python/依赖版本与仓库所选 canonical lock；不为通过验收静默替换用户全局环境。用一次性测试目录/数据库、禁用真实行情和交易副作用后，才执行下面这些**待执行**示例。

后端：工作目录 `/Users/yunjinqi/Documents/new_projects/ai-for-investor/src/backend`。

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/test_auth.py tests/test_optimization_api.py tests/test_optimization_service.py tests/test_optimization_submission.py tests/test_optimization_helpers.py tests/test_optimization_task_state.py
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/asset_research/test_task_runner.py tests/asset_research/test_task_lifecycle.py
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/test_main_startup.py tests/test_ci_migration_checks.py tests/test_ai_research_v2_migration.py
```

前端：工作目录 `/Users/yunjinqi/Documents/new_projects/ai-for-investor/src/frontend`，使用 package.json 支持且锁文件验证过的 Node 版本。

```bash
npm run test -- --run src/__tests__/stores/auth.test.ts src/__tests__/api/index.test.ts src/__tests__/stores/workspace.test.ts src/__tests__/views/workspace/WorkspaceDetailPage.test.ts
npm run typecheck
npm run build
bash ../../scripts/ci/check_bundle_size.sh dist
npm exec playwright test -- --config=e2e/iteration202.config.ts
npm exec playwright test -- --config=e2e/tailwind4.config.ts
```

两套本轮浏览器配置使用 `vite preview`，必须先完成同一份 `dist` 构建，缺失时直接失败。受控 API 响应、单 worker、零重试保持不变，同时断言没有未捕获异常、全局错误处理器记录或未解析组件。此前 dev fixture 主动关闭热更新 websocket，导致 Vite 动态重优化时同页混用不同 hash 的 Vue/Pinia；保留失败 trace，后续以正式产物完成验收，不将其写成产品会话逻辑缺陷。

这些命令只是相关回归入口，不能替代新故障用例。修复后追加受影响文件的 Ruff/format、类型检查与现有 CI 门禁；只扩大到变更影响或失败证据支持的范围，不凭固定覆盖率/最低发现数量决定完成。

危险网格基线用例通过子进程/watchdog安全地捕获当前失败，不在服务进程直接执行无限循环。D04/D05不安排本轮验证，后续OpenData接入的事务/补缺验收另行确定。容器和证书场景的实际命令与环境现已写入下列收据；这里只保留原用例设计边界。

## 3. 证据收据

当前最终入口：[后端完整批次及 25 项失败逐例复验](evidence/2026-10-12/backend-final-composite-parent-review.json)、[前端 v15 Node 20/24 矩阵](evidence/2026-10-12/frontend-final-v15-matrix-parent-review.json)、[同产物浏览器](evidence/2026-10-12/frontend-final-v15-browser-parent-review.json)、[最终生产 v5](evidence/2026-10-12/prod-source-final-runtime-parent-review.json)、[最终镜像内容](evidence/2026-10-12/prod-source-final-image-parent-review.json)。完整旧批次仍为 FAIL_WITH_COMPLETE_EXECUTION；最终结论由整文件复验与源码差异映射形成，不声称单轮全量零失败。

### 历史收据说明（保留当时状态）

下面 v8/v9/v10、旧镜像、运行中及待复验的叙述均是过程快照，当前结论以前述最终入口为准。

2026-10-12 当前独立收据：鉴权日志为 `evidence/2026-10-12/auth-boundaries-v2-parent.txt`（27 passed，368.31 秒，4 条 warning）；TLS 为 [主审收据](evidence/2026-10-12/tls-parent/receipt.json)。TLS 记录的 10 个输入源码哈希与运行后工作树一致，失败路径前后服务证书指纹、lineage 身份保持一致。TLS 日志按明确规则脱敏，不保存测试私钥和环境文件。

优化生命周期主审复验为 **14 passed / 142.87 秒**，见[完整命令和受测镜像收据](evidence/2026-10-12/optimization-lifecycle-linux-parent-receipt.json)。该轮在离线容器内运行，测试 watchdog 为 180 秒；生产取消和 sandbox 时限未修改。随后主审优化关联五文件 169 passed / 642.86 秒。新专项组合中 14 passed / 1 failed / 53.91 秒：两个受支持目标的实际 ZIP 下载、全失败摘要和无有效分数的 best 均通过；唯一失败是 heartbeat 测试缺少必需的 resolver 参数，尚未进入产品函数，修正后独立复验。该失败仍保留，不能把原整批改写为 PASS。修正 resolver 测试参数后，heartbeat 单项主审复验 1 passed / 4.29 秒，见[独立复验收据](evidence/2026-10-12/optimization-heartbeat-v2-linux-parent-receipt.json)。见[专项原始结果](evidence/2026-10-12/optimization-final-boundaries-linux-parent.txt)及[受测快照](evidence/2026-10-12/linux-regression-source-overlay-v3-manifest.json)。

主审 MySQL 8.0.46 独立备份恢复演练通过，见[恢复与构建收据](evidence/2026-10-12/restore-and-build-parent-receipt.json)。检查真实 gzip/hash/0600、重复备份路径拒绝、未授权恢复 exit 2 且保持 `after`、授权恢复后独立连接读回 `before`；只操作一次性项目，资源清理已确认。第一次尝试因 fixture 使用 `mysqladmin ping` 过早判断就绪而失败；改用 TCP 鉴权 `SELECT 1` 后重新执行通过，未修改产品备份恢复脚本。

Tailwind 4 实现者真实浏览器的 6 项通过制品已保存至[浏览器证据及主审复核记录](evidence/2026-10-12/tailwind-worker/review-receipt.json)。主审已查看断言和代表截图；这是实现者运行证据，不冒充主审重跑，也不覆盖最低版本 Safari 16.4 / Chrome 111 / Firefox 128。

主审 v8 正式 dist preview 的会话/工作区组合 **7 passed / 53.0 秒**，见[完整收据](evidence/2026-10-12/frontend-session-browser-v8-preview-parent-receipt.json)及同名制品目录；无重试、受控 API 响应、产物前后哈希不变。v8 的原 bundle gate 也经主审独立执行通过：入口 2 个、登录 4 个 JS 请求，入口/登录闭包 gzip 分别 471,714 / 492,689 bytes。三浏览器样式组合另有 **4 passed / 5 failed / 59.4 秒**：失败均为切换 390px viewport 后读取到更宽的 scrollWidth，正在区分真实布局缺陷与 resize 后断言时机；不能沿用早期样式 PASS 关闭当前门槛。

真实 MySQL/PostgreSQL 租约检查均通过。新迁移及最终锁下的两次宿主 D13 重跑均在历史 migration 子进程阶段触发 180 秒 pytest watchdog，保留为 **INCOMPLETE / BLOCKED_ENVIRONMENT**。随后主审在最终开发镜像中复验：PostgreSQL 迁移 1 passed（66.60 秒）；MySQL 租约与迁移 2 passed（215.97 秒）。MySQL 验收容器在开发锁之外明确安装生产锁指定的 `aiomysql==0.3.2`，因为 MySQL 是可选 extra，不能把它描述为开发锁自带。容器集成测试的 pytest watchdog 为 600 秒，产品 sandbox/取消时限未改。运行环境和收据见[执行台账](EXECUTION_STATUS.md)。

D12 第三轮从空卷启动最终开发镜像，Compose `up --wait` 退出 0，耗时 205.189 秒；独立网络内 HTTP 探针返回 `healthy` 且数据库健康，见[主审复核](evidence/2026-10-12/d12-fresh-start-parent-review.json)。本轮使用 `init: true`，开发日志位于 reload 观察树之外，健康检查 180 秒宽限期未再调整。隔离 fixture 的 internal 网络没有宿主端口端点，宿主 curl 退出 7 单独保留，不算宿主端口发布通过。前两轮首次启动失败也不覆盖或改写。

20:50 更新：正式产物样式 v9 **9 passed / 34.9 秒，exit 0**，主审已检查 Chromium 浅色登录和 WebKit 深色移动工作区截图。唯一测试修订是等同一个主题 popper 完成关闭，再执行原有 390px 宽度断言；产品 CSS、dist 与其他断言未变。见[样式复核](evidence/2026-10-12/frontend-style-browser-v9-preview-parent-artifacts/parent-review.json)。前一轮 4 passed / 5 failed 保留；最低版本浏览器未运行的边界也保留。

最终前端 v10 在有效的 Vitest 配置下 **157 files / 1,721 tests 全部通过**（143.89 秒，命令 exit 0），构建配置独立 TypeScript 检查也通过，受测源码前后无变化，见[完整前端收据](evidence/2026-10-12/frontend-final-v10-parent-receipt.json)。前一轮 1,715 passed / 6 failed 全为 10 秒测试超时，未提高该时限；额外类型检查发现的 Vite 类型引用、ES2020 编译目标和 setupFiles `first`→`list` 已修正，顺序执行语义不变，分块算法不变。

最终生产镜像的两 worker 启动、受限账户、独立 HTTP 健康、真实 TERM 退出以及前后 schema 指纹一致已完成[组合复核](evidence/2026-10-12/prod-runtime-parent/parent-review.json)。v2 启动容器；v3 独立读取 PID 树和健康后停止；v4 对同一已退出容器读取两 worker shutdown/finished、master shutdown、exit 0、OOM=false 与数据库结构指纹。v1–v3 的 harness 失败分别保留，不将旧整轮结果改写为通过。

后端完整 v3 中两个测试基础设施问题已有当前修订复验：AkShare runner **32 passed / 166.47 秒，exit 0**，见[进程组复验](evidence/2026-10-12/akshare-v7-parent-receipt.json)；无 `.git` 源码快照中的 OpenBB root 定位 **5 passed / 89 deselected，exit 0**，见[路径边界复验](evidence/2026-10-12/openbb-root-parent-receipt.json)。两处都未改产品执行/路径拒绝逻辑。原完整运行仍在继续，其五项旧 fixture 失败不被覆盖。

每个案例至少记录：

| 字段 | 要求 |
| --- | --- |
| `case_id` / `requirement_id` | AC-Dxx 与 Dxx 对应，包含具体子场景 |
| `git_sha` / `dirty_scope` | 实际受测版本、未提交路径范围；不能只写分支名 |
| `environment` | Python/Node/依赖锁摘要、OS、数据库版本、worker数、关键非秘密配置 |
| `command` / `exit_code` | 完整可复核命令、执行目录与退出状态 |
| `started_at` / `finished_at` | 带时区时间和耗时 |
| `expected` / `observed` | 业务断言；授权拒绝、写入量、终态、资源归属、进程清理等 |
| `artifacts` | 原始日志和摘要路径及SHA-256；不保存token、秘密或用户明细 |
| `verdict` | PASS / FAIL / NOT_RUN / BLOCKED_ENVIRONMENT / INCOMPLETE；说明原因 |
| `review` | 主审对diff与证据的独立复核结果、残余风险 |

数据库案例额外保存 revision、关键行数/约束、输入fixture摘要及独立连接读回；取消案例保存执行前后进程树；前端竞态保存受控响应顺序与最终资源ID；部署案例保存镜像digest及健康/revision状态。

## 4. 完成门槛

| 阶段 | 通过条件 | 本轮状态 |
| --- | --- | --- |
| 文档 | 新编号无冲突，14项发现中12项纳入本轮、2项明确延后，4项优化有位置，追踪/本地链接/编辑范围核对 | PASS，见下节 |
| 静态分析 | D01–D14 有完整条件与源码链，未把推测或历史结果写成动态实证 | CONFIRMED_STATIC |
| 单项修复 | 本轮D01–D03、D06–D14对应命名案例及相关回归通过，主审已看diff | PASS；命名案例及最终完整批次/整文件复验组合均通过 |
| 集成验收 | 本轮12项对应的HTTP/WS、浏览器、任务/数据库、受支持容器路径有当前SHA的新鲜证据；排除WP03 | PASS / ACCEPTED_LOCAL：最终前端矩阵/同产物浏览器、后端组合证据、两库迁移和最终镜像 v5 闭环已完成；明确保留 skip/范围外 NOT_RUN |
| 延期移交 | D04/D05及WP03随OpenData接入统一处理，不阻塞202关闭 | DEFERRED_TO_OPENDATA |
| 发布决定 | 与具体部署配置绑定，迁移/恢复/TLS条件满足，残余项明确 | NOT_RUN；本计划不授予发布批准 |

本轮缺陷尚未实现时保持 OPEN；D04/D05保持DEFERRED_TO_OPENDATA，不要求先修旧THS实现，也不记为PASS。若部分工作包先通过，只关闭有证据的工作包。不得以200历史回归绿灯、compose静态配置成功或mock commit次数替代202行为验收。

## 5. 最初计划文档检查记录（历史快照）

主线程于2026-10-12完成以下检查：

- 使用 Anaconda base 的只读 Python 校验脚本确认本目录恰有四个文档，14个D条目、4个O条目、9个WP编号（8个本轮、WP03延后）和14个AC行完整对应；范围调整后12行为NOT_RUN、2行为DEFERRED_TO_OPENDATA。
- 本目录全部Markdown相对链接目标存在，迭代索引包含202入口。
- `git diff --check -- docs/iterations` 通过；Git状态显示本轮仅新增本目录和修改迭代索引。
- 根目录原有README中英文版、DISCLAIMER和三个许可证草稿的SHA-256均与编辑前一致。

这些检查仅证明最初计划文档交付时的完整性和改动边界，不是产品测试。随后用户授权开发和验收，已执行的检查与当前代码状态见第三节及执行台账；不能把本历史快照解释为当前仍仅修改文档。
