# 迭代 200：验收

## 判定规则

CQ-200-01 至 CQ-200-05、CQ-200-07 至 CQ-200-22 以本地静态检查、依赖安装和 fixture 测试记录结果。CQ-200-06 的 T1–T61 行是历史失败快照；T62–T64 的 0/625 是当时快照，当前树以 T69 的 canonical dev lock Mypy 1.20.2、0-error ratchet、当前前端门禁和全量非性能回归为准。局部 fixture、静态门禁和本地非性能回归均不替代未运行的外部系统验收，也不表示 CI workflow 已运行。

## 用例与结果

| ID | 检查 | 预期 | 状态 / 证据 |
| --- | --- | --- | --- |
| CQ-200-06（T69 当前复验） | canonical dev lock 的全量 Mypy、0-error ratchet 与最终本地非性能回归 | 固定锁环境零错误、ratchet 不抬高基线；所有非性能测试通过 | PASS：170 个锁定包同步；`mypy app` 为 `Success: no issues found in 630 source files`，ratchet 为 `errors=0 baseline=0 delta=+0`；最终 `pytest -q -m "not performance" --maxfail=0` 为 `7864 passed, 123 skipped, 24 deselected in 3206.49s`。未运行 CI workflow。 |
| CQ-200-68（T69） | CI 固定开发锁下的 Mypy 可复现性 | 四个 CI scope 与全量 Mypy 都在 canonical lock 下通过 | PASS：四个 scope 分别为 58、7、4、15 个源文件零错误；workflow 已改为先安装 dev lock 再 `--no-deps -e .`。远端 CI 为 NOT_RUN。 |
| CQ-200-69（T69） | 已知告警枚举的 wire value 与兼容字符串输入 | webhook、摘要和按类型统计输出稳定 value；未知值安全回退 | PASS：监控/告警六文件 `204 passed`；直接用例覆盖三种已知 enum、内置 str、未知 `str, Enum`、`None`、未知对象，以及 webhook/摘要缺失时间戳时的安全 `null` 投影。未发真实通知或连接外部服务。 |
| CQ-200-70（T69） | warning-free 前端 lint 与受审查的尺寸棘轮 | lint 不接受 warning；格式化增量不静默放宽尺寸门禁 | PASS：Node 24 下 lint/typecheck 通过，Vitest `156 files / 1695 tests` 通过，build/manifest bundle hard budgets 通过；7 个 lint 格式路径经逐项审查后精确更新，`large_file_ratchet.py` 通过。 |
| CQ-200-06（T68 当前复验，本地使用 CI 锁定 Mypy 1.20.2） | 全量 Mypy 0-error ratchet 与本地非性能回归 | 固定版本 Mypy 为零、ratchet 不抬高基线；非性能测试选择器不产生 warning summary | PASS：新的临时 target/cache 下 fresh-cache 为 `Success: no issues found in 630 source files`，ratchet 为 `errors=0 baseline=0 delta=+0`；`pytest -q -m "not performance" --maxfail=0` 为 `7859 passed, 123 skipped, 24 deselected`，无 warning summary。未运行 CI workflow。 |
| CQ-200-06（T64，本地使用 CI 锁定 Mypy 1.20.2） | 全量 Mypy 0-error ratchet | 固定版本的全量 Mypy 与 ratchet 基线均为 0；计数增加时 ratchet 应失败 | PASS：临时 PYTHONPATH 环境 fresh-cache 全量检查 0/625；guarded baseline update 记录 Mypy 1.20.2 和 0 errors；本地常规 ratchet 输出 `errors=0 baseline=0 delta=+0`。未运行 CI workflow。 |
| CQ-200-06（T63 复审后最终复验） | 复审修复后的当前工作树完整 Mypy | 625 个源文件零错误；不通过配置放宽或忽略取得通过 | PASS：新的隔离缓存下 `python -m mypy app --show-error-codes` 输出 `Success: no issues found in 625 source files`，退出码 0。 |
| CQ-200-06（T62 最终复验） | 当前工作树完整 Mypy | 625 个源文件零错误；不通过配置放宽或忽略取得通过 | PASS：在 base Conda 环境和新建隔离缓存中运行 `python -m mypy app --show-error-codes`，输出 `Success: no issues found in 625 source files`，退出码 0。 |
| CQ-200-01 | npm ci、lint、typecheck、Vitest、production build | 在项目支持的 Node 版本下安装、前端检查和构建通过 | PASS（本地 Node 矩阵）：Node 20.20.2/npm 10.8.2 与 Node 24.2.0/npm 11.6.2 下 clean npm ci、lint、typecheck、全量 Vitest（154 files / 1687 tests）及 production build 均通过；两版本 lint 均为 0 errors / 0 warnings。T67 在当前 Node 20 锁文件上复验 production/full npm audit 均为 0 vulnerability，详见 QD-200-03 的 Git 来源覆盖边界。 |
| CQ-200-02 | 触及文件 Ruff lint、三个文件 format check | 通过 | PASS：lint 全部通过；三个文件已格式化 |
| CQ-200-03 | 精确 Mypy；THS rate limiter fixture | 类型无错，clock 熔断测试通过 | PASS：目标 Mypy 通过；THS 和 completeness 指定测试合计 18 passed |
| CQ-200-04 | 精确 Mypy 检查六个 package init | 六处无 __all__ 注解错误 | PASS：八个目标源文件 Mypy 检查通过 |
| CQ-200-05 | 精确 Mypy；多记录 completeness fixture | helper 与 Iterable 契约通过 | PASS：目标 Mypy 与多记录 fixture 通过 |
| CQ-200-06（T1–T16 历史快照） | 保留当时全量 Mypy 的 FAIL / NO-GO 记录 | 历史数值与结论可追溯；不得将其视为当前状态 | 历史 FAIL / NO-GO：基线 625 个源文件、1120 errors / 188 files；T1 后 1072/168；T2 后 1027/145；T3 后 984/143；T4 后 929/140；T5 后 849/136；T6 后 789/135；T7 后 662/129；T8 后 625/131；T9 后 615/128；T10 后 581/127；T11 后 556/126；T12 后 536/125；T13 后 516/124；T14 后 498/123；T15 后 489/122；T16 后重新扫描 625 个源文件，483 errors / 121 files，退出码 1。当前状态见 T67/T68。 |
| CQ-200-07 | Node 24.2.0；四个 file-level jsdom 测试；完整前端门禁 | Markdown 用例通过，其余测试仍使用 happy-dom | PASS（本地）：四个 Markdown 相关文件 4/4、35/35 通过；全量 Vitest 154/154 files、1687/1687 tests 通过。 |
| CQ-200-08 | StrategyDetailDialog 模块级 MonacoEditor mock | 在 SFC 加载前隔离非被测 Monaco；生产 Monaco 不变 | PASS（本地）：目标文件 1/1 通过；四文件及全量结果见下方执行记录。 |
| CQ-200-09 | T3 MySQL 核心静态契约、空查询结果与连接状态 | 两个核心文件精确 Mypy 为 0；Ruff/定向测试通过；不连接真实 MySQL | PASS（局部）：精确 Mypy 0 errors；目标 Ruff check/format 通过；`test_data_fetch_common_utils.py` 11 passed。真实 MySQL 未实测；其余范围外模块债务仍开放。 |
| CQ-200-10 | T4 AkShare data-fetch consumer 类型合同 | 三个目标文件精确 Mypy 为 0，Ruff 与 fake-only tests 通过；不连接真实外部系统 | PASS（局部）：基线 55 errors（21/21/13），修复后 0；Ruff check/format 通过；三份定向测试共 23 passed、1 warning。真实 MySQL、AkShare、网络均未运行；全量 Mypy 929/140 仍 FAIL / NO-GO。 |
| CQ-200-11 | T5 股票分析 ORM 实例字段静态合同及 schema 保持 | 四个目标源文件精确 Mypy 为 0；目标 Ruff/测试通过；ORM schema 语义不变 | PASS（局部）：三文件基线 58 errors，四文件最终 0；五个股票表的 schema metadata 签名 hash 修改前后相同；ChatMessage 仍映射 JSON 列 `metadata` 且 nullable=True；定向测试 26 passed。全量 Mypy 849/136 仍 FAIL / NO-GO；未运行真实 DB/AI/网络。 |
| CQ-200-12 | T6 仿真交易 ORM 与持仓快照类型合同 | 两个目标源文件精确 Mypy 为 0；schema 参数、Ruff/测试通过；不连接外部系统 | PASS（局部）：服务基线 60 errors，模型/服务最终 0；HEAD/工作区 67 个 `Column`/`relationship` 参数无差异，metadata 显示四张表的列面保持预期；定向服务/API 测试 142 passed、1 warning。全量 Mypy 789/135 仍 FAIL / NO-GO。 |
| CQ-200-13 | T7 市场数据平台 ORM 实例字段静态合同及 schema/relationship 保持 | 模型精确 Mypy 为 0；参数、metadata、Ruff/测试通过 | PASS（局部）：模型基线 2 errors，最终 0；220 个列调用和 25 个 relationship 调用与 HEAD 无参数差异，schema hash 保持；`test_store.py` 47 passed、1 warning；store 从 43 errors 降至 9 个非 ORM 错误。全量 Mypy 662/129 仍 FAIL / NO-GO。 |
| CQ-200-14 | T8 工作空间 ORM 实例字段和递归 JSON 合同 | 模型精确 Mypy 为 0；列/关系参数、mapper、Ruff/测试保持 | PASS（局部）：39 个列调用和 3 个 relationship 调用与 HEAD 无参数差异；mapper 为 2 tables / 39 columns / 3 relationships；相关服务/API 测试 159 passed、1 warning。四个直接消费者从 60 errors 降至 18；完整 Mypy 625/131 仍 FAIL / NO-GO。 |
| CQ-200-15 | T9 工作空间 JSON 直接消费者安全收窄 | 三个消费者精确 Mypy 为 0；有效/畸形 JSON fixture、Ruff/格式通过 | PASS（局部）：基线 10 errors（tasks 2、optimization 1、reports 7），最终 0；定向 fake/SQLite fixture 5 passed、1 warning，包含合法聚合、保存去重与畸形 JSON 安全退化。完整 Mypy 615/128 仍 FAIL / NO-GO。 |
| CQ-200-16 | T10 市场数据查询回执可见性、Store 参数与 signed cursor JSON 边界 | 精确 Mypy 为 0；deferred fail-closed、lease release、malformed signed cursor fixture 通过 | PASS（局部）：`query_service.py` 基线 34 errors，最终 0；目标 Ruff check/format、tracked diff check 和新增 diff 抑制扫描通过；`test_query_service.py` 69 passed、1 条既有 warning。完整 Mypy 581/127 仍 FAIL / NO-GO。 |
| CQ-200-17 | T11 Scanner plan ORM 实例字段类型契约 | 两个模型/服务精确 Mypy 为 0；schema/relationship、API fixture、Ruff/格式通过 | PASS（局部）：模型/服务基线 25 errors，最终 0；32 个列和 2 个 relationship 参数保持，mapper 为 15/17 columns、4/5 indexes；2 项 scanner-plan API fixture 通过、1 warning。完整 Mypy 556/126 仍 FAIL / NO-GO。 |
| CQ-200-18 | T12 仓位估值 `safe_float` 的 float/None fallback 类型契约 | 精确 Mypy 为 0；direct helper 与既有估值场景、Ruff/格式通过 | PASS（局部）：基线 20 errors，最终 0；3 项 helper 回归和 21 项估值场景通过、均为 1 条既有 warning；完整 Mypy 536/125 仍 FAIL / NO-GO。 |
| CQ-200-19 | T13 市场标的仓库 snapshot、Pandas 行与指标聚合类型边界 | 精确 Mypy 为 0；string-only 名称回退、异构行取值、指标聚合、Ruff/格式通过 | PASS（局部）：基线 20 errors，最终 0；5 项新增 fake/Pandas 回归与 15 项既有 API fixture 通过、共 20 passed、1 条既有 warning；完整 Mypy 516/124 仍 FAIL / NO-GO。 |
| CQ-200-20 | T14 新闻情报可选 session、loaded ORM 标量与 feed JSON 边界 | 精确 Mypy 为 0；session guard、历史 JSON 降级、Ruff/格式通过 | PASS（局部）：基线 18 errors，最终 0；3 项新增 boundary 回归与 5 项既有新闻 fixture 通过、共 8 passed、1 条既有 warning；完整 Mypy 498/123 仍 FAIL / NO-GO。 |
| CQ-200-21 | T15 认证服务 loaded ORM 标量与 logout token ID 边界 | 精确 Mypy 为 0；无效 `jti` 在仓储前失败关闭，Ruff/格式通过 | PASS（局部）：基线 9 errors，最终 0；6 项新增无数据库 token-ID fixture 与 18 项既有 auth-service/refresh/JWT fixture 共 24 passed、1 warning；auth API 回归另为 15 passed、7 条既有 warning；完整 Mypy 489/122 仍 FAIL / NO-GO。 |
| CQ-200-22 | T16 告警规则配置、可选数值与 alert type 边界 | 精确 Mypy 为 0；异常配置/类型在下游指标调用前失败关闭，Ruff/格式通过 | PASS（局部）：基线 6 errors，最终 0；4 项新增无数据库 boundary fixture 与 92 项既有告警/异常 fixture 共 96 passed、1 条既有 warning；完整 Mypy 483/121 仍 FAIL / NO-GO。 |

## T8：工作空间 ORM 与递归 JSON 类型批次补充验收（2026-09-20）

范围仅为 `src/backend/app/models/workspace.py` 与本迭代文档。`Workspace`、`StrategyUnit` 的 39 个 legacy `Column` 与 3 个 relationship 迁移为精确 SQLAlchemy 2 映射；JSON 字段使用递归 `WorkspaceJSONMapping`，未新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、迁移或配置豁免。HEAD/工作区 AST 参数对比为 columns=39、relationships=3，均无 missing/extra/changed；SQLAlchemy mapper 配置实测为 2 tables、39 columns、3 relationships。

模型精确 Mypy 为 0，Ruff check/format 与 `git diff --check` 通过；`tests/test_trading_workspace_service.py tests/test_workspace_trading_api.py` 为 159 passed、1 条既有 Quandl deprecation warning。四个紧邻服务的精确 Mypy 从 60 errors 降至 18；完整扫描的 `Found 625 errors in 131 files (checked 625 source files)` 相较 T7 下降 37 条错误、但报错文件数增加 2。严格 JSON 契约暴露出三个此前未报错的直接消费者，同时一个 lifecycle 文件消失；该变化不作为全仓通过或单一模型批次的机械归因，T9 单独处理三个直接消费者。未运行迁移、真实数据库、网络、外部数据或交易系统。

## T9：工作空间 JSON 直接消费者批次补充验收（2026-09-20）

范围仅为 `app/services/stock_analysis/tasks.py`、`app/services/workspace/optimization.py`、`app/services/workspace/reports.py`、新增 `tests/test_workspace_json_consumers.py`、现有保存报告兼容测试与本迭代文档。递归 TypeGuard 仅接受合法 JSON mapping；任务保存保留合法旧记录、替换重复 report_id、限制最近 50 条并删除非法项；优化配置保留合法旧项并写入本次 JSON 快照；报告只接受字符串日期和有限 int/float，忽略 bool、非数值、NaN、Infinity 及错误形状。未弱化模型 JSON 类型，也未修改 ORM、迁移、API、配置、依赖或规则。

三目标源文件精确 Mypy 从 10 errors（tasks 2、optimization 1、reports 7）到 0；五个源/测试文件 Ruff check 与 format check 通过，目标 tracked diff 无 whitespace error，抑制扫描没有 `type: ignore`、`# noqa`、`cast(Any)`。根代理独立复验 `tests/test_workspace_json_consumers.py` 和保存报告兼容用例为 5 passed、1 条既有 Quandl deprecation warning：覆盖合法配置合并、非法 JSON/指标安全退化、simple 年化、按 initial_cash 的 custom 权重、交易总数、best/worst 选择及保存去重。所有数据库交互均为 fake/SQLite fixture；没有真实 DB 服务、网络、外部数据或交易系统。

T9 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 615 errors in 128 files (checked 625 source files)`。相较 T8 净减少 10 errors、3 个报错文件，三个 T9 消费者均不再出现在错误清单；完整门禁继续是 FAIL / NO-GO。

## T10：市场数据查询回执和 cursor 类型边界批次补充验收（2026-09-20）

范围仅为 `app/services/market_data/query_service.py`、`tests/market_data_platform/test_query_service.py` 与本迭代文档。`_Store.persist_provider_result` 精确反映真实 Store 的 `PersistedProviderFetch | DeferredProviderFetch` 返回；query service 仅允许已可见回执进入 fetch、fresh revision、knowledge cutoff 与 visibility anchor 路径。收到 deferred 回执时抛出 `PROVIDER_RECEIPT_NOT_VISIBLE`，该分支仍在既有 fetch-lease `try/finally` 内。局部读取改为 explicit typed Store calls，避免把 `dict[str, object]` 展开给具名参数，同时保留无 allow-list fake Store 与有 allow-list 生产筛选路径。

签名 cursor 的 JSON 首先收窄为 string-key object，再验证完整形状；四个 required digest、optional access-grant digest 和两个 anchor sequence 都在领域对象构造前受运行时验证。有效 HMAC 但 payload 字段为 `None`、list、数值、bool、负数或 float 时统一返回 `CURSOR_INVALID`，且不调用 resolver、local Store 或 provider。新增 fixture 还断言 deferred 写入后没有追加 local read / visibility anchor，且恰好释放同一 fetch lease。根代理独立复验精确 Mypy 为 0、目标 Ruff check/format 与 tracked `git diff --check` 为通过；新增 diff 没有 `type: ignore`、`# noqa`、`cast(Any)`。`tests/market_data_platform/test_query_service.py -q` 为 69 passed、1 条既有 Backtrader Quandl deprecation warning。全部为 fake/local fixture，未连接真实数据库、网络、数据供应商或交易系统。

