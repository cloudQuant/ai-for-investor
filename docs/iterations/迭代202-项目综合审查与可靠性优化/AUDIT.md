# 迭代 202：审查依据与问题分析

## 1. 证据口径与覆盖范围

- 日期：2026-10-12；分支：`feature/a5-opendata-provider`；HEAD：`50b6a54baa6a7d9424bc3b3664c399c297908852`。
- 依据为本 checkout 当前源码、测试源码和迭代文档；下列行号绑定此基线，实施前须重新核对。
- 审查了 HTTP/WS 认证与部分资源授权、优化任务、交互式多资产研究任务、THS 回填/调度、前端认证/工作区、Docker/数据库启动/生产入口。没有逐行审计全部 data_fetch 适配器、全部券商插件或全部策略。
- D01–D14 的结论为 `CONFIRMED_STATIC`；动态复现为 `NOT_RUN`。描述的是可从代码推出的条件行为，不声明现网已经触发。
- 范围调整（2026-10-12）：用户决定后续将数据接入 OpenData；D04/D05 的处理状态改为 `DEFERRED_TO_OPENDATA`，不在202单独修复或验收。原始发现仍保留，延期不表示已经修复。
- O01–O04 是优化建议；性能收益没有实测。迭代 196/200 的历史通过数字未作为当前测试结果使用。
- 本轮开始时，用户已有根 README 中英文版的修改，以及 DISCLAIMER/许可证评审草稿；这些文件不属于本轮编辑范围。
- `AGENTS.md` 引用的 `.joyincode/rules/backend.md`、`.joyincode/rules/frontend.md` 在当前 checkout 中未找到。本次只做分析和文档；未来开发前应恢复有效引用。

## 2. 认证和授权

### D01 · P1 · Refresh token 被接受为资源访问凭证

**证据：** [令牌签发/解码](../../../src/backend/app/utils/security.py) L128–173、185–198；[HTTP/WS 认证依赖](../../../src/backend/app/api/_dependencies.py) L37–41、65–77、95–103；[TokenPayload](../../../src/backend/app/schemas/auth.py) L113–119。Access/refresh JWT 使用同一签名配置，带不同 `token_type`；`decode_access_token()` 只解码，调用方也没有要求 `token_type == access`，DTO 的类型仅为 `str`。

**触发与影响：** 将合法 refresh token 放到 HTTP Bearer 或 WS 认证子协议中，它可获得普通 access 身份。刷新令牌的长有效期及刷新流程中的撤销检查因此不能约束这条资源访问路径。此问题不等于可以任意伪造其他用户身份，但破坏了短期 access/长期 refresh 的边界。

**修复方向：** 为 HTTP、optional auth、WS 统一实施用途校验；refresh 仅用于刷新接口。缺失/未知用途也失败关闭；如确有旧 token 兼容需求，记录明确迁移窗口。不要误把响应中的 `token_type: bearer` 当成 JWT claim 的用途值。

**验收：** AC-D01；检查正常 access、refresh、缺失/未知用途、过期令牌；资源路由和 WS 都覆盖。刷新令牌撤销后的资源访问仍须拒绝。

### D02 · P1 · 优化任务授权异常时放宽为内存访问

**证据：** [公开路由](../../../src/backend/app/api/optimization_api.py) L282–352 传入 `current_user.sub`；[数据库 owner 检查](../../../src/backend/app/services/optimization/execution_manager.py) L53–59；[任务 gateway](../../../src/backend/app/services/optimization/task_gateway.py) L24–51、77–103；[内存任务结构](../../../src/backend/app/services/optimization/task_state.py) L42–63、79–107。

**触发与影响：** 用户 B 已知 A 的 task ID，任务还在处理请求的进程内存中，且数据库授权读取/取消调用抛异常。正常路径的 owner 不符会拒绝，但异常路径会返回或更新内存任务；内存任务没有 owner 字段。由此可读取别人的优化进度/结果或取消任务。没有验证 task ID 的可发现性，也不声称任意 DB 故障都会触发。

