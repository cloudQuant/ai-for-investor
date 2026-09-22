# 迭代 200：需求

> 历史说明：T1–T61 的全量 Mypy 错误数及 `FAIL / NO-GO` 描述是各批次执行时的历史快照；T62/T63 是当时 base Conda 环境的本地复验。T64 的 0/625 是当时快照；T67/T68 使用相同 Mypy 1.20.2 的 fresh-cache 最终复验为 0/630，并通过实际 0-error ratchet。历史状态不代表当前门禁仍开放，也不表示 CI workflow 已运行。

## CQ-200-01：前端依赖锁一致性

**问题**：@vitest/coverage-v8 锁定为 5.0.0，但项目使用 Vitest 1.x，锁文件实际解析到 1.6.0；coverage-v8 5.0.0 的 peer dependency 要求 Vitest 5.0.0，导致 npm ci --ignore-scripts 返回 ERESOLVE。

**要求**：将 coverage-v8 对齐至兼容的 1.6.x 版本线并更新 package-lock。不得为解决 peer 冲突而整体升级 Vitest/Vite 生态或使用 legacy peer-deps。

**验收**：干净依赖目录下 npm ci --ignore-scripts 成功；锁文件中的 coverage-v8 与 Vitest peer 版本相容。

**本地结果**：Node 20.20.2/npm 10.8.2 与 Node 24.2.0/npm 11.6.2 下 clean npm ci、lint、typecheck、全量 Vitest 和 production build 均通过，具体数量见 ACCEPTANCE.md。T67 随后在 Node 20.20.2 重新执行 production/full `npm audit --json`，均为 0 vulnerability；旧的 2/16 finding 是先前历史快照。

**T67 受控修订**：原“不得整体升级 Vitest/Vite 生态”仅适用于为解决原
coverage peer 冲突而进行的无证据升级，不能要求将已验证的当前安全兼容组合降级。
本轮当前树已使用 `Vitest`/`@vitest/coverage-v8` 4.1.11、`ECharts` 6.1.0、
`vue-echarts` 8.3.0 与 `monaco-editor` 0.56.0；这是一项针对依赖安全、Node
引擎兼容性和测试运行时的具名修订，而不是对未来大范围升级的默认授权。
该修订的验收仍要求 clean install、Node 20 typecheck、全量 Vitest、production
build、manifest bundle gate、Node engine guard 和 npm audit；其实际结果记录在
`ACCEPTANCE.md` T66/T67。Vite 主版本未在本修订中被升级。

## CQ-200-02：Ruff 格式门禁

**问题**：格式检查命中 provider_contracts.py、export_ths_to_stock_data.py 和 test_market_instrument_freshness.py。

**要求**：仅格式化上述三个文件，不对仓库其他文件批量重排。

**验收**：三个文件通过 ruff format --check，并通过本轮触及后端文件的 ruff check。

## CQ-200-03：THS 时钟可调用类型

**问题**：限流器构造参数把可注入时钟标为 object，内部调用产生 Mypy operator 错误。

**要求**：时钟参数和内部字段使用 Callable[[], float] 类型，默认仍使用 time.monotonic，不改变限流和熔断行为。

**验收**：精确 Mypy 范围无该类型错误；fixture 测试覆盖注入时钟对熔断恢复时间的控制。

## CQ-200-04：服务包导出注解

**问题**：strategy、optimization、live_trading、gateway、backtest、akshare 六个包的 __all__ 空列表未标注类型。

**要求**：将六处声明统一注解为 list[str]，不改变导出内容。

**验收**：精确 Mypy 范围中六个包初始化文件不再报告该错误。

## CQ-200-05：expected manifest 类型契约

**问题**：B2 selector 对外接受 Iterable[str] | None，但 completeness helper 错把输入收窄为 frozenset[str] | None，与 selector 的公开注解不一致。

**要求**：保留 selector 接受 Iterable 的契约；helper 接受 Iterable 并在入口通过现有归一化函数转换为 frozenset。保留去重拒绝、大小上限和 fail-closed 行为。不得改动独立的 query-service helper。

**验收**：精确 Mypy 范围通过；多记录完整性 fixture 测试通过。

## CQ-200-06：全量 Mypy 历史积压

**基线**：本次修改前，全量 mypy app 检查 625 个源文件，在 188 个文件中报告 1120 个错误。

**要求**：在迭代文档保留该基线和各批次全量门禁快照，并按最新全量运行更新当前门禁状态。不得以局部修复宣称全项目 Mypy 通过，也不得通过关闭规则、忽略错误或排除模块降低错误数。

**验收状态**：历史基线为 1120 errors / 188 files（扫描 625 个源文件）；T1/T2/T3/T4 后分别为 1072/168、1027/145、984/143、929/140；T5 后为 849/136；T6 后为 789/135；T7 后为 662/129；T8 后为 625/131；T9 后为 615/128；T10 后为 581/127；T11 后为 556/126；T12 后为 536/125；T13 后为 516/124；T14 后复验为 498 errors / 123 files（均为 625 checked，退出码 1）。以上为 T14 阶段的历史观测，当时状态为 FAIL / NO-GO；当前状态见本节末尾 T62/T63/T64/T67/T68。

**T15 更新**：认证服务局部扫描由 9 errors 收敛到 0；完整 `mypy app` 随后扫描 625 个源文件并报告 489 errors / 122 files（退出码 1）。目标 `app/services/auth_service.py` 已不在完整错误清单，但 CQ-200-06 仍为 FAIL / NO-GO。

**T16 更新**：告警评估服务局部扫描由 6 errors 收敛到 0；完整 `mypy app` 随后扫描 625 个源文件并报告 483 errors / 121 files（退出码 1）。目标 `app/services/alert_evaluation.py` 已不在完整错误清单，但 CQ-200-06 仍为 FAIL / NO-GO。

**T17 更新**：动态 `app.services.backtest_service` shim 的静态入口由 sibling stub 精确导出 `BacktestService`；此前 11 条 `[attr-defined]` 误报已消失。完整 `mypy app` 随后扫描 625 个源文件并报告 486 errors / 120 files（退出码 1）：stub 同时暴露了 14 条真实调用契约错误（12 条比较服务可空结果、1 条优化服务可空失败结果、1 条增强回测请求 schema 不兼容），所以不得以少一个报错文件或目标误报消失宣称全局净改善。CQ-200-06 仍为 FAIL / NO-GO。

**T18 更新**：比较服务将每个输入位置的回测结果读取、`None` 验证与 payload 构造合并为单循环，消除了 12 条可空结果错误；完整 `mypy app` 随后为 474 errors / 120 files（625 checked，退出码 1）。去除行号后与 T17 错误清单的差异仅为这 12 条，仍不得以局部通过替代 CQ-200-06 的 FAIL / NO-GO。

**T19 更新**：参数优化等待器的初始和轮询 FAILED 分支统一处理缺失回测结果，消除了 1 条可空结果错误；完整 `mypy app` 随后为 473 errors / 120 files（625 checked，退出码 1）。去除行号后与 T18 错误清单的差异仅为该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T20 更新**：动态 `app.services.strategy_service` shim 的 sibling stub 精确转发 8 个 canonical public exports，20 条 `[attr-defined]` 误报均消失；完整 `mypy app` 随后为 453 errors / 116 files（625 checked，退出码 1）。去除行号后与 T19 清单比较无新增诊断，CQ-200-06 仍为 FAIL / NO-GO。

**T21 更新**：增强回测路由在既有 client-controlled `runtime_dir` 拒绝之后，将增强请求显式验证为基础 `app.schemas.backtest.BacktestRequest` 再交给 `BacktestService`；目标 `[arg-type]` 错误消失。完整 `mypy app` 随后为 452 errors / 115 files（625 checked，退出码 1）；去除行号后与 T20 清单比较仅移除该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T22 更新**：分析服务月度复利累计值和 MA 前置结果列表改为精确数值类型，2 条局部推断错误消失。完整 `mypy app` 随后为 450 errors / 114 files（625 checked，退出码 1）；去除行号后与 T21 清单比较仅移除该两条错误，CQ-200-06 仍为 FAIL / NO-GO。

**T23 更新**：日志查询参数脱敏容器改为精确的 string/list 值联合类型，1 条局部推断错误消失。完整 `mypy app` 随后为 449 errors / 113 files（625 checked，退出码 1）；去除行号后与 T22 清单比较仅移除该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T24 更新**：版本参数 diff 的四分类 local container 改为显式返回结构类型，1 条局部推断错误消失。完整 `mypy app` 随后为 448 errors / 112 files（625 checked，退出码 1）；去除行号后与 T23 清单比较仅移除该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T25 更新**：监控规则创建服务的 description 签名与 nullable schema/model 对齐，1 条 API `[arg-type]` 错误消失。完整 `mypy app` 随后为 447 errors / 111 files（625 checked，退出码 1）；去除行号后与 T24 清单比较仅移除该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T26 更新**：市场数据授权 helper 的 principal 返回类型从 object 收紧为 `MarketDataPrincipal`，1 条访问上下文 `[arg-type]` 错误消失。完整 `mypy app` 随后为 446 errors / 110 files（625 checked，退出码 1）；去除行号后与 T25 清单比较仅移除该错误，CQ-200-06 仍为 FAIL / NO-GO。

**T62/T63/T64/T67/T68 最终状态**：T62/T63 的 base Conda 新缓存扫描当时输出 `Success: no issues found in 625 source files`，作为历史本地复验保留。T64 在本地使用与 CI 锁定版本相同的 Mypy 1.20.2（临时 target + base Conda `PYTHONPATH`），在新隔离缓存中得到 0/625 并经 `ALLOW_BASELINE_UPDATE=1` 将 `mypy_app_baseline.json` 的 `baseline_errors` 设为 0。T67 在新的隔离缓存中再次得到 `Success: no issues found in 630 source files`，常规 ratchet 输出 `errors=0 baseline=0 delta=+0`；T68 以同一固定版本和新的临时缓存独立复验相同结果，并完成最终本地非性能后端回归 `7859 passed, 123 skipped, 24 deselected` 且无 warning summary。历史 T1–T61 的失败结果保留作追溯，不作为当前状态；没有运行 CI workflow。此静态检查和本地回归不构成生产、数据库、网络、行情、供应商或交易系统验收。

## CQ-200-07：DOMPurify 测试环境兼容性

**复现事实**：支持的 Node 24.2.0 下，四个 Markdown 相关 Vitest 文件复现 9 个失败。最小探针确认 DOMPurify 3.4.15 在 happy-dom 中依赖的 Node.prototype.nodeName 语义不兼容，导致允许标签被误移除，且删除首个节点后遍历可能停止。

**要求**：把 jsdom ^27.0.0 加为直接 devDependency。在 markdown-sanitizer、StockAnalysisPage、ChatMessageBubble、StrategyDetailDialog 四个测试文件顶部添加官方 Vitest file-level jsdom 指令，并说明隔离原因。只改变这四个文件的测试环境；其余前端测试继续使用全局 happy-dom。

**安全边界**：不修改或升级生产 DOMPurify/marked，不改生产清洗逻辑，不全局切换 Vitest 环境，不跳过或抑制测试。jsdom 只提供受影响测试的 DOM 实现。

**验收**：Node 24.2.0 下 npm ci、lint、typecheck 通过；四个指定测试文件的 35 个测试通过，全量 Vitest 154 个文件、1687 个测试通过。StrategyDetailDialog 的 Monaco 导入问题由 CQ-200-08 的测试模块级 mock 解决；不修改生产代码。全量 Mypy 仍为 FAIL / NO-GO；最新记录的 npm audit 为全量 16 项（production 2 项、dev-only 14 项），详见 ACCEPTANCE.md。

## CQ-200-08：非被测 Monaco 模块导入隔离

**问题**：StrategyDetailDialog 测试原来在 mount 时通过 `global.stubs.MonacoEditor` 替身，但 Vitest 在执行 mount 之前已经加载 SFC 及其静态 MonacoEditor.vue 依赖。jsdom 因而仍执行 monaco-editor 初始化，报 `document.queryCommandSupported is not a function`，mount-level stub 无法阻止该导入。

**要求**：在 StrategyDetailDialog 测试模块中使用 Vitest hoist 的模块级 `vi.mock('@/components/common/MonacoEditor.vue', ...)`，使测试替身在 SFC 加载前生效；移除冗余的 mount-level MonacoEditor stub，保留通用 Element stubs。该文件仍使用 CQ-200-07 的 file-level jsdom 环境以验证 Markdown 清洗。

**安全与范围边界**：仅隔离非被测 MonacoEditor 模块；不修改 Monaco、StrategyDetailDialog 或 Markdown 生产代码，不在 shared setup 增加 `document.queryCommandSupported` polyfill，不修改 DOMPurify/marked，不切换 Vitest 全局环境，不跳过测试。

**验收**：Node 24.2.0 下 StrategyDetailDialog 单文件 1/1 通过；四个 Markdown 相关文件 4/4、35/35 通过；全量 Vitest 154/154 文件、1687/1687 测试通过；lint 与 typecheck 通过。详见 ACCEPTANCE.md。CQ-200-06 的全量 Mypy FAIL / NO-GO 和当前 16 项未解决 npm audit 漏洞维持开放。