T10 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 581 errors in 127 files (checked 625 source files)`。相较 T9 净减少 34 errors、1 个报错文件；目标 `app/services/market_data/query_service.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T11：Scanner plan ORM 实例字段批次补充验收（2026-09-20）

范围仅为 `app/models/scanner_plan.py` 与本迭代文档。`ScannerPlanModel`、`ScannerPlanRunModel` 的 32 个 legacy `Column` 和两个 relationship 迁移为 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)`；`JSONValue` 递归表示 scalar/list/mapping，未新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、迁移或配置豁免。逐项 diff 审阅确认每个列及 relationship 调用保留原有参数；运行时 mapper 显示 `scanner_plans` 15 列、4 个 index，`scanner_plan_runs` 17 列、5 个 index，关系 target/uselist/back_populates/cascade/order_by/passive_deletes 保持预期。

根代理独立复验 `app/models/scanner_plan.py app/services/scanner_plan.py` 精确 Mypy 为 0，目标 Ruff check/format 和 tracked `git diff --check` 为通过，新增 diff 无 `type: ignore`、`# noqa`、`cast(Any)`。`tests/test_scanners.py -k scanner_plan -vv` 为 2 passed、4 deselected、1 条既有 Backtrader Quandl deprecation warning，覆盖日报计划缓存、计划更新/删除、动态结果表创建/删除。未修改服务、API、兼容 schema 逻辑、迁移、依赖或静态规则；全部为本地 SQLite/fake fixture，未连接真实数据库、网络或交易系统。

T11 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 556 errors in 126 files (checked 625 source files)`。相较 T10 净减少 25 errors、1 个报错文件；目标 `app/models/scanner_plan.py` 与 `app/services/scanner_plan.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T12：仓位估值数值回退类型批次补充验收（2026-09-20）

范围仅为 `app/services/position_valuation.py`、新增 `tests/test_position_valuation.py` 与本迭代文档。`safe_float` 以两个 overload 区分 float 与 `None` fallback：默认/float 分支静态返回 float，`None` 分支保留 `float | None`。实现体和递归 dict/list 路径的运行时行为保持：dict 查找第一个可用数值，list/tuple 仅聚合有效数，空有效集合返回调用方 default；估值、佣金、保证金、entry/current price、notional 和 PnL 公式未修改。

根代理独立复验精确 Mypy 为 0，目标 Ruff check/format、tracked `git diff --check`、untracked test whitespace check 均通过，新增 diff 没有 `type: ignore`、`# noqa`、`cast(Any)`。`tests/test_position_valuation.py` 为 3 passed，覆盖 default float、显式 float、`None` fallback、嵌套 dict 与 list 聚合；`tests/test_trading_workspace_service.py -k 'position_valuation or value_position' -vv` 为 21 passed、119 deselected。两组均仅有 1 条既有 Backtrader Quandl deprecation warning。未连接真实数据库、网络、账户或交易系统。

T12 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 536 errors in 125 files (checked 625 source files)`。相较 T11 净减少 20 errors、1 个报错文件；目标 `app/services/position_valuation.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T13：市场标的 snapshot 与指标类型批次补充验收（2026-09-20）

范围仅为 `app/services/market_instrument.py`、新增 `tests/test_market_instrument_type_boundaries.py` 与本迭代文档。五处仓库 lookup 的 name 只保留非空 string，数字、空字符串或缺失值回退到调用方既有标的代码；Pandas 导出的可哈希键 row 只按精确字符串候选列读取；指标循环先收集有效 float，仍在没有 close 时返回空价格指标并使用可用 volume 计算平均。未改变 online/warehouse 路由、provider、行情源、payload 形状或 API。

根代理独立复验 `app/services/market_instrument.py` 精确 Mypy 为 0，目标 Ruff check/format、tracked `git diff --check`、untracked test whitespace check 均通过，新增 diff 没有 `type: ignore`、`# noqa`、`cast(Any)` 或新的 `Any`。新增 `tests/test_market_instrument_type_boundaries.py` 为 5 passed，覆盖数字/空名称 fallback、可哈希键 mapping、Pandas 外汇行和缺失 close/volume；与 `tests/test_market_instrument_api.py` 合跑为 20 passed、1 条既有 Backtrader Quandl deprecation warning。所有验证均为 fake/Pandas/API fixture，未连接真实数据库、网络、供应商或交易系统。

T13 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 516 errors in 124 files (checked 625 source files)`。相较 T12 减少 20 errors、1 个报错文件；目标 `app/services/market_instrument.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T14：新闻情报 session 与 feed 元数据类型批次补充验收（2026-09-20）

范围仅为 `app/services/news_intelligence.py`、新增 `tests/test_news_intelligence_type_boundaries.py` 与本迭代文档。构造函数、公开 `db` 属性和 `get_news_intelligence_service` 保持 optional session；所有持久化路径（含内部计数）都通过返回 `AsyncSession` 的 guard 得到局部 session。默认服务的 analyze/RSS helper 仍可无 session 使用，持久化调用缺少 session 时仍抛出 `RuntimeError("database_session_required")`。

根代理独立复验 `app/services/news_intelligence.py` 精确 Mypy 为 0，目标 Ruff check/format、tracked `git diff --check`、untracked test whitespace check 均通过，新增 diff 没有 `type: ignore`、`# noqa`、`cast(Any)` 或新的 `Any`。由于 session 收窄显露 legacy Model 的 class-attribute 误推断，服务内仅在 loaded NewsSourceModel 边界使用显式 scalar Protocol cast，未修改模型、SQL、API 或迁移。新增测试为 3 passed，覆盖无 session helper、持久化异常、非 Mapping JSON 和 Mapping ticker；与既有新闻 API/classifier fixture 合跑为 8 passed、1 条既有 Backtrader Quandl deprecation warning。所有验证使用 fake HTTP、未持久化 ORM instance 或本地 fixture，未连接真实数据库、网络或交易系统。

T14 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 498 errors in 123 files (checked 625 source files)`。相较 T13 减少 18 errors、1 个报错文件；目标 `app/services/news_intelligence.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T15：认证服务 ORM 标量与 logout token ID 批次补充验收（2026-09-20）

范围仅为 `app/services/auth_service.py`、新增 `tests/test_auth_service_type_boundaries.py` 与本迭代文档。根代理逐段审阅确认：两个 Protocol 仅列出服务实际使用的 loaded User/RefreshToken 标量字段，`cast` 只出现在仓储或 SQLAlchemy 已返回真实 instance 的边界；未修改模型、SQL query、事务、JWT payload、路由、配置、依赖、迁移或 schema。密码哈希更新和撤销标记仍落在原 ORM instance 上。

根代理独立复验 `app/services/auth_service.py` 精确 Mypy 为 0，Ruff check/format、tracked `git diff --check`、untracked test whitespace check 通过，新增 diff 没有 `cast(Any)`、`type: ignore` 或新的 `# noqa`。新增 fixture 为 6 passed，覆盖缺失、`None`、数值、空字符串和 list `jti` 都返回 `False` 且不调用撤销方法，以及非空字符串继续调用撤销方法；与 `tests/test_auth_service_extra.py tests/test_refresh_token.py tests/test_jwt_migration.py` 合跑为 24 passed、1 条既有 Backtrader Quandl deprecation warning。根代理另行执行 `tests/test_auth.py`，结果 15 passed、7 条既有 warning（Quandl 弃用与 Starlette 的 422 常量弃用）。未连接真实数据库、网络或交易系统。

T15 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 489 errors in 122 files (checked 625 source files)`。相较 T14 减少 9 errors、1 个报错文件；目标 `app/services/auth_service.py` 已退出错误清单。完整门禁继续是 FAIL / NO-GO。

## T61：fetch lease 与 publication 游标/时钟/动态模型边界验收（2026-09-21）

范围仅为 `src/backend/app/services/market_data/fetch_lease.py`、`app/services/market_data/publication.py` 与本迭代文档。根代理审阅确认修复的边界语义：rowcount helper 的 isinstance 收窄表达运行时事实（DML execute 恒返回 CursorResult），`or 0` 归 0 与原 `rowcount != 1` 判断在 rowcount 为 None/不可用时同为不等于 1 的结论；fetch lease 时钟 None 早退产生的异常类型与错误码和原 ValueError 穿透路径一致；publication 的 `found` 重建对二元 Row 逐行取索引与 `dict(rows)` 的键值配对一致，显式 `dict[str, str]` 与 entity_id/receipt_sha256 的运行时形态一致；`model.__dict__["id"]` 为直接类属性映射（entity_specs 的四个模型均直接声明 id）；B2 可空哈希清单的 None 失败关闭沿用 T56 同款错误码并经既有 except 归一为 `PUBLICATION_ENTITY_INTEGRITY`。无新增错误码，无行为变化。

根代理在隔离 pycache 下合跑五个定向测试文件（test_fetch_lease、test_publication_recovery、test_deferred_publication、test_multi_record_evidence、test_store + test_query_service），结果 141 passed、1 条既有 Backtrader Quandl warning。两文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 214 errors / 70 files（625 checked，退出码 1）。与 T60 的 226/72 比较 error 级标准化差分：恰移除 12 条（fetch_lease 6、publication 6），新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T60：live trading 管理器动态边界与回调合同验收（2026-09-21）

范围仅为 `src/backend/app/services/live_trading/manager.py` 与本迭代文档。根代理审阅确认四处修复的边界语义：单次读取与原二次 `get` 在 isinstance 与非空守卫下逐值等价；异常的 `open_order_cancel` 动态属性经 `__dict__` 直写与点号赋值语义严格等价（普通异常实例无 `__slots__`），属性保留未删除；server-attested 私有字段 pop 前移到 cast 之前对同一 dict 对象执行，finally 的 store 清理与 result pop 相互独立、异常路径不执行 pop 的行为保持，返回值身份不变；回调窄注解 `Callable[[str], Awaitable[...]]` 同时接受完整签名的绑定方法（多余参数有默认值）与单参包装函数，`start_all`/`stop_all` 的调用合同不变。方案备选留档：`dict[str, object]` 视图赋值被 TypedDict 与可变 dict 的类型规则拒绝（初版方案），最终采用 pop 位置前移。

根代理在隔离 pycache 下合跑四个 live_trading 定向测试文件（manager、manager_runtime_shim、service、api），结果 151 passed、1 条既有 Backtrader Quandl warning。目标文件精确 Mypy 为 0；Ruff check/format（I001 由 --fix 自动整理后复检通过）与 tracked `git diff --check` 通过；新增行零 `Any`、`type: ignore`、`# noqa`，唯一 cast 命中为既有 `cast(StartResult, ...)` 的等价重排。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 226 errors / 72 files（625 checked，退出码 1）。与 T59 的 234/73 比较 error 级标准化差分：恰移除 manager.py 的 8 条（3 条二次 get、1 条动态属性、2 条 TypedDict key、2 条回调签名），新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实网关、交易、数据库、网络、行情或供应商系统。

## T59：知识库 ORM 补完迁移与 reqdocs 导入边界验收（2026-09-21）

范围仅为 `src/backend/app/models/knowledge_base.py`、`src/backend/app/services/reqdocs_migration_service.py` 与本迭代文档。根代理审阅确认：七模型补完迁移保持全部表/列名、SQL 类型、显式 nullable/default/onupdate、PK/FK/ondelete/index/unique、`remote_side` 自引用与关系语义；时间戳列 HEAD 未显式传 nullable（legacy 默认 True），按 T8/T51 先例注解为 `Mapped[datetime | None]`，与 alembic baseline 的 nullable=True 一致；T5 批次已迁移的五个字段注解（含 `settings: dict[str, Any]`）原样保留未动。reqdocs 的六个循环改写为运行时等价的单次读取形态（isinstance 守卫、非 None 条目与 int() 转换的值均不变）；ChatMessage 块的独立变量名消除 CQ-200-45 式跨块复用。

根代理在隔离 pycache 下合跑三个定向测试文件，结果 44 passed、1 条既有 Backtrader Quandl warning。模型与 reqdocs 精确 Mypy 为 0；AST 归一化对比声明零差异；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `cast`、`type: ignore`、`# noqa`，`typing.Any` 为既有 import 的保留（其使用处为 T5 既有注解）。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 234 errors / 73 files（625 checked，退出码 1）。与 T58 的 247/75 比较 error 级标准化差分：恰移除 13 条——reqdocs_migration_service 的 9 条（6 条二次 get 的 int 转换、3 条 Column 误推断，含模型收紧暴露的 2 条变量复用一并修复）与 `rag_service.py` 的 4 条 knowledge_base 模型同根因连带；新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T58：discovery 试验物化发布可空边界验收（2026-09-21）

范围仅为 `src/backend/app/services/research/discovery_trial_materialization.py` 与本迭代文档。根代理审阅确认三处失败关闭的边界语义：`from_mapping(None)` 在契约类内部经 `_validate_result`/`_canonical_bytes` 的既有异常路径必然抛出同一 `DISCOVERY_EXECUTION_RESULT_INVALID`，调用点显式化仅把该失败提前且不再依赖动态类型异常；quota 十项校验块共享 `DISCOVERY_PUBLICATION_QUOTA_DENIED`，行缺失归入同一拒绝语义；dataset 快照是候选证据链的组成部分，缺失归入 `DISCOVERY_PUBLICATION_CANDIDATE_DENIED`。无新增错误码，无可空值进入后续消费。

根代理在隔离 pycache 下运行定向测试 `test_ai_research_discovery_trial_materialization.py`，结果 22 passed、1 条既有 Backtrader Quandl warning。目标文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 247 errors / 75 files（625 checked，退出码 1）。与 T57 的 260/76 比较 error 级标准化差分：恰移除该文件 13 条（2 条 result_json、10 条 quota、1 条 dataset），新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T57：db 基础设施泛型仓库与引擎边界验收（2026-09-21）

范围仅为 `src/backend/app/db/sql_repository.py`、`src/backend/app/db/database.py` 与本迭代文档。根代理审阅确认：`_cursor_rowcount` 的 isinstance 收窄表达运行时事实（AsyncSession.execute 对 DML 语句返回 CursorResult），`rowcount or 0` 归 0 与原 `if not result.rowcount`/`or 0` 语义等价；`_id_column()` 的 `__dict__["id"]` 为直接类属性映射访问（全部模型直接声明 `id`，无 MRO 遍历差异），与原 `self.model_class.id` 运行时等价，且与 `_apply_filters` 既有的 `getattr(self.model_class, key)` 动态风格一致；TypeVar 无 bound 保持原状，泛型使用者的公开方法签名未变。`database.py` 的 helper 收窄同样表达运行时事实（`__table__` 声明值运行时恒为 Table）；`get_db` 的 `AsyncGenerator` 注解是 FastAPI 依赖注入对 async generator 的标准形态。

方案选择过程留档：Protocol bound 的 `ColumnElement[str]` 声明把类属性解析为实例属性导致 where 拒绝；`Mapped[str] | Mapped[int]` 联合声明被 mutable 协议成员不变式拒绝（`Mapped[str]` 不是联合的子类型）；`getattr` 常量属性被 Ruff B009 既有门禁拒绝（与 T54 setattr 常量同族）。最终方案未引入任何豁免。

根代理在隔离 pycache 下运行 db 影响面回归（test_monitoring_api、test_comparison_api、test_auth、test_exceptions_and_alerts、test_auth_service_extra、test_refresh_token），结果 147 passed、既有 warnings；`SQLRepository` 以三个真实模型（str/str/int 主键混合）实例化的探针 Mypy 通过。两文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 260 errors / 76 files（625 checked，退出码 1）。与 T56 的 279/78 比较 error 级标准化差分：恰移除 19 条（sql_repository 11、database 8），新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T56：市场数据存储 T7 挂账非 ORM 边界验收（2026-09-21）

范围仅为 `src/backend/app/services/market_data/store.py` 与本迭代文档。根代理审阅确认七处修复的边界语义：五处失败关闭全部沿用各函数既有错误码与既有 except 归一路径（B2 哈希清单、观测时间等价早退、发布序列、授权容器、semantic dimensions），无新错误码；两处为等价守卫/纯静态表达（shared payload 单次读取与 `_get_or_create` 的 None-入-None-出契约一致、calendar 元组列表 CQ-200-51 式注解）。两处显式行为收紧单独记录：`publication.visibility_sequence` 为 None 时从"构造含 None 的 receipt（TypedDict 运行时不拦截，None 进入后续消费）"改为 `DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY`；授权断言的 `allowed_uses`/`jurisdictions` 为非容器值时从"迭代 object 必然 TypeError 上抛"改为显式 `SOURCE_AUTHORIZATION_INVALID`——均为不可信输入的失败关闭，与 CQ-200-16/21 系列同向。

根代理在隔离 pycache 下运行 market_data_platform 全套定向测试（62 个文件，含 test_store、test_query_service、test_deferred_publication、test_multi_record_* 等），结果 1254 passed、137 条既有 warning。目标文件精确 Mypy 为 0（T7 挂账的非 ORM 错误全量关闭）；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 279 errors / 78 files（625 checked，退出码 1）。与 T55 的 287/79 比较 error 级标准化差分：恰移除 store.py 的 8 条，新增 0 条。完整静态门禁仍为 FAIL / NO-GO；market_data_platform 全套之外未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T55：数据治理 ORM 实例字段与连接器注册表边界验收（2026-09-21）

范围仅为 `src/backend/app/models/data_governance.py`、`src/backend/app/services/data_connectors/registry.py`、`app/services/market_data/store.py` 的两处容器注解与本迭代文档。根代理审阅确认：八模型迁移保持全部表/列名、SQL 类型、显式 nullable/default/onupdate、PK/FK/index/unique/CheckConstraint、`Enum(DgJobStatus)` 无 `values_callable` 的既有存储语义与全部关系 target/back_populates/cascade；时间戳在 HEAD 即显式 `nullable=False`，无推导翻转风险；`DataTable` 跨模型双向前向引用（akshare_mgmt ↔ data_governance）仅经 `TYPE_CHECKING`，运行时 mapper 配置核验通过。