**已有测试缺口：** [test_optimization_service.py](../../../src/backend/tests/test_optimization_service.py) L771–791 反而期望带 `user_id` 的 DB 异常取消降级成功；本轮仅阅读，未运行。

**修复方向：** 用户接口无法证明归属时失败关闭；若保留安全降级，必须有可信的 owner 绑定并重新校验，不能只凭 task ID。内部 worker 无用户上下文的查询与用户 API 分开处理。

**验收：** AC-D02；注入授权仓储异常，对读、结果、取消分别断言没有泄露/状态变化；同 owner 的降级策略也应有明确契约。

## 3. THS 回填事务与完整性

> **DEFERRED_TO_OPENDATA**：以下两项按用户决定延后，随 OpenData 接入统一处理。本节修复方向及 AC-D04/AC-D05 仅作为后续迁移参考；届时按实际保留/替换的采集链路重新设计，不要求先修复即将替换的 THS 实现，也不阻塞202关闭。

### D04 · P1 · 默认 dry-run 仍可持久化 daily-k 数据

**证据：** [backfill_ths_history.py](../../../src/backend/scripts/backfill_ths_history.py) L79 声明缺省 dry-run，L101–105 只将 `commit_every` 设为 None，L131–134 最后 rollback；[每日采集 CLI](../../../src/backend/scripts/collect_ths_daily.py) L64–67、81–84 同样处理。调用经 [ThsHistoryRunner](../../../src/backend/app/services/market_data/ths_history_runner.py) L293–301、708–722，进入 [dump importer](../../../src/backend/app/services/market_data/ths_dump_importer.py) L387–392，最后 [MarketDataStore](../../../src/backend/app/services/market_data/store.py) L778–783 自行 commit durable facts，再尝试 L817–823 的 publication。

**触发与影响：** 有可导入的新数据、身份/授权前置满足时，不带 `--apply` 执行上述 daily-k CLI，也会到达内部提交。最外层 rollback 无法撤销已经完成的提交；即使提交后发布或外层 savepoint 出错，也不能推导“没有写入”。这违背了 CLI 对 dry-run 的零持久写入承诺。此处确认的是历史/每日 daily-k 路径，其他 reference/calendar 路径列为扩展回归，不混称全部已复现。

**已有测试缺口：** [test_ths_history_runner.py](../../../src/backend/tests/market_data_platform/test_ths_history_runner.py) L951–984 的 CLI 用例 mock runner，仅检查外层 rollback，未穿透真实 Store 的 commit。[原199验收](../迭代199-THS全市场历史回填与定时采集/ACCEPTANCE.md) AC-10 的零写入要求应继续保留。

**修复方向：** 明确事务所有者和 apply/dry-run 传播边界。只读规划/解析路径不得调用自行提交的 store；若验证真实写入链路，使用隔离一次性数据库。不要通过删除 store 的全部 commit 破坏既有“先durable、后publish”可见性合同。还需验证正常 apply 模式的嵌套事务和回执完整性。

**验收：** AC-D04；默认CLI和每日CLI运行后，独立连接读回的所有相关持久数据与运行前一致；同一fixture显式apply得到完整的观测/来源/发布证据；异常路径也检查残留。

### D05 · P1 · 已有 series 不等于所请求历史已经完整

**证据：** [回填CLI](../../../src/backend/scripts/backfill_ths_history.py) L75–79、101–105 默认 skip existing；[ths_history_runner.py](../../../src/backend/app/services/market_data/ths_history_runner.py) L322–337 只按 dataset_code 查询 `MdDataSeries.canonical_id`，L700–702 将这些标的整体从导入列表剔除，没有读取事件覆盖、请求窗口或manifest完成证据。

**触发与影响：** 某标的只导入过较短窗口，或已经有空/部分series，随后执行全历史回填，整个标的被跳过；再次使用默认参数运行也不会补齐缺口。该判断还不足以区分同数据域的其他series维度。没有声称数据库中的每个标的当前都缺数。