## CQ-200-10：AkShare data-fetch consumer 类型合同

**问题**：T3 显性化的 MySQL connection/cursor Optional 状态、驱动 row/description 形状，以及 `save_data` 的 `int | Literal[False]` 合同，在 Akshare consumer 中留下 55 条精确 Mypy 错误；requests probe 将 `dict[str, object]` 直接展开到 `Session.get`，与 requests 的参数类型不符。

**要求**：仅修复 `akshare_to_mysql.py`、`akshare_provider.py`、`akshare_network_proxy.py` 及直接 fake-based 测试和本迭代文档。对 MySQL 驱动连接/游标使用窄契约或最小运行时守卫，对 requests 参数使用明确的受支持形状；保留 SQL、事务顺序、异常传播和 save_data 成功行数/空数据 False 合同。不得修改 T3 核心、AkShare 外部脚本、Mypy/Ruff 配置、依赖版本或引入 Any/cast(Any)/type: ignore。

**验收**：三文件精确 Mypy 从 55 errors 收敛到 0；改动文件 Ruff check/format 通过；定向 fake-only tests 通过。禁止连接真实 MySQL、调用 AkShare 或发出网络请求；随后刷新一次全量 Mypy 并记录仍开放的 FAIL / NO-GO 状态。

## CQ-200-11：股票分析任务 ORM 实例字段类型契约

**问题**：T4 后 `StockAnalysisTaskModel`、报告/导出模型与信号模型仍使用 legacy `Column[...]` class-attribute 声明；实例属性在任务服务调用处被推断为 `Column[Mapped[Any]]`，导致多个真实 Mypy 错误。`ChatMessage.metadata_json` 作为兼容报告写入路径上的唯一剩余字段也有同类问题。

**要求**：仅将 `stock_analysis.py`、`stock_signal.py` 的 ORM 字段迁移为精确 `Mapped[...]`/`mapped_column(...)` 类型，并修复 `stock_analysis/tasks.py` 的静态类型错误；经单独批准，允许仅把 `knowledge_base.py` 的 `ChatMessage.metadata_json` 改为 `Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)`。严格保留全部既有数据库表/列名、SQL 类型、nullable/default/onupdate、PK/FK、index/unique/约束语义与业务调用；不修改其他知识库字段、迁移、服务或调用方。JSON 字段用窄且符合真实读写的递归/结构化类型；不以 Any、cast(Any)、ignore 或动态属性绕过类型错误。

**验收**：三个股票分析/信号源文件及经批准的 `knowledge_base.py` 精确 Mypy 为 0；目标 Ruff check/format 通过；直接相关 SQLite/fake 测试通过。对五个受影响股票表的 SQLAlchemy metadata 签名保持不变，并核验 ChatMessage `metadata_json` 仍映射到 JSON 列 `metadata` 且 nullable=True。最后刷新一次全量 Mypy 并记录 FAIL / NO-GO 状态；不连接外部数据库、不调用真实 AI 或网络。

## CQ-200-12：仿真交易 ORM 与服务快照类型契约

**问题**：`paper_trading.py` 的 legacy `Column[...]` 实例字段使 `paper_trading_service.py` 将运行时 ORM 值误推断为列对象；精确扫描初始有 60 条 Mypy 错误，覆盖订单、持仓、账户权益和快照/通知调用边界。

**要求**：仅迁移 `paper_trading.py` 的 SQLAlchemy 2 实例字段，并在 `paper_trading_service.py` 用窄的持仓快照/事件类型消除其真实静态契约错误。必须保留 `paper_trading_accounts`、`paper_trading_positions`、`paper_trading_orders`、`paper_trades` 四张表的全部表列语义、关系和现有现金/保证金/持仓/订单业务计算；兼容现有 Mock/simple-namespace 测试替身。不得改迁移、API/配置、模型以外的生产文件、依赖或静态检查设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：两目标源文件精确 Mypy 为 0，Ruff check/format 通过，现有服务/边界/API 定向测试通过。以 HEAD 与工作区 AST 对比所有 67 个 `Column`/`relationship` 调用参数，必须无缺失、额外或差异；运行时 metadata 必须显示四张表的列、SQL 类型、nullable、PK/FK 与索引保持预期。最后刷新全量 Mypy 并保留 FAIL / NO-GO；不连接真实交易、外部数据库或网络。

## CQ-200-13：市场数据平台 ORM 实例字段类型契约

**问题**：`market_data_platform.py` 中 21 张 `md_*` 表的 220 个 legacy `Column` 声明和 25 个 relationship 使调用方将 ORM 实例误判为 SQL expression。模型自身有 2 条显式 Mypy 错误，`market_data/store.py` 初始有 43 条精确错误，其中列对象传播是主要根因；全量审计中仍有大量同形态错误。

**要求**：仅将 `market_data_platform.py` 全部实例字段与 relationship 迁移为精确 SQLAlchemy 2 映射类型。JSON 字段必须使用能表达实际嵌套内容的递归窄类型；外部模型只通过 `TYPE_CHECKING` 前向引用参与静态注解。严格保留 21 张表的表列、SQL 类型、nullable/default/onupdate、PK/FK/index/unique/约束以及 25 个 relationship 的 target、cascade、order_by、back_populates、passive_deletes/uselist 语义。不得改 store、迁移、服务/API、配置、依赖或测试，不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：模型精确 Mypy 为 0，Ruff check/format 与 `git diff --check` 通过；`test_store.py` 本地回归通过。HEAD/工作区 AST 对比 220 个列调用与 25 个 relationship 调用均无缺失、额外或参数差异；SQLAlchemy metadata/mapper 配置核验 21 tables / 220 columns / 25 relationships，摘要 schema signature SHA-256 保持 `9b5a93f18df29c7b2b364c09691f36a33c442fdb8358a02058e145e7d55761b5`。store 剩余非 ORM 错误需明确记录，不通过扩张范围掩盖。最后刷新全量 Mypy 并保持 FAIL / NO-GO；不运行迁移、真实数据库或外部数据源。

## CQ-200-14：工作空间 ORM 递归 JSON 类型契约

**问题**：`workspace.py` 的 `Workspace` 与 `StrategyUnit` 仍使用 legacy `Column[...]` 声明，实例属性被静态地视为 SQL expression；其 `settings`、`trading_config`、`optimization_config`、`data_config` 与 `metrics_snapshot` 又承载嵌套 JSON，调用方无法区分 mapping、列表和数值。

**要求**：仅把 `workspace.py` 的 39 个列和 3 个 relationship 迁移为精确 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)` 类型，使用递归 `WorkspaceJSONMapping` 表达 JSON 字段。保留两张表的全部表列、SQL 类型、nullable/default/onupdate、PK/FK/index/unique、关系 target/back_populates/cascade 语义；不得修改迁移、服务/API、配置、依赖或静态检查设置，不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：模型精确 Mypy 为 0；HEAD/工作区 AST 对比 39 个列调用和 3 个 relationship 调用无参数差异；mapper 配置核验 2 tables / 39 columns / 3 relationships；相关服务/API 测试 159 passed。模型收紧后直接消费者的错误另由 CQ-200-15 处理；全量 Mypy 仍明确记录 FAIL / NO-GO，不连接真实数据库、外部系统或交易通道。

## CQ-200-15：工作空间 JSON 直接消费者安全收窄

**问题**：CQ-200-14 的递归 JSON 类型准确暴露了 `stock_analysis/tasks.py`、`workspace/optimization.py` 和 `workspace/reports.py` 中 10 条错误：此前直接将未知 JSON 当作字典、日期或数值使用，畸形历史数据可能触发错误或污染聚合。

**要求**：仅在三个直接消费者中使用递归 JSON mapping 守卫和顶层安全拷贝。保存股票分析报告时保留合法旧记录、替换重复 report_id、维持最近 50 条并丢弃非法条目；优化配置保留合法历史项并用有效 JSON 快照更新本次运行字段；报告仅接受字符串日期和有限 int/float 指标，bool、非数值、NaN/Infinity 或错误形状安全忽略。不得弱化 `WorkspaceJSONMapping`，不得改 ORM 模型、迁移、API、配置、依赖或静态检查设置，且不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：三文件精确 Mypy 从 10 errors 到 0；Ruff check/format 与目标 `git diff --check` 通过；本地 fake fixture 覆盖合法配置合并、畸形 JSON/非数值安全退化、合法报告聚合、保存去重/旧记录保留，合计 5 passed。随后刷新完整 Mypy 并保留 FAIL / NO-GO；不连接真实 DB、网络、外部数据或交易系统。

## CQ-200-16：市场数据查询回执与签名 cursor 类型边界

**问题**：`MarketDataStore.persist_provider_result` 的实际返回类型允许 `PersistedProviderFetch | DeferredProviderFetch`，但查询服务协议把它窄化为已可见回执；这样会把无可信 `received_at` 的 staged 回执误当作可读事实。局部读取还将 `dict[str, object]` 展开给具名 Store 参数；签名 cursor 的 JSON 值未在构造 `_CursorBindingDigest` / `MarketDataVisibilityAnchor` 前完成严格运行时收窄，导致 34 条精确 Mypy 错误和隐藏的边界风险。

**要求**：仅修改 `app/services/market_data/query_service.py` 及其直接 fixture 测试。准确表达 Store 回执联合类型；遇到 `DeferredProviderFetch` 必须以稳定错误码失败关闭，且不得构造 fetch、推进 knowledge cutoff / visibility anchor 或重读局部数据；无论异常与否，已获取的精确 fetch lease 必须在既有 `finally` 路径释放。局部读取必须显式传递有类型的具名参数，保留无 allow-list 的 legacy fake Store 兼容性。cursor JSON object、四个必需 scope/policy digest、可选 grant digest 与两个 visibility sequence 都要在使用前收窄；bool、负数、非整数、非字符串或错误 object 形状必须返回 `CURSOR_INVALID`，且在 resolver/local store/provider 工作前拒绝。不得修改 Store、模型、API、迁移、配置、依赖或静态规则，也不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：`query_service.py` 精确 Mypy 从 34 errors 到 0；目标 Ruff check/format、tracked `git diff --check` 和新增 diff 抑制扫描通过。`tests/market_data_platform/test_query_service.py` 69 passed、1 条既有 Backtrader Quandl deprecation warning；测试覆盖 deferred 回执不重新读取/重锚、释放同一 lease，以及八类带有效 HMAC 的错误字段类型在本地读取前返回 `CURSOR_INVALID`。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实 DB、网络、数据供应商或交易系统。

## CQ-200-17：Scanner plan ORM 实例字段类型契约

**问题**：`ScannerPlanModel`、`ScannerPlanRunModel` 使用 legacy `Column[...]` / 未标注 relationship，使 `scanner_plan.py` 中真实 ORM 实例写入和 ID 读取被静态识别为 SQL expression。精确扫描在服务中报告 25 条错误，涉及计划保存/更新、结果表名称、状态更新和时间戳写入。

**要求**：仅将 `app/models/scanner_plan.py` 的两个模型全部字段及两个 relationship 迁移为 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)` 类型。JSON 字段用无 `Any` 的递归 `JSONValue` 表达，保留 list/dict JSON 值；严格保持表名、列名、SQL 类型、nullable、default/onupdate、PK/FK、index、unique、两个 unique constraint、关系 target/back_populates/cascade/order_by 和 FK `ondelete` 语义。不得改服务/API、数据库兼容逻辑、迁移、依赖或静态检查设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：模型与服务的精确 Mypy 从 25 errors 到 0；目标 Ruff check/format、tracked `git diff --check` 和新增 diff 抑制扫描通过。运行时 mapper 必须显示 `scanner_plans` 15 列、`scanner_plan_runs` 17 列、4/5 个既有索引与两个 relationship；既有 scanner-plan API fixture 覆盖日报缓存、计划更新、创建/删除动态结果表和删除计划，2 passed、1 条既有 warning。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实外部数据库、网络或交易系统。

## CQ-200-18：仓位估值数值回退类型契约

**问题**：`safe_float` 的运行时逻辑在 default 省略或提供 float 时始终返回 float，只有显式提供 `None` 才可能返回 `None`；但原注解始终为 `float | None`，使 20 条假阳性沿着费率归一化、entry/current price、notional 与 PnL 计算扩散。

**要求**：仅在 `app/services/position_valuation.py` 为 `safe_float` 增加精确 overload，并新增直接回归测试。省略 default 或传入 float 时静态返回 `float`；传入 `None` 时返回 `float | None`。递归 dict/list 处理必须在 `None` 和 float fallback 分支中保留相同运行时回退，默认值、非法输入处理、费率/保证金/佣金/价格/PnL 计算均不得改变。不得新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、配置豁免或真实外部调用。

**验收**：`position_valuation.py` 精确 Mypy 从 20 errors 到 0；目标 Ruff check/format、tracked/untracked diff whitespace check 与新增 diff 抑制扫描通过。直接回归覆盖 default float、显式 float、`None` fallback、嵌套 dict 和 list 聚合；既有 workspace 估值筛选测试 21 passed。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实数据库、网络或交易系统。

## CQ-200-20：新闻情报 session 与 feed 元数据边界