registry.py 的 `tuple(row)` 适配与既有 `tuple[DgEndpoint, DgProvider] | None` 返回合同一致，两个调用点仅做解包、Row 为 tuple 子类，语义等价；`_PROVIDER_SEEDS` 注解为纯静态表达，provider_id 的 isinstance 收窄在字面量恒为 str 时行为不变、对未来非 str 种子 fail-safe 跳过。store.py 两处 `dict[str, object]` 注解与下游 `Mapping[str, object]` 字段/参数合同（snapshot provenance 与 registry 匹配断言）一致，是模型收紧暴露的既有自由 JSON 形态的诚实表达而非放宽。

根代理在隔离 pycache 下合跑五个定向测试文件（test_data_governance_compat、market_data_platform 的 test_catalog/test_research_binding/test_legacy_contract/test_store），结果 148 passed、20 条既有 warning。模型与 registry 精确 Mypy 为 0；AST 归一化对比 91 声明零差异；mapper 核验 8 tables 列数 9/8/8/8/20/9/9/7 共 78 列，时间戳 nullable=False 全数保持；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 287 errors / 79 files（625 checked，退出码 1）。与 T54 的 307/81 比较 error 级标准化差分：恰移除 20 条——registry.py 14（12 条 `Column` 误推断 + 2 条 Row 合同）、模型 2、`bootstrap.py` 2 与 `quant_tools_runtime.py` 1 条 Dg 同根因连带、`store.py` 1 条（模型收紧中间态暴露的 2 条当场修复后无痕，净减 3325 一条既有签名）；新增 0 条。store.py 剩余 8 条为 T7 挂账的非 ORM 错误，另行批次处理。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T54：live trading 执行器异步上下文与动态属性验收（2026-09-21）

范围仅为 `src/backend/app/services/live_trading/execution.py` 与本迭代文档。根代理审阅确认：`_optional_lock()` 的返回注解从同步 `AbstractContextManager` 修正为 `AbstractAsyncContextManager` 表达的是六处 `async with` 调用点的既有运行时合同——运行时探针（Python 3.11，`nullcontext` 具备 `__aenter__`）与 Mypy `--python-version 3.10` 探针（typeshed 为 3.10+ 声明异步协议，`Success: no issues`）双重验证；锁存在/缺失分支、获取顺序与释放语义不变。三个 `_bt_*` 句柄改经 `proc.__dict__[...]` 直写：对无 `__slots__` 的普通实例与点号赋值语义严格等价，且与读取侧 `_close_subprocess_log_handles` 的 `getattr(proc, "__dict__", {}).get(attr)` 完全对称；初版 `setattr` 常量属性方案被既有 Ruff B010 门禁拒绝，最终方案未引入 `# noqa`。`_merge_runtime_contract_metadata` 为 CQ-200-50/52 同根因的二次 `get` 单次读取收窄。

根代理在隔离 pycache 下合跑七个 live_trading/instance 定向测试文件（live_instance_service、live_trading_api、instance_store、execution_model、manager、manager_runtime_shim、service），结果 208 passed、1 条既有 Backtrader Quandl warning。目标文件精确 Mypy 为 0；Ruff check/format（含 B010）与 tracked `git diff --check` 通过；`_optional_lock` 签名行的 `Any` 参数化为既有形态、非新增。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 307 errors / 81 files（625 checked，退出码 1）。与 T53 的 323/82 比较 error 级标准化差分：恰移除 execution.py 的 16 条（12 条 `__aenter__`/`__aexit__`、3 条 `Process` 动态属性、1 条二次 `get`），新增 0 条。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实网关、交易、数据库、网络、行情或供应商系统。

## T53：AkShare 管理 ORM 实例字段与脚本服务边界验收（2026-09-21）

范围仅为 `src/backend/app/models/akshare_mgmt.py`、`src/backend/app/services/akshare/script.py` 与本迭代文档。根代理审阅确认：七模型迁移保持全部表/列名、SQL 类型、显式 nullable/default/onupdate、PK/FK/index/unique、五个 `Enum(..., values_callable=_enum_values)` 列参数、`metadata_json` 显式列名 "metadata" 与全部关系 target/back_populates/cascade 语义；时间戳列在 HEAD 即显式 `nullable=False`，无 T51 形态的推导翻转风险；JSON 列按语义以 `JSONValue`/`dict[str, JSONValue]` 表达，`DgDatasetStorage` 仅经 `TYPE_CHECKING` 前向引用。

script.py 四处修复均经行为等价审查：`_SCRIPT_MIN_TIMEOUT_SECONDS` 的 33 个键全为 str，新 None 守卫与原 `get(None, 0.0)` 等价；`raw_timeout` 的 `A or B or "60"` 与原 `A or getenv(B, "60")` 逐情形等价（B 空串时旧码经 ValueError 回退 60.0、新码直接 60.0，最终值相同）；`safe_defaults` 注解为纯 PEP 526 局部注解、运行时不求值，Mypy 反向验证全量条目并揭露既有 `list[str]` 值；legacy 表名 `_legacy_callable_table_name` 为纯 getattr 函数，单次调用复用等价，双 None 条件的唯一行为差异位于不可达路径（`normalize_existing_table_name` 不返回空串），且消除旧代码可能把 None 静默归一为 "data" 错表同步的隐患。

根代理在隔离 pycache 下合跑六个 akshare 测试文件，结果 178 passed、79 skipped（既有环境相关跳过）、1 条既有 Backtrader Quandl warning。五文件（模型 + script/execution/scheduler_service/api tables）精确 Mypy 为 0；AST 归一化对比 114 声明零差异；运行时 mapper 核验 7 tables 列数 20/18/5/14/10/16/22 共 105 列、9 关系，`frequency` 列类型为 `sqlalchemy.Enum` 且 `enum_class=ScriptFrequency`，nullable 抽查与显式列名探针通过；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。独立审查代理复核 A–E 全部 PASS、未发现缺陷。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 323 errors / 82 files（625 checked，退出码 1）。与 T52 的 355/87 比较去除行号标准化差分：移除 32 条 errors——模型 5、script.py 17、execution 3、scheduler 3、api tables 2（合计 30 预期）加 `data_connectors/registry.py` 引用 `DataInterface` 的 2 条同根因连带；新增 0 条。`market_data/akshare_provider.py` 的 2 条与本模型族无关，保留后续。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T52：比较 ORM 实例字段与服务容器边界验收（2026-09-21）

范围仅为 `src/backend/app/models/comparison.py`、`src/backend/app/services/comparison_service.py` 与本迭代文档。根代理审阅确认：两模型迁移保持全部表/列名、SQL 类型、显式 nullable/default/onupdate、PK/FK/index 与关系 target/back_populates/secondary 语义；时间戳列 HEAD 未显式传 nullable（legacy 默认 True），按 T8/T51 先例注解为 `Mapped[datetime | None]`，mapper 探针与 alembic baseline（`0001_baseline.py` 的 `backtest_comparisons` 时间戳列均无 nullable=False）双重核验无翻转；association table 的 `Column` 声明保持原样。`backtest_task_ids: list[str]` 与既有 request/response schema 的 `list[str]` 合同一致。

服务侧仅做局部容器注解与一个显式可空守卫：`metrics_comparison`/`equity_comparison`/`trades_comparison`/`drawdown_comparison` 的注解与各自函数既有 `-> dict[str, Any]` 返回签名一致（文件已有 `Any`，按 T24 先例继续表达既有合同，输入参数本即 `dict[str, dict[str, Any]]`）；`best_metrics` 以 `dict[str, dict[str, str | float | None]]` 表达既有 `{"task_id": str|None, "value": float}` 形态；`filters`/`update_dict` 与 T51/T24 同款。update 后的 `Comparison | None` 在传入 `_to_response` 前显式返回 None——原路径在 update 失效时必然 `AttributeError`，属失败关闭改进；函数返回类型本即 `ComparisonResponse | None`。

根代理在隔离 pycache 下运行 `test_comparison_service.py` 为 30 passed、1 条既有 warning；`test_comparison.py` + `test_comparison_api.py` 为 54 passed、5 条既有 warning。两文件精确 Mypy 为 0；AST 归一化对比 21 声明零差异；Ruff check/format、tracked `git diff --check` 通过；新增行无 `cast`、`type: ignore`、`# noqa`，新增的 4 处 `dict[str, Any]` 局部注解与既有返回签名一致并在此记录。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 355 errors / 87 files（625 checked，退出码 1）。与 T51 的 373/88 比较去除行号标准化差分：恰移除 comparison_service.py 的 18 条（T18 挂账全量，含 1 条 `Column[str]` 误推断与 17 条容器/边界错误），新增 0 条；其它 Comparison 消费者（comparison API/schema 路径）无新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T51：告警 ORM 实例字段与监控服务边界验收（2026-09-21）

范围仅为 `src/backend/app/models/alerts.py`、`src/backend/app/services/monitoring_service.py` 与本迭代文档。根代理审阅确认：三模型迁移保持全部表/列名、SQL 类型、nullable/default/onupdate、PK/FK/index 与关系 target/back_populates/backref 原样；JSON 字段以递归 `JSONValue` 表达（`trigger_config` 为 mapping、`notification_channels` 为 list、`details` 可空任意 JSON），外部模型仅经 `TYPE_CHECKING` 前向引用。服务侧的 `AlertRule | None` 守卫与原 `getattr(rule, "is_active", False)` 短路运行时等价（None 时两者都不调用 `_start_monitoring`）；filters 注解与 webhook 单次读取不改变任何成功路径。

模型迁移揭露并修复两处真实运行时缺陷：其一，`_send_websocket_alert` 的 `alert.alert_type.value`/`alert.severity.value` 对已加载的 str 标量必然 `AttributeError`（此前被 legacy `Column` 误推断掩盖），现直接使用字符串值；其二，webhook url 为非字符串 truthy 值时 `urllib.request.Request(url=...)` 在 try 块外抛出异常并向上传播，违反 `_send_webhook` docstring 声明的 fire-and-forget 契约，现于读取点收窄为 str，非字符串归一为 None 并走既有 "missing webhook url" 失败关闭记录。

根代理在隔离 pycache 下合跑六个 monitoring/alert fixture 文件（monitoring API/service、alert evaluation 及 type boundaries、exceptions/alerts、strategy version edge cases），结果 198 passed、7 条既有 warning（Quandl 弃用与 Starlette 422 常量弃用）。两文件精确 Mypy 为 0；AST 归一化对比确认 59 个列/关系调用参数与 HEAD 零差异；运行时 mapper 核验 alerts 26 列、alert_rules 15 列、alert_notifications 8 列（声明关系 10，`alerts` 表运行时第 8 个关系为 AlertRule 侧 backref 生成的 `rule`，属 backref 正常行为）；Ruff check/format、tracked `git diff --check` 与 diff 抑制扫描通过，新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。

独立审查代理复核发现一处 P2 缺陷并已修正：迁移初版将 5 个时间戳列（`alerts.created_at/updated_at`、`alert_rules.created_at/updated_at`、`alert_notifications.created_at`）的 nullable 从 legacy Column 默认的 True 推导翻转为 False（AST 级不可见，mapper 探针与 alembic baseline `0001_baseline.py` 双重证实漂移）。修正按 T8 workspace 先例将注解改为 `Mapped[datetime | None]`（与 HEAD legacy 默认及 baseline DDL 的 nullable=True 一致），并对 monitoring_service 三处 `.isoformat()` 消费点加等价守卫（其中两处原为 `getattr` 冗余防御形态，一处无防御；default 恒供值下 None 分支运行时不可达）。修正后复验：AST 对比仍零差异、mapper nullable 探针全数恢复、两文件精确 Mypy 仍为 0、定向测试仍 198 passed。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 373 errors / 88 files（625 checked，退出码 1）。与 T50 的 388/89 比较去除行号标准化差分：恰移除 monitoring_service.py 的 15 条（T25 挂账全量），新增 0 条；`paper_runtime_service`、`api/risk_control`、`alert_evaluation` 等其它 alerts 模型消费者无新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网络、行情或交易系统。

## T50：portfolio 候选数值协议收窄验收（2026-09-21）

范围仅为 `src/backend/app/api/portfolio/api.py` 与本迭代文档。根代理审阅确认：候选值先收窄为 `object` 局部读取，nested 候选为 `object | None`；新增 `_is_float_input()` TypeGuard 仅放行 `float()` 的既有输入协议（str/bytes/bytearray/memoryview/`SupportsFloat`/`SupportsIndex`，以 isinstance 与 `__float__`/`__index__` 探测表达），非协议值继续下一候选键——与旧路径中 `float()` 必然抛 `TypeError` 再被捕获 `continue` 的可观察行为等价。`(TypeError, ValueError)` 捕获、nested 字段优先级（amount/value/balance/total）、string trim/逗号移除、NaN/Infinity 原样返回、`float | None` 返回合同及全部 portfolio 聚合/position/account 调用方均未改。

根代理在隔离 pycache 下运行三项直接 `_first_number` fixture（本工作区已建立，覆盖 nested numeric text/trim/逗号、invalid-first-key 到 next-key fallback、Decimal 数值协议与 NaN/bytearray），结果 3 passed；完整 `tests/test_portfolio_api.py` 为 129 passed、1 条既有 Backtrader Quandl deprecation warning。目标文件精确 Mypy 为 0（含本批目标 `float()` `[arg-type]`）；Ruff check/format、target `git diff --check` 与 diff 抑制扫描通过，新增 hunk 无 `Any`、`cast`、`type: ignore` 或 `# noqa`，累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 388 errors / 89 files（625 checked，退出码 1）。与 T49 的 389/90 比较：恰减 1 条错误、1 个报错文件，`api/portfolio/api.py`（T49 清单中该文件唯一错误即本批目标，T50 前单文件精确扫描证实为唯一诊断）退出完整清单，计数闭合且无新增诊断迹象。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网关、交易、网络、行情或供应商系统。

## T49：attested paper runtime anchor JSON 边界验收（2026-09-21）

范围仅为 `src/backend/app/services/trading_workspace_service.py`、对应直接测试与本迭代文档。根代理审阅确认只有 raw anchor 的局部读取被加上 dict guard；有效 dict 仍进入原 verifier、re-check 与 refresh 流程，非 Mapping 则以 `None` 传给同一 verifier。没有修改 provenance verifier、server-owned predicate、risk gate、runtime sync 或 manager。

根代理在隔离 pycache 下运行 scalar-anchor fail-closed、live risk-gate 和普通 paper-start 三项 fixture，结果为 3 passed、1 条既有 Backtrader Quandl deprecation warning。新 fixture 用真实 verifier spy 确认 scalar anchor 已归一为 `None`、结果保持 `AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID`，并断言 runtime sync 和 `add_instance` 均未调用。目标 service Mypy 为 0；Ruff check/format、target `git diff --check` 通过。T49 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 389 errors / 90 files（625 checked，退出码 1）。与 T48 比较，原始和标准化清单均仅移除一条 WorkspaceJSON anchor `[assignment]`，没有新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网关、交易、网络、行情或供应商系统。

## T48：position-log 方向代码受控数值转换验收（2026-09-21）

范围仅为 `src/backend/app/api/portfolio/api.py`、`src/backend/app/services/trading_workspace_service.py`、两个直接测试模块及本迭代文档。根代理审阅确认两个同构 parser 都保留了文本 alias、key group、数字 code mapping 和原 `except (TypeError, ValueError)`；唯一变动是用各模块已有 `_safe_float(value, float("nan"))` 取得与旧 `float(value)` 相同的成功转换，并让失败值经 `int(nan)` 的既有异常分支回到 signed-size fallback。

根代理在隔离 pycache 下运行 portfolio/workspace 的 Bybit one-way、numeric-code/invalid-fallback 与 hedge dual-side 六项 fixture，结果为 6 passed、1 条既有 Backtrader Quandl deprecation warning。两文件精确 Mypy 仅余 `portfolio/api.py:559` 与 `trading_workspace_service.py:2177` 两条非 T48 错误，两个目标 `float()` `[arg-type]` 均为 0；Ruff check/format、target `git diff --check` 通过。T48 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 390 errors / 90 files（625 checked，退出码 1）。与 T47 比较，原始和标准化清单均仅移除两条 direction parser `float()` `[arg-type]`，没有新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网关、交易、网络、行情或供应商系统。

## T47：portfolio equity 浮点序列容器验收（2026-09-21）

范围仅为 `src/backend/app/api/portfolio/api.py` 与本迭代文档。根代理审阅确认 `strategy_series` 和 `strategy_pnl_series` 的 key 仍由原 instance ID 推导，赋值后仅追加 `_safe_round()` 返回的浮点数；统一时间轴、聚合、drawdown、采样重建和 `values`/`pnl_values` payload 输出均未改。

根代理在隔离 pycache 下运行 running-source history 过滤、include-inactive 历史保留、空数据、有数据、intraday datetime 与首日初始现金 6 项既有 fixture，结果为 6 passed、1 条既有 Backtrader Quandl deprecation warning。目标 `api.py` Mypy 仅余两条非 T47 的 `float()` `[arg-type]`，两条 strategy series `[var-annotated]` 均为 0；Ruff check/format、target `git diff --check` 通过。T47 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 392 errors / 90 files（625 checked，退出码 1）。与 T46 比较，原始和标准化清单均仅移除两条 strategy series `[var-annotated]`，没有新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网关、交易、网络、行情或供应商系统。

## T46：portfolio metadata 单次读取与资产规格持久化验收（2026-09-21）

范围仅为 `src/backend/app/api/portfolio/api.py` 与本迭代文档。根代理审阅确认 `_persist_source_asset_specs()` 仅将 `params.get("contract_metadata")` 保存为 `raw_metadata` 并对经 `dict` 验证的同一对象 shallow-copy；user/workspace 查询、server-owned early return、resolved-spec alias/merge/source、changed 判定、`unit.params` 写回和 async transaction 均未改。