**已有测试缺口：** [历史runner测试](../../../src/backend/tests/market_data_platform/test_ths_history_runner.py) 的若干dump路径显式设置 `skip_existing=False`，没有证明部分coverage下默认续跑正确。

**修复方向：** 完成状态绑定准确series身份、来源/manifest版本和窗口覆盖，按事件缺口导入；交易日历、上市区间等决定应有事件集合，不能按自然日简单计数。完整覆盖且版本匹配时才跳过，未完整的失败/未知状态保持可恢复。

**验收：** AC-D05；预置部分历史后默认续跑能补齐；相同输入再跑不重复；完整/空series、来源版本变化和中断恢复分别覆盖。

## 4. 参数优化与研究任务

### D03 · P1 · 参数网格缺少终止性与容量约束

**证据：** [请求模型与调用](../../../src/backend/app/api/optimization_api.py) L38–65、94–110、238–263；[生成器](../../../src/backend/app/services/optimization/submission.py) L7–27；[转发层](../../../src/backend/app/services/param_optimization_service.py) L247–260 没有补充校验。

**触发与影响：** 合法登录用户提交一个存在的策略、`start <= end` 和 `step = 0` 或负数。`while v <= end + 1e-9` 永远无法退出；该函数在 async API 内同步执行，阻塞所在事件循环并不断分配列表。即使步长为正，过小步长/多个大维度也会通过 `list(product(...))` 一次性物化巨量组合；浮点加法不再推进的极小步长同样需要拒绝。

**修复方向：** API 与服务边界同时校验有限数、正步长、范围顺序、合法参数类型和整数参数语义；先计算单轴数量与乘积并执行服务端上限，再生成网格。只把生成器移到线程不能解决无限循环或内存耗尽。

**验收：** AC-D03；危险输入应在分配网格/创建任务前以稳定 4xx 拒绝；测试不能直接无超时调用现有无限循环。

### D06 · P1 · 批量领取后的排队时间消耗执行租约

**证据：** [task_runner.py](../../../src/backend/app/services/asset_research/task_runner.py) L100–155 一次领取整批并设相同到期时间；L187–198 领取后才等待 semaphore；L241–254 到 `_run_claim()` 后才启动心跳；L157–180 过期即标 FAILED。[默认参数](../../../src/backend/app/config.py) L599–615 为 lease 900 秒、batch 20、并发 4。

**触发与影响：** 整批任务先变成 RUNNING，后 16 个还在等待许可。若等待超过 lease，另一进程的恢复循环可把尚未执行的任务记成 `TASK_LEASE_EXPIRED`。单进程没有其他恢复者时，[run_claimed_task](../../../src/backend/app/services/asset_research/orchestrator.py) L1848–1857 也只校验状态/token，不校验到期时间，等待任务仍可能从过期租约开始执行。

**已有保护：** CAS、心跳及取消胜出后的回滚可保护已开始的任务；它们没有覆盖领取与真正执行之间的等待窗口。配置明确是进程内并发，本项不把它误报为未实现全局并发上限。

**修复方向：** 优先只领取立即可执行的数量，余下保持 QUEUED；也可设计明确的排队租约，但不能把已到期 token 恢复为有效执行权。派发前重查状态/token/有效期，保护取消、终态 CAS 和输出回滚语义。

**验收：** AC-D06；两 runner、短可控时钟、batch 大于并发，首项阻塞时后项不被误判失败；过期/取消任务不得触发 Provider I/O。

### D07 · P1 · 优化取消缺少执行终止与终态竞争约束

**证据：** [thread_runner.py](../../../src/backend/app/services/optimization/thread_runner.py) L132–151 先提交整个网格，收到完成项时才检查取消，且只调用 `Future.cancel()`；L184–211 依本地状态决定并持久化 completed。[trial_runner.py](../../../src/backend/app/services/optimization/trial_runner.py) L307–314 同步启动子进程，单次 timeout 600 秒，没有任务取消信号。[数据库终态写入](../../../src/backend/app/services/optimization/execution_manager.py) L61–100 仅按 ID 更新。