**问题**：`NewsIntelligenceService` 的构造/工厂有意支持可选 `AsyncSession`，以便 `analyze()` 与 RSS helper 可脱离数据库使用；但持久化方法在检查后仍直接使用可选 `self.db`，形成 17 条静态空值错误。收窄 session 后，legacy ORM 类属性还会把已加载 `NewsSourceModel` 标量误识别为 `Column`。另有一处 feed 解析假定 `metadata_json` 永远是 mapping，历史或异常 JSON 为 list/scalar 时可能在读取 ticker 时失败。

**要求**：仅修改 `app/services/news_intelligence.py` 并新增本地测试。保留构造函数、公开 `db` 属性和工厂的 optional session 契约；持久化路径（含内部计数）必须从 guard 获得非空局部 session，缺失 session 仍抛出 `RuntimeError("database_session_required")`。服务内可用窄 Protocol 描述已加载 ORM 行的实际标量字段，但不得迁移模型、改变 SQL/API 或用 `cast(Any)`/忽略掩盖。feed 元数据必须先收窄为 Mapping，非 Mapping 安全退化为空默认 ticker，Mapping ticker 清理行为保持。不得改配置、依赖或外部连接，也不得新增 `Any`、`type: ignore`、`# noqa`。

**验收**：`news_intelligence.py` 精确 Mypy 从 18 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace check 与新增 diff 抑制扫描通过。新增测试覆盖无 session 的 analyze/RSS helper、持久化 RuntimeError、非 Mapping 元数据降级及 Mapping 默认 ticker；既有新闻 API/classifier fixture 同时通过，共 8 passed、1 条既有 warning。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实数据库、网络或交易系统。

## CQ-200-21：认证 ORM 实例与 logout token ID 边界

**问题**：认证服务从 `SQLRepository` 或 SQLAlchemy query 取得的真实 `User` / `RefreshToken` 实例，其 legacy `Column(...)` 声明会被静态工具错误地当作 SQL expression，导致密码校验、令牌撤销、改密和 response 组装出现 8 条假阳性。另有一条 `logout` 路径直接将解码 JWT payload 中未收窄的 `jti` 传给只接受 `str` 的撤销仓储，异常 payload 可能跨越服务边界。

**要求**：仅修改 `app/services/auth_service.py` 并新增本地 boundary 测试。服务内可以用窄 `Protocol` 描述仓储/SQLAlchemy 已返回 ORM 实例的实际标量字段，且 `cast` 必须仅发生在这些 loaded-instance 边界；不得迁移 ORM 模型、改变 query、持久化、JWT 结构、路由、配置、依赖或数据库 schema，不得使用 `cast(Any)`、新增 `Any`、`type: ignore` 或新的 `# noqa`。登出只在 `jti` 是非空 `str` 时调用 `revoke_refresh_token`；缺失、空或其他类型必须在仓储调用前返回 `False`。

**验收**：`auth_service.py` 精确 Mypy 从 9 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace 检查和新增 diff 抑制扫描通过。新增无数据库 fixture 覆盖缺失、`None`、数字、空字符串和 list `jti` 均不访问撤销方法，以及非空字符串仍走原撤销路径；与 auth-service/refresh-token/JWT fixture 合跑 24 passed、1 条既有 warning，API auth 回归 15 passed、7 条既有 warning。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实数据库、网络或交易系统。

## CQ-200-22：告警规则配置与类型失败关闭边界

**问题**：`alert_evaluation.py` 直接把 legacy `AlertRule` 的 `trigger_type`、`trigger_config` 和 `alert_type` 当作运行时标量，静态工具却看到 `Column`；在 `cross` / `current_value` 分支中，`dict.get` 的可选值还直接进入 `float`。这产生 6 条精确 Mypy 错误，也让 list/scalar 形式的异常 JSON 在调用 `.get()` 时可能抛出异常，而未知 alert type 会落到未收窄的兼容值。

**要求**：仅修改 `app/services/alert_evaluation.py` 并新增本地 boundary 测试。服务内可使用窄 `Protocol` 描述评估边界的真实 AlertRule 标量字段，并且不得使用 `cast(Any)`、新增 `Any`、`type: ignore` 或新的 `# noqa`，不得改 AlertRule 模型、MonitoringService、API、数据库 schema、迁移、配置、依赖或下游服务接口。触发配置必须先验证为 Mapping，并仅保留字符串键后传给既有 helper；非 Mapping 必须在 metric getter 前返回 `False`。cross 和 current_value 的 `None` 必须返回不触发/`None`；未知 alert type 必须返回 `None`，不得继续调用指标服务。

**验收**：`alert_evaluation.py` 精确 Mypy 从 6 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace 检查与新增 diff 抑制扫描通过。新增无数据库 fixture 覆盖非 Mapping 配置不调用 metric getter、cross/current_value 的 `None` 失败关闭、未知 alert type 在服务调用前返回 `None`；与既有告警/异常 fixture 合跑 96 passed、1 条既有 warning。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实数据库、网络、行情或交易系统。

## CQ-200-23：动态回测服务 shim 的静态公开接口

**问题**：`app/services/backtest_service.py` 通过 `sys.modules[__name__] = app.services.backtest.service` 在运行时转发整个模块，行为上可导入 `BacktestService`，但 Mypy 无法解析这种动态替换，导致 11 个直接调用方全部报告不存在该类。

**要求**：仅新增 `app/services/backtest_service.pyi` 与本地运行时身份测试。stub 只能显式导出 canonical `app.services.backtest.service.BacktestService`；不得修改 runtime shim、canonical 回测服务、调用方、Mypy/Ruff 配置、依赖或模块导出运行时语义，不得引入 `Any`、`__getattr__`、wildcard import、`cast(Any)`、`type: ignore` 或新的 `# noqa`。

**验收**：stub 的精确 Mypy 为 0，`app.services.backtest_service` 与 canonical service 模块及其 `BacktestService` 类在运行时保持身份相同；与既有 `test_backtest_service.py` 合跑通过。完整 Mypy 须单独刷新并记录新暴露的调用方错误，不得以 sibling stub 掩盖真实参数或可空性不兼容；全量门禁保持 FAIL / NO-GO，且不连接数据库、网络、行情或交易系统。

## CQ-200-24：比较创建的可空回测结果与一致性快照

**问题**：`BacktestService.get_result()` 的明确返回类型为 `BacktestResult | None`。`create_comparison()` 先在一个循环验证结果，随后在第二个循环重新读取并立即解引用；任务在两次读取之间被删除、失效或不再可访问时，会产生 `None` 属性访问，并导致 12 条静态错误。

**要求**：仅修改 `app/services/comparison_service.py` 与其直接本地测试。对于输入列表的每一个位置，只读取一次回测结果；如果为 `None`，继续抛出原有 `ValueError("Backtest task not found: {task_id}")`；否则立即使用已验证的同一结果构造完整 payload。不得去重或重排 `backtest_task_ids`，不得修改回测服务、Comparison 模型/API/schema、比较指标算法、配置、依赖或静态检查设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：第 78–89 行原 12 条 `[union-attr]` 全部消失；新增 fixture 证明第二次读取即使会返回 `None`，创建仍仅调用一次并成功，原缺失任务失败行为保留。完整 comparison-service fixture、Ruff check/format 与 whitespace/diff 抑制检查通过；完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-25：参数优化 FAILED 结果的受控失败语义

**问题**：参数优化的 `_wait_for_backtest_completion()` 在轮询到 `FAILED` 时直接读取可空 `get_result()` 的 `error_message`，结果已缺失会变成 `AttributeError`；首次 `get_task_status()` 已返回 `FAILED` 时又走不同路径，直接返回结果而不抛统一的失败错误。

**要求**：仅修改 `app/services/param_optimization_service.py` 与其直接本地测试。初始和轮询后的 `FAILED` 都必须抛 `RuntimeError`：存在非空字符串错误信息时保留 `Backtest failed: <message>`，结果缺失或空/None 错误信息时使用固定 `Backtest failed: result unavailable`。不得改变 COMPLETED、CANCELLED、PENDING/RUNNING 或 timeout 路径，且不得改回测服务、优化 API/schema、任务持久化、配置、依赖或静态检查设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：目标 `[union-attr]` 消失；回归覆盖轮询后 FAILED 且结果缺失、初始 FAILED 且有错误消息，既有失败/取消/完成/超时用例继续通过。完整优化 API fixture、Ruff check/format 与 whitespace/diff 抑制检查通过；完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-26：动态策略服务 shim 的静态公开接口

**问题**：`app/services/strategy_service.py` 通过 `sys.modules[__name__] = app.services.strategy.core` 在运行时转发模块。canonical `core.py` 已精确通过 Mypy，但静态工具看不到替换，致使 20 个直接导入点把 8 个公开符号误报为缺失。

**要求**：仅新增 `app/services/strategy_service.pyi` 与本地 runtime identity 测试。stub 必须显式 re-export canonical core 的全部公开 `__all__` 名称：`STRATEGIES_DIR`、`StrategyService`、`build_ai_strategy_draft`、`get_all_strategy_templates`、`get_strategy_dir`、`get_strategy_readme`、`get_template_by_id`、`render_ai_strategy_draft_answer`。不得修改 runtime shim/core/调用方、配置或依赖；不得使用 wildcard import、`Any`、`__getattr__`、`cast(Any)`、`type: ignore` 或新的 `# noqa`。

**验收**：stub 与 canonical core 精确 Mypy 为 0；legacy module 与 core 为同一对象，8 个公开导出全为同一对象；新 shim fixture 加既有策略扫描 fixture 通过。完整 Mypy 须独立刷新、证明 20 条目标误报消失且记录真实新错误；全量门禁保持 FAIL / NO-GO，且不连接数据库、网络、行情或交易系统。

## CQ-200-27：增强回测请求与基础服务契约

**问题**：增强路由的 `app.schemas.backtest_enhanced.BacktestRequest` 与 `BacktestService.run_backtest()` 所需的 `app.schemas.backtest.BacktestRequest` 是两个独立的 Pydantic 模型。增强校验已完成后仍直接把前者传入后者，留下 1 条真实 `[arg-type]` 错误；简单放宽服务签名会让服务层同时承担两个入口模型及其安全语义。

**要求**：仅修改 `app/api/backtest_enhanced.py` 与其直接本地测试。路由必须继续以增强模型接收并验证客户端输入，且必须先保留 `model_fields_set` 对任意 client-provided `runtime_dir`（含 null）的 422 拒绝；仅在该拒绝之后，使用 Pydantic 显式验证/转换为基础服务请求模型，再调用既有服务签名。不得修改两个 schema、BacktestService、路由响应/WebSocket 语义、配置、依赖、数据库 schema 或迁移；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：`backtest_enhanced.py` 精确 Mypy 为 0。使用 FastAPI dependency override 的本地 fixture 必须证明 service 收到基础请求模型且关键字段保持；带 client `runtime_dir` 的请求仍返回既有 422 payload，并在服务调用前被拒绝。完整增强回测 fixture、Ruff check/format 与 whitespace/diff 抑制检查通过；完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-28：分析服务复利与均线结果的精确数值类型

**问题**：`process_monthly_returns()` 的累计值从整数 `1` 开始，随后乘以 float 月收益，Mypy 将变量锁定为 int；`calculate_indicators()` 的均线前置 `[None] * n` 也被推断为 `list[None]`，与函数的 `list[float | None]` 返回合同不符。这两处都不是需要修改计算的运行时问题。

**要求**：仅修改 `app/services/analytics_service.py` 与其直接本地测试。复利累计值必须以精确 float 类型初始化，均线前置列表必须显式为 `list[float | None]`；不得改变复利乘积、`round(..., 6)` 精度、MA 计算/长度、前置 None、空输入和短序列 MA60 为空的语义。不得修改 schema、API、依赖、配置、数据库或迁移；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`analytics_service.py` 精确 Mypy 从 2 errors 收敛到 0；月度复利数值断言和既有 MA fixture 通过，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-29：日志查询参数脱敏容器的联合值类型

**问题**：`parse_qs()` 产生字符串到字符串列表的映射，但 `_sanitize_query_params()` 对敏感键写入遮蔽字符串、对普通单值写入字符串、对普通重复值保留列表。未标注的空 dict 被静态工具错误锁定为字符串值，形成 1 条 `[assignment]`；运行时脱敏/保留行为本身正确。

**要求**：仅修改 `app/middleware/logging.py` 与其直接本地测试。local sanitized dict 必须精确表达 `str | list[str]` 的既有值形态；不得改变 parse_qs 参数、敏感键集合/大小写处理、遮蔽文本、单值/多值格式、空 query 的 None 返回或 `str(dict)` 结果。不得重构中间件调用流程，且不得改 API、配置、依赖、数据库或迁移；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`logging.py` 精确 Mypy 为 0；直接测试证明敏感输入被遮蔽、重复非敏感值保留为 list，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-30：版本参数 diff 四分类容器的精确返回结构

**问题**：`generate_params_diff()` 已声明返回四个分类的 `dict[str, dict[str, Any]]`，但 local 空容器没有注解，Mypy 无法为嵌套空 dict 推断键值类型，留下 1 条 `[var-annotated]`。函数的新增、删除、修改、未变及修改项 `{from, to}` 运行时结构已有测试覆盖。