根代理在隔离 pycache 下运行本地 SQLite/fake gateway 的 `test_portfolio_positions_persist_gateway_asset_specs_to_workspace_unit`，结果为 1 passed、1 条既有 Backtrader Quandl deprecation warning；它继续断言写回的 multiplier、margin、commission 和 `stale_local+ctp_gateway` source。目标 `api.py` Mypy 仅余 4 条非 T46 错误，精确 `dict()` `[arg-type]` 为 0；Ruff check/format、target `git diff --check` 通过。T46 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 394 errors / 90 files（625 checked，退出码 1）。与 T45 比较，原始和标准化清单均仅移除 1 条 `dict()` `[arg-type]`，没有新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实数据库、网关、交易、网络、行情或供应商系统。

## T45：position-log tuple 状态表局部身份验收（2026-09-21）

范围仅为 `src/backend/app/services/trading_workspace_service.py`、`src/backend/app/api/portfolio/api.py` 与本迭代文档。根代理审阅确认两处 `_latest_position_rows()` 仍使用原有四张状态表和 tuple 形状；T45 只把来自不同表的候选读取分为按 direction 的 flat、按 symbol 的 flat、按 key 的 non-flat 与按 symbol 的 non-flat 等独立局部变量。所有 timestamp/index 比较、long/short 双边保留、无方向 flat 覆盖、方向 flat 仅覆盖本 side、`selected` 构建及排序均保持。

根代理在隔离 pycache 下运行 workspace 的 dual-side/Bybit/directional-flat 三项，以及 portfolio 的 dual-side/Bybit/两条 flat/directional-flat 五项，结果为 8 passed、1 条既有 Backtrader Quandl deprecation warning。两文件精确 Mypy 仅保留 7 条非 T45 诊断，6 条目标 tuple `[assignment]` 均为 0；Ruff check/format、target `git diff --check` 通过。T45 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异的唯一 `Any` 命中是 T43 已有的 `_runtime_config_for_instance()` 返回注解，T45 未改动它。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 395 errors / 90 files（625 checked，退出码 1）。与 T44 比较，原始和标准化清单均仅移除 6 条 tuple `[assignment]`，没有新增诊断。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T44：合约 metadata 单次读取与浅拷贝边界验收（2026-09-21）

范围仅为 `src/backend/app/services/trading_workspace_service.py`、`src/backend/tests/test_trading_workspace_service.py` 与本迭代文档。根代理审阅确认两个同步 helper 均先将 `params.get("contract_metadata")` 保存为局部值，且只在该值为 `dict` 时创建原有浅拷贝；server-owned/空输入短路、alias、asset-spec merge/source、changed 判定和 `unit.params` 写回时机均未改。没有修改 `_safe_dict()`、manager、gateway、persistence、API/schema、模型、配置、依赖或迁移。

根代理在隔离 pycache 下运行两个新增 instance/spec metadata merge fixture，以及最小 StartResult、runtime metadata sync、after-start asset-spec 三条相邻回归，结果为 5 passed、1 条既有 Backtrader Quandl deprecation warning。新 fixture 锁定已有 `IF2609` multiplier/margin、添加 commission/source 组合以及 `RB2610` 兄弟 metadata 保持。目标 Mypy 保留 5 条既有非 T44 错误，但两条精确 `dict()` `[arg-type]` 已为 0；Ruff check/format、target `git diff --check` 均通过，新增差异没有 `Any`、`cast`、`type: ignore` 或 `# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 401 errors / 90 files（625 checked，退出码 1）。与 T43 比较，原始错误数减 2，标准化诊断清单没有新增；因两条修复诊断文本相同，去重后的清单移除 1 个签名。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T43：live trading 实例只读 Mapping 边界验收（2026-09-21）

范围只包括 `src/backend/app/api/portfolio/api.py`、`src/backend/app/services/trading_workspace_service.py`、`src/backend/tests/test_portfolio_api.py`、`src/backend/tests/test_trading_workspace_service.py` 与本迭代文档。根代理审阅确认所有 manager record consumer 都只读 `Mapping[str, object]`；`start_units()` 的 started handoff 显式覆盖已运行 `InstanceData`、正常 `StartResult` 和 already-running refresh，不增加 manager 调用。唯一会写入 record 的既有 `persist_asset_specs()` 只接收 `dict(instance)` 局部浅拷贝，后续 unit metadata sync、snapshot、状态和 run_count 顺序保持。

根代理独立运行目标两文件 Mypy：命令仍以 15 条既有非 T43 错误退出 1，但 T42 明确列出的 11 条 `InstanceData`/`StartResult` 到可变 dict 的诊断为 0。独立隔离 pycache 下 5 项回归通过、1 条既有 Backtrader Quandl deprecation warning，覆盖 TypedDict/bare-dict batch lookup、最小 StartResult snapshot、already-running、runtime contract sync 和 persistence。Ruff check/format、target `git diff --check`、全迭代文档 whitespace 和新增 diff suppression 检查通过；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 403 errors / 90 files（625 checked，退出码 1）。与 T42 的原始计数相比净减 19：11 条受控合同错误及 8 条 portfolio params `[union-attr]` 消失；标准化清单差分没有无关新增。完整静态门禁仍为 FAIL / NO-GO；未运行全量 pytest，也没有连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T42：动态 live trading manager shim 静态入口补充验收（2026-09-21）

范围仅为新增 `app/services/live_trading_manager.pyi`、新增 `tests/test_live_trading_manager_runtime_shim.py` 与本迭代文档。根代理独立审阅确认 sibling stub 只精确 re-export canonical `LiveTradingManager` 和 `get_live_trading_manager`；运行时 `.py` 仍以 `sys.modules` 指向 canonical module，未改 singleton、manager、调用方、网关、交易、API、模型、配置、依赖、数据库 schema 或迁移。

stub 精确 Mypy 为 0；identity fixture 为 1 passed、1 条既有 Backtrader Quandl deprecation warning，根代理另以不调用 factory 的原始 import identity 断言复验 module/class/factory 均相同。Ruff check/format、untracked whitespace 与新增 diff 抑制扫描通过，未引入 `Any`、`__getattr__`、wildcard import、`cast`、`type: ignore` 或 `# noqa`。11 个直接 importer 的独立 Mypy 检查为 47 条其他错误/6 文件，没有 legacy shim `[attr-defined]` 或新 class/factory 调用签名错误；未构造 manager 或连接真实网关、交易、数据库、网络、行情或供应商系统。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 422 errors / 90 files（625 checked，退出码 1）。与 T41 的标准化清单差分没有无关新增：15 条 shim `[attr-defined]` 消失，同时揭露 11 条真实 `InstanceData | None` 到 dict 接口错误（`api/portfolio/api.py` 1、`trading_workspace_service.py` 10）；净减 4 条。完整静态门禁继续为 FAIL / NO-GO，11 条真实合同债务记入 QD-200-48。

## T41：自定义因子一元正负精确分派补充验收（2026-09-21）

范围仅为 `app/services/factor_lib/custom.py`、`tests/test_factor_correlation.py` 与本迭代文档。根代理独立审阅确认，evaluator 仅在既有 `ast.UnaryOp` 分支中对 `ast.UAdd`/`ast.USub` 显式调用 `operator.pos`/`operator.neg`；`_validate_node()` 与一元 allowlist 未改，其他 unary node 继续拒绝。四则/幂算术、缺值 record 的 `None` 降级、unsafe expression 的 degraded 结果、API、schema、registry、配置、依赖、数据库 schema 与迁移均未改变。

根代理独立复验目标精确 Mypy 为 0；隔离 `PYTHONPYCACHEPREFIX` 的完整 factor fixture 为 9 passed、1 条既有 Backtrader Quandl deprecation warning，新增参数化断言 `+close`/`-close` 和缺值 record。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过，未引入新的 `Any`、`cast`、`type: ignore` 或 `# noqa`；`_eval_node` 没有外部调用方。未连接真实数据库、网络、行情或交易系统。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 426 errors / 95 files（625 checked，退出码 1）。与 T40 的标准化清单差分无新增诊断，仅移除 `factor_lib/custom.py` 的 unary `[operator]`；全量静态门禁继续为 FAIL / NO-GO。

## T40：网关合约正数判定可空值补充验收（2026-09-21）

范围仅为 `app/services/gateway/runtime.py`、新增 `tests/test_gateway_runtime_contracts.py` 与本迭代文档。根代理独立审阅确认，唯一生产修改把 `value in (None, "")` 改为显式 `value is None or value == ""`；因此 float 转换前的 None 被明确跳过，空字符串、`TypeError`/`ValueError` 回退、零/负数拒绝和任一后续正数候选通过均保持。未修改 asset spec 来源/顺序、gateway 启动、账户/订单/行情连接、交易、API、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验目标精确 Mypy 为 0；隔离 `PYTHONPYCACHEPREFIX` 的直接参数化 fixture 为 5 passed、1 条既有 Backtrader Quandl deprecation warning，覆盖 None/空字符串、后续正数、TypeError、ValueError、零与负数。Ruff check/format、tracked/untracked diff whitespace 与新增 diff 抑制扫描均通过，未引入新的 `Any`、`cast`、`type: ignore` 或 `# noqa`。未连接真实网关、交易、数据库、网络、行情或供应商系统。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 427 errors / 96 files（625 checked，退出码 1）。与 T39 的标准化清单差分无新增诊断，仅移除 `gateway/runtime.py` 的 float `[arg-type]`；全量静态门禁继续为 FAIL / NO-GO。

## T39：run record pipeline 单次读取补充验收（2026-09-21）

范围仅为 `app/services/research/run_records.py`、新增 `tests/test_ai_research_run_records.py` 与本迭代文档。根代理独立审阅确认，helper 将 `raw.get("pipeline")` 读取一次；仅在值为字典时调用 `get("current_stage")`，缺失、null 和非字典继续等效为空字典。`force=True`、非过期状态、ready 为真和 `live_candidate` 的原有短路结果、persist 决策、run record/paper/live handoff、API、模型、配置、依赖、数据库 schema 与迁移均未改变。

根代理独立复验目标精确 Mypy 为 0；隔离 `PYTHONPYCACHEPREFIX` 的直接参数化 fixture 为 8 passed、1 条既有 Backtrader Quandl deprecation warning，覆盖缺失、null、非字典、空/合法字典、live candidate、ready、force 及非过期状态。Ruff check/format、tracked/untracked diff whitespace 与新增 diff 抑制扫描均通过，未引入新的 `Any`、`cast`、`type: ignore` 或 `# noqa`。未连接真实数据库、网络、模型供应商、行情或交易系统。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 428 errors / 97 files（625 checked，退出码 1）。与 T38 的标准化清单差分无新增诊断，仅移除 `run_records.py` 的 pipeline `[union-attr]`；全量静态门禁继续为 FAIL / NO-GO。

## T38：holdout journal lease 到期时间失败关闭补充验收（2026-09-21）

范围仅为 `app/services/research/holdout_execution_journal.py` 与本迭代文档。根代理独立审阅确认，`prepare()` 在把 live binding 的 `lease_expires_at` 交给 `_as_utc(datetime)` 前，先保存至局部变量并重复执行既有 `HOLDOUT_EXECUTION_PREPARE_DENIED` 失败关闭；状态机、lease 比较、幂等性、record/journal 写入、evaluator、API、模型、配置、依赖、数据库 schema 与迁移均未改变。

根代理独立复验目标精确 Mypy 为 0；隔离 `PYTHONPYCACHEPREFIX` 的完整 `test_ai_research_holdout_execution_journal.py` 为 7 passed、1 条既有 Backtrader Quandl deprecation warning，覆盖 prepare 持久化、幂等及无效 binding 拒绝。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过，未引入 `Any`、`cast`、`type: ignore` 或 `# noqa`。未连接真实数据库、网络、模型供应商、行情或交易系统。

完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 为 429 errors / 98 files（625 checked，退出码 1）。与 T37 的标准化清单差分无新增诊断，仅移除 `holdout_execution_journal.py` 的 lease `[arg-type]`；全量静态门禁继续为 FAIL / NO-GO。

## T37：LLM 成对用量 TypeGuard 补充验收（2026-09-21）

范围仅为 `app/services/research/llm_gateway.py` 与本迭代文档。根代理独立审阅确认唯一生产逻辑形状变化是新增 `_is_non_negative_token_count(value: object) -> TypeGuard[int]`，其函数体严格使用 `type(value) is int and value >= 0`；每个 usage pair 先取具名值、验证、再相加。pair 顺序、total_tokens 一致性、None 的 `LLM_PROVIDER_USAGE_UNVERIFIED`、quota settlement、审计/redaction、provider/API、模型、配置、依赖、数据库 schema 与迁移均未改变。

根代理独立复验目标精确 Mypy 为 0；隔离 `PYTHONPYCACHEPREFIX` 的完整 `test_ai_research_llm_gateway.py` 为 70 passed、1 条既有 Backtrader Quandl deprecation warning，涵盖有效 12/5 结算及 bool、缺项、负数、总量不一致的失败关闭。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；源文件 `Any` 词出现次数为变更前后均 26，未引入新 Any/cast/ignore/noqa。未连接真实数据库、网络、模型供应商、行情或交易系统。

T37 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 430 errors in 99 files (checked 625 source files)`。与 T36 的标准化错误清单比较没有新增诊断，唯一移除的是 `llm_gateway.py` 对 `Any | None` usage pair 使用 sum 的 1 条 `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T36：文件系统回执 SHA-256 TypeGuard 补充验收（2026-09-21）

范围仅为 `app/services/research/filesystem_dataset_resolver.py`、`tests/test_ai_research_filesystem_dataset_resolver.py` 与本迭代文档。根代理独立审阅确认唯一生产源码变更是从 `typing` 导入 TypeGuard，并将 `_valid_sha256(value: object)` 的既有 bool 声明替换为 `TypeGuard[str]`；函数体的 isinstance、64 位长度和小写 hex 规则、后续 canonical record hash、constant-time `compare_digest` 及所有失败关闭异常均未改。未修改回执 schema、文件根/权限、路径/描述符操作、API、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验目标精确 Mypy 为 0；新增 public fixture 将 receipt_hash 设为 null 但不改变字段集，完整 `test_ai_research_filesystem_dataset_resolver.py` 为 9 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；源文件 `Any` 词出现次数为变更前后均 9，未引入新 Any/cast/ignore/noqa。未连接真实数据库、网络、模型供应商、行情或交易系统。

T36 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 431 errors in 100 files (checked 625 source files)`。与 T35 的标准化错误清单比较没有新增诊断，唯一移除的是 `filesystem_dataset_resolver.py` 中 compare_digest 前 receipt_hash 未静态收窄的 1 条 `[type-var]`；完整门禁继续 FAIL / NO-GO。

## T35：日志 fallback 指标可空序列补充验收（2026-09-21）

范围仅为 `app/services/log_parser_service.py`、`tests/test_log_parser.py` 与本迭代文档。根代理独立审阅确认 fallback 分支的唯一行为相关调整是使用 `bar_indicators: dict[str, list[float | None]]` 和 `bar_values` 局部名称；它仍按日期优先、索引回退取得指标，仍对后出现指标补前序 `None`，并保持 JSON/pipe bar、indicator、OHLCV、volume 和 TSV 分支不变。未修改 parser 之外的服务、API、schema、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `app/services/log_parser_service.py` 精确 Mypy 为 0。新回归 fixture 证明首日无指标、第二日 fast_ma 出现时仍输出 `[None, 1.16]`；隔离 `PYTHONPYCACHEPREFIX` 的完整 `test_log_parser.py test_log_parser_extended.py test_log_parser_service_edge_cases.py` 为 56 passed、2 条既有 warnings：Backtrader Quandl deprecation 及 drawdown 分析对全 NaN slice 的 RuntimeWarning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T35 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 432 errors in 101 files (checked 625 source files)`。与 T34 的标准化错误清单比较没有新增诊断，唯一移除的是 `log_parser_service.py` fallback 的 4 条 `[list-item]`、`[assignment]`、`[attr-defined]`、`[no-redef]`；完整门禁继续 FAIL / NO-GO。

## T34：AI 策略改稿 metadata 异构值容器补充验收（2026-09-21）

范围仅为 `app/services/research/generation.py` 与本迭代文档。根代理独立审阅确认 `_merge_ai_improvement()` 的唯一运行时相关变更是 metadata 局部变量标注为 `dict[str, object]`；source、provider、model_id 和条件性 total_tokens 写入的键、值、分支及 `StrategyImprovement` 构造均未改变。未修改模型响应解析、策略改稿、代码/参数校验、回退、API、schema、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `app/services/research/generation.py` 精确 Mypy 为 0，既有 `test_ai_strategy_improver_uses_model_json_to_rewrite_strategy` 为 1 passed、1 条既有 Backtrader Quandl deprecation warning，并继续断言 `total_tokens == 123`。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、模型供应商、行情或交易系统。

T34 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 436 errors in 102 files (checked 625 source files)`。与 T33 的标准化错误清单比较没有新增诊断，唯一移除的是 `generation.py` 中 int `total_tokens` 写入被推断为 string dict 的 1 条 `[assignment]`；完整门禁继续 FAIL / NO-GO。

## T33：压力测试 scenarios 协变 Sequence 合同批次补充验收（2026-09-21）

范围仅为 `app/services/risk_analytics/stress_test.py` 与本迭代文档。根代理独立审阅确认 `run_scenarios()` 与私有 `_normalize_scenarios()` 的 scenarios 均改为 `Sequence[dict | StressScenario] | None`；两个函数仍只遍历输入并创建新的 normalized list，未修改 API、schema、built-in scenario、dict 归一化、equity/指标计算、输出、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `app/services/risk_analytics/stress_test.py app/api/risk_analytics.py` 联合精确 Mypy 为 0，完整 `tests/test_risk_analytics_stress_test.py` 为 5 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T33 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 437 errors in 103 files (checked 625 source files)`。与 T32 的标准化错误清单比较没有新增诊断，唯一移除的是 API 将 `list[StressScenario]` 传入不变 service list 的 1 条 `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T32：legacy evidence-gate target Iterable 合同批次补充验收（2026-09-21）

范围仅为 `app/services/market_data/legacy_stock_daily_evidence_gate_adapter.py` 与本迭代文档。根代理独立审阅确认唯一语义相关注解变化是私有 `_assert_isolated_unverified_targets()` 的 targets 参数从 `Sequence` 改为 `Iterable`；其函数体仍仅逐项调用 `_assert_target_source_binding()`，未修改 source provenance、fail-closed 错误、read authorization、source batch/permit、store、API、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验目标精确 Mypy 为 0，使用新建隔离 `PYTHONPYCACHEPREFIX` 的完整 `tests/market_data_platform/test_legacy_stock_daily_import_adapter.py` 为 16 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T32 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 438 errors in 104 files (checked 625 source files)`。与 T31 的标准化错误清单比较没有新增诊断，移除的是一个出现在两个调用行的 ValuesView-to-Sequence `[arg-type]` 签名；因此标准化差分为 1 条、完整错误计数实际减少 2 条。完整门禁继续 FAIL / NO-GO。