**触发与影响：** trial 正在运行时取消，API 可已显示 cancelled，但该子进程仍执行，线程也可能停在等待完成项/进程池退出上。跨实例取消若发生在最后一次取消检查之后，worker 的无条件 completed 更新还可覆盖取消终态。取消已完成任务也没有终态条件保护。

**修复方向：** 设计 `cancel_requested → cancelling → cancelled` 或等价明确状态；有界投递 trial，传播取消到正在执行的子进程/进程组，确认清理后才宣告停止。终态以原状态/执行租约 CAS 写入，定义完成与取消竞争规则。

**验收：** AC-D07；取消长 trial 后在约定期限内无任务残留进程；停止继续投递；完成/取消竞争不覆盖胜出的终态。不能仅断言 DB 字段变成 cancelled。

### D08 · P2 · 导出摘要的 best_result 实际为首个完成项

**证据：** [thread_runner.py](../../../src/backend/app/services/optimization/thread_runner.py) L147–165 按完成顺序追加，L76、101 直接取 `successful_results[0]`。该摘要通过 [工件下载](../../../src/backend/app/api/workspace_optimization_api.py) L255–262 打入 ZIP，因此不只是内部临时字段。

**触发与影响：** 两个成功 trial 的完成顺序与评价指标排名不同，导出 `best_result` 会选中更快完成者；同样结果集可能随调度顺序改变摘要结论。

**修复方向：** 持久化目标指标、方向和稳定并列规则，再确定 best；未指定目标时改用准确字段含义或明确没有 best，不擅自选择一个收益指标。

**验收：** AC-D08；反转完成顺序后最优项不变，最大化/最小化/并列/无成功项均覆盖。

## 5. 前端状态一致性

### D09 · P2 · 获取当前用户的临时错误导致登出

**证据：** [auth store](../../../src/frontend/src/stores/auth.ts) L34–40 无差别 catch/logout，L52–57 在初始化时调用。已有 [auth store 测试](../../../src/frontend/src/__tests__/stores/auth.test.ts) L96–107 也按通用错误退出。

**触发与影响：** 有效 token 下 `/auth/me` 超时、网络断开或 503，用户被清除凭证，业务 store 也被清空。登录后读取用户失败还可能让调用方把已退出状态当作 login 已完成。

**修复方向：** 区分认证失败与可重试的资料加载失败；保留凭证不等于宣告身份资料已验证，错误期间保护路由/敏感操作应维持待确认状态。

**验收：** AC-D09；网络/503 保留可恢复会话，401 正确退出，恢复成功后重新加载用户。

### D10 · P1 · 旧会话请求的 401 会清理新会话

**证据：** [API client](../../../src/frontend/src/api/index.ts) L178–185 为请求读取 token，L243–245 遇到 401 无条件清理；[main.ts](../../../src/frontend/src/main.ts) L99–110 响应全局过期事件登出。没有会话代次核对。

**触发与影响：** A 会话发出的请求尚未返回，用户退出并登录 B，随后 A 的请求返回 401，B 的有效凭证被清除。未声称该路径能绕过服务端认证。

**修复方向：** 请求绑定会话代次，只有仍属于当前会话的失败才可触发清理；成功响应和自动重试也检查旧会话，避免把旧请求带入新账号。

**验收：** AC-D10；受控 Promise 交错旧请求、新登录和迟到 401；新 token/用户及路由不变，当前会话的真正 401 仍有效。

### D11 · P1 · 切换工作区时旧响应覆盖当前资源

**证据：** [WorkspaceDetailPage.vue](../../../src/frontend/src/views/workspace/WorkspaceDetailPage.vue) L638–644 对路由变化依次请求；[workspace store](../../../src/frontend/src/stores/workspace.ts) L93–101、129–137 无条件写 `currentWorkspace`/`units`。页面 L72–79 用前者显示标题；[交易工作区单元操作](../../../src/frontend/src/components/workspace/TradingWorkspaceUnitsTab.vue) L349–364 组合 store 中单元和当前 `props.workspaceId`。