**要求**：仅修改 `app/services/version_diff_service.py`，直接测试仅在确有缺口时修改。local diff 容器必须显式与既有返回签名及四分类 payload 形状一致；不得改变分类键、参数键遍历、值比较、嵌套 from/to 字段、对外签名、策略版本调用方、API、模型、配置、依赖、数据库或迁移。不得新增 `cast`、`type: ignore` 或 `# noqa`；文件已有 `Any` 只能继续表达既有公开返回合同。

**验收**：`version_diff_service.py` 精确 Mypy 为 0；完整版本 diff fixture、Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-31：监控规则可空 description 的跨层服务契约

**问题**：`AlertRuleCreate.description` 是可选字符串，`AlertRule.description` 数据库列也 nullable，但 `MonitoringService.create_alert_rule()` 错误声明 description 必须为 `str`。API 已在运行时把可选值原样传递，造成 1 条真实 `[arg-type]`，且将 API 层空值替换为空字符串会改变已存在的 nullable 存储/响应语义。

**要求**：仅修改 `app/services/monitoring_service.py` 与直接 API 测试；若 API 实现无需改动则不得改动。服务创建方法的 description 参数必须为 `str | None`，其余创建、通知默认、调度和日志流程不变。客户端省略 description 时，服务应继续收到 `None`，响应也应保持 null；不得修改 schema、AlertRule 模型、数据库/迁移、配置或依赖，不得以 `or ""`、`Any`、`cast`、`type: ignore` 或 `# noqa` 绕过。

**验收**：`app/api/monitoring.py` 精确 Mypy 为 0；完整监控 API fixture 覆盖显式描述与省略描述路径，后者断言 service 参数和 response 均为 None/null；Ruff check/format 与 whitespace/diff 抑制检查通过。服务文件已有无关 Mypy 诊断须单独记录，完整 Mypy 仍 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-32：市场数据授权 principal 类型连续性

**问题**：`MarketDataAccessAuthorizer.principal_for_user()` 的明确返回类型是 `MarketDataPrincipal`，但 API 内 `_authorize_market_data_read()` 把第一个 tuple 元素宽化为 `object`，随后无法满足 `MarketDataQueryAccess(principal=...)` 的契约。该 helper 已经执行 principal 生成和 `require_read_data()`，错误只是静态信息在边界丢失。

**要求**：仅修改 `app/api/data/deps.py` 与直接本地测试。helper 返回注解必须为 `tuple[MarketDataPrincipal, MarketDataAccessAuthorizer]`，且调用 `principal_for_user()`、`require_read_data()`、对 `MarketDataAuthorizationError` 的 HTTP 403 映射和数据库授权器行为都不得改变。不得修改授权器、用户/权限模型、查询服务、路由、配置、依赖、数据库或迁移；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`app/api/data/deps.py` 精确 Mypy 为 0；无数据库 fake authorizer fixture 必须证明同一 principal 经 read check 后进入 `MarketDataQueryAccess`；Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-33：股票研究兼容层 reconciliation payload 容器合同

**问题**：`reconcile_system()` 已将 pairs 声明为 `list[tuple[dict[str, object], dict[str, object]]]`，但含 `narrative: None` 的 legacy local dict 被推断为 `dict[str, str | None]`，无法作为该 tuple 的首项追加。这是局部推断丢失，并不表示已有 legacy/generic 映射或 reconciliation 语义有误。

**要求**：仅修改 `app/services/asset_research/stock_compat.py`；直接测试仅在确有缺口时修改。legacy local dict 必须显式保持与既有 pairs 合同相同的 `dict[str, object]`，不改变 `reference`、`canonical_id`、`cutoff_at`、`recommendation`、`narrative` 的值、generic payload、mapping version、记录顺序或 `reconcile_batch()` 调用。不得修改 stock signal service、schema、模型、API、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`stock_compat.py` 精确 Mypy 从 1 error 收敛到 0；完整本地 stock compatibility fixture、Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-34：主数据 manifest literal 与类别计数键合同

**问题**：`Literal[MASTER_DATA_MANIFEST_VERSION]` 将运行时常量作为 Literal 参数，静态工具无法将其视为有效的 literal type；由 `InstrumentIdentity.asset_type` 推断出的 `Counter[AssetType]` 也不能直接满足结果 DTO 的 `dict[str, int]` 合同。这两条错误均位于既有严格 version 和七类统计行为的静态表达，而非运行时验证/计数缺陷。

**要求**：仅修改 `app/services/market_data/master_data_importer.py`；直接测试仅在确有缺口时修改。必须以实际 `Literal["market-data-master-v1"]` 类型别名描述 version，并将常量保持为同一 wire value；类别计数器必须明确以 `str` 为键，仍基于每个 prepared identity 的原始 asset_type 值计数。不得改变 Pydantic `extra="forbid"`、manifest 校验、导入事务、identity 写入、publication、计数/排序输出、schema、模型、API、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`master_data_importer.py` 精确 Mypy 从 2 errors 收敛到 0；完整本地 master-data importer fixture 必须继续覆盖严格 manifest 和七类资产计数，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-35：缓存单例的 Redis/内存联合合同

**问题**：无注解 `_cache_instance = None` 在首次 Redis 分支赋值后被静态推断为 `RedisCache | None`，随后默认内存分支的 `MemoryCache` 赋值报错。运行时 factory 本来就按 `REDIS_URL` 返回两种实现，错误只是 singleton 的静态状态未完整表达。

**要求**：仅修改 `app/db/cache.py`；直接测试仅在确有缺口时修改。singleton 必须显式为 `RedisCache | MemoryCache | None`，factory 返回必须表达 `RedisCache | MemoryCache`，同时保持首次按 `REDIS_URL` 选择、其后复用相同实例、MemoryCache/RedisCache 方法、惰性 Redis import、配置和错误行为不变。不得修改缓存键/TTL/序列化、调用方、配置、依赖、API、数据库或迁移；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`cache.py` 精确 Mypy 从 1 error 收敛到 0；完整本地 cache 与 cache-extended fixture 必须覆盖默认内存实例和 patched Redis 分支，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实 Redis、数据库、网络、行情或交易系统。

## CQ-200-36：日历 manifest 默认 version 的 literal 合同

**问题**：`MarketDataCalendarManifest.manifest_version` 已要求 `Literal["market-data-calendar-v1"]`，但作为默认值的 `MANIFEST_VERSION` 未显式标注而被推断为一般 `str`，产生 1 条赋值错误。固定 wire value 和 Pydantic 严格行为本身没有运行时缺陷。

**要求**：仅修改 `app/services/market_data/calendar_importer.py`；直接测试仅在确有缺口时修改。`MANIFEST_VERSION` 必须显式为既有 `Literal["market-data-calendar-v1"]` 值，schema 默认值仍使用该常量。不得改变 default wire value、strict model、manifest loader、日期/时区/coverage 验证、导入事务、publication、API、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`calendar_importer.py` 精确 Mypy 从 1 error 收敛到 0；完整本地 calendar importer fixture 必须继续覆盖 manifest 的严格校验和导入路径，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-37：AkShare 数据库引擎 kwargs 的异构值容器

**问题**：`_get_akshare_data_engine()` 的空 `extra_kwargs` 在 MySQL 分支首先写入 `poolclass: NullPool` 后，被静态推断为仅接受 pool class；非 MySQL 分支随后写入 `pool_pre_ping: True` 产生 1 条赋值错误。两个分支及其传给 `create_async_engine()` 的运行时参数早已存在。

**要求**：仅修改 `app/db/akshare_data_database.py`；直接测试仅在确有缺口时修改。local kwargs 容器必须精确容纳现有 poolclass 类型和值为 bool 的 pool_pre_ping，不得改变 URL 解析、MySQL 使用 NullPool、非 MySQL 使用 pool_pre_ping、engine singleton、sessionmaker、配置读取、连接或错误语义。不得修改调用方、API、数据库/迁移、依赖或配置；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`akshare_data_database.py` 精确 Mypy 从 1 error 收敛到 0；完整本地 AkShare management API fixture 在隔离 `PYTHONPYCACHEPREFIX` 下通过，且要记录任何测试基础设施警告，不删除或覆盖既有 pycache。Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实 MySQL、网络、行情或交易系统。

## CQ-200-38：legacy evidence-gate target 的可遍历合同

**问题**：`_assert_isolated_unverified_targets()` 只对 targets 做 for-loop，却将参数声明为 `Sequence`；两个真实调用点传入字典的 `ValuesView`，产生两条 `[arg-type]` 错误。helper 不使用索引、长度或重复遍历，不需要 Sequence 的额外能力。

**要求**：仅修改 `app/services/market_data/legacy_stock_daily_evidence_gate_adapter.py`；直接测试仅在确有缺口时修改。此一个私有 helper 的 targets 参数必须为 `Iterable[LegacyStockDailyCanonicalTarget]`，仍逐一调用既有 `_assert_target_source_binding()`。不得修改 fail-closed 错误、source provenance、read authorization、source batch/permit、store、网络、API、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`legacy_stock_daily_evidence_gate_adapter.py` 精确 Mypy 从 2 errors 收敛到 0；完整隔离 SQLite legacy import adapter harness 通过，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-39：压力测试 scenarios 的协变只读序列合同

**问题**：风险 API 的 Pydantic 请求提供 `list[StressScenario] | None`，但 `StressTestService.run_scenarios()` 将只读 scenarios 参数声明为不变的 `list[dict | StressScenario] | None`，造成 1 条 `[arg-type]`。服务和 `_normalize_scenarios()` 仅遍历输入，不追加、删除、排序或原地修改。

**要求**：仅修改 `app/services/risk_analytics/stress_test.py`；直接测试仅在确有缺口时修改。`run_scenarios()` 和 `_normalize_scenarios()` 的 scenarios 参数必须改为协变 `Sequence[dict | StressScenario] | None`；保留既有 bare dict 运行时输入兼容。不得修改 API、schema、built-in scenario、场景归一化、equity point 处理、损失/回撤/恢复期计算、输出、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`stress_test.py` 与 `api/risk_analytics.py` 联合精确 Mypy 为 0；完整本地 stress-test fixture 必须覆盖 dict service 输入与 API 的已验证 scenarios，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-40：AI 策略改稿元数据的异构值容器

**问题**：`_merge_ai_improvement()` 的 metadata 局部字典先以三个字符串字段初始化；可选 `total_tokens` 存在时又写入整型值，导致静态推断为 `dict[str, str]` 后出现 1 条 `[assignment]`。返回的既有 `StrategyImprovement.metadata` 契约允许工作流元数据使用动态值，本批不调整该公开契约。

**要求**：仅修改 `app/services/research/generation.py`；直接测试仅在确有缺口时修改。该局部 metadata 容器必须标注为 `dict[str, object]`，保留 source、provider、model_id 和可选 total_tokens 的键名、值、写入条件和返回路径。不得修改模型响应解析、参数/代码改稿、回退、工作流、API、schema、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`generation.py` 精确 Mypy 从 1 error 收敛到 0；既有 AI 改稿直接 fixture 必须继续断言 provider/model 和 `total_tokens == 123`，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、模型供应商、行情或交易系统。

## CQ-200-41：日志 fallback 指标序列的缺失值与作用域边界

**问题**：`parse_data_log()` 在无 data.log 的 bar/indicator fallback 中已用 `None` 为后续才出现的指标补齐前序日期，但容器被声明为 `dict[str, list[float]]`；同一函数又在 TSV 分支重新声明同名 `indicators`。这产生 4 条 `[list-item]`、`[assignment]`、`[attr-defined]` 和 `[no-redef]`，并掩盖了输出序列可包含缺失值的既有事实。

**要求**：仅修改 `app/services/log_parser_service.py` 和直接相关 `tests/test_log_parser.py`。bar/indicator fallback 必须使用独立局部容器 `dict[str, list[float | None]]`，仅在该分支内更新/返回它；TSV 分支继续保留纯 float 指标容器。必须保留当前按日期优先、按索引回退的匹配顺序、`None` 前缀补齐、OHLCV/volume 解析与返回 payload。不得将 `None` 改为 0 或过滤，不得修改其他 parser、API、配置、依赖、模型、数据库/迁移；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`log_parser_service.py` 精确 Mypy 从 4 errors 收敛到 0；新增/直接 fixture 必须覆盖两个 bar 日期、首日无指标值、第二日首次出现指标且输出精确为 `[None, 1.16]`。完整三文件日志解析 fixture、Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-42：文件系统回执 SHA-256 的字符串类型守卫

**问题**：文件系统 dataset resolver 的 `_valid_sha256()` 已在运行时以 `isinstance(value, str)` 和规范 SHA-256 校验拒绝非字符串回执 hash，但它仅声明 bool 返回，导致 `_validate_receipt_record()` 在失败关闭后传入 `secrets.compare_digest()` 的 `receipt_hash` 仍被静态视为 `str | Any | None`，产生 1 条 `[type-var]`。