## T31：AkShare engine kwargs 异构值容器批次补充验收（2026-09-21）

范围仅为 `app/db/akshare_data_database.py` 与本迭代文档。根代理独立审阅确认唯一源码变更是 `extra_kwargs: dict[str, object]`；两个现有互斥分支仍分别传递 `poolclass=NullPool` 与 `pool_pre_ping=True`，未修改 URL 解析、engine/sessionmaker singleton、连接、调用方、API、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `akshare_data_database.py` 精确 Mypy 为 0，Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过。首次完整 `tests/test_akshare_management_api.py` 在默认 bytecode cache 下退出码 1，141 个 fixture setup errors 的共同根因是 `inspect.getsourcelines()` 读取到测试函数指向不存在的 `/private/tmp/ai-for-investor-final.E0zN2K/...` 历史 `co_filename`；未删除或改写任何现有 pycache。使用新建隔离 `PYTHONPYCACHEPREFIX` 后，完整 fixture 为 66 passed、79 skipped、2 warnings（Backtrader Quandl deprecation；`test_execute_callable_times_out_threaded_function` 观测到 pytest-rerunfailures 的 `run_connection` 线程 warning），无测试失败。未连接真实 MySQL、网络、行情或交易系统。

T31 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 440 errors in 105 files (checked 625 source files)`。与 T30 的标准化错误清单比较没有新增诊断，唯一移除的是非 MySQL bool 写入 kwargs 的 1 条 `[assignment]`；完整门禁继续 FAIL / NO-GO。

## T30：calendar manifest 默认 literal 类型批次补充验收（2026-09-21）

范围仅为 `app/services/market_data/calendar_importer.py` 与本迭代文档。根代理独立审阅确认唯一改动是 `MANIFEST_VERSION: Literal["market-data-calendar-v1"]`，其字符串值未变，MarketDataCalendarManifest 仍引用同一常量作为 literal 字段默认值；未修改 strict model、calendar loader、日期/时区/coverage 验证、事务、publication、API、模型、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `calendar_importer.py` 精确 Mypy 为 0，完整 `tests/market_data_platform/test_calendar_importer.py` 为 13 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T30 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 441 errors in 106 files (checked 625 source files)`。与 T29 的标准化错误清单比较没有新增诊断，唯一移除的是 calendar manifest 默认 string-to-literal 的 1 条 `[assignment]`；完整门禁继续 FAIL / NO-GO。

## T29：缓存单例 Redis/内存联合类型批次补充验收（2026-09-21）

范围仅为 `app/db/cache.py` 与本迭代文档。根代理独立审阅确认改动仅为 `_cache_instance: RedisCache | MemoryCache | None` 与 `get_cache() -> RedisCache | MemoryCache`；默认 Redis_URL 分支、首次创建、后续单例复用、两种 cache 实现及其惰性 Redis import 均未变，未修改调用方、配置、依赖、API、数据库 schema 或迁移。

根代理独立复验 `cache.py` 精确 Mypy 为 0，完整 `tests/test_cache.py tests/test_cache_extended.py` 为 17 passed、1 条既有 Backtrader Quandl deprecation warning。测试默认走内存缓存，Redis 分支使用 patched constructor；Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过，未连接真实 Redis、数据库、网络、行情或交易系统。

T29 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 442 errors in 107 files (checked 625 source files)`。与 T28 的标准化错误清单比较没有新增诊断，唯一移除的是 MemoryCache 赋给 Redis-only singleton 的 1 条 `[assignment]`；完整门禁继续 FAIL / NO-GO。

## T28：主数据 manifest literal 与类别计数类型批次补充验收（2026-09-21）

范围仅为 `app/services/market_data/master_data_importer.py` 与本迭代文档。根代理独立审阅确认 `ManifestVersion` 是实际 `Literal["market-data-master-v1"]`，常量 wire value 未变；Counter 仍以每个 prepared identity 的 asset_type 更新，只明确容器键为 `str`。未修改 Pydantic strict manifest、七类计数/排序、导入事务、writer/publication、schema、模型、API、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `master_data_importer.py` 精确 Mypy 为 0，完整 `tests/market_data_platform/test_master_data_importer.py` 为 8 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T28 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 443 errors in 108 files (checked 625 source files)`。与 T27 的标准化错误清单比较没有新增诊断，唯一移除的是 manifest Literal 的 `[valid-type]` 与 Counter-to-dict 的 `[arg-type]` 两条错误；完整门禁继续 FAIL / NO-GO。

## T27：股票研究兼容层 reconciliation payload 类型批次补充验收（2026-09-21）

范围仅为 `app/services/asset_research/stock_compat.py` 与本迭代文档。根代理独立审阅确认变更只把 `legacy` local dict 标注为 `dict[str, object]`；legacy/generic 的五个既有字段值、mapping version、记录顺序和 `reconcile_batch()` 调用全部保持原状，未改 stock signal service、schema、模型、API、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `stock_compat.py` 精确 Mypy 为 0，完整 `tests/asset_research/test_stock_compat.py` 为 2 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T27 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 445 errors in 109 files (checked 625 source files)`。与 T26 的标准化错误清单比较没有新增诊断，唯一移除的是 legacy payload append 的 1 条 `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T26：市场数据授权 principal 类型批次补充验收（2026-09-21）

范围仅为 `app/api/data/deps.py`、`tests/test_data_management_deps.py` 与本迭代文档。根代理独立审阅确认 `principal_for_user()` 既有返回类型为 `MarketDataPrincipal`；改动仅恢复 helper tuple 的精确注解，未改变调用顺序、403 映射或授权器实现。

根代理独立复验 `app/api/data/deps.py` 精确 Mypy 为 0，完整 `tests/test_data_management_deps.py` 为 4 passed、1 条既有 Backtrader Quandl deprecation warning。新增 fake authorizer fixture 证明同一 principal 依次通过 read check 并成为 access context 的 principal。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T26 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 446 errors in 110 files (checked 625 source files)`。与 T25 的标准化错误清单比较没有新增诊断，唯一移除的是 access context 接收 object principal 的 1 条 `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T25：监控规则可空 description 契约批次补充验收（2026-09-21）

范围仅为 `app/services/monitoring_service.py`、`tests/test_monitoring_api.py` 与本迭代文档。根代理独立审阅确认 schema 的 description 已是 `str | None`、AlertRule 数据库列 nullable=True；服务签名现与该既有合同相符，API 实现没有被改成空字符串 fallback。

根代理独立复验 `app/api/monitoring.py` 精确 Mypy 为 0；`app/services/monitoring_service.py` 仍报告 15 条本批前已存在的 ORM Column、Optional 和 local inference 诊断，均未修改或掩盖。完整 `tests/test_monitoring_api.py` 为 49 passed、7 条既有 warning；新增 fixture 验证 client 省略 description 时 mock service 收到 None 且 response JSON 为 null。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T25 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 447 errors in 111 files (checked 625 source files)`。与 T24 的标准化错误清单比较没有新增诊断，唯一移除的是 API 调用 monitoring service 的 1 条 nullable description `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T24：版本参数 diff 容器类型批次补充验收（2026-09-21）

范围仅为 `app/services/version_diff_service.py` 与本迭代文档。根代理独立审阅确认 diff 的四个分类和所有赋值/比较分支未改；新注解恰好等同函数原有声明返回结构，未触及策略版本调用方或持久化。

根代理独立复验 `version_diff_service.py` 精确 Mypy 为 0，完整 `tests/test_version_diff_service.py` 为 18 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T24 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 448 errors in 112 files (checked 625 source files)`。与 T23 的标准化错误清单比较没有新增诊断，唯一移除的是版本参数 diff local container 的 1 条 `[var-annotated]`；完整门禁继续 FAIL / NO-GO。

## T23：日志查询参数脱敏类型批次补充验收（2026-09-21）

范围仅为 `app/middleware/logging.py`、`tests/test_logging_middleware.py` 与本迭代文档。根代理独立审阅确认 local dict 的唯一变化是类型声明；敏感字段继续使用既有 `***REDACTED***` 文本，单值与重复非敏感值分别沿用字符串和字符串列表，之后仍返回字符串化 dict。

根代理独立复验 `logging.py` 精确 Mypy 为 0，完整 `tests/test_logging_middleware.py` 为 8 passed、1 条既有 Backtrader Quandl deprecation warning。新测试使用无效占位 token，断言输出只含遮蔽文本并保留普通重复 tag 列表。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T23 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 449 errors in 113 files (checked 625 source files)`。与 T22 的标准化错误清单比较没有新增诊断，唯一移除的是日志 helper 的 1 条 string/list dict assignment；完整门禁继续 FAIL / NO-GO。

## T22：分析服务复利与均线类型批次补充验收（2026-09-21）

范围仅为 `app/services/analytics_service.py`、`tests/test_analytics_service.py` 与本迭代文档。根代理独立审阅确认两处修改均为局部类型标注：复利起始值从语义等价的 `1` 变为显式 `float` 的 `1.0`，均线占位结果变为明确的 nullable-float 列表；计算/输出控制流未改。

根代理独立复验 `analytics_service.py` 精确 Mypy 为 0，完整 `tests/test_analytics_service.py` 为 22 passed、1 条既有 Backtrader Quandl deprecation warning；新增断言锁定 0.05、-0.02、0.03 的复利结果。Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描均通过；未连接真实数据库、网络、行情或交易系统。

T22 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 450 errors in 114 files (checked 625 source files)`。与 T21 的标准化错误清单比较没有新增诊断，唯一移除的是分析服务的 1 条累计赋值与 1 条均线返回类型错误；完整门禁继续 FAIL / NO-GO。

## T21：增强回测请求服务契约批次补充验收（2026-09-21）

范围仅为 `app/api/backtest_enhanced.py`、`tests/test_backtest_enhanced.py` 与本迭代文档。根代理独立审阅确认：既有 `model_fields_set` 的 runtime_dir 422 拒绝先执行；成功路径才以 `ServiceBacktestRequest.model_validate(request.model_dump())` 生成基础服务模型，并沿用既有 BacktestService 调用、任务事件与响应路径。未修改 BacktestService、任一请求 schema、配置、依赖、数据库 schema 或迁移。

根代理独立复验 `backtest_enhanced.py` 精确 Mypy 为 0，Ruff check/format、tracked diff whitespace 与新增 diff 抑制扫描通过。通过 FastAPI dependency override 的两项新增测试为 2 passed、1 条既有 Backtrader Quandl deprecation warning：成功路径确认 service 接收基础模型及保留字段，client runtime_dir 路径仍返回既有 422 且 mock service 不被 await。完整 `tests/test_backtest_enhanced.py` 由实现执行器复验为 52 passed、5 条既有 warning（Quandl 1、Starlette 422 常量弃用 4）；未连接真实数据库、网络、行情或交易系统。

T21 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 452 errors in 115 files (checked 625 source files)`。与 T20 的标准化错误清单比较没有新增诊断，唯一移除的是增强请求传入基础 BacktestService 的 1 条 `[arg-type]`；完整门禁继续 FAIL / NO-GO。

## T20：动态策略服务 shim 静态接口批次补充验收（2026-09-21）

范围仅为新增 `app/services/strategy_service.pyi`、新增 `tests/test_strategy_service_runtime_shim.py` 与本迭代文档。根代理独立审阅确认 sibling stub 仅显式转发 canonical `strategy.core` 的八个 `__all__` export，未改 `strategy_service.py` runtime replacement、canonical core、调用方、配置或依赖。

根代理独立复验 stub/core 精确 Mypy 为 0；runtime identity 和既有 `tests/test_strategy_service_scan_edge_cases.py` 为 9 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked `git diff --check`、untracked whitespace check 与新增 diff 抑制扫描均通过。identity fixture 断言 legacy module 等于 core，`__all__` 和八个 export 均保持同一对象；没有新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、`__getattr__` 或 wildcard import。未连接真实数据库、网络、行情或交易系统。

T20 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 453 errors in 116 files (checked 625 source files)`。相较 T19，20 条动态 shim `[attr-defined]` 误报全部消失，标准化清单不存在新增诊断；完整门禁继续 FAIL / NO-GO。

## T19：参数优化 FAILED 回测结果批次补充验收（2026-09-21）

范围仅为 `app/services/param_optimization_service.py`、`tests/test_optimization_api.py` 与本迭代文档。根代理独立审阅确认：初始和轮询后的 FAILED 状态都委托给同一 async message helper；非空字符串错误信息沿用原文本，缺失结果或空/None 消息均返回稳定 `Backtest failed: result unavailable`。COMPLETED、CANCELLED、PENDING/RUNNING 和 timeout 分支未改。

根代理独立复验目标 `[union-attr]` 不再出现；`param_optimization_service.py` 的精确 Mypy 仍只报告一条既有 `strategy_service.get_strategy_dir` 动态导出 `[attr-defined]`。完整 `tests/test_optimization_api.py` 为 48 passed、1 条既有 Backtrader Quandl deprecation warning；Ruff check/format、tracked `git diff --check` 与新增 diff 抑制扫描通过。新增 fixture 覆盖轮询 FAILED 但无结果的 fallback，以及初始 FAILED 保留原错误消息；未连接真实数据库、网络、行情或交易系统。

T19 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 473 errors in 120 files (checked 625 source files)`。与 T18 的标准化错误清单相比不存在新增诊断，唯一移除的是 FAILED 分支的 1 条 `BacktestResult | None` 属性访问错误；完整门禁继续 FAIL / NO-GO。

## T18：比较创建可空回测结果批次补充验收（2026-09-21）

范围仅为 `app/services/comparison_service.py`、`tests/test_comparison_service.py` 与本迭代文档。根代理独立审阅确认：实现不以 cast/断言假定结果存在，而是在每个输入位置的单次 `get_result()` 后立即检查 `None` 并构造原字段齐全的 payload；缺失任务仍抛原 `ValueError`，重复 task ID 不被去重或重排。

根代理独立复验 comparison-service 精确 Mypy 中原第 78–89 行的 12 条 `[union-attr]` 均不再出现；该文件剩余 18 条非目标历史错误保留。`tests/test_comparison_service.py` 为 30 passed、1 条既有 Backtrader Quandl deprecation warning；Ruff check/format、tracked `git diff --check` 与新增 diff 抑制扫描通过。新增 fixture 将第二个 mock 返回设为 `None` 并断言成功路径只 await 一次，证明没有验证后第二次读取。未连接真实数据库、网络、行情或交易系统。

T18 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 474 errors in 120 files (checked 625 source files)`。与 T17 清单移除行号后比较，不存在新增诊断，唯一移除的是 12 条 `BacktestResult | None` 属性访问错误；完整门禁继续 FAIL / NO-GO。

## T17：动态回测服务 shim 静态接口批次补充验收（2026-09-20）

范围仅为新增 `app/services/backtest_service.pyi`、新增 `tests/test_backtest_service_runtime_shim.py` 与本迭代文档。根代理逐段审阅确认 stub 只显式转发 canonical `BacktestService`，未改 `backtest_service.py` 的 runtime module replacement、canonical 回测服务、调用方、配置或依赖。

根代理独立复验 stub 精确 Mypy 为 0，runtime identity 加既有 `tests/test_backtest_service.py` 为 46 passed、1 条既有 Backtrader Quandl deprecation warning；Ruff check/format、tracked `git diff --check`、untracked whitespace check 与新增 diff 抑制扫描均通过。identity fixture 断言 legacy 模块即 canonical service，且二者的 `BacktestService` 为同一 class；没有新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、`__getattr__` 或 wildcard import。未连接真实数据库、网络、行情或交易系统。

T17 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 486 errors in 120 files (checked 625 source files)`。相较 T16，11 条动态 shim `[attr-defined]` 误报消失，却因真实 class 合同可见而新暴露 14 条调用方错误（比较服务 12、优化服务 1、增强回测 API 1）；故 raw 总数从 483 上升至 486，不能表述为全局净改善。完整门禁继续 FAIL / NO-GO。

## T16：告警规则配置与类型失败关闭批次补充验收（2026-09-20）

范围仅为 `app/services/alert_evaluation.py`、新增 `tests/test_alert_evaluation_type_boundaries.py` 与本迭代文档。根代理逐段审阅确认：Protocol 仅呈现评估入口读取的 AlertRule 标量字段，Mapping 配置只复制字符串键并沿用既有 helper；未修改模型、MonitoringService、API、schema、迁移、配置、依赖或指标服务接口。

根代理独立复验 `app/services/alert_evaluation.py` 精确 Mypy 为 0，Ruff check/format、tracked `git diff --check`、untracked test whitespace check 通过，新增 diff 没有 `cast(Any)`、`type: ignore` 或新的 `# noqa`。新增 4 项 fixture 证明：list 配置不调用 metric getter、cross 的 `None` 不改变状态、`current_value=None` 返回 `None`、未知 alert type 在调用下游服务前返回 `None`；与既有告警/异常 fixture 合跑为 96 passed、1 条既有 Backtrader Quandl deprecation warning。未连接真实数据库、网络、行情或交易系统。