**触发与影响：** A→B 快速切换，B 响应先到、A 后到，URL 是 B 而标题或单元为 A。操作可能用 A 的单元 ID 请求 B 的 workspace；服务端归属检查仍可能拒绝，本项不把 UI 竞态等同于后端越权。

**修复方向：** 以 workspace ID 与请求代次检查写入，废弃前一轮加载/选择态；只取消网络请求而不核对响应不够。列表、详情、指标和操作按钮使用一致资源身份。

**验收：** AC-D11；分别让详情、单元请求逆序，切换后两者都属于 B，旧请求不得清掉 B 的 loading 或选择状态。

## 6. 部署与升级

### D12 · P1 · PostgreSQL 开发环境的依赖和探测不一致

**证据：** [dev Compose](../../../docker/compose/dev.yml) L49–50 配置 `postgresql+asyncpg`；[dev Dockerfile](../../../docker/backend.dev.Dockerfile) L20–21 安装 `.[dev,backtrader]`，而 [pyproject](../../../src/backend/pyproject.toml) 的 `postgres` extra 才声明 asyncpg。[entrypoint-dev.sh](../../../docker/entrypoint-dev.sh) L22–26 又删掉 `+asyncpg` 后用同步 engine 探测，所需同步 PostgreSQL 驱动也不在所选依赖中。

**触发与影响：** 干净构建、按默认 PostgreSQL dev 组合启动，数据库即便已就绪，驱动缺失仍让等待脚本重试并最终退出。现有开发机偶然安装的驱动不能证明镜像可复现。

**修复方向：** 对齐开发镜像 extra、锁文件和连接探测所用驱动；优先复用实际异步连接路径。依赖错误应立即显示原因，不吞 stderr 后伪装成数据库尚未就绪。

**验收：** AC-D12；干净镜像无缓存构建，默认 dev 组合真实 SELECT 1，启动失败诊断可区分缺驱动与未就绪。

### D13 · P1 · 生产升级路径未执行版本化迁移

**证据：** [部署脚本](../../../scripts/ops/docker_deploy.sh) L309–310 和 [prod Compose](../../../docker/compose/prod.yml) L85–91 打开 schema/admin 自举；[startup/database.py](../../../src/backend/app/startup/database.py) L15–25 调用 [ensure_database_ready](../../../src/backend/app/db/database.py) L855–863。开启时走 L821–838 的 `metadata.create_all` 和有限兼容 DDL；关闭时 L859–861 仍执行 `ensure_schema_compatibility`。

**触发与影响：** 将新版应用部署到旧 schema，自动建表不能代替 Alembic 的既有列变更和回填。例如 [candidate hash 迁移](../../../src/backend/alembic/versions/20260905_ai_research_holdout_candidate_hash.py) L24–44 要求加列、回填、改 NOT NULL，这些步骤不在普通 `create_all` 中。多个应用 worker 还会各自进入启动 DDL；设置开关 false 不会实现完全只读启动。本轮没有执行升级，具体存量数据库是否落后未知。

**修复方向：** 发布前单次 migration job，应用按 revision/schema 检查就绪；启动时不执行隐式兼容 DDL。新库初始化、旧库升级和管理员初始化分开，管理员显式一次性引导；生产镜像/迁移镜像声明各自所需依赖。

**验收：** AC-D13；从有真实旧行的前序 revision 升级，验证回填和 revision；迁移失败阻止新版本接流量；双 worker 启动且关闭自举时零 DDL；备份恢复在一次性数据库演练。

### D14 · P1 · TLS 首次部署存在配置闭环缺口

**证据：** [docker_deploy.sh](../../../scripts/ops/docker_deploy.sh) L133–139 检测访问地址；[nginx.prod.conf](../../../docker/nginx.prod.conf) L4、20、26–27 固定 `aifortrader.cn` 及证书路径；[prod Compose](../../../docker/compose/prod.yml) L130–148 挂载证书目录，certbot 只有 renew 循环，没有首次签发。