**要求**：仅修改 `app/services/research/filesystem_dataset_resolver.py` 和直接相关 `tests/test_ai_research_filesystem_dataset_resolver.py`。`_valid_sha256(value: object)` 必须以 `TypeGuard[str]` 表达已有的字符串验证；运行时 isinstance、长度/hex 规则、receipt schema、canonical record hash、`compare_digest`、公开错误代码、文件读取/发布、root/权限/路径信任边界均不得改变。测试应保留回执字段集，将 `receipt_hash` 置为非字符串，并经 public resolve 验证 `DATASET_OBJECT_RECEIPT_INVALID` 失败关闭。不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`filesystem_dataset_resolver.py` 精确 Mypy 从 1 error 收敛到 0；完整本地 resolver fixture 必须覆盖真实字节 attestation、替换/篡改/非字符串 hash、FIFO 和 interrupted publication 边界，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、模型供应商、行情或交易系统。

## CQ-200-43：LLM 成对用量计数的严格整数收窄

**问题**：`_verified_token_count()` 对 input/output 和 prompt_tokens/completion_tokens pair 已以 `type(value) is int` 与非负条件拒绝 bool、负数、缺失和其他不可信值，但把两个 `usage.get()` 值放入 tuple 再调用 `sum()`，静态上仍为 `Any | None`，产生 1 条 `[arg-type]`。这一函数直接决定未知用量是否失败关闭并保留配额。

**要求**：仅修改 `app/services/research/llm_gateway.py`；直接测试仅在确有缺口时修改。用私有 `TypeGuard[int]` 或等价的精确静态收窄表达既有严格条件：仅内置 int 且 `>= 0` 可通过，bool 仍必须拒绝；每个 pair 经具名局部值校验后直接相加。不得改变 pair 顺序、total_tokens 一致性、未知用量 `None`、quota settlement、审计/redaction、provider/API、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`llm_gateway.py` 精确 Mypy 从 1 error 收敛到 0；完整 gateway fixture 必须继续验证有效 12/5 pair 结算以及 bool、缺项、负值、总量不一致的 `LLM_PROVIDER_USAGE_UNVERIFIED` 失败关闭，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、模型供应商、行情或交易系统。

## CQ-200-44：holdout journal lease 到期时间的持久化前失败关闭

**问题**：`_require_live_binding()` 已拒绝没有 lease_expires_at 的命令绑定并使用 `HOLDOUT_EXECUTION_PREPARE_DENIED`，但返回 ORM 模型的字段类型仍可空；`prepare()` 将属性直接传入 `_as_utc(datetime)`，产生 1 条 `[arg-type]`。这是一条静态可见性缺口，不能通过假定上游校验永久成立来消除。

**要求**：仅修改 `app/services/research/holdout_execution_journal.py`；直接测试仅在确有缺口时修改。`prepare()` 必须读取具名局部 lease_expires_at，空值时使用同一 `ValueError("HOLDOUT_EXECUTION_PREPARE_DENIED")` 失败关闭，再把已收窄值传给 `_as_utc`。不得修改 `_require_live_binding`、lease 比较、状态转换、并发/幂等、journal 写入、错误码、外部 evaluator/API、schema、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`holdout_execution_journal.py` 精确 Mypy 从 1 error 收敛到 0；完整 journal fixture 必须继续覆盖 prepare 持久化/幂等成功路径与绑定拒绝路径，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、evaluator、行情或交易系统。

## CQ-200-45：投研 run record 的 pipeline 形状收窄

**问题**：`_raw_run_record_needs_freshness_persist()` 对同一 `raw["pipeline"]` 反复读取；条件式里的 `isinstance(..., dict)` 不能把另一次 `raw.get(...)` 读出的 `Any | dict | None` 一并收窄，导致 `pipeline.get(...)` 有 1 条 `[union-attr]`。静态消除不能把任意非字典数据当作可读取 pipeline，也不能改变现有的 freshness 判定。

**要求**：只读取原始 pipeline 一次，并只在它是字典时读取 `current_stage`；缺失、`None` 或任何非字典值必须沿用既有空字典语义。`force=True` 继续无条件返回 `True`；状态非 `live_readiness_expired`、ready 为真、或合法 pipeline 的 `current_stage == "live_candidate"` 仍返回 `True`。不得改变持久化、run record、paper/live handoff、数据库、网络或交易行为。

**验收**：`run_records.py` 精确 Mypy 从 1 error 收敛到 0；直接 fixture 覆盖合法 dict、缺失/`None`/非 dict pipeline 与 `live_candidate` 条件，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、模型供应商、行情或交易系统。

## CQ-200-46：网关合约正数判定的可空值边界

**问题**：`_positive_spec_number()` 已跳过 `None`、空字符串并捕获其他无效数值，但采用 `value in (None, "")` 的组合判断，Mypy 不能确认后续 `float(value)` 已排除 `None`，产生 1 条 `[arg-type]`。不能用宽泛转换或静态豁免掩盖由网关/运行时配置传入的异常值。

**要求**：仅修改 `app/services/gateway/runtime.py`；直接测试仅在确有缺口时新增。以显式 `None` 守卫证明后续转换非空，同时保留空字符串跳过、非法值的 `TypeError`/`ValueError` 安全回退、零/负数不通过和任一后续正数键可通过的既有语义。不得改变 asset spec 选择、网关启动、配置读取、交易、API、模型、数据库/迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`gateway/runtime.py` 精确 Mypy 从 1 error 收敛到 0；直接 fixture 覆盖 None/空字符串、非法、零/负数、正数和候选键 fallback，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实网关、交易、数据库、网络、行情或供应商系统。

## CQ-200-47：自定义因子一元运算的精确分派

**问题**：自定义因子表达式已在 `_validate_node()` 只允许 `ast.UAdd` 和 `ast.USub`，但 `_eval_node()` 经未精确推断的字典值调用一元 operator，产生 1 条 `Cannot call function of unknown type [operator]`。消除该错误不得扩大 AST 许可集合、接受函数调用/属性访问或改变错误表达式的降级结果。

**要求**：仅修改 `app/services/factor_lib/custom.py`，并在 `tests/test_factor_correlation.py` 补充直接回归。正负一元分派必须只作用于已经递归计算出的浮点 operand；`+close`、`-close` 与既有四则/幂运算、记录缺值/算术异常、unsafe expression 的处理保持。不得修改 API、schema、registry、因子计算协议、配置、依赖、数据库/迁移或静态规则；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

**验收**：`custom.py` 精确 Mypy 从 1 error 收敛到 0；完整 factor correlation fixture 继续覆盖安全算术、unsafe expression、认证/API，并新增一元正负回归，Ruff check/format 与 whitespace/diff 抑制检查通过。完整 Mypy 单独刷新并保持 FAIL / NO-GO，不连接真实数据库、网络、行情或交易系统。

## CQ-200-48：动态 live trading manager shim 的静态入口

**问题**：`app.services.live_trading_manager` 在运行时通过 `sys.modules` 指向 canonical `app.services.live_trading.manager`，但没有静态导出；完整 Mypy 因而将 `LiveTradingManager` 和 `get_live_trading_manager` 误报为缺失，当前共有 15 条 `[attr-defined]`。不能通过修改调用方、在 runtime shim 添加动态 `__getattr__` 或掩盖 manager 类型来消除误报。

**要求**：仅新增 `app/services/live_trading_manager.pyi` 及一个 runtime identity fixture。stub 必须精确 re-export canonical `LiveTradingManager` 和 `get_live_trading_manager`，不得改动 `.py` shim、canonical manager、调用方、网关/交易行为、配置、依赖、数据库或迁移；不得新增 `Any`、`__getattr__`、wildcard import、`cast`、`type: ignore` 或 `# noqa`。

**验收**：stub 精确 Mypy 为 0；runtime fixture 证明 legacy module、class 和 factory 与 canonical 对象身份一致；对所有直接 app importers 的静态清单不再存在该 shim 的 `[attr-defined]`。完整 Mypy 单独刷新并逐条比较：15 条 shim 误报的移除与任何新暴露的真实调用合同必须分开记录，完整门禁仍保持 FAIL / NO-GO，不实例化真实 manager、不连接网关、交易、数据库、网络、行情或供应商系统。

## CQ-200-49：live trading 实例只读映射边界

**问题**：T42 的 canonical manager 静态入口揭露 11 条真实合同错误：`InstanceData` 和 `StartResult` 都是运行时字典形状的 `TypedDict`，却被 portfolio/workspace 的只读 snapshot、日志目录、资产规格和状态 helper 声明为可变 `dict[str, Any]`。其中 workspace 的“已在运行”分支取得 `InstanceData`，普通启动分支取得声明为 `StartResult` 的结果，二者都只被读取；唯一需要可变普通字典的现有 `persist_asset_specs()` 会写入其输入的 `params`。

**要求**：仅修改 `app/api/portfolio/api.py`、`app/services/trading_workspace_service.py` 及直接相关测试。面向 manager 返回记录的只读 helper/局部边界必须改为 `Mapping[str, object] | None` 或等价的只读协议，使 `InstanceData`、`StartResult` 和既有 bare dict fake 均可进入，且不把 manager、shim 或调用方退化为 `Any`。workspace 启动路径必须显式以该只读边界承接“已运行实例 / 正常 StartResult / already-running 刷新实例”三条既有路径，不增加 manager 重读、不给真实 manager 新增调用，也不改变状态、snapshot、run_count、gateway 或失败关闭顺序。`persist_asset_specs()` 仍只能接收其现有可变字典合同，故如需调用必须使用局部浅拷贝；unit 的 asset-spec 同步、运行时文件写入和现有 manager 返回对象不得依赖此局部写入来持久化。

不得修改 `live_trading_manager` runtime shim/sibling stub、canonical manager、`app/types/live_trading.py`、asset-info persistence、API/schema、模型、迁移、配置或依赖；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。不得连接真实 gateway、交易、数据库、网络、行情或供应商系统。

**验收**：T42 揭露的 11 条精确 Mypy 诊断必须为 0，且目标文件的其他既有诊断单独保留和记录；直接 fixture 必须覆盖 TypedDict/bare-dict 记录经 snapshot/log 路径的同样结果，以及启动返回记录经既有 snapshot 同步路径的 status/instance id 行为。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T42 标准化差分比较，不以全量仍 FAIL / NO-GO 为局部通过。

**结果（T43）**：两个消费端和直接测试完成最小修改；11 条精确合同诊断为 0，额外清除了 `_source_from_instance()` 同一读边界的 8 条既有 `params` `[union-attr]`。根代理复验 5 项 TypedDict/bare-dict、StartResult、already-running、contract sync/persistence 回归通过（1 条既有 warning）；完整 Mypy 为 403 errors / 90 files，较 T42 原始计数净减 19，标准化差分无新增诊断，仍为 FAIL / NO-GO。

## CQ-200-50：合约元数据的单次读取与浅拷贝边界

**问题**：T43 后 `trading_workspace_service.py` 仍有两条同根的 `[arg-type]`：两个 contract-metadata 同步 helper 均先以 `isinstance(params.get("contract_metadata"), dict)` 判断，再第二次调用 `params.get()` 传入 `dict()`。由于 `params` 的值域仍含动态值，Mypy 不能把第二次读取收窄，报为 `Any | None`。运行时代码本意是“仅当当前 metadata 为字典时创建浅拷贝，否则从空容器开始”，不应以放宽 `_safe_dict()`、注解为 `Any` 或抑制规则来掩盖这一边界。

**要求**：仅修改 `app/services/trading_workspace_service.py` 及其直接本地测试。`_sync_unit_contract_metadata_from_instance()` 与 `_sync_unit_contract_metadata_from_specs()` 必须各自单次读取 `params["contract_metadata"]` 的既有 get 值，仅在该局部值为 `dict` 时创建同样的浅拷贝，否则保留空字典 fallback。不得改变 server-owned 单元拒绝、空输入短路、symbol alias、asset-spec merge/source、changed 判定、`unit.params` 写入时机或两个 helper 的返回语义；不得把该读取移动到共享宽泛 helper。

不得修改 `_safe_dict()`、asset-spec merge/persistence、manager、gateway、API/schema、模型、迁移、配置、依赖或 Mypy/Ruff 设置；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。测试必须为本地 fake/内存对象，禁止连接真实 gateway、交易、数据库、网络、行情或供应商系统。

**验收**：两条精确 `dict()` `[arg-type]` 诊断为 0，目标文件的其他既有 Mypy 诊断须分开记录；直接 fixture 必须分别经 instance metadata 和 asset-spec metadata 路径证明：已有 metadata 的浅拷贝/合并语义、兄弟条目和新字段均保持。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T43 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T44）**：两个 helper 均完成单次局部读取及原有 `dict` 浅拷贝 fallback；instance/spec 的两个直接 fixture 与 3 条相邻启动/metadata 回归共 5 passed、1 条既有 warning。目标文件只剩 5 条非 T44 诊断，两个精确 `dict()` `[arg-type]` 为 0；Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 401 errors / 90 files，较 T43 原始计数减 2，标准化差分无新增（同文本的两条诊断去重后移除 1 个签名），仍为 FAIL / NO-GO。

## CQ-200-51：position-log 最新行状态的异构 tuple 局部变量