T16 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 483 errors in 121 files (checked 625 source files)`。相较 T15 减少 6 errors、1 个报错文件；目标 `app/services/alert_evaluation.py` 已退出错误清单。完整门禁继续是 FAIL / NO-GO。

## T1：后端类型债务批次补充验收（2026-09-20）

本批次限定修复 12 个源文件：`app/services/process_supervisor.py`、`app/services/market_data/multi_record_contracts.py`、`app/services/ctp_tunnel.py`、`app/services/instance_store.py`、`app/services/stock_analysis/pipeline.py`、`app/services/research/model_budget.py`、`app/services/research/http_holdout_executor.py`、`app/services/research/http_discovery_sandbox.py`、`app/services/research/openai_compatible_provider.py`、`app/services/research/holdout_worker_process.py`、`app/research_deployments/holdout.py`、`app/research_deployments/discovery.py`，以及 `pyproject.toml` 中 AnyIO 运行时依赖声明。数值校验仍拒绝 bool、非有限值和越界值；Windows 特有 API 在缺失时受控失败并保持锁/隐藏窗口语义；B2 selector、CTP socket/callback 与 action label 使用显式契约。

为兼容项目 Python `>=3.10`，三个 HTTP/provider 执行器使用同步 `with anyio.fail_after(...)`，并将 `anyio>=3.7.1,<5.0` 声明为直接运行时依赖；超时捕获与既有错误码语义未改。本次执行环境为 Python 3.11.8，实际 Python 3.10 解释器运行未验证。未改 Mypy/Ruff 配置，也未引入 `Any` cast、`type: ignore` 或测试跳过。

精确 Mypy 修复前为 12 文件 37 errors，修复后 0 errors；目标文件 Ruff check 与 `ruff format --check` 均通过。现有相关测试分组执行且逐用例有输出：process/instance/multi-record/gateway 113 passed；HTTP/provider/model_budget 88 passed；holdout/deployment/stock-analysis 55 passed；合计 256 passed、0 failed。三组各有同一个既有 backtrader Quandl deprecation warning。此前一次 14 文件聚合 `-q` 测试因长时间无逐用例输出被人工中断（约已到 56%，未观察到断言失败），不计为通过证据；上述三组是最终测试结果。

## T2：动态 API shim 静态接口补充验收（2026-09-20）

仅新增 `app/api/deps.pyi`，将 `deps.py` 的静态接口显式转发到 `app.api._dependencies`。转发涵盖 runtime 中的公开 API、认证/WebSocket/权限 helper 与 `Require*` 常量，以及调用/测试所需的 `_extract_websocket_token` 和 `decode_access_token`。未修改 `deps.py` 或 `_dependencies.py`；`sys.modules` 动态别名及模块身份语义保持原样，既有 `deps is _dependencies` 测试通过。stub 不包含 `Any`、`__getattr__`、ignore 或 wildcard import。

以 `app/api/deps.pyi` 为 Mypy 静态入口，覆盖全部 37 个直接导入 `app.api.deps` 的 API 文件和 `app/api/data/deps.py`（共 39 个检查源文件），确认 `Module "app.api.deps" has no attribute ...` 为 0。该检查退出码为 1，尚有 55 个其他既有错误分布于 15 个文件（例如 data access principal 类型、Service 属性和 ORM 列推断）；这些不计入 stub 关闭项。将 runtime `deps.py` 本身作为 Mypy CLI 输入会绕过 sibling stub 并再次解析动态 alias，因此不作为静态接口验收入口；单文件 stub Mypy 单独通过。

指定测试 62 passed、1 skipped、1 warning。唯一 skip 是 `test_misc_branch_fixes.py::test_drawdown_analyzer_updates_peak_branch` 的既有 skip（需要 backtrader strategy context）；`test_deps_get_current_user_delegates` 身份关系用例通过。全量 Mypy T2 后为 1027 errors / 145 files（扫描 625 个源文件），对比 T1 后 1072 errors / 168 files，观察到净减少 45 条错误及 23 个报错文件；全量门禁仍 FAIL / NO-GO，且不把全量差值单独归因于 shim。

## T3：数据抓取 MySQL 核心类型债务批次补充验收（2026-09-20）

仅修改 `src/backend/app/data_fetch/core/database.py`、`app/data_fetch/core/mysql_base.py`、`tests/test_data_fetch_common_utils.py` 和 Iteration200 文档。`Database.connection` / `cursor` 保持 Optional 状态字段，避免改变现有外部采集代码的 `is None` 连接分支；连接与游标静态接口由窄 Protocol 表达。`MysqlBase.connect_db` 实际检查 connector 连接状态、游标非空并在缺游标时恢复；pool wrapper 通过委托适配器保留 close/归还连接池语义，并对返回游标执行真实 `MySQLCursorAbstract` 类型检查。

`Database.save_data` / `MysqlBase.save_data` 的返回类型为 `int | Literal[False]`：成功仍返回写入行数，空或不可写仍返回 `False`。`fetchone()` 返回 `None` 或空行时，`get_latest_date` 返回 `None`；查询游标的 `description` 为 `None` 或空列表时，`get_data_by_columns` 返回空 DataFrame。未改 SQL、自动补列、提交/回滚顺序或错误捕获语义；未使用盲目 cast，也没有连真实 MySQL。

修复前两个目标文件精确 Mypy 为 49 errors，修复后 0 errors；Ruff check/format 均通过。指定 `tests/test_data_fetch_common_utils.py -vv` 为 11 passed、0 failed、1 个既有 backtrader Quandl deprecation warning；新增用例均使用 fake cursor/connection。

本批次随后执行一次全量 `mypy app`：退出码 1，`Found 984 errors in 143 files (checked 625 source files)`；较 T2 1027/145 观测净减少 43 个错误、2 个报错文件。全量仍 FAIL / NO-GO；T3 未涵盖的 provider/script consumer 错误中，三个指定 data-fetch consumer 随后由 T4 单独处理，其余范围外错误仍需治理。真实数据库连接、事务及服务器差异未验证。

## T4：AkShare data-fetch consumer 类型债务批次补充验收（2026-09-20）

范围仅为 `app/data_fetch/providers/akshare_to_mysql.py`、`app/data_fetch/providers/akshare_provider.py`、`app/data_fetch/utils/akshare_network_proxy.py`、直接测试 `tests/test_data_fetch_common_utils.py` / `tests/test_akshare_network_proxy.py`、新增 `tests/test_akshare_provider_storage.py` 和本迭代文档。T3 MySQL 核心文件和 `app/services/akshare/script.py` 均未改。

修复对齐了 T3 暴露的可空连接/游标与 `save_data` 联合返回类型；Akshare provider 使用窄 TypedDict/Protocol 并在 connector 结果进入操作前执行结构守卫，空 fetchone/fetchall 与缺失查询描述安全返回。SQL、有效输入的事务/异常语义未改；成功写入仍报告实际行数，空/无可写列返回 `False`。代理探测对 `requests.Session.get` 使用显式参数类型。未引入 Any/cast(Any)/type: ignore，未放宽 Mypy/Ruff 配置或修改依赖版本。

三目标文件精确 Mypy 基线为 55 errors：`akshare_to_mysql.py` 21、`akshare_provider.py` 21、`akshare_network_proxy.py` 13；修复后 0 errors / 3 source files。定向用例全用 fake/mock，不连接真实 MySQL、不调用 AkShare、不发出网络请求。

最终静态/测试结果：六个改动源/测试文件 Ruff check 与 format check 均通过；`test_data_fetch_common_utils.py`、`test_akshare_network_proxy.py` 和 `test_akshare_provider_storage.py` 合计 23 passed、0 failed、1 条 backtrader Quandl deprecation warning。唯一一次 T4 后全量 `mypy app` 退出码 1，`Found 929 errors in 140 files (checked 625 source files)`；相较 T3 984/143 观测净减少 55 条错误和 3 个报错文件，但无法据净差单独归因所有错误，完整门禁仍 FAIL / NO-GO。

## T5：股票分析 ORM 实例字段类型批次补充验收（2026-09-20）

初始精确 Mypy 覆盖 `app/models/stock_analysis.py`、`app/models/stock_signal.py` 和 `app/services/stock_analysis/tasks.py`，退出码 1，`Found 58 errors in 1 file`（均为任务服务消费 legacy ORM `Column[...]` 实例字段的静态类型错误）。根据父代理批准的最小扩展，另将 `app/models/knowledge_base.py` 中仅 `ChatMessage.metadata_json` 改为精确 `Mapped[dict[str, object] | None]` 映射；`tasks.py` 保留普通显式属性赋值，没有使用 `setattr` 动态规避。

四文件精确 Mypy 命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/stock_analysis.py app/models/stock_signal.py app/models/knowledge_base.py app/services/stock_analysis/tasks.py` 退出码 0：`Success: no issues found in 4 source files`。Ruff check 与 `ruff format --check` 对四个源文件及五个直接测试文件均退出码 0；format check 为 9 files already formatted。

股票分析任务/报告/导出及信号共五张表的 SQLAlchemy metadata signature 修改前后 SHA-256 均为 `5be915161e846230a3c84c51f95f1e6fffb38ce1f9b0fc11216adb37ec25a652`，表/列、SQL 类型、nullable/default/onupdate、主外键、index/unique 与约束元数据保持一致。SQLite metadata introspection 另确认 `ChatMessage.metadata_json` 属性的 SQL 列名/key 为 `metadata`、SQLAlchemy 类型 JSON、nullable 为 True；不是线上 schema 验收。

定向测试命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -vv tests/test_stock_analysis_tradingagents_compat.py tests/test_stock_signal_service.py tests/test_stock_signal_batch.py tests/test_stock_signal_outcomes.py tests/test_stock_signal_api.py` 退出码 0：`26 passed, 1 warning in 13.76s`。测试使用 in-memory SQLite/fake；`test_stock_analysis_from_ai_chat_generates_compat_report_and_exports` 读取持久化的 assistant 消息并断言 metadata 中 `assistant_mode`、task card 的 `task_id`/完成状态及 report ID 键值。唯一 warning 为既有 backtrader Quandl deprecation；没有连接真实数据库、调用外部 AI 或网络。

唯一一次 T5 后全量 Mypy 在 base 环境中通过 `subprocess.run([sys.executable, "-m", "mypy", "app"])` 执行，外层使用 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -c ...` 收集汇总；子进程退出码 1：`Found 849 errors in 136 files (checked 625 source files)`。四个 T5 目标文件均无全量错误。相较 T4 后观测值 929 errors / 140 files，净减少 80 errors、4 个报错文件；由于跨文件错误可能受上下文影响，不把全量净差全部归因于 T5。全量 Mypy 仍 FAIL / NO-GO。

按 T5 JSON 声明修正后，四文件精确 Mypy 仍为 0；该修正只调整 Python 注解，没有改变任何 `mapped_column(...)` 参数，前述 metadata signature 仍保持。tracked diff 的 `git diff --check` 退出码 0；迭代文档（此前未跟踪）另经 trailing-whitespace 扫描无匹配。本批次未改数据库迁移、其他 knowledge-base 字段/调用方、Mypy/Ruff 配置或服务业务流程；无真实数据库 schema/迁移执行、外部 AI 和网络验收。

## T6：仿真交易 ORM 与服务快照类型批次补充验收（2026-09-20）

初始精确 Mypy 对 `app/models/paper_trading.py` 与 `app/services/paper_trading_service.py` 为 `Found 60 errors in 1 file`，均来自服务将 legacy ORM 实例字段视为 `Column[...]` 及其相关快照边界。实现只迁移该模型的字段/关系映射，并在服务内部引入不可变 `PositionSnapshot`、可选快照的 `PositionEvent`、窄数值转换和日期规范化；订单、现金、保证金、手续费、持仓与通知的业务分支未作逻辑重写。

最终命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/paper_trading.py app/services/paper_trading_service.py --show-error-codes` 退出码 0，输出 `Success: no issues found in 2 source files`。对两文件的 Ruff check 与 `ruff format --check` 均退出码 0。将 HEAD 的 legacy `Column`/`relationship` 调用与工作区 `mapped_column`/`relationship` 调用做 AST 结构归一化比较，结果为 `head_mappings=67 current_mappings=67`，无 missing/extra/changed；SQLAlchemy metadata 另列出四张表的列、SQL 类型、nullable、PK/FK 与索引，未观察到 schema 参数漂移。

定向命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -q tests/test_paper_trading_service.py tests/test_service_edge_cases_113.py tests/test_paper_trading_api.py` 在最终语义复核后退出码 0：`142 passed, 1 warning in 31.21s`。唯一 warning 是既有 backtrader Quandl deprecation；未连接真实交易、外部数据库或网络。测试曾暴露两个 Mock 动态属性兼容问题：快照边界现在只保留真实 `datetime`，动态生成的 Mock 日期属性规范化为 `None`，使现有 long/partial-close 用例保持原有行为。

随后全量 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 789 errors in 135 files (checked 625 source files)`；相较 T5 的 849/136 观察值净少 60 个错误、1 个报错文件，但跨文件误差不据净差全部归因于 T6。完整门禁仍为 FAIL / NO-GO。

## T7：市场数据平台 ORM 类型批次补充验收（2026-09-20）

本批仅修改 `app/models/market_data_platform.py`。初始模型精确 Mypy 为 2 errors；`app/services/market_data/store.py` 初始精确 Mypy 为 43 errors，错误中大量为模型 `Column[...]` 实例误推断。220 个列与 25 个关系转换为 SQLAlchemy 2 映射，JSON 字段使用递归 `MarketDataJSONMapping`；没有修改 Store、迁移、服务/API、依赖或静态配置。

最终命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/market_data_platform.py --show-error-codes` 退出码 0：`Success: no issues found in 1 source file`；目标 Ruff check、`ruff format --check` 和 `git diff --check` 均退出码 0。HEAD/工作区 AST 归一化比较为 columns `220/220`、relationships `25/25`，无 missing/extra/changed；同一 schema 摘要算法在改前后均为 SHA-256 `9b5a93f18df29c7b2b364c09691f36a33c442fdb8358a02058e145e7d55761b5`。导入外部模型并配置 mapper 后，实际计数为 21 tables、220 columns、25 relationships，mapper configuration 为 PASS。

定向命令 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -q tests/market_data_platform/test_store.py` 退出码 0：`47 passed, 1 warning in 11.13s`。唯一 warning 为既有 backtrader Quandl deprecation；未运行迁移、真实数据库或外部数据源。Store 精确 Mypy 复验为 9 errors / 1 file，剩余项是 source-payload 可空性、expected manifest、calendar list 可空性、时间/sequence 可空性、dict 协变、未知 iterable 和 semantic dimension 数据流问题，不由 Column 实例误推断造成，也未在 T7 越界修复。

全量 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 662 errors in 129 files (checked 625 source files)`；相较 T6 的 789/135 净少 127 errors、6 个报错文件。该差异涉及调用方上下文，不把净减全部机械归因于单一模型变更；完整 Mypy 门禁仍 FAIL / NO-GO。

## CQ-200-07 根因与修复

支持的 Node 24.2.0 下，修复前四个 Markdown 测试文件复现 9 个失败。已确认 DOMPurify 3.4.15 在 happy-dom 中对 Node.prototype.nodeName 的依赖语义不兼容，造成允许标签移除和节点遍历提前停止。处理方式是在四个受影响文件使用 file-level jsdom，并把 jsdom ^27.0.0 加为直接 devDependency。生产 DOMPurify/marked、清洗逻辑和 Vitest 全局 happy-dom 环境不变。

## CQ-200-08 根因与修复

CQ-200-07 初次 Node 24.2.0 复验时，StrategyDetailDialog 测试因 Monaco 在 jsdom 环境初始化失败，原始错误为：

    TypeError: document.queryCommandSupported is not a function
    at node_modules/monaco-editor/esm/vs/editor/contrib/clipboard/browser/clipboard.js:46:114

当时虽然定义了 mount-level `global.stubs.MonacoEditor`，但 StrategyDetailDialog SFC 的静态依赖已在执行 mount 前被 Vitest 加载，因此这个 stub 无法阻止 Monaco Editor 初始化。CQ-200-08 改为在测试模块中使用 hoisted module-level `vi.mock('@/components/common/MonacoEditor.vue', ...)`，并移除冗余 mount stub。通用 Element stubs 保留；测试仍使用 file-level jsdom。未修改生产 Monaco/StrategyDetailDialog/Markdown 清洗代码，也未增加 shared setup polyfill。

CQ-200-08 修复后的 Node 24.2.0 结果：StrategyDetailDialog 文件 1/1、四个 Markdown 相关文件 4/4 共 35/35 测试通过；全量 Vitest 154/154 files、1687/1687 tests 通过。CQ-200-07 初次验证时的 suite 导入失败和全量失败均为历史结果，已由上述修复复验覆盖。