**触发与影响：** 空证书目录的首次部署无法加载固定 TLS 证书，Nginx 不能正常启动；自定义域/IP 的访问设置也不能自动改成对应证书。已有人工放入匹配证书的部署不受“空目录”条件影响。

**修复方向：** 域名和证书名称统一配置；提供 HTTP 引导/独立签发到 TLS 的显式流程。IP-only 模式应有明确方案，不能套用固定域证书；证书更新后验证安全 reload。

**验收：** AC-D14；空目录的引导可启动；隔离 ACME/staging 环境验证自定义域首次签发与 reload；本轮不申请真实证书。

## 7. 可独立安排的优化

### O01 · 编排器拆分继续归属迭代 201

当前 `wc -l`：`market_data/store.py` 4,556；`api/portfolio/api.py` 3,393；`trading_workspace_service.py` 3,089；`market_instrument.py` 2,514；`position_valuation.py` 2,379；`ai_strategy_research_task_manager.py` 2,152；`useStrategyPage.ts` 8,204。与 [201 工作包](../迭代201-核心编排器职责拆分/IMPLEMENTATION_PLAN.md) 的基线一致，拆分目标仍有依据。

行数不是功能缺陷或性能瓶颈的证明。优先提取纯查询、状态转换和 API 适配边界，复用 201 的回归/兼容要求；202 的功能修复不要顺带改这些模块的全部结构。另观察 `asset_research/orchestrator.py` 3,046 行，是否追加到 201 由职责分析决定，不仅按阈值拆文件。

### O02 · 会话刷新接入属于体验增强

[前端 auth API](../../../src/frontend/src/api/auth.ts) L4–7 使用 access-only 登录；[auth store](../../../src/frontend/src/stores/auth.ts) L11–27、110–114 声明并持久化 refreshToken，但未从登录响应赋值。后端已有 [refresh 登录及轮换接口](../../../src/backend/app/api/auth.py) L112–190。

这是能力尚未接入，不将“到期后要求重新登录”单独定为认证缺陷。先修 D01/D09/D10，再决定是否采用单次共享刷新、轮换失败退出和有界重试；不能笼统自动重放所有有副作用请求，也不要将长期凭证放入新的不必要存储位置。

### O03 · 大工件下载先建立性能基线

[workspace_optimization_api.py](../../../src/backend/app/api/workspace_optimization_api.py) L255–273 在 async handler 中同步遍历压缩整个工件到 `BytesIO`。能确定其占用内存和同步压缩路径，但本轮没有测量响应时间或内存峰值。

建议在固定文件集和并发下记录压缩前后字节、首字节/总耗时、RSS 峰值与事件循环延迟；若超过 S0 冻结预算，考虑后台生成受控临时文件并用 FileResponse 输出，或有界流式方案。验证授权、取消清理和下载内容一致后再接受优化。

### O04 · 导航与运行指南和当前仓库保持一致

本轮前的 [迭代索引](../README.md) 最新设计只写到 197，近期表停在 193；同时 AGENTS 的两个开发规范引用不存在。本轮只补充 202 导航，历史状态不批量改写。后续逐项登记 194–201 的权威入口、最后验证 SHA/日期/证据级别，恢复有效规范引用，避免从旧通过数字推导当前生产状态。

## 8. 未下结论的范围

- 没有将共享交易网关直接定为越权：其共享/按用户隔离的产品授权策略尚需明确。
- 未对全部 OpenData、AkShare 和券商适配器进行真实连接、数据覆盖或执行验收。
- OpenData 响应中 symbol 与请求身份的完整校验链尚未核验完毕，不将局部适配器观察升级为确认缺陷；可另安排契约复查。
- 真实 PostgreSQL/MySQL、跨进程调度、Redis、Provider、浏览器、沙箱与生产拓扑均 `NOT_RUN`；已有 fixture 或历史记录不替代这些证据。
- 未检查或改动秘密配置，未做当前漏洞数据库检索，不凭依赖版本号报告 CVE。
- 本清单是针对关键路径的审查结果，不保证穷尽全项目缺陷。