**问题**：`trading_workspace_service.py` 与 `api/portfolio/api.py` 各有同构的 `_latest_position_rows()`。它们的三张状态表分别存放四元组（按 side 的 latest row）、三元组（按 symbol 的 flat row）和二元组（按 symbol 的 latest non-flat index/time）；但同一函数作用域重用 `current_flat`、`current` 和 `latest_nonflat` 变量名。Mypy 因函数级局部推断将后三次读取误认为首个 tuple 形状，形成两端各 3 条、共 6 条 `[assignment]`。运行时表和比较逻辑本来就是独立的，不能通过把 tuple 容器退化为 `Any`、宽泛 union 或共享重构来掩盖。

**要求**：仅修改 `app/services/trading_workspace_service.py`、`app/api/portfolio/api.py` 与直接相关本地测试。三个不同 tuple 容器的候选局部变量必须具有独立身份（或等价的精确局部类型），使 Mypy 可保持四元组、三元组、二元组的既有形状。不得改变 `latest_by_key`、`latest_flat_by_key`、`latest_flat_by_symbol`、`latest_nonflat_by_symbol` 的键和值结构，亦不得改变 timestamp/index 比较、同标的 long/short 保留、无方向 flat 清理、方向 flat 仅清理本 side、输出排序或空行过滤。

不得抽取共享 helper、修改方向识别、日志解析、gateway/manager、API/schema、模型、迁移、配置、依赖或 Mypy/Ruff 设置；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。仅运行本地 fixture，不连接真实 gateway、交易、数据库、网络、行情或供应商系统。

**验收**：两端 6 条精确 tuple `[assignment]` 诊断均为 0，其他既有目标文件错误须单独记录；既有直接 fixture 必须继续覆盖双向同标的、Bybit positionIdx 双边、无方向 flat 清理及方向 flat 保留另一边。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T44 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T45）**：两处选择器只分离了三个不同 tuple 状态表的候选局部变量，没有改字典、tuple、比较或输出结构。根代理复验 8 项既有 dual-side、Bybit、flat/directional-flat fixture 为 8 passed、1 条既有 warning；两文件精确 Mypy 只剩 7 条非 T45 错误，6 条目标 `[assignment]` 为 0，Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 395 errors / 90 files，较 T44 原始计数减 6，标准化差分无新增，仍为 FAIL / NO-GO。

## CQ-200-52：portfolio 资产规格持久化的单次 metadata 读取

**问题**：`_persist_source_asset_specs()` 在经过用户/工作区、server-owned 保护及 `_safe_dict(unit.params)` 后，仍以 `isinstance(params.get("contract_metadata"), dict)` 判断再第二次读取给 `dict()`。这与 T44 已关闭的 workspace 根因相同：Mypy 将第二次动态读取视为 `Any | None`，出现一条 `[arg-type]`。运行时设计是只复制当前 metadata 字典再合并解析后的 specs，不能借由修改 persistence、模型或宽泛 helper 来解决。

**要求**：仅修改 `app/api/portfolio/api.py` 与直接相关本地测试。该函数必须将既有 `contract_metadata` get 值保存为单次局部读取，仅在其为 `dict` 时创建相同浅拷贝，否则维持空 metadata fallback。不得改变 user/workspace 查询、server-owned 早退、resolved-specs 遍历、symbol alias、asset-spec merge/source、changed 判定、`unit.params` 写回和事务语义。

不得修改 `_safe_dict()`、asset-spec merge、workspace service、manager/gateway、API/schema、模型、迁移、配置、依赖或 Mypy/Ruff 设置；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。测试只能使用现有本地 SQLite/fake gateway fixture，不连接真实数据库、网关、交易、网络、行情或供应商系统。

**验收**：一条精确 `dict()` `[arg-type]` 诊断为 0，目标文件的其他既有 Mypy 错误须分开记录；现有 gateway asset-spec 持久化 fixture 必须仍验证 unit metadata 的 multiplier/margin/commission 和组合 source。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T45 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T46）**：portfolio persistence path 完成单次 `raw_metadata` 读取与原有 dict 浅拷贝 fallback；本地 SQLite/fake gateway 持久化 fixture 为 1 passed、1 条既有 warning，继续验证 multiplier/margin/commission 和 `stale_local+ctp_gateway` source。目标文件只剩 4 条非 T46 诊断，精确 `dict()` `[arg-type]` 为 0；Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 394 errors / 90 files，较 T45 原始计数减 1、标准化差分无新增，仍为 FAIL / NO-GO。

## CQ-200-53：portfolio equity 策略序列的显式浮点容器

**问题**：`get_portfolio_equity()` 以含空 list 的 comprehension 创建 `strategy_series` 和 `strategy_pnl_series`，但后续只向它们追加 `_safe_round()` 的浮点值。Mypy 在严格局部变量规则下不能从空 list 推断元素类型，产生两条 `[var-annotated]`；运行时数据流、抽样和返回 payload 已经确定，不能依赖 `Any` 或改变响应结构来修复。

**要求**：仅修改 `app/api/portfolio/api.py` 与直接相关本地测试。两个容器必须显式为以实例 ID 为键、浮点列表为值的字典，且初始化 comprehension、每日期序列追加、sampling 重建、strategy output、total equity/pnl/drawdown 计算及空数据响应都不得改变。

不得修改 equity parser、portfolio source、gateway/manager、API/schema、模型、迁移、配置、依赖或 Mypy/Ruff 设置；不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。只运行本地 fake/log fixture，不连接真实数据库、网关、交易、网络、行情或供应商系统。

**验收**：两条精确 `[var-annotated]` 为 0，目标文件其他既有 Mypy 错误须分开记录；既有 equity fixture 必须继续覆盖 running source history 过滤、include-inactive 历史保留、数据曲线和无数据策略。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T46 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T47）**：两个容器均只补充 `dict[str, list[float]]` 注解，初始化 comprehension、`_safe_round()` append、统一采样和 payload 输出均未变。根代理在隔离 pycache 下复验 running-source history、include-inactive 历史、空数据、有数据、intraday datetime 与首日初始现金 6 项 fixture，结果为 6 passed、1 条既有 Backtrader Quandl deprecation warning。目标 `api.py` 只剩两条非 T47 的 `float()` `[arg-type]`，两条 `[var-annotated]` 为 0；Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 392 errors / 90 files（625 checked、退出码 1），相对 T46 原始和标准化清单均净减 2、没有新增诊断，仍为 FAIL / NO-GO。

## CQ-200-54：position-log 方向代码的受控数值转换

**问题**：portfolio 与 workspace 的两个同构方向解析器均在识别完文本 alias 后，对动态日志 `value` 直接执行 `int(float(value))`。运行时原本以 `TypeError`/`ValueError` 回退到 signed size，但 Mypy 仍将输入推导为 `Any | None` 或 `str | Any | None`，各报一条 `[arg-type]`。数值小数文本必须仍可识别为既有代码；无效值不能被默认为 long，也不能改变 Bybit `positionIdx=0`、CTP `PosiDirection`、trade action 或 long/short/flat alias 的优先级。

**范围**：T48 只修改 `src/backend/app/api/portfolio/api.py`、`src/backend/app/services/trading_workspace_service.py`、两个对应的直接测试模块及本迭代文档。每处只以本模块已有 `_safe_float()` 和 NaN 哨兵将转换失败重新落入已有 `ValueError` 分支；不得抽取共享 helper、修改日志解析、position state selection、估值、gateway/manager、API/schema、模型、迁移、配置或依赖。

不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。测试仅使用本地 dict fixture，不连接真实数据库、网关、交易、网络、行情或供应商系统。

**验收**：两条精确 `float()` `[arg-type]` 为 0；两端直接回归须保持 numeric text code、非法 code 的 signed-size fallback 与 Bybit one-way `positionIdx=0`。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T47 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T48）**：两个 parser 都只将 `int(float(value))` 替换为 `int(_safe_float(value, float("nan")))`；文本 alias、原 `except (TypeError, ValueError)`、数字 mapping 和末尾 signed-size fallback 均未变。新增的两端直接 fixture 均覆盖 `positionIdx="2.0"` 映射 short 与 invalid code 对负 size 的 short fallback，并与既有 Bybit one-way/dual-side fixture 合跑为 6 passed、1 条既有 Backtrader Quandl deprecation warning。两文件精确 Mypy 仅余两个非 T48 错误，目标两条 `float()` `[arg-type]` 为 0；Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 390 errors / 90 files（625 checked、退出码 1），相对 T47 原始和标准化清单均净减 2、没有新增诊断，仍为 FAIL / NO-GO。

## CQ-200-55：attested paper runtime anchor 的 JSON 边界

**问题**：`start_units()` 预检 server-attested paper runtime 时，从 `WorkspaceJSONMapping` 的 `unit_settings` 读取 anchor，却把所有 JSON 标量、list、dict 联合直接赋给后续只使用字典的 `paper_runtime_anchor`。Mypy 因此报一条 `[assignment]`。运行时的 `verify_ai_research_paper_runtime_anchor_for_unit()` 已对非 Mapping 返回 `False`，随后路径以 `AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID` 失败关闭；该 fail-closed 行为必须保持，不能因静态修复使非字典 anchor 进入 runtime sync、manager 或启动能力。

**范围**：T49 仅修改 `src/backend/app/services/trading_workspace_service.py`、其直接测试模块和本迭代文档。读取 anchor 后只在其为 `dict` 时赋给既有字典局部变量，否则保持 `None`，并维持同一次 verifier 调用、错误码、后续 re-check、anchor refresh 和 server-attested startup 流程。不得改 provenance verifier、risk gate、manager、runtime sync、模型、API/schema、迁移、配置或依赖。

不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。新增测试必须使用本地 fake manager 和 monkeypatch，验证非 Mapping anchor 在 manager/runtime sync 之前失败关闭；不得连接真实数据库、网关、交易、网络、行情或供应商系统。

**验收**：一条精确 WorkspaceJSON `[assignment]` 为 0；直接 fixture 必须断言非字典 anchor 返回既有 `AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID`，并且不创建实例、不同步运行时。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T48 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T49）**：只增加 `raw_paper_runtime_anchor` 局部读取及 `isinstance(..., dict)` guard；有效 dict 仍赋给原 `paper_runtime_anchor`，其余 JSON 形状保持 `None` 后交给同一 verifier。根代理在隔离 pycache 下运行新的 scalar-anchor fail-closed、既有 live 风控拒绝和普通 paper start 回归，结果为 3 passed、1 条既有 Backtrader Quandl deprecation warning；新 fixture 断言 verifier 收到 `None`、错误码保持 `AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID`、runtime sync 与 `add_instance` 均未调用。目标 service Mypy 为 0；Ruff、format、target whitespace/diff 检查通过。完整 Mypy 为 389 errors / 90 files（625 checked、退出码 1），相对 T48 原始和标准化清单均净减 1、没有新增诊断，仍为 FAIL / NO-GO。

## CQ-200-56：portfolio 候选数值的协议收窄与 fallback

**问题**：`_first_number()` 从动态 row/嵌套 mapping 读取候选值后直接调用 `float(value)`。函数已有行为是：支持直接或嵌套的数值字符串/标准数值对象，保留 `NaN`/Infinity 作为原始 `float()` 结果，并在无效首选键时继续尝试后续键；但 Mypy 将局部值视为 `str | Any | None`，报一条 `[arg-type]`。不能用 `Any`、cast、忽略或把失败值改成零/NaN，因为这会破坏“继续下一候选”的语义。

**范围**：T50 只修改 `src/backend/app/api/portfolio/api.py`、其直接测试模块和本迭代文档。局部变量先收窄为 `object`，只对 `float()` 的既有字符串、buffer 与标准 `SupportsFloat`/`SupportsIndex` 输入协议执行转换；非兼容值继续原有 loop 到下一个 key。保留 nested 字段优先级、string trim/comma removal、异常范围、返回 `float | None` 和所有 portfolio 聚合/position/account 调用方。不得改 `_safe_float()`、数据源、API/schema、模型、manager/gateway、迁移、配置或依赖。

不得新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。直接 fixture 至少覆盖 nested numeric text、invalid-first-key 到 next-key fallback、标准数值协议与 `NaN` 保留；不得连接真实数据库、网关、交易、网络、行情或供应商系统。

**验收**：一条精确 `float()` `[arg-type]` 为 0，目标文件 Mypy 为 0；direct fixture 保持 nested/trim/comma、fallback、numeric protocol 与 NaN 语义，且一个既有 portfolio position/account fixture继续通过。Ruff check/format、whitespace/diff 抑制检查通过；随后完整 Mypy 单独刷新并与 T49 标准化清单比较，完整门禁继续保持 FAIL / NO-GO。

**结果（T50）**：候选值收窄为 `object` 局部注解（nested 候选为 `object | None`），新增 `_is_float_input()` TypeGuard 仅放行 `float()` 的既有输入协议（str/bytes/bytearray/memoryview/`SupportsFloat`/`SupportsIndex`）；非协议值继续下一候选键，与旧 `float()` TypeError 路径运行时等价，`(TypeError, ValueError)` 捕获、nested 字段优先级、string trim/逗号移除、NaN/Infinity 保留、返回 `float | None` 和全部调用方未改。目标文件精确 Mypy 为 0（含本条 `float()` `[arg-type]`）；直接 fixture 由本工作区已建立的三项 `_first_number` 回归承担，完整 portfolio fixture 为 129 passed、1 条既有 Backtrader Quandl warning；Ruff check/format、tracked `git diff --check` 与 diff 抑制扫描通过（新增 hunk 无 `Any`、`cast`、`type: ignore`、`# noqa`）。完整 Mypy 为 388 errors / 89 files（625 checked、退出码 1）：较 T49 的 389/90 恰减 1 条错误、1 个报错文件，`api/portfolio/api.py` 退出完整错误清单，仍 FAIL / NO-GO。