## 执行记录

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| Node 24.2.0 node/npm version | 0 | node v24.2.0；npm 11.6.2 |
| npm install --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org（CQ-200-07 历史快照） | 0 | 当时 audited 536 packages；20 项漏洞（1 low、7 moderate、10 high、2 critical）；后续锁与审计见 QD-200-03。 |
| npm ci --ignore-scripts --registry=https://registry.npmjs.org（Node 24.2.0，CQ-200-07 历史快照） | 0 | 当时 added 535 packages、20 项漏洞；后续锁与审计见 QD-200-03。 |
| 四个 Markdown 测试文件（Node 24.2.0，CQ-200-08 前历史结果） | 1 | 3 files passed / 1 failed；34 tests passed；StrategyDetailDialog import 报 document.queryCommandSupported is not a function；已由 CQ-200-08 修复并复验通过 |
| npm run test -- --run（Node 24.2.0，CQ-200-08 前历史结果） | 1 | 153 files passed / 1 failed；1686 tests passed；唯一失败为 StrategyDetailDialog suite import；已由 CQ-200-08 修复并复验通过 |
| StrategyDetailDialog.test.ts（Node 24.2.0，CQ-200-08 后） | 0 | 1 file passed；1 test passed |
| 四个 Markdown 相关测试文件（Node 24.2.0，CQ-200-08 后） | 0 | 4 files passed；35 tests passed |
| npm run test -- --run（Node 24.2.0，CQ-200-08 后） | 0 | 154 files passed；1687 tests passed；耗时 86.67s |
| npm run lint（Node 24.2.0，CQ-200-08 后的历史结果；后由 QD-200-02 复验） | 0 | 当时为 0 errors、1357 warnings；后续最新记录为 0 errors、0 warnings（404 files）。 |
| npm run typecheck（Node 24.2.0，CQ-200-08 后） | 0 | vue-tsc 无诊断输出 |
| npm run build（Node 24.2.0，独立复核） | 0 | 4093 modules transformed；构建完成。Vite 仍警告部分 chunk 超过 500 KiB，已记入 QUALITY_DEBT_REGISTER.md。 |
| npm run lint（Node 24.2.0，前端 lint 债务修复前历史快照） | 0 | 当时为 0 errors、1357 warnings；后由 QD-200-02 在 Node 20/24 复验为 0 errors、0 warnings。 |
| npm run typecheck（Node 24.2.0） | 0 | vue-tsc 无诊断输出 |
| npm install --package-lock-only --ignore-scripts | 0 | 锁文件同步完成；Node 25.1.0 超出项目 .nvmrc=20 与 engines 范围，npm 发出 EBADENGINE 警告 |
| npm install --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org（依赖安全升级前历史快照） | 0 | 当时 audit 报告 20 项依赖漏洞（1 low、7 moderate、10 high、2 critical）；后续审计见 QD-200-03。 |
| package-lock registry host normalization + mirror URL check | 0 | 将本轮生成的 72 个 npmmirror URL 归一为 registry.npmjs.org；未发现残留 mirror URL |
| npm ci --ignore-scripts --registry=https://registry.npmjs.org（Node 25.1.0 历史快照） | 0 | 当时安装 492 packages 并发出 EBADENGINE；20 项审计结果为历史快照，后续 Node 20/24 证据见上文。 |
| npm ls --depth=0 @vitest/coverage-v8 vitest | 0 | 两者均解析为 1.6.1，peer 版本一致 |
| npm run lint（Node 25.1.0，CQ-200-07 修改前历史快照） | 0 | 当时为 0 errors、1357 warnings；仅 Node 20/24 后续版本有 0/0 复验，不据此声称 Node 25 lint 矩阵通过。 |
| npm run typecheck（Node 25.1.0，CQ-200-07 修改前） | 0 | vue-tsc 无诊断输出 |
| npm run test -- --run（Node 25.1.0，CQ-200-07 修改前） | 1 | 150 files passed / 4 failed；1678 passed / 9 failed。Node 24.2.0 复现了 DOMPurify/happy-dom 根因；加 file-level jsdom 后三文件已通过，剩余 Monaco API 错误如上。 |
| ruff check（迭代触及的后端文件） | 0 | All checks passed |
| ruff format --check（指定三个文件） | 0 | 3 files already formatted |
| mypy（THS rate limiter、multi_record、六个 package init） | 0 | Success: no issues found in 8 source files |
| pytest tests/market_data_platform/test_ths_rate_limiter.py tests/market_data_platform/test_multi_record_completeness.py -q | 0 | 18 passed，1 个 backtrader deprecation warning |
| git diff --check | 0 | 无 tracked diff 空白错误 |
| git status --short | 0 | 确认迭代 197–199 的既有变更仍在；本迭代文件已列入工作树，未暂存或提交 |
| Node 24.2.0：`npm install --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org --prefer-online`（前端依赖质量批次） | 0 | lock 更新到 ECharts 6.1.0、vue-echarts 8.3.0、Monaco 0.56.0；审计汇总 16 项：2 low、4 moderate、8 high、2 critical |
| 隔离目录 fresh resolution：`npm install --ignore-scripts --package-lock=false --registry=https://registry.npmjs.org --prefer-online`，随后 `npm ls dompurify monaco-editor --all` | install 0；ls 1 | `monaco-editor@0.56.0` 仍内嵌 `dompurify@3.4.8 invalid: ^3.4.15`；`$dompurify` override 未形成有效树，因此已移除。临时无 lock 安装无法独立运行 `npm audit`（ENOLOCK），该检查不作为审计证据。 |
| Node 24.2.0：`npm ci --ignore-scripts --registry=https://registry.npmjs.org` | 0 | added 532 packages，audited 533；npm 报告 16 项漏洞（2 low、4 moderate、8 high、2 critical） |
| Node 24.2.0：`npm ls monaco-editor dompurify echarts vue-echarts --all` | 0 | Monaco 0.56.0 -> nested DOMPurify 3.4.8；root DOMPurify 3.4.15；ECharts 6.1.0 与 vue-echarts 8.3.0；无 invalid 节点。 |
| Node 24.2.0：`npm run lint` / ESLint JSON 计数（404 files） | 0 | 0 errors、0 warnings、0 fixable diagnostics。 |
| Node 24.2.0：`npm run typecheck` | 0 | vue-tsc 无诊断输出；mount helper 返回类型与 Vue Test Utils 泛型一致。 |
| Node 24.2.0：`npm run test -- --run` | 0 | 154 files passed；1687 tests passed；耗时 58.55s。 |
| Node 24.2.0：`npm run build` | 0 | approval error manifest 检查通过（48 entries）；Vite transformed 4160 modules 并成功构建；仍提示有 chunk 超过 500 KiB。 |
| Node 24.2.0：`npm audit --omit=dev --json --registry=https://registry.npmjs.org` | 1（发现漏洞） | production audit 2 项：moderate nested DOMPurify（Monaco 固定解析为 3.4.8，受影响范围 `<=3.4.12`）和 low Monaco（由该 DOMPurify 引起）；未以降级 Monaco 或无效 override 清零。 |
| Node 24.2.0：`npm audit --json --registry=https://registry.npmjs.org` | 1（发现漏洞） | 全量 16 项：2 low、4 moderate、8 high、2 critical；其中 production 2 项、dev-only 14 项，逐项仍需后续治理。 |
| Node 20.20.2/npm 10.8.2：`npm ci --dry-run --ignore-scripts --registry=https://registry.npmjs.org`（锁兼容修复后） | 0 | dry-run 通过；锁文件包含 Sass 可选 peer 子树及 Node 24 npm 所需的 Parcel watcher 平台条目。 |
| Node 24.2.0/npm 11.6.2：`npm ci --dry-run --ignore-scripts --registry=https://registry.npmjs.org`（锁兼容修复后） | 0 | dry-run 通过；合并后的锁文件未丢失 npm 11 要求的 optional 平台条目。 |
| Node 20.20.2/npm 10.8.2：`npm install --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org` | 0 | 从含 npm 11 完整 optional 平台集合的锁文件生成 Node 20 兼容锁；保留全部 13 个 `@parcel/watcher` 平台条目，并写入 `sass@1.99.0`、嵌套 `chokidar@4.0.3` 与 `readdirp@4.1.2`。未改 package.json 依赖语义。 |
| Node 20.20.2/npm 10.8.2：clean `npm ci --ignore-scripts --registry=https://registry.npmjs.org` | 0 | added 535 packages，audited 536；Node 20 初始缺失的 Sass peer 依赖现可安装。 |
| Node 20.20.2/npm 10.8.2：`npm run lint` / `npm run typecheck` | 0 / 0 | lint 0 errors、0 warnings；vue-tsc 无诊断输出。 |
| Node 20.20.2/npm 10.8.2：`npm run test -- --run` | 0 | 154 files passed；1687 tests passed；耗时 65.10s。 |
| Node 20.20.2/npm 10.8.2：`npm run build` | 0 | approval error manifest 48 entries 校验通过；Vite transformed 4160 modules 并成功构建；仍警告超过 500 KiB 的 chunk。 |
| Node 24.2.0/npm 11.6.2：clean `npm ci --ignore-scripts --registry=https://registry.npmjs.org` | 0 | added 535 packages，audited 536；组合锁文件在 Node 24/npm 11 下也可复现安装。 |
| Node 24.2.0/npm 11.6.2：`npm run lint` / `npm run typecheck` | 0 / 0 | lint 0 errors、0 warnings；vue-tsc 无诊断输出。 |
| Node 24.2.0/npm 11.6.2：`npm run test -- --run` | 0 | 154 files passed；1687 tests passed；耗时 58.14s。 |
| Node 24.2.0/npm 11.6.2：`npm run build` | 0 | approval error manifest 48 entries 校验通过；Vite transformed 4160 modules 并成功构建；仍警告超过 500 KiB 的 chunk。 |
| Node 20.20.2 与 Node 24.2.0：production/full `npm audit --json --registry=https://registry.npmjs.org`（production 加 `--omit=dev`） | 1（发现漏洞） | 两版本结果相同：production 2 项（moderate nested DOMPurify、low Monaco）；全量 16 项（2 low、4 moderate、8 high、2 critical）。未关闭 QD-200-03。 |
| `git diff --check` | 0 | 当前完整 tracked diff 无 whitespace errors。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy`（本批次 12 个指定源文件） | 0 | 修复前为 37 errors；修复后 `Success: no issues found in 12 source files`。 |
| `ruff check`（本批次 12 个指定源文件） | 0 | All checks passed；未调整 lint 配置。 |
| `ruff format --check`（本批次 12 个指定源文件） | 0 | 12 files already formatted。 |
| 第一组：process supervisor、instance store、multi-record contracts、gateway manual helpers 的现有 pytest | 0 | `113 passed, 1 warning in 218.45s`。 |
| 第二组：AI research model budget、HTTP holdout/discovery、OpenAI-compatible provider 的现有 pytest | 0 | `88 passed, 1 warning in 185.53s`。 |
| 第三组：holdout worker/process、holdout/discovery deployment、stock-analysis compat 的现有 pytest | 0 | `55 passed, 1 warning in 87.54s`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app`（T1 后全量复验） | 1 | `Found 1072 errors in 168 files (checked 625 source files)`；全量 Mypy 仍为 FAIL / NO-GO，未扩展到本批次外修复。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app/api/deps.pyi` | 0 | Success: no issues found in 1 source file。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app/api/deps.pyi` + `app/api/data/deps.py` + `rg` 枚举的全部直接 importer（共 39 files） | 1（含未关闭错误） | `Found 55 errors in 15 files (checked 39 source files)`；`app.api.deps` 缺属性错误为 0。残留错误在其他 API 类型合同，不属于本 shim 修复范围。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff check app/api/deps.pyi` | 0 | All checks passed。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff format --check app/api/deps.pyi` | 0 | `1 file already formatted`。 |
| `tests/test_deps.py tests/test_deps_permissions.py tests/test_backtest_websocket_runtime.py tests/test_misc_branch_fixes.py`（verbose pytest） | 0 | `62 passed, 1 skipped, 1 warning in 14.15s`；skip 为既有 backtrader strategy context 要求。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app`（T2 后全量复验） | 1 | `Found 1027 errors in 145 files (checked 625 source files)`；较 T1 后观测净减 45 errors、23 个报错文件，全量仍 FAIL / NO-GO。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app/data_fetch/core/database.py app/data_fetch/core/mysql_base.py` | 0 | 修复前 49 errors；修复后 `Success: no issues found in 2 source files`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff check app/data_fetch/core/database.py app/data_fetch/core/mysql_base.py tests/test_data_fetch_common_utils.py` | 0 | All checks passed。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff format --check app/data_fetch/core/database.py app/data_fetch/core/mysql_base.py tests/test_data_fetch_common_utils.py` | 0 | 3 files already formatted。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base pytest -vv tests/test_data_fetch_common_utils.py` | 0 | 11 passed、0 failed、1 warning；所有数据库交互均为 fake，未连接真实 MySQL。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m mypy app`（T3 后全量复验） | 1 | `Found 984 errors in 143 files (checked 625 source files)`；较 T2 后观测净减 43 errors、2 个报错文件，全量仍 FAIL / NO-GO。 |
| `git diff --check`（T3 后） | 0 | 无 tracked diff 空白错误；文档和目标源码另经 whitespace scan。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/data_fetch/providers/akshare_to_mysql.py`（T4 基线） | 1 | `Found 21 errors in 1 file`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/data_fetch/providers/akshare_provider.py`（T4 基线） | 1 | `Found 21 errors in 1 file`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/data_fetch/utils/akshare_network_proxy.py`（T4 基线） | 1 | `Found 13 errors in 1 file`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/data_fetch/providers/akshare_to_mysql.py app/data_fetch/providers/akshare_provider.py app/data_fetch/utils/akshare_network_proxy.py`（T4 最终精确检查） | 0 | `Success: no issues found in 3 source files`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base ruff check app/data_fetch/providers/akshare_to_mysql.py app/data_fetch/providers/akshare_provider.py app/data_fetch/utils/akshare_network_proxy.py tests/test_data_fetch_common_utils.py tests/test_akshare_network_proxy.py tests/test_akshare_provider_storage.py` | 0 | All checks passed。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base ruff format --check app/data_fetch/providers/akshare_to_mysql.py app/data_fetch/providers/akshare_provider.py app/data_fetch/utils/akshare_network_proxy.py tests/test_data_fetch_common_utils.py tests/test_akshare_network_proxy.py tests/test_akshare_provider_storage.py` | 0 | 6 files already formatted。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -vv tests/test_data_fetch_common_utils.py tests/test_akshare_network_proxy.py tests/test_akshare_provider_storage.py` | 0 | `23 passed, 1 warning in 5.82s`；warning 为 backtrader Quandl deprecation。数据库、AkShare 与请求调用全部 fake/mock。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app`（T4 后全量复验，唯一一次） | 1 | `Found 929 errors in 140 files (checked 625 source files)`；较 T3 观测值 984/143 净减 55 errors、3 files，全量仍 FAIL / NO-GO。 |
| `git diff --check`（T4 后） | 0 | 本批次 tracked diff 无 whitespace errors；新增 untracked 测试文件由 Ruff check/format 检查。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/paper_trading.py app/services/paper_trading_service.py --show-error-codes`（T6） | 0 | 初始为 `Found 60 errors in 1 file`；最终 `Success: no issues found in 2 source files`。 |
| `ruff check` / `ruff format --check`（T6 两源文件） | 0 / 0 | `All checks passed!`；`2 files already formatted`。 |
| `tests/test_paper_trading_service.py tests/test_service_edge_cases_113.py tests/test_paper_trading_api.py`（T6，最终复跑） | 0 | `142 passed, 1 warning in 31.21s`；warning 为既有 Quandl deprecation。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（T6 后全量复验） | 1 | `Found 789 errors in 135 files (checked 625 source files)`；完整 Mypy 仍 FAIL / NO-GO。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/market_data_platform.py --show-error-codes`（T7） | 0 | 初始为 `Found 2 errors in 1 file`；最终 `Success: no issues found in 1 source file`。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/services/market_data/store.py --show-error-codes`（T7 下游测量） | 1 | 初始 43 errors，模型迁移后 9 errors；均为非 Column 根因，未在本批修复。 |
| `ruff check` / `ruff format --check` / `git diff --check`（T7 模型文件） | 0 / 0 / 0 | All checks passed；1 file already formatted；无 whitespace error。 |
| `tests/market_data_platform/test_store.py`（T7） | 0 | `47 passed, 1 warning in 11.13s`；warning 为既有 Quandl deprecation。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（T7 后全量复验） | 1 | `Found 662 errors in 129 files (checked 625 source files)`；完整 Mypy 仍 FAIL / NO-GO。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/models/workspace.py --show-error-codes`（T8） | 0 | `Success: no issues found in 1 source file`。 |
| `tests/test_trading_workspace_service.py tests/test_workspace_trading_api.py`（T8） | 0 | `159 passed, 1 warning`；warning 为既有 Quandl deprecation。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（T8 后全量复验） | 1 | `Found 625 errors in 131 files (checked 625 source files)`；完整 Mypy 仍 FAIL / NO-GO。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/services/stock_analysis/tasks.py app/services/workspace/optimization.py app/services/workspace/reports.py --show-error-codes`（T9） | 0 | 基线为 10 errors；最终 `Success: no issues found in 3 source files`。 |
| `ruff check` / `ruff format --check`（T9 五个源/测试文件） | 0 / 0 | `All checks passed!`；`5 files already formatted`。 |
| `tests/test_workspace_json_consumers.py tests/test_stock_analysis_tradingagents_compat.py::test_stock_analysis_from_ai_chat_generates_compat_report_and_exports -vv`（T9） | 0 | `5 passed, 1 warning in 3.93s`；warning 为既有 Quandl deprecation；仅 fake/SQLite fixture。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（T9 后全量复验） | 1 | `Found 615 errors in 128 files (checked 625 source files)`；三个 T9 消费者无错误，完整 Mypy 仍 FAIL / NO-GO。 |

## T62 最终验收补充（2026-09-22）

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -q tests/test_trading_workspace_service.py` | 0 | `145 passed, 1 warning`；warning 为既有 Backtrader Quandl deprecation。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app/services/trading_workspace_service.py --show-error-codes` | 0 | `Success: no issues found in 1 source file`。 |
| `ruff check` / `ruff format --check`（`trading_workspace_service.py`） | 0 / 0 | All checks passed；1 file already formatted。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（新建隔离缓存） | 0 | `Success: no issues found in 625 source files`。 |

THS 历史 fixture 64 passed、直接订单与手工网关 fixture 56 passed、可观测性与工作空间 fixture 43 passed，均只使用本地 fixture/fake；全量后端 pytest 为 NOT_RUN。未连接真实数据库、网络、行情、供应商或交易系统。THS 日历同日 apply 的 importer 在测试中为 mock，真实数据库 importer 的同版本同哈希复用仍为 NOT_RUN。

## T63 复审后最终验收补充（2026-09-22）

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| `pytest -q`（订单、网关、可观测性、工作空间、THS history/reference/contracts/calendar importer 的 9 个文件） | 0 | `484 passed, 1 warning in 101.43s`；warning 为既有 Backtrader Quandl deprecation。 |
| `ruff check` / `ruff format --check`（17 个 T63 相关文件） | 0 / 0 | All checks passed；17 files already formatted。 |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes`（新建隔离缓存） | 0 | `Success: no issues found in 625 source files`。 |

T63 修复默认 dry-run 的内部批量提交、SQLite savepoint 外层事务、单标的失败的整批回滚/虚高计数、订单与工作空间的非有限方向码，以及资产规格对原 instance 的写回语义。真实生产数据库、外部网络、行情、供应商与交易系统和全量后端 pytest 均为 NOT_RUN；日历测试使用真实内存 SQLite 但 mock importer，不作为真实 `MarketDataCalendarImporter` 发布验收。

## T64 Mypy ratchet 基线归零（2026-09-22）

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pip install --target /tmp/iter200-mypy-1202.nKPLri --disable-pip-version-check mypy==1.20.2` | 0 | 将 CI 固定版本安装到临时 target；未修改仓库依赖锁或 Conda base 环境依赖。 |
| `PYTHONPATH=/tmp/iter200-mypy-1202.nKPLri /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy --version` | 0 | `mypy 1.20.2 (compiled: yes)`；Mypy 位于临时 target，不改 base 环境依赖。 |
| `PYTHONPATH=/tmp/iter200-mypy-1202.nKPLri /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes --cache-dir=/tmp/iter200-mypy-1202-cache.Puw5hr`（工作目录 `src/backend`） | 0 | `Success: no issues found in 625 source files`；新建隔离缓存。 |
| `ALLOW_BASELINE_UPDATE=1 PYTHONPATH=/tmp/iter200-mypy-1202.nKPLri /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python scripts/ci/mypy_ratchet.py --update` | 0 | `mypy_ratchet: baseline updated -> 0 errors (mypy 1.20.2 (compiled: yes))`。 |
| `PYTHONPATH=/tmp/iter200-mypy-1202.nKPLri /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python scripts/ci/mypy_ratchet.py` | 0 | `mypy_ratchet: errors=0 baseline=0 delta=+0`。 |

首轮固定版本扫描曾发现 `app/services/paper_trading_service.py:160` 的 `[arg-type]`，相关 P1 修复后 fresh-cache 全量扫描通过。仓库没有 mypy ratchet 合成回归测试，故验证了实际 baseline update 和常规 ratchet 路径。`src/backend/3.10/` 缓存保留原样并由 `.gitignore` 精确忽略。未运行全量后端 pytest，也未连接生产数据库、网络、行情、供应商或交易系统。

## T65 后端 Python 锁文件安全债务与 Python 3.10 解析（2026-09-22）

| 命令/检查 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| `UV_BIN=/Users/yunjinqi/.joyincode/runtime/workspaces/backtrader_web-433a785d/bin/uv ./scripts/ops/generate_lockfiles.sh`（连续运行两次） | 0 / 0 | 两次生成字节一致；dev SHA-256 `8829ec23bf964deacec638f4bf76218f8d9618d9ef035493d5a5e2ca1aaa5b3d`，prod SHA-256 `d774c6f35c760d729fb9e528f35d80115465dd631af59153b02d9a401407bb5a`。 |
| `pip-audit --requirement config/requirements-dev.lock --no-deps --desc`（base Conda Python） | 0 | `No known vulnerabilities found`；`backtrader (1.3.0)` 来自固定 Git 源、无法在 PyPI 找到，审计器报告 `Dependency not found on PyPI and could not be audited`。 |
| `pip-audit --requirement config/requirements-prod.lock --no-deps --desc`（base Conda Python） | 0 | `No known vulnerabilities found`；唯一未覆盖项同为固定 Git backtrader；没有其它漏洞结果。 |
| Python 3.10.19 下分别 `uv pip compile pyproject.toml --extra dev --extra backtrader --extra data --extra redis ...` 与 `--extra prod --extra postgres --extra mysql --extra redis --extra backtrader --extra data ...` | 0 / 0 | 两组临时锁均成功解析；AkShare 回退到 `1.18.88`，AnyIO 为 `4.15.1`、cryptography 为 `50.0.1`、soupsieve 为 `2.9.2`。临时锁不替代仓库 canonical Python 3.11 锁。 |
| Python 3.10 隔离环境按临时 dev/prod 锁同步后运行 `python -m pip_audit --desc` | 0 / 0 | 两组均输出 `No known vulnerabilities found`，并同样提示固定 Git backtrader 无法从 PyPI 审计；审计在对应 3.10 已安装分发上执行，以避免 pip-audit `--requirement` 临时环境创建器与跨版本锁/3.10 ensurepip 的不兼容。 |
| `check_deps_sync.py`、`check_prod_lock_singleton.py`、依赖同步 pytest | 0 / 0 / 0 | `OK: pyproject direct runtime dependencies satisfy the canonical production lock; legacy requirements.txt resolves exactly to that lock.`；`single SSOT at config/requirements-prod.lock`；5 passed。 |
| Ruff、后端选定测试、Mypy | 0 / 0 / 0 | Ruff check 与 format check 通过；安全、AkShare provider/storage、realtime data 定向回归 116 passed、15 条既有 warning；Mypy 1.20.2 为 `Success: no issues found in 630 source files`。 |

将 AnyIO 下限设为 `4.14.2`、cryptography 下限设为 `50.0.0`、soupsieve 下限设为 `2.9.0`，并按 Python 版本设置 AkShare 数据 extra：Python 3.11+ 使用 `>=1.18.96`，Python 3.10 使用 `>=1.18.88,<1.18.89`。规范后端锁最终解析为 AnyIO `4.15.1`、cryptography dev `50.0.1` / prod `50.0.0`、soupsieve `2.9.2`、AkShare `1.18.97`；没有改动 cloudQuant Git backtrader 源或固定 commit `04adc08c2deb02cbf240efbd495e5eee68b375d8`。依赖下限针对已报告 advisories，不以忽略或风险接受替代修复。

Python 3.10 AkShare 回退有上游 wheel metadata（`1.18.88` 支持 Python `>=3.9`）、函数源码对比（`fund_etf_fund_info_em` 的字段重命名/选列实现与 `1.18.96` 相同）以及离线 14 字段响应行为探针支持；包含 8 个额外字段的 `LSJZList` mock 成功得到预期六列。该证据不等同于在 Python 3.10 上请求 AkShare 实际服务：真实网络/供应商闭环仍为 NOT_RUN；迭代 197 的 `fund.nav` 端到端修复原验证版本为 `>=1.18.96`，故 1.18.88 回退只关闭解析/源码/离线字段形态兼容性风险，不声称 3.10 上游在线闭环已验收。

审计边界：pip-audit 的上述结果覆盖 PyPI 可识别分发；cloudQuant `backtrader` 是固定 Git 依赖，不存在可用 PyPI advisory 记录，因而被 pip-audit 明确跳过，并未被视为“零漏洞”分发。未运行 CI workflow、完整后端 pytest 或真实数据库、行情、网络、交易验收。

## T66 前端初始闭包预算与异步模块回退（2026-09-22）

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| `node --version` / `npm --version`（显式使用 `/opt/homebrew/opt/node@20/bin`） | 0 / 0 | `v20.20.2` / `10.8.2`。 |
| `npm --prefix src/frontend run typecheck` | 0 | `vue-tsc --noEmit` 通过。 |
| `npm --prefix src/frontend run test -- --run` | 0 | `156` test files、`1695` tests passed；Vitest 在完成后额外输出一次 `socket hang up` (`ECONNRESET`)，进程仍为 0，且所有测试均报告通过。 |
| `npm --prefix src/frontend run build` | 0 | Vite 6.4.3 转换 `3885` modules 并完成生产构建；仍有 >500 kB 单 chunk advisory warning。 |
| `node --test scripts/ci/tests/list_route_assets.test.mjs scripts/ci/tests/check_bundle_size.test.mjs` | 0 | `10` passed / `0` failed；包含不放宽 entry `300 KB` 和初始 JS `4` 个上限的回归断言。 |
| `bash scripts/ci/check_bundle_size.sh src/frontend/dist` | 0 | entry gzip `31,858` / `307,200` bytes；entry closure gzip `616,170` / `655,360`；`/login` closure gzip `619,716` / `655,360`；最大初始 JS `527,484` / `552,960` bytes；entry/login 初始 JS 数为 `2/4`，均 PASS。闭包和最大单文件计算包括 `application-vendor`。 |
| Monaco、共享异步模块、Workspace async factory 和页面定向 Vitest | 0 | `4` files、`23` tests passed；覆盖动态 import reject 后错误可见、点击 Retry 后 loader 第二次调用并成功、等待/timeout UI 以及 owner unmount 后忽略迟到结果。 |

bundle gate 保留原 entry gzip `300 KiB` 与 entry/login 各 `4` 个初始 JS 上限；新增 entry 静态闭包与 `/login` 初始闭包 gzip-9 `640 KiB` 上限，以及最大初始 JS gzip-9 `540 KiB` 上限。合成 manifest 测试明确保证 vendor 进入闭包、单个 vendor 超限和多个单文件合计超限都会失败，并断言原 entry `300 KiB` 和四个初始 JS 限制仍为硬门槛。精确资产和 closure 语义见 `docs/reference/frontend-bundle-budget.md`。Monaco 加入本地加载/错误/retry 状态，并在卸载后丢弃迟到模块；`WorkspaceOptimizationPane` 将 WorkspaceOptimizationTab 的 async boundary、加载 fallback 与现有 ErrorBoundary 抽为明确 props 的组件，15 秒超时进入错误状态。稳定 async wrapper 的定向测试证明 ErrorBoundary retry 会重新调用 loader 两次请求。

边界：未运行 Playwright/e2e、浏览器网络节流或真实 CDN 缓存测量；Vitest/build/gate 为本机 Node 20 的证据，Vite >500 kB advisory 仍存在。故关闭 manifest 静态预算与异步状态可见性代码债务，不据此声称真实首屏传输或感知加载时间达标。未运行 CI workflow、Node 24 复验或真实外部系统验收。

## T67 最终本地门禁与源码尺寸棘轮（2026-09-22）

| 命令 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| Mypy 1.20.2 fresh-cache：`python -m mypy app --show-error-codes` | 0 | `Success: no issues found in 630 source files`。 |
| `mypy_ratchet.py` | 0 | `errors=0 baseline=0 delta=+0`。 |
| Node 20 production/full `npm audit --json` | 0 / 0 | 两次均为 0 vulnerability；锁文件总依赖数为 570。 |
| canonical prod/dev `pip_audit --requirement ... --no-deps --desc` | 0 / 0 | 均为 `No known vulnerabilities found`；固定 Git `backtrader` 被明确列为无法通过 PyPI 审计。 |
| `check_deps_sync.py`、`check_prod_lock_singleton.py`、依赖同步 pytest | 0 / 0 / 0 | canonical production lock 是唯一 SSOT；同步测试 10 passed。 |
| `large_file_ratchet.py --update`（`ALLOW_BASELINE_UPDATE=1`）与普通 `large_file_ratchet.py` | 0 / 0 | 经 [SOURCE_SIZE_DISPOSITION.md](SOURCE_SIZE_DISPOSITION.md) 审查的 24 项增长和已缩小路径写入；普通门禁随后通过。 |
| 后端 Ruff check/format | 0 / 0 | `All checks passed`；2,331 个文件已格式化。 |

T67 当时仅启动了独立最终门禁；其实际完成记录见后续 T68，不能由上述静态或定向证据代替。

## T68 最终本地非性能回归、缓存隔离与测试运行时收口（2026-09-22）

| 命令 / 检查 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| Mypy 1.20.2 fresh-cache：`PYTHONPATH=/tmp/iter200-mypy.XmEcgo ... python -m mypy app --show-error-codes --cache-dir=/tmp/iter200-mypy-cache.xoZ0yy` | 0 | `Success: no issues found in 630 source files`。临时 target 未修改 Conda base 或仓库锁。 |
| 同一 Mypy 版本的 `mypy_ratchet.py` | 0 | `mypy_ratchet: errors=0 baseline=0 delta=+0`。base 自带的 Mypy 1.16.1 因版本不符被正确拒绝，未改写 1.20.2 基线。 |
| 全零 / 混合零回撤、JWT 错签名、AkShare 超时用例 | 0 | 7 passed；`RuntimeWarning`、`jwt.warnings.InsecureKeyLengthWarning`、`pytest.PytestUnhandledThreadExceptionWarning` 和 `PytestUnknownMarkWarning` 均按 error 运行，无对应告警。 |
| 本地非性能后端回归：`python -m pytest -q -m "not performance" --maxfail=0`（新 `PYTHONPYCACHEPREFIX`） | 0 | 收集 8,006 项；24 个 performance 用例被选择器排除；`7859 passed, 123 skipped, 24 deselected in 2986.46s (0:49:46)`，无 warning summary。 |

`response_cache` 对两条 owner-scoped 路由使用以 `SECRET_KEY` 域分隔的 HMAC 用户范围键；key 不含原始用户 ID，缺失或畸形 principal 直接 bypass，不读取/写入共享缓存。真实 ASGI 覆盖 Alice MISS/HIT、Bob 隔离及 404、旧未分区 key 不命中和 unknown principal 不缓存。回撤计算仅对全 NaN 早退，保留非有限结果的既有 `nanmin`/最终 0.0 回退；AkShare timeout 单测局部禁用代理探测并等待后台 callable 收尾；嵌套 `tests/pytest.ini` 保留自己的 rootdir/path 语义，但已与上级同步 strict markers、30 秒 thread timeout、marker 和 warning/logging 门禁。

部署边界：本地测试没有验证共享 Redis 的滚动发布。发布本缓存格式变更时，须先 drain/stop 全部旧 worker，再按 `backtests:*` 与 `strategies:*` 前缀失效旧/新缓存后切流；该操作及真实数据库、行情、供应商、券商/交易、浏览器 e2e、网络节流、CDN 与 CI workflow 均仍 NOT_RUN。

## T69 未关闭代码质量债务收口（2026-09-22）

| 命令 / 检查 | 退出状态 | 输出摘要 |
| --- | --- | --- |
| canonical dev lock `check_lockfile_sync.py config/requirements-dev.lock` | 0 | `All 170 locked packages match installed versions.` |
| canonical dev lock `mypy app --show-error-codes` 与 `mypy_ratchet.py` | 0 / 0 | `Success: no issues found in 630 source files`；`errors=0 baseline=0 delta=+0`。四个 CI scope（58/7/4/15 文件）也逐项为 0 errors。 |
| 监控与告警六文件 pytest | 0 | `204 passed in 55.59s`；覆盖 enum wire value、普通字符串、未知 `str, Enum` 回退，以及有效 webhook 与摘要的缺失 `created_at` 安全投影。 |
| 后端 Ruff / format / diff whitespace | 0 / 0 / 0 | `All checks passed`；`2217 files already formatted`；`git diff --check` 通过。 |
| Node 24 `npm run lint` / `npm run typecheck` / `npm run test -- --run` | 0 / 0 / 0 | lint 使用 `--max-warnings 0`；Vitest 为 `156 files / 1695 tests`。测试结束后输出一次 `ECONNRESET` 诊断但进程为 0、全部测试通过；该诊断未被归因到项目代码，也不作为 lint 零 warning 结论的一部分。 |
| Node 24 production build、manifest bundle gate、CI helper tests | 0 / 0 / 0 | entry gzip 31,862 / 307,200；entry closure 616,174 / 655,360；`/login` closure 619,722 / 655,360；最大初始 JS 527,484 / 552,960；Node helper 为 17/17。Vite >500 kB 提示仍是非阻断 advisory。 |
| `large_file_ratchet.py` | 0 | 前端 lint 的 7 个纯格式路径只精确更新对应 baseline；整体基线历史变动为 41 个键，详见 [SOURCE_SIZE_DISPOSITION.md](SOURCE_SIZE_DISPOSITION.md)。 |
| 最终本地非性能后端回归：`python -m pytest -q -m "not performance" --maxfail=0`（新 `PYTHONPYCACHEPREFIX`） | 0 | `7864 passed, 123 skipped, 24 deselected in 3206.49s (0:53:26)`。 |

该全量回归完成后，复审发现 webhook 对缺失 `created_at` 的兼容对象存在一处 P2 防御性回归；已以单行 helper 调用修复。修复后的完整监控/告警影响面为 204 passed，且 canonical-lock 目标 Mypy、Ruff、format、尺寸棘轮和 whitespace 检查均再次通过。因此本表不将回归前的全量结果误表述为“最后一行改动之后的全量执行”。

T69 关闭本轮可在本地验证的剩余质量债务：canonical-lock Mypy 可复现性、告警 enum wire 表达、warning-free ESLint 以及 lint 格式化引起的尺寸棘轮冲突。7 个多职责编排器和两个小型共享提取机会没有伪装为已关闭，保留为 [迭代 201](../迭代201-核心编排器职责拆分/README.md) 的量化拆分工作包。

边界：CI workflow、浏览器/Playwright E2E、真实数据库、外部行情/供应商、券商/交易系统、共享 Redis 的旧 worker drain 与缓存失效均为 NOT_RUN。提交时还必须纳入当前未跟踪的 CI helper/test 文件；本轮没有暂存、提交或推送任何内容。

## 历史证据边界（T9 快照）

本文件记录本地源码、依赖安装、静态检查和 fixture 的结果。Node 20/24 证据仅覆盖记录的本机 Node/npm 版本和命令，不证明 CI 或其他运行环境。T9 后全量 Mypy 的 615 errors / 128 files 是该历史快照，已由 T67/T68 的 0/630 复验证据取代。不得据本文件声称生产就绪、市场数据完整或任何外部供应商验收通过；真实 MySQL、AkShare 与外网请求均未实测。依赖审计和 bundle 风险的当前状态以质量债务台账为准。