## CQ-200-57：告警 ORM 实例字段与监控服务边界

**问题**：`app/models/alerts.py` 的 Alert（26 列/7 关系）、AlertRule（15 列/2 关系）、AlertNotification（8 列/1 关系）仍使用 legacy `Column[...]` 声明，使 `monitoring_service.py` 将已加载实例标量误判为 SQL expression，形成 T25 挂账的 15 条错误（10 条 `Column[...]` 误推断、2 条 filters 容器、1 条 `AlertRule | None` 可空边界、2 条 bool 赋值）。模型收紧同时揭露两处真实运行时缺陷：`_send_websocket_alert` 对 str 属性访问 `.value` 必然 `AttributeError`；webhook url 为非字符串时 `urllib.request.Request(url=...)` 在 try 块外崩溃，违反该方法自身声明的 fire-and-forget 契约。

**要求**：仅将 `app/models/alerts.py` 三模型全部列与关系迁移为 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)` 类型；JSON 字段用无 `Any` 的递归 `JSONValue`（`trigger_config: dict[str, JSONValue]`、`notification_channels: list[JSONValue]`、`details: JSONValue | None`），外部模型仅经 `TYPE_CHECKING` 前向引用参与注解。严格保留三张表的表/列名、SQL 类型、nullable/default/onupdate、PK/FK/index 与全部关系 target/back_populates/backref 语义。`monitoring_service.py` 仅做：显式 `AlertRule | None` 守卫（与原 getattr 短路运行时等价）、两处 filters 的 `str | bool` 容器注解、webhook url/headers 单次局部读取加 str/dict 收窄（非字符串 url 归一为 None 并走既有 "missing webhook url" 失败关闭记录）、以及 `_send_websocket_alert` 改为直接使用 str 属性值。不得改迁移、API/schema、配置、依赖或静态检查设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：两文件精确 Mypy 为 0；HEAD/工作区 AST 对比 59 个列/关系调用参数无差异；mapper 核验 3 tables（alerts 26 列、alert_rules 15 列、alert_notifications 8 列，声明关系 10）；定向测试（monitoring API/service、alert evaluation 与既有告警 fixture）通过；随后刷新完整 Mypy 并保留 FAIL / NO-GO；不连接真实数据库、网络、行情或交易系统。

**结果（T51）**：三模型迁移与 15 条错误清除完成；AST 对比 59 声明零差异，mapper 核验通过（含独立审查揭露并修正的 5 个时间戳列 nullable 推导翻转：`created_at`/`updated_at` 按 T8 workspace 先例改为 `Mapped[datetime | None]`，与 HEAD legacy 默认及 alembic baseline 的 nullable=True 一致，三处 `.isoformat()` 消费点同步加等价守卫），两文件精确 Mypy 为 0，Ruff check/format、tracked `git diff --check` 与 diff 抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。定向测试六个 monitoring/alert fixture 文件合跑 198 passed、7 条既有 warning。完整 Mypy 为 373 errors / 88 files（625 checked、退出码 1）：标准化差分恰移除 monitoring_service 15 条、新增 0 条，其它 alerts 模型消费者（`paper_runtime_service`、`risk_control`、`alert_evaluation`）无新增诊断；仍 FAIL / NO-GO。残余观察（HEAD 既有，非本批引入）：`_send_webhook` payload 的 `str(alert.alert_type)` 在同 session 命中 identity map 的 enum 成员时产出 `"AlertType.ACCOUNT"` 形态字符串，择机另行处理。

## CQ-200-58：比较 ORM 实例字段与比较服务容器边界

**问题**：`app/models/comparison.py` 的 Comparison（11 列/3 关系）与 ComparisonShare（5 列/2 关系）使用 legacy `Column[...]` 声明；`comparison_service.py` 留有 T18 挂账的 18 条错误：四个比较容器与 `best_metrics`/`filters`/`update_dict` 的嵌套字面量推断（var-annotated ×4、dict-item ×7、assignment ×4、index ×1）、1 条 `Column[str]` 误推断，以及 update 后 `Comparison | None` 直接传入 `_to_response` 的真实可空边界（update 失效时必然 AttributeError）。

**要求**：仅将 `app/models/comparison.py` 两模型迁移为 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)`；`backtest_task_ids` 为 `list[str]`（与既有 schema `list[str]` 合同一致）、`comparison_data` 为 `dict[str, JSONValue]`、时间戳按 T8/T51 先例为 `Mapped[datetime | None]`；association table 的 `Column` 声明保持原样。服务侧仅做局部容器注解（四个比较容器与各自既有 `-> dict[str, Any]` 返回签名一致，文件已有 `Any` 按既有合同继续表达）、`best_metrics` 的 `str | float | None` 联合、`filters: dict[str, str | bool]`、`update_dict: dict[str, object]`，以及 update 后的显式 `None` 守卫（返回 None 失败关闭）。不得改比较算法、payload 字段、schema、API、迁移、配置、依赖或静态检查设置；不得以 `cast`、`type: ignore` 或 `# noqa` 绕过。

**验收**：两文件精确 Mypy 为 0；AST 对比 16 列 + 5 关系调用参数与 HEAD 无差异；mapper 核验含时间戳 nullable；定向测试（comparison service/api fixture）通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T52）**：迁移与 18 条清除完成；AST 对比 21 声明零差异，mapper 核验 backtest_comparisons 11 列/3 关系、comparison_shares 5 列/2 关系且时间戳 nullable 保持，两文件精确 Mypy 为 0，Ruff check/format、tracked `git diff --check` 通过（新增行无 `cast`/`type: ignore`/`# noqa`；新增的 4 处 `dict[str, Any]` 局部注解与各自既有返回签名一致，按 T24 先例口径记录）。定向测试 `test_comparison_service.py` 30 passed、`test_comparison.py` + `test_comparison_api.py` 54 passed（1 条既有 warning）。完整 Mypy 为 355 errors / 87 files（625 checked、退出码 1）：标准化差分恰移除 comparison_service 18 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-59：AkShare 管理 ORM 实例字段与脚本服务边界

**问题**：`app/models/akshare_mgmt.py` 七模型（105 列 + 9 关系）使用 legacy `Column[...]` 声明，模型自身 5 条 Enum 列 var-annotated；`akshare/script.py` 17 条（含 `_script_timeout_seconds` 的 `Any | None`/`str | None` 传参、约 1100 行 `safe_defaults` 巨型字面量值域退化为 object、legacy 表名二次调用）；`execution.py`/`scheduler_service.py`/`api/akshare/tables.py` 8 条与 `data_connectors/registry.py` 引用 `DataInterface` 的 2 条同根因误推断。

**要求**：仅将 `akshare_mgmt.py` 七模型迁移为 SQLAlchemy 2 精确映射，保留五个 `Enum(..., values_callable=_enum_values)` 列参数、`metadata_json` 显式列名 "metadata"、全部显式 nullable kwarg 与关系语义；JSON 列按语义用 `JSONValue` 递归类型表达。`script.py` 仅做四处修复：timeout helper 显式属性访问与 getenv 链等价重写、`safe_defaults` 精确注解、legacy 表名单次调用复用加 fail-closed 双 None 条件。不得改 AkShare 数据流、脚本执行、调度语义、schema、API、迁移、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：模型与四个直接消费者精确 Mypy 为 0；AST 对比 114 声明零差异；mapper 核验含 Enum/nullable 探针；akshare 定向测试通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T53）**：迁移与 30 条预期 + registry 2 条同根因连带清除完成；AST 对比 114 声明零差异，mapper 核验 7 tables/105 列/9 关系且 Enum 类型、nullable、显式列名探针通过。五文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。`safe_defaults` 的 `dict[str, dict[str, str | int | list[str]]]` 注解经 Mypy 反向验证全量条目并揭露既有 list 值；legacy 守卫经独立审查证实加固的是不可达路径（`normalize_existing_table_name` 不返回空串），并消除旧代码可能静默同步 "data" 错表的隐患。akshare 定向测试六文件合跑 178 passed、79 skipped（既有）、1 条既有 warning；独立审查代理复核 PASS、未发现缺陷。完整 Mypy 为 323 errors / 82 files（625 checked、退出码 1）：标准化差分移除 32 条 errors、新增 0 条；仍 FAIL / NO-GO。`market_data/akshare_provider.py` 的 2 条（契约 dataclass 元组值、BaseException 参数）与本模型族无关，保留为后续批次。

## CQ-200-60：live trading 执行器异步上下文与动态属性边界

**问题**：`live_trading/execution.py` 的 `_optional_lock()` 声明返回同步 `AbstractContextManager`，而全部六个调用点以 `async with` 使用，产生 12 条 `__aenter__`/`__aexit__` 误报；三个 `_bt_*` 子进程日志句柄以点号赋值写入 `asyncio.subprocess.Process` 动态属性（读取侧经 `__dict__.get` 动态清理），产生 3 条 attr-defined；`_merge_runtime_contract_metadata` 对 `source.get("params")` 二次读取无法收窄，产生 1 条 union-attr。

**要求**：仅修改 `app/services/live_trading/execution.py`。锁 helper 返回注解改为 `AbstractAsyncContextManager`（`nullcontext` 于 Python 3.10+ 实现异步协议，须以运行时探针与 `--python-version 3.10` 的 Mypy 双重验证）；动态句柄写入改为与读取侧对称的 `__dict__` 直写（语义与点号赋值严格等价，且不得以 `setattr` 常量属性触发 Ruff B010 或新增 `# noqa`）；二次 `get` 改单次局部读取收窄。不得改锁语义、子进程启动/清理流程、contract metadata 合并、API/schema、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：目标文件精确 Mypy 为 0；live_trading 定向测试通过；Ruff check/format 与 whitespace 检查通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T54）**：三处修复完成；`async with nullcontext()` 在运行时 3.11 与 Mypy `--python-version 3.10` 探针双重验证通过，`__dict__` 直写通过 Ruff B010 门禁。目标文件精确 Mypy 为 0；live_trading 定向测试七文件合跑 208 passed、1 条既有 Backtrader Quandl warning；Ruff check/format、tracked `git diff --check` 通过（`_optional_lock` 签名行的 `Any` 为既有参数化）。完整 Mypy 为 307 errors / 81 files（625 checked、退出码 1）：error 级标准化差分恰移除 16 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-61：数据治理 ORM 实例字段与连接器注册表边界

**问题**：`app/models/data_governance.py` 八模型（78 列 + 13 关系）使用 legacy `Column[...]` 声明，模型自身 2 条错误；`data_connectors/registry.py` 14 条，其中 12 条为 Dg 模型误推断（含以 `provider.provider_id` 列对象误判为 dict 键类型的种子循环）、2 条为 `Row` 到 `tuple` 的返回合同不匹配、种子字面量值域退化为 object；`bootstrap.py` 2 条与 `quant_tools_runtime.py` 1 条为同根因连带。模型收紧在 `market_data/store.py` 暴露 provenance/authorization 两个自由 JSON 容器的窄化联合（`Sequence[str]`）与下游 `Mapping[str, object]` 合同不匹配。

**要求**：仅将 `data_governance.py` 八模型迁移为 SQLAlchemy 2 精确映射（时间戳显式 nullable=False 保持、`Enum(DgJobStatus)` 既有存储语义保持、JSON 列按 default 语义、跨模型 `TYPE_CHECKING` 前向引用）；registry.py 仅做 `tuple(row)` 返回适配、种子字面量精确注解与 provider_id isinstance 收窄；store.py 仅对暴露的两个容器补与下游合同一致的 `dict[str, object]` 注解。不得改种子内容、preview/job 流程、provenance/authorization 载荷字段、schema、API、迁移、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：模型与 registry 精确 Mypy 为 0；AST 对比 91 声明零差异；mapper 核验含时间戳 nullable；定向测试（data governance compat 与 market_data catalog/research_binding/legacy_contract/store）通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T55）**：迁移与 20 条清除完成（registry 14、模型 2、bootstrap 2 连带、quant_tools_runtime 1 连带、store 1 条模型收紧暴露后当场修复）；AST 对比 91 声明零差异，mapper 核验 8 tables/78 列且时间戳 nullable=False 保持。三文件精确 Mypy 为 0（store.py 剩余为 T7 挂账非 ORM 错误，另行处理）；Ruff check/format、tracked `git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。定向测试五文件合跑 148 passed、20 条既有 warning。完整 Mypy 为 287 errors / 79 files（625 checked、退出码 1）：error 级标准化差分恰移除 20 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-62：市场数据存储 T7 挂账非 ORM 边界

**问题**：`market_data/store.py` 自 T7 迁移模型后留有挂账的非 ORM 错误（T55 后剩 8 条）：B2 完整性证据的可空哈希清单、deferred legacy 的可空观测时间与发布序列、registry 授权断言对 object 值的直接迭代、semantic record key 的可空 dimensions、shared payload 引用对联合结构的属性访问、calendar 选择元组列表的联合赋值。

**要求**：仅修改 `app/services/market_data/store.py`。可空输入必须按各函数既有错误码失败关闭（B2CompletenessEvidenceError→`B2_COMPLETENESS_EVIDENCE_INTEGRITY`、`LOCAL_OBSERVATION_INTEGRITY`、`DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY`、`SOURCE_AUTHORIZATION_INVALID`）；`_stored_utc` 的 None 早退须与其内部行为完全等价；dimensions 非 Mapping 经 ValueError 走既有 except 路径；shared payload 用单次局部读取并保持 `_get_or_create` 的 None-入-None-出契约；calendar 元组列表用显式联合注解（CQ-200-51 模式）。不得改 B2 证据协议、deferred legacy 发布流程、授权断言语义、semantic key 规范、calendar 组合算法、schema、API、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：目标文件精确 Mypy 为 0；market_data_platform 全套定向测试通过；Ruff check/format 与 whitespace 检查通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T56）**：8 条清除完成（`visibility_sequence` 与授权容器两处为显式失败关闭的行为收紧，其余为等价守卫或纯静态表达）；目标文件精确 Mypy 为 0。market_data_platform 全套定向测试（62 个文件）1254 passed、137 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 279 errors / 78 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-63：db 基础设施泛型仓库与引擎边界的静态表达

**问题**：`app/db/sql_repository.py` 的 `T` 无 bound，七处 `self.model_class.id` 报 `type[T]` 属性缺失；四处 `Result.rowcount` 在 sqlalchemy 类型上仅 `CursorResult` 具备。`app/db/database.py` 的 engine `extra_kwargs` 局部容器值域退化（T31 同根因）、六处 `__table__.create` 因 `FromClause` 静态宽类型报缺失、`get_db` 为 async generator 却注解 `AsyncSession`。

**要求**：仅修改两文件。rowcount 以单点 helper 的 `CursorResult` isinstance 收窄表达（None/不可用归 0 与原语义等价）；`id` 访问收敛为单点 helper 的 `__dict__` 直接映射访问（模型均直接声明 `id`；不得以 `getattr` 常量形态触发 B009 或以 Protocol bound 破坏泛型兼容）；`extra_kwargs` 按 T31 先例注解；`__table__.create` 收敛为单点 isinstance 收窄 helper；`get_db` 注解修正为 `AsyncGenerator`。不得改仓库语义、DML 行为、建表/索引流程、会话生命周期、schema、API、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：两文件精确 Mypy 为 0；TypeVar 泛型使用者保持兼容（真实模型实例化探针）；db 影响面回归测试通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T57）**：19 条全数清除；Protocol bound 方案经探针证实被 `Mapped` 协议不变式拒绝（str/int 主键混合模型无法满足单一声明），最终采用与文件既有动态风格一致的单点 helper；`SQLRepository[AlertRule]`/`[Comparison]`/`[DataScript]` 实例化探针与既有泛型使用者全部兼容。db 影响面回归（monitoring/comparison API + auth/auth-service/refresh-token/alerts）147 passed、既有 warnings；两文件精确 Mypy 为 0，Ruff check/format、tracked `git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 260 errors / 76 files（625 checked、退出码 1）：error 级标准化差分恰移除 19 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-64：discovery 试验物化发布的三处可空边界

**问题**：`research/discovery_trial_materialization.py` 直接把 `journal.result_json`（`dict[str, Any] | None`）传入 `DiscoveryExecutionResult.from_mapping`、把 `session.get` 取得的 `ResearchQuotaReservation`（十项属性校验）与 `ResearchDatasetSnapshot`（registry 重验证）按非空使用，形成 13 条可空错误；其中 quota/dataset 行缺失时原路径必然 AttributeError。

**要求**：仅修改该文件。三处均按相邻既有错误码显式失败关闭：`result_json` None 抛 `DISCOVERY_EXECUTION_RESULT_INVALID`（与 from_mapping 既有拒绝路径等价）、quota None 抛 `DISCOVERY_PUBLICATION_QUOTA_DENIED`、dataset None 抛 `DISCOVERY_PUBLICATION_CANDIDATE_DENIED`。不得改物化/发布流程、候选完整性校验、配额结算语义、schema、API、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：目标文件精确 Mypy 为 0；定向测试通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T58）**：13 条清除完成；定向测试 22 passed、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过。完整 Mypy 为 247 errors / 75 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-65：知识库 ORM 补完迁移与 reqdocs 导入边界

**问题**：`app/models/knowledge_base.py` 处于 T5 单字段迁移后的混合状态，ChatConversation/KBDocument 等大部分列仍为 legacy `Column[...]`；`reqdocs_migration_service.py` 的六个 dict comprehension 以二次 `get` 取 reqdocs ID 后传 `int()`（CQ-200-50 根因），另有 3 条 Column 误推断；`rag_service.py` 4 条为同模型同根因连带。

**要求**：仅补完该模型文件的 legacy 列迁移（时间戳 T8/T51 先例、JSON 字段沿用既有先例、T5 既有注解不动），reqdocs 仅做单次读取循环与 ChatMessage 块的独立变量名。不得改导入/合并语义、幂等键、schema、API、配置、依赖或静态检查设置；不得新增 `cast`、`type: ignore`、`# noqa`（`typing.Any` 为 T5 既有保留）。

**验收**：模型与 reqdocs 精确 Mypy 为 0；AST 对比零差异；定向测试（reqdocs 迁移与知识库 API fixture）通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T59）**：13 条清除完成（reqdocs 9 + rag_service 4 连带）；AST 对比声明零差异，两文件精确 Mypy 为 0。定向测试三文件合跑 44 passed、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过。完整 Mypy 为 234 errors / 73 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-66：live trading 管理器的动态边界与回调合同

**问题**：`live_trading/manager.py` 的三处 instance params 读取为二次 `get`（CQ-200-50 根因）；停止路径对 `RuntimeError` 实例动态附加 `open_order_cancel` 属性；`StartResult`（TypedDict）上以模块常量 key pop 动态注入的私有字段；两个批量回调变量先绑完整签名方法再赋单参包装函数（签名不兼容）。

**要求**：仅修改该文件。二次 get 改单次局部读取；异常动态属性按 T54 先例以 `__dict__` 直写（不得 setattr 常量触发 B010 或删除既有属性）；私有字段 pop 移至既有 cast 之前的原始 dict 上（不得新增 cast 或以副本改变 dict 身份）；回调变量以 `Callable[[str], Awaitable[...]]` 显式注解。不得改启动/停止流程、server-attested 清理时序、schema、API、配置、依赖或静态检查设置；不得新增 `Any`、`type: ignore`、`# noqa`（既有 cast 为等价重排）。

**验收**：目标文件精确 Mypy 为 0；live_trading 定向测试通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T60）**：8 条清除完成；live_trading 定向测试四文件 151 passed、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过。完整 Mypy 为 226 errors / 72 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-67：fetch lease 与 publication 的游标/时钟/动态模型边界

**问题**：`fetch_lease.py` 五处 DML 结果的 `rowcount` 判 1、数据库时钟 scalar 的 `Any | None` 直传 `_stored_utc`；`publication.py` 一处 rowcount、`found` 字典的 `dict(Row)` 推断、动态注册模型（`entity_specs` 的 `type[Base]`）访问 `.id`、B2 selector 可空哈希清单直传完整性断言。

**要求**：仅修改两文件。rowcount 以各文件单点 helper 的 `CursorResult` isinstance 收窄（T57 模式）；时钟 None 早退按既有 `FETCH_LEASE_CLOCK_INVALID` 错误码；`found` 以行索引 comprehension 与显式 `dict[str, str]` 注解重建（运行时等价）；`model.id` 以 `__dict__["id"]` 直接映射（T57 模式）；可空哈希清单按 T56 同款 None 失败关闭。不得改 lease 状态机、发布事务顺序、完整性校验语义、schema、API、配置、依赖或静态检查设置；不得新增 `Any`、`cast`、`type: ignore`、`# noqa`。

**验收**：两文件精确 Mypy 为 0；market_data 定向测试通过；完整 Mypy 单独刷新并保留 FAIL / NO-GO。

**结果（T61）**：12 条清除完成；定向测试五文件（fetch_lease、publication_recovery、deferred_publication、multi_record_evidence、store+query_service）141 passed、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过。完整 Mypy 为 214 errors / 70 files（625 checked、退出码 1）：error 级标准化差分恰移除 12 条、新增 0 条；仍 FAIL / NO-GO。

## CQ-200-19：市场标的快照与指标类型边界

**问题**：`market_instrument.py` 的五个仓库查询把异构 snapshot 的 `name` 直接传给要求 `str` 的 payload；外汇 Pandas 行导出为 `dict[Hashable, Any]`，但 helper 只接受字符串键 dict；指标列表在过滤 `None` 后仍被静态视为 `float | None`。精确 Mypy 因此报告 20 条错误，且前两类边界有将数值作为展示名称或误读异构列键的风险。

**要求**：仅修改 `app/services/market_instrument.py` 并新增本地测试。仓库 snapshot 名只接受非空 `str`，非法或空值回退到既有标的代码；`_first_present` 必须以只读映射上的精确字符串键检索，兼容 Pandas 导出的可哈希键而不把非字符串键误认为候选列；指标聚合显式只保留有效 `float`，保留缺失值忽略和无 close 时仍计算 volume 均值的语义。不得改在线/仓库切换、行情数据源、API、配置、依赖、Mypy/Ruff 设置；不得新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。

**验收**：`market_instrument.py` 精确 Mypy 从 20 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace check 与新增 diff 抑制扫描通过。新增 fake/Pandas fixture 覆盖数字/空名称回退、异构键映射和缺失指标聚合；既有市场标的 API fixture 同时通过，共 20 passed、1 条既有 warning。随后刷新完整 Mypy 并明确保留 FAIL / NO-GO；不连接真实数据库、网络、供应商或交易系统。

## CQ-200-68：CI 固定开发锁下的 Mypy 可复现性

**问题**：本地可用的 Mypy 不等于 CI 使用的固定开发锁环境。缺少 PyMySQL 与 pytz 的类型桩、可选 Prometheus 导入重定义，以及 Redis `get()` 的宽返回类型会让 CI 范围的 Mypy 失去可复现性。

**要求**：开发依赖必须声明并锁定 `types-PyMySQL` 与 `types-pytz`；代码只在现有运行时边界处做精确类型表达，不放宽 Mypy 规则、不抬高 ratchet 基线。四个 `backend-mypy-*` CI job 必须先安装 canonical dev lock，再以 `--no-deps -e .` 安装项目，避免临时解析结果覆盖锁文件。不得改变 Redis、Prometheus、数据库或业务逻辑。

**验收**：在 canonical dev lock 环境中，lockfile sync 为 170 个已锁包一致；全量 `mypy app --show-error-codes` 为 0 errors，并且实际 ratchet 为 `errors=0 baseline=0 delta=+0`；四个与 CI 对应的 Mypy scope 均为 0 errors。CI workflow 的远端执行单独标记为 NOT_RUN。

## CQ-200-69：告警枚举的稳定 wire value 与测试夹具兼容

**问题**：SQLAlchemy Enum 既可能以真正的 `AlertType`/`AlertSeverity`/`AlertStatus` 实例出现，也可能由既有测试或兼容读取路径提供普通字符串。直接 `str(enum)` 会泄露 `AlertType.ACCOUNT` 这类 Python 表示，反过来对字符串调用 `.value` 会崩溃；未知的 `str, Enum` 也不能被误当成普通内置字符串返回。

**要求**：只在监控服务私有序列化边界处理三种已知告警枚举：已知枚举输出 `.value`，精确内置 `str` 原样保留，其他任何对象（包括未知 `str, Enum`）以内置 `str(...)` 回退。该规则适用于 webhook、摘要和按类型统计；保持 WebSocket 原有事件对象字段、模型、API、schema 和通知流程不变。摘要对没有 `created_at` 属性的兼容夹具继续安全返回 `None`。

**验收**：直接回归覆盖已知枚举、普通字符串、未知 `str, Enum`、`None` 与未知对象；webhook/summary/by-type 对枚举和字符串输入产生相同 wire key；监控与告警六文件回归通过。不得发出真实 webhook、连接数据库或外部通知系统。

## CQ-200-70：前端 ESLint 零 warning 门禁

**问题**：ESLint 即使存在 warning 也会以成功状态退出，导致纯格式和模板可读性问题能静默进入 CI。

**要求**：`npm run lint` 必须以 `--max-warnings 0` 运行，CI 复用该脚本而非绕过 warning。仅规范化实际触发 warning 的 Vue 模板；安全 HTML 继续使用 DOMPurify，并在两个 `v-html` 局部抑制处保留具体理由。不得关闭 ESLint 规则、修改功能逻辑或降低 TypeScript 严格度。

**验收**：Node 24 下 `npm run lint` 为 0 warning，`npm run typecheck`、全量 Vitest 与 production build 通过；manifest bundle hard budgets 与 Node engine/helper tests 通过。Vite 对大 chunk 的 advisory 不是 gate，通过记录但不作为零 warning 声明。
