# 迭代 200：剩余质量债务台账

> 本台账记录本轮没有通过配置放宽、忽略或批量重写来处理的问题及其状态。逐项是否关闭以对应的当前证据为准；尚未明确关闭的项均保持开放。

> 状态说明：T1–T61 的完整 Mypy 错误数和 `FAIL / NO-GO` 标记均是各批次当时的历史快照；T62–T64 的 0/625 也是此前本地证据。当前树由 T69 确认：canonical dev lock Mypy 为 0/630、0-error ratchet、registry 可审计 Python/npm 依赖为 0 finding、warning-free lint、manifest bundle 硬门槛、源码尺寸棘轮和 `7864 passed, 123 skipped, 24 deselected` 的本地非性能后端回归均通过。CI workflow、浏览器 e2e、真实外部系统和共享 Redis 滚动发布验收仍未运行。剩余边界见下方债务状态表。

## T62 全量静态类型门禁关闭（2026-09-22）

T62 当时在 base Conda 环境以新建隔离缓存执行 `python -m mypy app --show-error-codes`，得到 `Success: no issues found in 625 source files`（退出码 0）；该结果作为本地历史证据保留。最终使用与 CI 锁定版本相同的 Mypy 复验与关闭依据见 T64。T62 的最后四条错误来自 `trading_workspace_service.py` 经动态 facade 导入的 helper；改为直接导入其具名实现后，145 项服务回归、目标 Mypy、Ruff/format 和 diff whitespace 检查均通过。

该段只记录 T62 当时的静态类型门禁关闭；依赖与 bundle 的代码门禁随后由 T65/T66 补齐。所有真实数据库、网络、行情与交易验证仍未由本地门禁证明；THS 日历同日复用仍只有 mock importer 的 manifest 证据，真实数据库 importer 路径未运行。

## T63 复审发现的 P0/P1 关闭（2026-09-22）

- 数值边界：订单与工作空间方向码对 NaN、正负无穷和溢出安全失败关闭，保持正常数值方向映射；工作空间本地资产规格在 instance 为 dict 时保留 helper 对原对象 `params` 的更新。
- THS 事务边界：CLI dry-run 对所有可分批提交的日 K、复权和财务调用传 `commit_every=None`；显式 apply 保持日 K 200、reference 100 的批量间隔。三个逐标的写入循环以 savepoint 隔离失败，只有成功释放后才增加报告计数；SQLite 的 legacy transaction control 在保存点前建立物理 `BEGIN`，避免释放第一个保存点即提交。
- 根代理合并回归为 484 passed、1 条既有 warning；17 个相关文件 Ruff/format 通过，新的隔离缓存全量 Mypy 再次为 0 errors / 625 source files。全量后端 pytest、真实外部系统验证和真实 `MarketDataCalendarImporter` 数据库发布仍未运行。

## T64 CI Mypy ratchet 基线归零（2026-09-22）

- base Conda 环境通过临时 `PYTHONPATH` 使用与 CI 锁定版本相同的 Mypy 1.20.2（compiled: yes）；独立 fresh-cache 全量 Mypy 为 0 errors / 625 source files。受保护的 baseline update 将 `baseline_errors` 从历史值下调到 0，版本记录为 1.20.2；本地常规 ratchet 验证为 `errors=0 baseline=0 delta=+0`。未运行 CI workflow。
- `.gitignore` 精确忽略已确认的 `src/backend/3.10/` Mypy 缓存目录；该既有缓存未删除或清空。没有运行生产、真实数据库、网络、行情、供应商或交易系统验收。

## T65 后端 Python 锁文件安全修复（2026-09-22）

- `pyproject.toml` 对 AnyIO、cryptography、soupsieve 提高安全下限；AkShare data extra 按 Python 3.11+ / 3.10 分别使用 `>=1.18.96` 与 `>=1.18.88,<1.18.89`。canonical dev/prod 锁经指定 `generate_lockfiles.sh` 连续重建两次、哈希一致；版本分别解析为 AnyIO 4.15.1、cryptography 50.0.1/50.0.0、soupsieve 2.9.2、AkShare 1.18.97。
- canonical 两锁的 `pip-audit --requirement ... --no-deps --desc` 均为 0 退出码并输出 `No known vulnerabilities found`；Python 3.10 临时 dev/prod 锁同步至隔离 3.10 环境后执行 pip-audit 亦均为 0。pip-audit 对固定 cloudQuant Git backtrader 明确报告无法在 PyPI 找到并审计；不得将其解释为已审计无漏洞。
- 1.18.88 的 Python 3.10 回退有 wheel metadata、`fund_etf_fund_info_em` 源码对比和 14 字段离线 mock 行为证据；AkShare Python 3.10 实际网络请求/供应商闭环仍 NOT_RUN。`fund.nav` 上游在线闭环验证仍以 1.18.96 为准。

## T66/T67 前端与源码尺寸门禁收口（2026-09-22）

- T66 将 entry 与 `/login` 静态闭包分别限制为 640 KiB gzip-9、最大初始 JS（含 vendor）限制为 540 KiB，同时保留 entry 300 KiB 与四个初始 JS 文件上限。Monaco 和工作空间优化页均有 loading、error、retry 与卸载/timeout 边界的测试。最终 Node 20 构建的 entry closure 为 616,170 bytes，`/login` 为 619,716 bytes，最大初始 JS 为 527,484 bytes，门禁通过；Vite 的大 chunk advisory 仍是非阻断提示。
- T67 在 Node 20 上重新执行 production 与 full `npm audit --json`，两者均为 0 vulnerability。固定 Git `backtrader` 仍无法被 pip-audit 的 PyPI advisory 数据库覆盖，已明确记录为覆盖边界而不是“已审计无漏洞”。
- T67 还在 24 项受审查增长、以及已缩小模块自动收紧的前提下执行 guard 保护的源码尺寸基线更新；普通 `large_file_ratchet.py` 随后通过。七个巨型编排器的结构债务没有被伪装关闭，已转入迭代 201。

## T68 缓存租户隔离、测试运行时和最终本地回归（2026-09-22）

- 两条 owner-scoped 响应缓存路由显式启用 HMAC 用户范围键：有效 `sub` 使用 `SECRET_KEY` 的域分隔 HMAC，原始用户 ID 不进入 key；身份缺失、畸形或取密钥异常时直接 bypass，而非回退到共享缓存。真实 ASGI 测试覆盖 Alice MISS/HIT、Bob 不能读到 Alice 的结果、旧无分区 key 不命中和 unknown principal 不缓存。
- 全零权益曲线的最大回撤保持既有 0.0 结果而不再调用全 NaN `nanmin`；混合零/负数曲线仍保留原有非有限结果→0.0 fallback。AkShare timeout 单测不再触发真实代理探测，且等待故意超时的后台 callable 结束；JWT 错签名 fixture 使用长度足够但不同的测试密钥；嵌套 pytest 配置恢复 strict markers、30 秒 thread timeout 和完整 marker/warning 规则。
- Mypy 1.20.2 fresh-cache 为 0/630，实际 ratchet 为 `errors=0 baseline=0 delta=+0`；最终 `pytest -q -m "not performance" --maxfail=0` 为 `7859 passed, 123 skipped, 24 deselected`，无 warning summary。
- 代码级缓存隔离已关闭；共享 Redis 的滚动发布仍是操作性边界：发布前须 drain/stop 全部旧 worker，再对 `backtests:*` 与 `strategies:*` 失效缓存后切流。该部署动作未执行。

## T69 当前门禁可复现性、告警 wire value 与 lint 尺寸冲突收口（2026-09-22）

- canonical dev lock 与 CI Mypy 安装顺序收敛为“锁文件安装后 `--no-deps -e .`”；170 个锁定包一致，全量 Mypy 630/0、ratchet 0→0，四个 CI scope 均为零错误。此项关闭本地可复现性风险；远端 CI 仍为 NOT_RUN。
- 三种已知告警枚举在 webhook、摘要和类型统计使用 wire `.value`；精确内置 str 保持原样，未知 `str, Enum` 和其他对象使用内置 `str(...)` 回退。有效 webhook 与摘要对缺失 `created_at` 均安全投影为 `null`；监控/告警六文件 204 passed，避免再泄漏 `AlertType.ACCOUNT` 或对字符串访问 `.value`。
- 前端 lint 改为 warning 也失败。7 个 Vue 文件的物理行数增长经逐路径审计确认为 lint 所需的模板格式化或安全抑制说明；只精确更新这 7 个 baseline 键，整体相对 HEAD 的 41 个 baseline 变化和结构债务保持可追溯，详见 [SOURCE_SIZE_DISPOSITION.md](SOURCE_SIZE_DISPOSITION.md)。
- 最终非性能后端回归为 `7864 passed, 123 skipped, 24 deselected in 3206.49s`。该全量回归之后发现并修复一处 webhook 缺失时间戳的 P2 兼容性问题；修复后的 204 项监控/告警影响面、目标 Mypy、Ruff/format、尺寸棘轮和 whitespace 检查均通过，不将该较早的全量结果表述为补丁后的全量重跑。Node 24 lint/typecheck、156 文件/1695 测试、build、bundle gate 和 17 项 CI helper 测试通过；Vitest 的单次 `ECONNRESET` 诊断以退出码 0、测试全通过记录，不表述为 warning-free 测试结论。

## 本批次已关闭的债务

| ID | 证据 | 关闭边界 |
| --- | --- | --- |
| QD-200-02 | Node 24.2.0 下 ESLint 对 404 个文件检查为 0 errors、0 warnings。1345 条纯格式警告由自动修复处理；其余类型、未使用变量和 HTML sink 告警逐项修复/审计，未改规则或配置。 | 仅关闭本次前端 lint 基线债务；不代表类型、依赖安全或 bundle 性能债务关闭。 |
| QD-200-05 | Node 20.20.2/npm 10.8.2 与 Node 24.2.0/npm 11.6.2 均完成 clean `npm ci`、lint、typecheck、全量 Vitest（154 files / 1687 tests）和 build；两版本安装及全部门禁均通过。Node 20 首次失败所缺的 Vite 可选 Sass peer (`sass@1.99.0`、嵌套 `chokidar@4.0.3` / `readdirp@4.1.2`) 已进入锁文件，同时保留 Node 24 所需的全部 13 个 `@parcel/watcher` 平台 optional 条目。 | 关闭仅限当前锁文件在 `.nvmrc` Node 20/npm 10 与 Node 24/npm 11 上的本地复现兼容性；不宣称 CI、其他 npm 版本或 Node 25+ 已验证。 |
| QD-200-06 | T1 后端类型批次：限定的 12 个 Python 源文件 Mypy 从 37 errors 收敛到 0；对应 Ruff check 与 format check 通过；三组现有相关测试合计 256 passed。 | 该项仅记录 T1 的 12 个模块局部边界；全量 Mypy 门禁由 T62/T63 关闭，并在 T64 将 CI ratchet 基线更新为 0。实际 Python 运行时为 3.11.8，未在 Python 3.10 解释器上实跑。 |
| QD-200-07 | T2 为动态 `app.api.deps` 增加显式 PEP 484 sibling stub，转发 `_dependencies.py` 的 auth/WebSocket/permission API 与调用兼容符号；runtime shim 及 `sys.modules` 身份关系未改。覆盖 stub 与全部 37 个直接 API importer 的精确 Mypy 检查中，`app.api.deps` 缺属性错误为 0；指定测试 62 passed、1 个既有 skip。 | 仅关闭 `deps` 动态别名造成的静态缺属性误报；不关闭 `_dependencies.py` 本身或 importer 内其他真实类型错误。 |
| QD-200-08 | T3 将 `database.py` / `mysql_base.py` 的精确 Mypy 从 49 errors 收敛到 0；Ruff check/format 通过，`test_data_fetch_common_utils.py` 为 11 passed。连接/游标由窄 Protocol 描述；pool wrapper 通过适配器和真实 cursor 类型检查；`save_data` 明确返回 `int | Literal[False]`，空 fetch 与空列描述受保护。 | 仅关闭两个核心模块的局部静态类型债务；未实连真实 MySQL。外部 provider/script 调用方仍有基于 Optional cursor/row 与返回联合类型的全量 Mypy 错误，不能宣称调用链类型债务关闭。 |
| QD-200-09 | T4 三个 AkShare consumer/provider/proxy 文件精确 Mypy 从 55 errors（21/21/13）降为 0；六个源码/测试文件 Ruff check 与 format check 通过，直接 fake-only tests 23 passed。MySQL 连接与游标通过窄 Protocol/运行时契约校验，requests probe 参数具体化；`save_data` 保持成功行数、空/不可写返回 False。 | 仅关闭这三个 consumer 文件的局部类型债务；无真实 MySQL、AkShare 或外网验证，完整调用链与全量类型门禁仍开放。 |
| QD-200-10 | T5 三个股票分析/信号模型与任务服务精确 Mypy 初始 58 errors、最终为 0；经父代理批准仅扩展 `ChatMessage.metadata_json` 映射注解后，四文件精确 Mypy 为 0。目标 Ruff check/format 通过，直接 SQLite/fake 测试 26 passed，并断言 assistant mode、task card 状态/ID 和 report ID 的 JSON 键值持久化。五个股票分析表的 SQLAlchemy metadata signature hash 前后不变；ChatMessage 仍为 JSON 列 `metadata` 且 nullable=True。 | 仅关闭 T5 ORM 实例字段静态类型债务；未执行数据库迁移或真实 DB/schema 验收。全量 Mypy 继续开放。 |
| QD-200-11 | T6 将 `paper_trading.py` 的 67 个 ORM 字段/关系迁移为精确 SQLAlchemy 2 映射，并以 `PositionSnapshot`/`PositionEvent` 收紧服务快照边界。精确 Mypy 从 60 errors / 1 file 收敛到 0 / 2 files；Ruff check/format 通过，服务/API 定向测试 142 passed、1 warning。HEAD/工作区 AST 比较无 67 个 `Column`/`relationship` 参数差异，metadata 显示四张仿真交易表的列面保持预期。 | 仅关闭仿真交易模型/服务的局部静态类型债务；未跑迁移、真实交易、真实外部数据库或网络，完整 Mypy 仍未通过。 |
| QD-200-12 | T7 将 `market_data_platform.py` 的 220 个列和 25 个关系迁移为精确 SQLAlchemy 2 映射。模型 Mypy 从 2 errors 收敛到 0；Ruff/format/diff check 通过，store 测试 47 passed、1 warning。AST 参数比较无缺失/额外/差异；schema hash 和 mapper 计数（21/220/25）保持。Store 精确 Mypy 从 43 降至 9 个非 ORM 错误。 | 仅关闭市场数据平台模型实例字段静态类型债务；未关闭 Store 的 9 个数据流/可空性/容器错误，未运行迁移、真实数据库或外部数据源，完整 Mypy 仍未通过。 |
| QD-200-13 | T8 将 `workspace.py` 的 39 个列和 3 个关系迁移为精确 SQLAlchemy 2 映射，JSON 字段使用递归 `WorkspaceJSONMapping`。模型 Mypy 为 0；AST 参数比较无差异；mapper 为 2 tables / 39 columns / 3 relationships；相关服务/API 测试 159 passed、1 warning。 | 仅关闭工作空间模型实例字段静态债务；模型收紧暴露的直接 JSON 消费者由 T9 处理，完整 Mypy 仍未通过；未运行迁移、真实 DB、外部系统或交易通道。 |
| QD-200-14 | T9 将三个工作空间 JSON 消费者的精确 Mypy 从 10 errors（2/1/7）收敛到 0。递归 mapping 守卫保留合法配置/报告行为，并安全丢弃错误形状、非数值及非有限指标；Ruff/format/diff check 通过，5 个 fake/SQLite fixture 通过。 | 仅关闭这三个直接消费者的静态/坏数据处理债务；不关闭完整 Mypy、其他工作空间服务或全局 JSON 消费链，也未验证真实 DB、网络、外部数据或交易系统。 |
| QD-200-15 | T10 将 `market_data/query_service.py` 的精确 Mypy 从 34 errors 收敛到 0。联合回执类型使 deferred receipt 在任何可见性推进、局部 reread 或 response fetch 组装前失败关闭；新增 fixture 断言精确 lease release，并以 8 类有效 HMAC 的错误 JSON payload 验证 cursor 在读取前拒绝。目标 Ruff/format/diff check 通过，完整 query-service fixture 为 69 passed、1 warning。 | 仅关闭查询服务的回执可见性、Store 调用参数和 cursor JSON 静态/运行时边界债务；不关闭 Store、multi-record query 或其他市场数据模块的剩余错误，不构成真实 DB/供应商/网络验收。 |
| QD-200-16 | T11 将 `models/scanner_plan.py` / `services/scanner_plan.py` 的精确 Mypy 从 25 errors 收敛到 0。两个模型的 32 个列和 2 个关系改为精确映射；JSON 使用递归 `JSONValue`。目标 Ruff/format/diff check 通过，mapper 为 15/17 columns、4/5 indexes、2 relationships，scanner-plan API fixture 为 2 passed、1 warning。 | 仅关闭 scanner plan 模型实例字段造成的静态类型债务；不关闭其他模型、服务/API 的广泛动态输入类型或全量 Mypy，也不构成真实数据库、网络或交易系统验收。 |
| QD-200-17 | T12 将 `services/position_valuation.py` 的精确 Mypy 从 20 errors 收敛到 0。`safe_float` overload 准确表达 float/None fallback 返回边界，递归 dict/list 行为与估值计算保持；Ruff/format/diff check 通过，3 个 helper 回归及 21 个既有估值场景通过。 | 仅关闭该数值回退 helper 向估值路径传播的静态误报；不关闭其他动态数据入口、市场行情完整性、真实账户/数据库/交易系统验证或全量 Mypy。 |
| QD-200-18 | T13 将 `services/market_instrument.py` 的精确 Mypy 从 20 errors 收敛到 0。仓库 snapshot 名只接受非空 string，Pandas 可哈希键 row 仅按字符串列名读取，指标显式聚合有效 float；Ruff/format/diff check 通过，5 个新增 fake/Pandas 测试及 15 个既有 API fixture 共 20 passed、1 warning。 | 仅关闭市场标的服务的 snapshot 名称、异构行键和缺失数值聚合静态边界；不关闭其他行情服务、真实数据供应商、数据库/网络/交易系统验证或全量 Mypy。 |
| QD-200-19 | T14 将 `services/news_intelligence.py` 的精确 Mypy 从 18 errors 收敛到 0。可选 session guard 返回局部 AsyncSession，loaded NewsSourceModel 通过窄 scalar Protocol 描述，feed metadata 仅以 Mapping 读取 tickers；Ruff/format/diff check 通过，3 个新增 boundary 测试及 5 个既有新闻 fixture 共 8 passed、1 warning。 | 仅关闭新闻情报服务的可选 session、已加载 ORM 标量和异常 JSON 输入边界；不关闭 legacy NewsSourceModel 的全模型 Mapped 迁移、其他服务、真实数据库/网络或全量 Mypy。 |

| QD-200-20 | T15 将 `services/auth_service.py` 的精确 Mypy 从 9 errors 收敛到 0。两类窄 scalar Protocol 仅覆盖已加载 User/RefreshToken 实例，logout 只把非空 string `jti` 传给撤销仓储；Ruff/format/diff check 通过，6 个新增 token-ID fixture 与 18 个既有认证 fixture 共 24 passed、1 warning，auth API 回归 15 passed、7 warnings。 | 仅关闭认证服务中 legacy ORM scalar 误推断和异常 logout token ID 的失败关闭边界；不关闭 User/RefreshToken 的全模型 Mapped 迁移、其他认证调用方、真实数据库/网络或全量 Mypy。 |

| QD-200-21 | T16 将 `services/alert_evaluation.py` 的精确 Mypy 从 6 errors 收敛到 0。入口 AlertRule scalar view 只在评估边界使用，非 Mapping 配置、空数值与未知 alert type 都在指标服务前失败关闭；Ruff/format/diff check 通过，4 个新增 boundary fixture 与 92 个既有告警/异常 fixture 共 96 passed、1 warning。 | 仅关闭告警评估函数的 legacy ORM scalar 误推断和异常配置/类型边界；不关闭 AlertRule 全模型迁移、MonitoringService 的独立重复逻辑、真实数据库/网络/行情/交易系统或全量 Mypy。 |
| QD-200-22 | T17 为动态 `services/backtest_service.py` 增加仅导出 canonical `BacktestService` 的 sibling stub；stub Mypy 为 0，runtime identity 加既有回测服务 fixture 为 46 passed、1 warning，11 条 shim `[attr-defined]` 误报消失。 | 仅关闭动态 module replacement 造成的静态公开接口误报；stub 显露的调用方可空性/参数真实错误不在本项内，runtime shim、回测服务、数据库、网络与完整 Mypy 均未关闭。 |
| QD-200-23 | T18 将 comparison 创建的验证和 payload 构造收敛为每个输入位置一次 `get_result()`；12 条可空结果 `[union-attr]` 消失，30 项本地比较服务 fixture 与 Ruff/format/diff check 通过。 | 仅关闭 comparison 创建的验证后重复读取/可空解引用债务；不关闭该服务余下 18 条历史类型错误、回测服务、模型/API、真实数据库/网络或完整 Mypy。 |
| QD-200-24 | T19 将参数优化初始/轮询 FAILED 状态统一到受控消息路径；目标 `get_result()` 可空 `[union-attr]` 消失，完整优化 API fixture 为 48 passed、1 warning，Ruff/format/diff check 通过。 | 仅关闭 FAILED 状态的可空错误消息解引用和状态时序不一致；不关闭 `strategy_service` 动态导出、其余优化服务错误、真实数据库/网络或完整 Mypy。 |
| QD-200-25 | T20 为动态 `services/strategy_service.py` 增加 8 名称 sibling stub；stub/core Mypy 为 0，runtime identity 加策略扫描 fixture 为 9 passed、1 warning，20 条 shim `[attr-defined]` 误报消失。 | 仅关闭动态 strategy module replacement 的静态公开接口误报；不关闭 canonical core 以外的调用方真实错误、数据库/网络或完整 Mypy。 |
| QD-200-26 | T21 在增强回测 API 的 client runtime_dir 拒绝之后显式验证为基础服务请求；精确 Mypy 为 0，完整增强回测 fixture 为 52 passed，且转换/拒绝 boundary fixture 为 2 passed、1 warning，1 条 `[arg-type]` 消失。 | 仅关闭增强入口与基础服务间的请求模型不兼容；不关闭 BacktestService 内部余下错误、其他 API/schema 契约、真实数据库/网络或完整 Mypy。 |
| QD-200-27 | T22 为月度复利累计值和 MA 前置结果补充精确数值类型；`analytics_service.py` Mypy 从 2 errors 到 0，22 项分析服务 fixture 通过，2 条局部推断错误消失。 | 仅关闭 analytics service 的两个局部推断错误；不关闭其他分析/指标数据形状、行情/数据库/网络或完整 Mypy。 |
| QD-200-28 | T23 为日志查询参数脱敏容器补充 `str | list[str]` 值类型；`logging.py` Mypy 为 0，8 项日志中间件 fixture 证明 sensitive redaction 与重复普通参数保留，1 条推断错误消失。 | 仅关闭日志 helper 的 local dict 类型推断；不关闭中间件其余类型/运行时错误、审计日志、真实网络或完整 Mypy。 |
| QD-200-29 | T24 为版本参数 diff 的四分类 local dict 补充与公开返回相同的嵌套类型；`version_diff_service.py` Mypy 为 0，18 项版本 diff fixture 通过，1 条 `[var-annotated]` 消失。 | 仅关闭 version diff local container 的类型推断；不关闭策略版本调用方、持久化、数据库/网络或完整 Mypy。 |
| QD-200-30 | T25 将 MonitoringService 的创建 description 签名对齐为 `str | None`；API Mypy 为 0，49 项监控 API fixture 验证省略描述仍以 None/null 往返，1 条 `[arg-type]` 消失。 | 仅关闭 monitor rule create 的 nullable description 合同；不关闭服务内 15 条历史 ORM/Optional 错误、其他监控路径、数据库/网络或完整 Mypy。 |
| QD-200-31 | T26 将 market-data authorization helper 的 principal 返回从 object 收紧为 `MarketDataPrincipal`；API deps Mypy 为 0，4 项 fake-authorizer fixture 验证同一 principal 经 read check 后进入 access context，1 条 `[arg-type]` 消失。 | 仅关闭授权 helper 的静态类型信息丢失；不关闭授权器其余路径、数据查询、真实数据库/网络或完整 Mypy。 |
| QD-200-32 | T27 将 stock compatibility reconciliation 的 legacy local dict 收紧为既有 `dict[str, object]` pairs 合同；`stock_compat.py` Mypy 为 0，2 项 compatibility fixture 保留映射与 zero-defect reconciliation，1 条 append `[arg-type]` 消失。 | 仅关闭该 local container 的类型推断；不关闭 stock-signal 权限/查询、其他 asset-research 路径、真实数据库/网络或完整 Mypy。 |
| QD-200-33 | T28 以实际 literal alias 表达主数据 manifest version，并将类别 Counter 收紧为 `str` 键；`master_data_importer.py` Mypy 为 0，8 项 importer fixture 保留严格 version 与七类计数，2 条 `[valid-type]`/`[arg-type]` 消失。 | 仅关闭 importer 的 version/Counter 静态表达；不关闭 identity writer、publication、其他 market-data 路径、真实数据库/网络或完整 Mypy。 |
| QD-200-34 | T29 将 cache singleton 与 factory 收紧为 `RedisCache | MemoryCache` 联合合同；`cache.py` Mypy 为 0，17 项 cache fixture 保留默认内存和 patched Redis 选择，1 条 `[assignment]` 消失。 | 仅关闭 singleton 的联合实现类型推断；不关闭 Redis 连通性、缓存调用方、TTL/序列化、真实数据库/网络或完整 Mypy。 |
| QD-200-35 | T30 将 calendar manifest version 常量收紧为既有 literal；`calendar_importer.py` Mypy 为 0，13 项 calendar importer fixture 保留 strict manifest 和导入路径，1 条 `[assignment]` 消失。 | 仅关闭 calendar default 的 static literal 表达；不关闭日历验证、事务/publication、其他 market-data 路径、真实数据库/网络或完整 Mypy。 |
| QD-200-36 | T31 将 AkShare engine `extra_kwargs` 收紧为 `dict[str, object]`，保留 NullPool/bool 的互斥参数形状；目标 Mypy 为 0，隔离 pycache 下管理 API fixture 66 passed、79 skipped、2 warnings，1 条 `[assignment]` 消失。 | engine kwargs 的局部异构值推断已关闭；历史默认 pycache `co_filename` 污染由 T68 改按当前 AST node path 判定，timeout fixture 的线程观察由本地 proxy patch + Event 收口，并在最终无 warning 回归中复验。真实 MySQL、调用方和外部网络仍不在本项范围。 |
| QD-200-37 | T32 将只遍历 targets 的 legacy evidence-gate helper 收紧为 `Iterable`；目标 Mypy 为 0，16 项隔离 SQLite harness 维持 fail-closed import 链，两个 ValuesView `[arg-type]` occurrences 消失。 | 仅关闭私有 helper 的输入协议过窄；不关闭 source provenance、授权/permit、store、真实数据库/网络或完整 Mypy。 |
| QD-200-38 | T33 将 stress-test scenarios 参数收紧为协变 `Sequence[dict | StressScenario]`；service/API Mypy 为 0，5 项 fixture 保留 dict 与 Pydantic 场景计算，1 条 API `[arg-type]` 消失。 | 仅关闭只读 scenarios 的列表不变性；不关闭风险分析其他路径、内置场景、外部数据、真实数据库/网络或完整 Mypy。 |
| QD-200-39 | T34 将 AI 改稿 metadata 局部容器标注为 `dict[str, object]`，保留字符串字段和可选 int token；`generation.py` Mypy 为 0，既有 AI 改稿 fixture 保留 total_tokens 断言，1 条 `[assignment]` 消失。 | 仅关闭该局部容器的异构值推断；不关闭公开 metadata 契约、模型响应解析、策略改稿/回退、外部模型、真实数据库/网络或完整 Mypy。 |
| QD-200-40 | T35 将日志 fallback 指标容器隔离为 `dict[str, list[float | None]]`，保留 None 前缀补齐；`log_parser_service.py` Mypy 为 0，56 项 fixture 覆盖 JSON/pipe/TSV 和延后指标，4 条错误消失。 | fallback 可空序列与同作用域变量推断已关闭；当时未覆盖的全 NaN 回撤告警由 T68 在 `FincoreAdapter` 的 all-NaN early return 关闭并保留混合零/负数 fallback。其他 parser、API、真实数据库/网络仍不在本项范围。 |
| QD-200-41 | T36 将文件系统回执 SHA-256 helper 标注为 `TypeGuard[str]`，保留非字符串失败关闭和 constant-time compare；resolver Mypy 为 0，9 项 fixture 覆盖 null hash，1 条 `[type-var]` 消失。 | 仅关闭验证 helper 的静态收窄；不关闭回执 schema、文件系统权限/路径边界、外部部署控制、真实数据库/网络或完整 Mypy。 |
| QD-200-42 | T37 将 LLM pair 计数校验标注为严格 `TypeGuard[int]`，保留 bool/负数/缺项失败关闭；gateway Mypy 为 0，70 项 fixture 保留结算与审计，1 条 `[arg-type]` 消失。 | 仅关闭计数求和前的静态收窄；不关闭 provider、配额、账务、redaction、真实数据库/网络或完整 Mypy。 |
| QD-200-43 | T38 在 holdout journal 持久化前重复检查 live lease 到期时间；journal Mypy 为 0，7 项 fixture 保留 prepare/幂等/拒绝路径，1 条 `[arg-type]` 消失。 | 仅关闭写入点的可空 lease 静态边界；不关闭状态机、evaluator、数据库/网络或完整 Mypy。 |
| QD-200-44 | T39 将 run record freshness helper 的 pipeline 收窄为单次读取的字典边界；`run_records.py` Mypy 为 0，8 项直接 fixture 保留 force、状态、ready、异常形状与 live candidate 判定，1 条 `[union-attr]` 消失。 | 仅关闭该 private helper 的重复读取/可空 pipeline 静态边界；不关闭 run record 持久化、paper/live handoff、数据库/网络或完整 Mypy。 |
| QD-200-45 | T40 将 gateway contract 正数 helper 的 None 守卫显式化；`runtime.py` Mypy 为 0，5 项直接 fixture 保留空字符串、异常、非正数与后续正数 fallback，1 条 `[arg-type]` 消失。 | 仅关闭转换前可空值的静态边界；不关闭 gateway runtime、账户/订单/行情、交易、数据库/网络或完整 Mypy。 |
| QD-200-46 | T41 对 custom factor 的 `ast.UAdd`/`ast.USub` 执行端显式分派；`custom.py` Mypy 为 0，9 项 fixture 保留安全 AST、缺值降级和 API，1 条 `[operator]` 消失。 | 仅关闭一元 operator 容器的静态调用类型；不关闭 AST 策略、registry、因子计算、外部数据、数据库/网络或完整 Mypy。 |
| QD-200-47 | T42 为动态 `live_trading_manager` 增加仅转发 canonical class/factory 的 sibling stub；stub Mypy 为 0、identity fixture 为 1 passed，完整清单移除 15 条 shim `[attr-defined]`。 | 仅关闭 runtime module alias 造成的静态导出误报；不关闭 canonical manager、调用方、真实 gateway/交易或完整 Mypy。新揭露的 11 条 `InstanceData` 合同错误另列 QD-200-48。 |
| QD-200-48 | T43 将 portfolio/workspace 的只读实例记录边界收紧为 `Mapping[str, object]`，并把唯一 `persist_asset_specs()` 写入改为局部浅拷贝；T42 暴露的 11 条 `InstanceData`/`StartResult` 到可变 dict 错误均为 0。直接 TypedDict/bare-dict 与 StartResult fixture、根代理 5 项相邻回归通过；同根 8 条 portfolio params `[union-attr]` 也消失。 | 仅关闭实例记录消费协议和该动态 params 单次读取边界；不关闭 canonical manager/types、runtime shim、asset-info persistence、其他 target-file Mypy 错误、真实 gateway/交易或完整 Mypy。 |
| QD-200-49 | T44 将两个 contract-metadata 同步 helper 改为单次读取的局部 `dict` 收窄，并保留浅拷贝 fallback；两条 `dict()` `[arg-type]` 为 0。instance/spec merge fixture 与 3 条相邻回归为 5 passed、1 条既有 warning；完整 Mypy 从 403/90 到 401/90，标准化差分无新增。 | 仅关闭这两个重复动态读取的静态边界；不关闭 `_safe_dict()`、merge/persistence、其余目标文件 5 条错误、manager/gateway/交易或完整 Mypy。 |
| QD-200-50 | T45 为两个 `_latest_position_rows()` 的不同 tuple 状态表分离局部候选变量；6 条 `[assignment]` 为 0。8 项既有 dual-side、Bybit、flat/directional-flat fixture 为 8 passed、1 条既有 warning；完整 Mypy 从 401/90 到 395/90，标准化差分无新增。 | 仅关闭 state-table 局部变量复用造成的 tuple 推断；不关闭两端其他 Mypy 错误、方向/日志协议、manager/gateway/交易或完整 Mypy。 |
| QD-200-51 | T46 将 portfolio persistence path 的 `contract_metadata` 收窄为单次 `raw_metadata` 读取后的浅拷贝；一条 `dict()` `[arg-type]` 为 0。SQLite/fake gateway persistence fixture 为 1 passed、1 条既有 warning，完整 Mypy 从 395/90 到 394/90，标准化差分无新增。 | 仅关闭 portfolio 此处重复动态读取的静态边界；不关闭 persistence/transaction、其他 portfolio Mypy 错误、manager/gateway/交易或完整 Mypy。 |
| QD-200-52 | T47 为 portfolio equity 的 `strategy_series` 与 `strategy_pnl_series` 明确 `dict[str, list[float]]`；两条 `[var-annotated]` 为 0。6 项既有 equity fixture 为 6 passed、1 条既有 warning；完整 Mypy 从 394/90 到 392/90，标准化差分无新增。 | 仅关闭空 list 容器的浮点元素推断；不关闭 equity 聚合/采样、两条数值转换错误、portfolio API、gateway/交易或完整 Mypy。 |
| QD-200-53 | T48 将两个 direction parser 的 `int(float(value))` 改为现有 `_safe_float(value, float("nan"))` 后的同一 `int()`/异常回退；两条 `[arg-type]` 为 0。两端 numeric text、invalid fallback、Bybit one-way/dual-side fixture 为 6 passed、1 条既有 warning；完整 Mypy 从 392/90 到 390/90，标准化差分无新增。 | 仅关闭动态数值代码的静态转换边界；不关闭 alias/协议、flat 状态表、其余 portfolio/workspace 错误、gateway/交易或完整 Mypy。 |
| QD-200-54 | T49 将 attested paper-runtime anchor 的 raw WorkspaceJSON 只在其为 dict 时赋给既有局部变量；一条 `[assignment]` 为 0。scalar-anchor fake-manager fixture为 3 passed 组的一项，验证真实 verifier 收到 None、返回既有 provenance-invalid 错误且不 sync/add instance；完整 Mypy 从 390/90 到 389/90，标准化差分无新增。 | 仅关闭 anchor JSON 读取的静态边界；不关闭 provenance verifier、分类器、有效 anchor 材料化、manager/gateway/交易或完整 Mypy。 |
| QD-200-55 | T50 将 portfolio `_first_number()` 候选收窄为 `object` 局部（nested 为 `object | None`），并以 `_is_float_input()` TypeGuard 仅放行 `float()` 既有输入协议；目标文件精确 Mypy 为 0，一条 `float()` `[arg-type]` 消失。三项直接 fixture（nested/trim/逗号、invalid-first-key fallback、Decimal/NaN/bytearray）与完整 portfolio fixture 129 passed、1 条既有 warning；完整 Mypy 从 389/90 到 388/89，恰减 1 条与 1 个报错文件。 | 仅关闭该 helper 候选数值转换的静态协议边界；不关闭 `_safe_float()`、数据源、其他 portfolio 聚合路径、manager/gateway/交易或完整 Mypy。 |
| QD-200-56 | T51 将 `alerts.py` 三模型（49 列/10 声明关系）迁移为精确 SQLAlchemy 2 映射并清除 monitoring_service 的 T25 挂账 15 条错误；两文件精确 Mypy 为 0，AST 对比 59 声明零差异，mapper 核验 26/15/8 列。定向测试 198 passed、7 条既有 warning；完整 Mypy 从 388/89 到 373/88，标准化差分恰移除 15 条、新增 0。同批修复模型揭露的两处真实缺陷：WebSocket 告警 `str.value` AttributeError、非字符串 webhook url 在 try 块外崩溃改为既有 missing-url 失败关闭。 | 仅关闭 alerts 模型实例字段静态债务与 monitoring 服务的对应边界；不关闭其它模型的 `Column[...]` 误推断（全仓仍 83 条/27 文件）、通知渠道集成、真实 webhook 投递验证或完整 Mypy。 |
| QD-200-57 | T52 将 `comparison.py` 两模型（16 列/5 关系）迁移为精确 SQLAlchemy 2 映射并清除 comparison_service 的 T18 挂账 18 条错误（含 update 后 `Comparison | None` 从必然 AttributeError 改为返回 None 失败关闭）；两文件精确 Mypy 为 0，AST 对比 21 声明零差异，mapper 核验 11/5 列且时间戳 nullable 保持。定向测试 84 passed；完整 Mypy 从 373/88 到 355/87，标准化差分恰移除 18 条、新增 0。 | 仅关闭 comparison 模型实例字段静态债务与该服务的容器/可空边界；不关闭比较算法语义、`_find_best_metrics` 的 None-vs-float 比较行为、其它模型的 `Column[...]` 误推断或完整 Mypy。 |
| QD-200-58 | T53 将 `akshare_mgmt.py` 七模型（105 列/9 关系）迁移为精确 SQLAlchemy 2 映射并清除 script.py 17 条与模型/execution/scheduler/api-tables/registry 同根因 15 条（含 `safe_defaults` 巨型字面量的精确注解与 legacy 表名 fail-closed 守卫）；五文件精确 Mypy 为 0，AST 对比 114 声明零差异，mapper 核验 7 tables/105 列含 Enum/nullable 探针。定向测试 178 passed、79 skipped（既有）；独立审查 PASS、未发现缺陷；完整 Mypy 从 355/87 到 323/82，标准化差分移除 32 条、新增 0。 | 仅关闭 akshare 管理模型族实例字段静态债务与 script.py 对应边界；不关闭 `market_data/akshare_provider.py` 的 2 条无关错误、AkShare 外部数据流验证、真实调度/网络或完整 Mypy。 |
| QD-200-59 | T54 将 `live_trading/execution.py` 的 16 条全数清除：`_optional_lock` 返回注解修正为 `AbstractAsyncContextManager`（nullcontext 3.10+ 异步协议双重验证）、三个 `_bt_*` 动态句柄改 `__dict__` 直写（与读取侧对称、通过 B010 门禁）、二次 `get` 单次读取收窄；目标文件精确 Mypy 为 0，live_trading 定向测试 208 passed、1 条既有 warning。完整 Mypy 从 323/82 到 307/81，error 级差分恰移除 16 条、新增 0。 | 仅关闭该执行器的静态边界表达；不改变锁语义与子进程清理流程的运行时验证边界、live_trading manager 的 8 条既有错误、真实网关/交易或完整 Mypy。 |
| QD-200-60 | T55 将 `data_governance.py` 八模型（78 列/13 关系）迁移为精确 SQLAlchemy 2 映射并清除 registry 14 条（含 Row→tuple 适配与种子字面量注解收窄）、模型 2 条、bootstrap 2 条与 quant_tools_runtime 1 条连带、store 1 条模型收紧暴露后修复；模型与 registry 精确 Mypy 为 0，AST 对比 91 声明零差异，mapper 核验 8 tables/78 列含时间戳探针。定向测试 148 passed、20 条既有 warning；完整 Mypy 从 307/81 到 287/79，error 级差分恰移除 20 条、新增 0。 | 仅关闭数据治理模型族实例字段静态债务与 registry 对应边界；不关闭 store.py 剩余 8 条 T7 挂账非 ORM 错误、catalog/bootstrap 的运行时数据流验证、真实数据库/网络或完整 Mypy。 |
| QD-200-61 | T56 将 T7 挂账的 `market_data/store.py` 非 ORM 错误全量关闭（T55 后剩 8 条）：五处按既有错误码失败关闭（B2 哈希清单、观测时间等价早退、发布序列、授权容器、semantic dimensions）、两处等价守卫/静态表达；目标文件精确 Mypy 为 0。market_data_platform 全套 1254 passed、137 条既有 warning；完整 Mypy 从 287/79 到 279/78，error 级差分恰移除 8 条、新增 0。两处显式行为收紧（发布序列 None、授权非容器值）为不可信输入失败关闭，与 CQ-200-16/21 同向。 | 仅关闭 store.py 的静态边界与对应失败关闭表达；不关闭 B2/授权/deferred legacy 的真实外部系统验证、query_service 之外的查询路径或完整 Mypy。 |
| QD-200-62 | T57 将 db 基础设施双文件 19 条全数清除：`sql_repository.py` 的 rowcount 经单点 `CursorResult` 收窄、`type[T].id` 经单点 `__dict__` 直接映射访问（Protocol bound 被 Mapped 不变式拒绝、getattr 常量被 B009 拒绝后选定的诚实方案，TypeVar 无 bound 保持泛型兼容）；`database.py` 按 T31 先例注解 engine kwargs、六处 `__table__.create` 单点收窄、`get_db` 修正为 AsyncGenerator。两文件精确 Mypy 为 0；db 影响面回归 147 passed；完整 Mypy 从 279/78 到 260/76，error 级差分恰移除 19 条、新增 0。 | 仅关闭 db 基础设施的静态边界表达；不关闭未迁移模型族的 `Column[...]` 误推断、`BaseRepository` 抽象层、真实 MySQL/PostgreSQL 连接验证或完整 Mypy。 |
| QD-200-63 | T58 将 `research/discovery_trial_materialization.py` 的 13 条可空错误全数清除：两处 `result_json` None 提前抛 `DISCOVERY_EXECUTION_RESULT_INVALID`（与 from_mapping 既有拒绝路径等价）、quota 行缺失抛 `DISCOVERY_PUBLICATION_QUOTA_DENIED`、dataset 快照缺失抛 `DISCOVERY_PUBLICATION_CANDIDATE_DENIED`（后两处从 AttributeError 崩溃改为显式拒绝）。目标文件精确 Mypy 为 0；定向测试 22 passed、1 条既有 warning；完整 Mypy 从 260/76 到 247/75，error 级差分恰移除 13 条、新增 0。 | 仅关闭该物化发布路径的三处可空边界；不关闭 research 模块族其余 27 条左右错误、真实沙箱/配额系统验证或完整 Mypy。 |
| QD-200-64 | T59 补完 `knowledge_base.py` 七模型的 T5 混合迁移状态并清除 reqdocs 9 条（六个二次 get 循环、3 条 Column 误推断、变量复用分离）与 rag_service 4 条同根因连带；模型与 reqdocs 精确 Mypy 为 0，AST 声明零差异。定向测试 44 passed、1 条既有 warning；完整 Mypy 从 247/75 到 234/73，error 级差分恰移除 13 条、新增 0。 | 仅关闭知识库模型族静态债务与 reqdocs 导入边界；不关闭 reqdocs 真实外部系统迁移验证、聊天/检索运行时路径或完整 Mypy。 |
| QD-200-65 | T60 将 `live_trading/manager.py` 的 8 条全数清除：三处二次 get 单次读取、异常动态属性 `__dict__` 直写（T54 模式）、server-attested 私有字段 pop 前移至既有 cast 之前（TypedDict 不可赋可变 dict，同一 dict 与异常路径等价）、批量回调以 `Callable[[str], Awaitable[...]]` 窄注解；目标文件精确 Mypy 为 0。live_trading 定向测试 151 passed、1 条既有 warning；完整 Mypy 从 234/73 到 226/72，error 级差分恰移除 8 条、新增 0。 | 仅关闭该管理器的动态边界与回调合同表达；不改变 server-attested 运行时验证边界、真实网关/交易验证或完整 Mypy。 |
| QD-200-66 | T61 将 market_data 的 `fetch_lease.py` 与 `publication.py` 各 6 条全数清除：六处 rowcount 单点 CursorResult 收窄（T57 模式）、时钟 None 早退（既有 FETCH_LEASE_CLOCK_INVALID）、`found` 行索引重建、动态模型 `__dict__["id"]` 映射、B2 可空哈希清单 None 失败关闭（T56 同款）；两文件精确 Mypy 为 0。定向测试 141 passed、1 条既有 warning；完整 Mypy 从 226/72 到 214/70，error 级差分恰移除 12 条、新增 0。 | 仅关闭这两个文件的静态边界表达；不关闭 lease 状态机/发布事务的并发验证、multi_record_evidence 等其余 market_data 文件或完整 Mypy。 |
| QD-200-67 | T68 为 owner-scoped response cache 引入 HMAC 用户范围，缺失/畸形身份 bypass；真实 ASGI 覆盖两个用户、旧 key 和 unknown principal，最终本地非性能回归为 7859 passed、123 skipped、24 deselected且无 warning summary。 | 关闭当前代码中的跨用户共享缓存读取风险；不等同于共享 Redis 滚动发布已经完成，旧 worker 必须先下线并清理相关缓存。 |
| QD-200-68 | T68 将全 NaN 回撤、JWT fixture 密钥长度、AkShare timeout 网络副作用/后台线程以及嵌套 pytest 门禁逐项收口；相关告警按 error 执行，最终回归无 warning summary。 | 关闭已定位的测试运行时不确定性；不关闭真实 AkShare、MySQL、供应商或交易环境验证。 |
| QD-200-69 | T69 使 canonical dev lock、CI Mypy scope 与 0-error ratchet 在同一依赖集合下可复现：170 个锁定包一致、全量 630/0、四个 scope 0 errors。 | 本地可复现性已关闭；CI workflow 执行仍为 NOT_RUN。 |
| QD-200-70 | T69 将告警 enum wire value、有效 webhook 缺失时间戳兼容、warning-free ESLint 与 7 个 lint 格式化路径的尺寸棘轮冲突收口；监控/告警 204 passed、Node helper 17/17、普通尺寸门禁通过。 | 代码/门禁债务已关闭；真实通知、浏览器 E2E 和 CI 执行仍为 NOT_RUN。 |

## 债务状态（含已关闭项与当前剩余项）

| ID | 当前证据 | 风险 | 建议后续批次 | 关闭标准 |
| --- | --- | --- | --- | --- |
| QD-200-01 | 历史 T1 前 `mypy app` 扫描 625 个源文件，在 188 个文件报告 1120 个错误；T1 后 1072/168；T2 后 1027/145；T3 后 984/143；T4 后 929/140；T5 后 849/136；T6 后 789/135；T7 后 662/129；T8 后 625/131；T9 后 615/128；T10 后 581/127；T11 后 556/126；T12 后 536/125；T13 后 516/124；T14 后 498/123；T15 后 489/122；T16 后 483/121；T17 后 486/120（11 条 shim 误报消失同时暴露 14 条真实调用方错误）；T18 后 474/120；T19 后 473/120；T20 后 453/116；T21 后 452/115；T22 后 450/114；T23 后 449/113；T24 后 448/112；T25 后 447/111；T26 后 446/110；T27 后 445/109；T28 后 443/108；T29 后 442/107；T30 后 441/106；T31 后 440/105；T32 后 438/104；T33 后 437/103；T34 后 436/102；T35 后 432/101；T36 后 431/100；T37 后 430/99；T38 后 429/98；T39 后 428/97；T40 后 427/96；T41 后 426/95；T42 后 422/90；T43 后 403/90；T44 后 401/90；T45 后 395/90；T46 后 394/90；T47 后 392/90；T48 后 390/90；T49 后 389/90；T50 后 388/89；T51 后 373/88；T52 后 355/87；T53 后 323/82；T54 后 307/81；T55 后 287/79；T56 后 279/78；T57 后 260/76；T58 后 247/75；T59 后 234/73；T60 后 226/72；T61 后扫描 625 个源文件，报告 214 errors / 70 files，退出码 1。T61 相对 T60 的 error 级标准化差分恰移除 12 条、新增 0 条。 当前关闭证据：T62/T63 新隔离缓存全量检查为 0 errors / 625 source files；T64 guarded baseline update 将 CI 基线设为 0，常规 ratchet 为 errors=0、baseline=0、delta=+0。 | 已关闭：当前全量 Mypy 与 CI ratchet 均为 0 errors。 | CI 持续用 0-error ratchet 阻止类型错误回归；新增错误应修复后再合入，不抬高基线。 | 已满足：新缓存全量 Mypy 0/625、guarded baseline update 0、常规 ratchet delta +0；不据此声明外部或生产验收通过。 |
| QD-200-03 | T65 的 canonical Python dev/prod 锁与 Python 3.10 临时解析环境均为 pip-audit 0 finding；T67 的 Node 20 production/full `npm audit --json` 也均为 0 vulnerability。固定 Git backtrader 不在 PyPI advisory 覆盖范围。 | 已关闭可审计注册表依赖债务；Git 来源仍是明确的覆盖边界，不得表述为已由 pip-audit 证明无漏洞。 | CI 持续运行 npm/pip registry audit；Git 来源另行保留 commit provenance 与人工安全复审。 | 已满足：Python/npm registry audit 有当前可复现的 0 finding 证据，Git 来源的不可审计边界已明确记录。 |
| QD-200-04 | T66 最终 Node 20.20.2 构建后的 manifest gate 通过：entry gzip 31,858 / 307,200 bytes、entry static closure 616,170 / 655,360、`/login` initial closure 619,716 / 655,360、最大初始 JS（含 vendor）527,484 / 552,960；entry/login 初始 JS 均不超过 4 个。Monaco 与 Workspace async 边界有可见 loading/error/retry；Workspace 15 秒 timeout 和 ErrorBoundary 重试二次 loader 调用有测试。Vite 仍有 >500 kB 单 chunk advisory warning。 | 已关闭静态 bundle 门禁与可恢复异步 UI 代码债务；真实浏览器网络、缓存与感知加载测量仍 NOT_RUN，不能据此声称真实首屏体验达标。 | CI 持续运行 manifest gate；后续用浏览器 network throttling / 实际部署 CDN 记录首屏关键路径与错误 chunk 重试行为。 | 已满足代码门禁；浏览器/E2E 证据是发布体验验证的独立后续项。 |
| QD-200-71 | T69 已关闭 lint/尺寸棘轮交叉债务；但七个大型编排器与两个共享提取候选仍保持 OPEN，准确范围与量化上限见迭代 201。 | 不以基线刷新掩盖结构复杂度。 | Iteration 201。 | 九个工作包实际达到其行数上限、兼容 facade 与回归通过后才可关闭。 |

| QD-200-72 | 代码路径已使用 HMAC 用户分区并经 ASGI/最终本地非性能回归验证；本地结果为 `7859 passed, 123 skipped, 24 deselected`，无 warning summary。 | 代码级跨用户缓存读取风险已关闭；共享 Redis 中旧版 worker 仍可能继续使用 legacy key，属于未验证的发布期残余。 | 发布 runbook：drain/stop 全部旧 worker，按 `backtests:*` 与 `strategies:*` 失效缓存后再切流。 | 部署日志证明旧 worker 已退出、缓存失效完成且新 worker 独占处理请求；当前为 NOT_RUN。 |

## 维护规则

- 后续批次先更新本台账的基线和责任范围，再修改代码；不得把历史失败归为本轮成功。
- 每个债务项目的局部测试只能证明对应根因，不能替代完整门禁。
- 依赖升级、格式化和性能优化分别评审，避免一个质量修复把无关的行为改动混入同一变更集。

## T61 fetch lease 与 publication 游标/时钟/动态模型边界批次（2026-09-21）

- 修改仅限 `src/backend/app/services/market_data/fetch_lease.py`、`app/services/market_data/publication.py` 与本迭代文档。没有改 lease 状态机、发布事务顺序、完整性校验语义、schema、API、配置、依赖或静态检查设置；新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。
- 全部修复为 T56/T57 已验证模式的复刻（CursorResult 收窄、None 早退/失败关闭、`__dict__` 直接映射、行索引重建），无新增错误码、无行为变化。
- 根代理定向测试五文件 141 passed、1 条既有 warning；两文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 214 errors / 70 files（625 checked、退出码 1）：error 级标准化差分恰移除 12 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T60 live trading 管理器动态边界与回调合同批次（2026-09-21）

- 修改仅限 `src/backend/app/services/live_trading/manager.py` 与本迭代文档。没有改启动/停止流程、server-attested 清理时序、schema、API、配置、依赖或静态检查设置；新增行零 `Any`、`type: ignore`、`# noqa`（唯一 cast 命中为既有 cast 的等价重排）。
- 四处修复均为运行时等价或既有合同的表达收敛：单次读取、`__dict__` 直写（属性保留未删）、pop 前移（同一 dict、异常路径不变）、回调窄注解（绑定方法与包装函数均满足）。
- 根代理 live_trading 定向测试四文件 151 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 226 errors / 72 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T59 知识库 ORM 补完迁移与 reqdocs 导入边界批次（2026-09-21）

- 修改仅限 `src/backend/app/models/knowledge_base.py`、`src/backend/app/services/reqdocs_migration_service.py` 与本迭代文档；rag_service 的消除为同根因连带，未改该文件。没有改导入/合并语义、幂等键、schema、API、配置、依赖或静态检查设置；新增行零 `cast`、`type: ignore`、`# noqa`（`typing.Any` 为 T5 既有 import 保留）。
- 时间戳按 T8/T51 先例（baseline nullable=True 佐证），JSON 字段沿用 ChatMessage.metadata_json 的 `dict[str, object] | None` 先例与递归 `JSONValue`；T5 既有注解原样未动。reqdocs 的循环改写与变量分离均为运行时等价形态。
- 根代理定向测试三文件 44 passed、1 条既有 warning；模型与 reqdocs 精确 Mypy 为 0，AST 声明零差异，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 234 errors / 73 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T58 discovery 试验物化发布可空边界批次（2026-09-21）

- 修改仅限 `src/backend/app/services/research/discovery_trial_materialization.py` 与本迭代文档。没有改物化/发布流程、候选完整性校验、配额结算语义、schema、API、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 三处失败关闭全部沿用相邻既有错误码：`result_json` None 的显式化与 from_mapping 内部拒绝路径完全等价；quota 与 dataset 两处从 AttributeError 崩溃改为显式拒绝，是行为收紧但方向为失败关闭。
- 根代理定向测试 22 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 247 errors / 75 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T57 db 基础设施泛型仓库与引擎边界批次（2026-09-21）

- 修改仅限 `src/backend/app/db/sql_repository.py`、`src/backend/app/db/database.py` 与本迭代文档。没有改仓库语义、DML 行为、建表/索引流程、会话生命周期、schema、API、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 两处单点收窄（rowcount 的 CursorResult、`__table__.create` 的 Table）表达运行时事实；`_id_column` 的 `__dict__` 直接映射访问与文件既有动态风格一致，方案选择过程（Protocol 两种声明与 getattr 常量均被既有类型/门禁拒绝）留档 ACCEPTANCE。
- 根代理 db 影响面回归 147 passed、既有 warnings；`SQLRepository` 三个真实模型实例化探针通过；两文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 260 errors / 76 files（625 checked、退出码 1）：error 级标准化差分恰移除 19 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T56 市场数据存储 T7 挂账非 ORM 边界批次（2026-09-21）

- 修改仅限 `src/backend/app/services/market_data/store.py` 与本迭代文档。没有改 B2 证据协议、deferred legacy 发布流程、授权断言语义、semantic key 规范、calendar 组合算法、schema、API、迁移、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 七处修复中五处为按既有错误码的失败关闭（不引入新错误码），两处为等价守卫/纯静态表达；`visibility_sequence` None 与授权非容器值两处显式行为收紧均为不可信输入失败关闭，单独记录。
- 根代理 market_data_platform 全套定向测试（62 文件）1254 passed、137 条既有 warning；目标文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 279 errors / 78 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T55 数据治理 ORM 与连接器注册表边界批次（2026-09-21）

- 修改仅限 `src/backend/app/models/data_governance.py`、`src/backend/app/services/data_connectors/registry.py`、`app/services/market_data/store.py` 的两处容器注解与本迭代文档；bootstrap 与 quant_tools_runtime 的消除为同根因连带，未改这些文件。没有改种子内容、preview/job 流程、载荷字段、schema、API、迁移、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 八模型迁移保持 91 声明调用参数与 HEAD 一致（AST 归一化零差异）；`Enum(DgJobStatus)` 无 `values_callable` 的既有存储语义、显式 nullable=False 时间戳、CheckConstraint/UniqueConstraint 与跨模型关系全部保持。registry 的 Row→tuple 适配、种子注解与 isinstance 收窄、store 的容器注解均为既有合同/形态的诚实表达。
- 根代理定向测试五文件 148 passed、20 条既有 warning；模型与 registry 精确 Mypy 为 0，mapper 核验 8 tables/78 列含时间戳探针，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 287 errors / 79 files（625 checked、退出码 1）：error 级标准化差分恰移除 20 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T54 live trading 执行器异步上下文与动态属性批次（2026-09-21）

- 修改仅限 `src/backend/app/services/live_trading/execution.py` 与本迭代文档。没有改锁语义、子进程启动/清理流程、contract metadata 合并、API/schema、配置、依赖或静态检查设置；未新增 `Any`、`cast`、`type: ignore`、`# noqa`（`_optional_lock` 签名行 `Any` 为既有参数化）。
- 异步上下文注解修正经运行时 3.11 与 Mypy `--python-version 3.10` 探针双重验证；`__dict__` 直写方案与读取侧对称并通过既有 B010 门禁（初版 setattr 方案被该门禁拒绝后换用，未加豁免）。
- 根代理定向测试七文件 208 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff/format/target whitespace 检查通过。完整 Mypy 为 307 errors / 81 files（625 checked、退出码 1）：error 级标准化差分恰移除 16 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T53 AkShare 管理 ORM 与脚本服务边界批次（2026-09-21）

- 修改仅限 `src/backend/app/models/akshare_mgmt.py`、`src/backend/app/services/akshare/script.py` 与本迭代文档；execution/scheduler/api-tables 与 registry 的消除为同根因连带，未改这些文件。没有改 AkShare 数据流、脚本执行、调度语义、schema、API、迁移、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 七模型迁移保持 114 声明调用参数与 HEAD 一致（AST 归一化零差异）；五个 Enum 列保持 `values_callable` 与 enum 类型注解，`metadata_json` 保持显式列名 "metadata"，全部显式 nullable kwarg 不变。script.py 四处修复经独立审查逐情形证实行为等价；legacy 守卫加固不可达路径并消除静默同步 "data" 错表隐患。
- 根代理定向测试六文件 178 passed、79 skipped（既有）、1 条既有 warning；五文件精确 Mypy 为 0，mapper 核验 7 tables/105 列/9 关系含 Enum/nullable 探针，Ruff/format/target whitespace 与 diff suppression 检查通过；独立审查 PASS、未发现缺陷。完整 Mypy 为 323 errors / 82 files（625 checked、退出码 1）：标准化差分移除 32 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T52 比较 ORM 实例字段与服务容器边界批次（2026-09-21）

- 修改仅限 `src/backend/app/models/comparison.py`、`src/backend/app/services/comparison_service.py` 与本迭代文档。没有改比较算法、best-metric 选择语义、payload 字段、schema、API、迁移、配置、依赖或静态检查设置；新增行无 `cast`、`type: ignore`、`# noqa`，新增的 4 处 `dict[str, Any]` 局部注解与各自既有 `-> dict[str, Any]` 返回签名一致（T24 先例口径）。
- 两模型迁移保持 16 列 + 5 关系调用参数与 HEAD 一致（AST 归一化对比 21 声明零差异）；时间戳按 T8/T51 先例 `Mapped[datetime | None]`，mapper 探针与 baseline 双重核验无 nullable 翻转；update 后 `Comparison | None` 显式守卫从必然 AttributeError 改为返回 None 失败关闭。
- 根代理定向测试 84 passed（service 30 + comparison/api 54）、既有 warnings；两文件精确 Mypy 为 0，Ruff/format/target whitespace 检查通过。完整 Mypy 为 355 errors / 87 files（625 checked、退出码 1）：标准化差分恰移除 18 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T51 告警 ORM 实例字段与监控服务边界批次（2026-09-21）

- 修改仅限 `src/backend/app/models/alerts.py`、`src/backend/app/services/monitoring_service.py` 与本迭代文档。没有改迁移、API/schema、`alert_evaluation` 的评估边界、通知渠道集成、调度、配置、依赖或静态检查设置；新增行零 `Any`、`cast`、`type: ignore`、`# noqa`。
- 三模型迁移保持全部列/关系调用参数与 HEAD 一致（AST 归一化对比 59 声明零差异）；服务侧仅做等价守卫与单次读取收窄。模型揭露的两处真实缺陷按既有失败关闭语义修复：WebSocket 告警的 str 属性直接传值，非字符串 webhook url 走既有 "missing webhook url" 记录路径。
- 根代理合跑六个 monitoring/alert fixture 为 198 passed、7 条既有 warning；两文件精确 Mypy 为 0，mapper 核验 26/15/8 列与关系配置（含独立审查揭露并修正的 5 个时间戳列 nullable 翻转，按 T8 先例恢复 `Mapped[datetime | None]`），Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 373 errors / 88 files（625 checked、退出码 1）：标准化差分恰移除 15 条、新增 0；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T50 portfolio 候选数值协议收窄批次（2026-09-21）

- 修改仅限 `src/backend/app/api/portfolio/api.py` 与本迭代文档。没有改 `_safe_float()`、数据源、API/schema、模型、manager/gateway、迁移、配置或依赖；本批未修改测试模块，直接 fixture 由本工作区已建立的三项 `_first_number` 回归承担。
- 候选值先收窄为 `object` 局部读取，nested 候选为 `object | None`；`_is_float_input()` TypeGuard 仅放行 `float()` 既有输入协议（str/bytes/bytearray/memoryview/`SupportsFloat`/`SupportsIndex`），非协议值继续下一候选键，与旧 `float()` TypeError→捕获→continue 路径可观察行为等价。`(TypeError, ValueError)` 捕获、nested 优先级、string trim/逗号移除、NaN/Infinity 保留未改；新增 hunk 无 `Any`、`cast`、`type: ignore` 或 `# noqa`，累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解。
- 根代理的三项直接 fixture 为 3 passed，完整 `tests/test_portfolio_api.py` 为 129 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 388 errors / 89 files（625 checked、退出码 1）：恰较 T49 减 1 条与 1 个报错文件，`api/portfolio/api.py` 退出完整清单；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T49 attested paper runtime anchor JSON 边界批次（2026-09-21）

- 修改仅限 `src/backend/app/services/trading_workspace_service.py`、对应直接测试与本迭代文档。没有改 provenance verifier、server-owned 分类器、risk gate、runtime sync、manager、API/schema、模型、配置、依赖或迁移。
- raw anchor 仅在 dict 时赋给原 `paper_runtime_anchor`；非 Mapping JSON 继续由同一 verifier 失败关闭，产生相同 `AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID`。有效 dict 的 pre/post-sync re-check、refresh 与启动路径未改；T49 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有 `_runtime_config_for_instance()` 返回注解。
- 根代理的 scalar-anchor fail-closed、live risk-gate 与普通 paper-start fixture 为 3 passed、1 条既有 warning；新 fixture 断言 verifier 收到 None、runtime sync 与 add_instance 为零调用，target Mypy 为 0，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 389 errors / 90 files（625 checked、退出码 1）：精确减 1、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T48 position-log 方向代码受控数值转换批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/portfolio/api.py`、`src/backend/app/services/trading_workspace_service.py`、两个直接测试模块及本迭代文档。没有改 alias table、code mapping、flat/latest-row state、估值、日志解析、manager/gateway、API/schema、模型、配置、依赖或迁移。
- 两处只以原模块 `_safe_float(value, float("nan"))` 代替内部 `float(value)`，随后保留同一 `int()` 和同一 `TypeError`/`ValueError` 捕获。numeric code 保持原 mapping，invalid code 仍通过 NaN 的 `ValueError` 落入原 signed-size fallback。T48 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有 `_runtime_config_for_instance()` 返回注解。
- 根代理的两端 direct numeric-code/invalid-fallback/Bybit dual-side fixture 合计为 6 passed、1 条既有 warning；两文件精确 Mypy 的两条目标 `[arg-type]` 为 0，余两条为既有非 T48 错误，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 390 errors / 90 files（625 checked、退出码 1）：精确减 2、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T47 portfolio equity 浮点序列容器批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/portfolio/api.py` 与本迭代文档。没有改 aggregation、drawdown、sampling、response payload、API/schema、模型、manager/gateway、配置、依赖或迁移。
- `strategy_series` 与 `strategy_pnl_series` 只增加 `dict[str, list[float]]` 局部注解；同一 comprehension、同一 `_safe_round()` append、同一采样重建与输出访问保持不变。T47 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有 `_runtime_config_for_instance()` 返回注解。
- 根代理的 6 项既有 equity fixture 为 6 passed、1 条既有 warning；目标 Mypy 的两条 `[var-annotated]` 为 0，余两条为既有非 T47 `float()` `[arg-type]`，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 392 errors / 90 files（625 checked、退出码 1）：精确减 2、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T46 portfolio metadata 单次读取与资产规格持久化批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/portfolio/api.py` 与本迭代文档。没有改 `_safe_dict()`、asset-spec merge、async session/transaction、manager/gateway、API/schema、模型、配置、依赖或迁移。
- persistence helper 将 `params.get("contract_metadata")` 保存为 `raw_metadata`，只对已验证的 dict 建立原有 shallow copy；user/workspace 查询、server-owned 早退、alias/merge/source、changed、写回均未变。T46 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中为 T43 已有 `_runtime_config_for_instance()` 返回注解。
- 根代理的 SQLite/fake gateway persistence fixture 为 1 passed、1 条既有 warning；目标 Mypy 的一条精确 `dict()` `[arg-type]` 为 0，余 4 条为既有非 T46 错误，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 394 errors / 90 files（625 checked、退出码 1）：精确减 1、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T45 position-log tuple 状态表局部身份批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/trading_workspace_service.py`、`src/backend/app/api/portfolio/api.py` 与本迭代文档。没有改日志解析、方向识别、manager/gateway、API/schema、模型、配置、依赖或迁移，也没有抽取共享 helper。
- 每个改变后的候选变量仍从同一张四元组、三元组或二元组状态表读取，并以相同 tuple slot 的 timestamp/index 比较。dual-side/Bybit/无方向 flat/方向 flat 与排序逻辑未改；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 根代理的 8 项既有 latest-row fixture 为 8 passed、1 条既有 warning；两文件精确 Mypy 的 6 条目标 `[assignment]` 为 0，余 7 条为既有非 T45 错误，Ruff/format/target whitespace 与 diff suppression 检查通过。T45 新增 hunk 没有 `Any`、`cast`、`type: ignore` 或 `# noqa`；累计差异唯一 `Any` 命中为 T43 已有的 `_runtime_config_for_instance()` 返回注解。完整 Mypy 为 395 errors / 90 files（625 checked、退出码 1）：精确减 6、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T44 合约 metadata 单次读取与浅拷贝批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/trading_workspace_service.py`、`src/backend/tests/test_trading_workspace_service.py` 与本迭代文档。没有改 `_safe_dict()`、asset-spec merge/persistence、manager、gateway、API/schema、模型、配置、依赖或迁移。
- 两个同步 helper 各自将 `params.get("contract_metadata")` 保存为单次局部读取，仅当该值为 `dict` 时保留原有浅拷贝，否则继续用空字典。server-owned/空输入短路、alias、merge/source、changed 和写回顺序未变；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 根代理的两个直接 merge fixture 与 3 条相邻回归为 5 passed、1 条既有 warning；目标 Mypy 中两条精确 `dict()` `[arg-type]` 为 0，剩余 5 条为既有非 T44 错误，Ruff/format/target whitespace 与 diff suppression 检查通过。完整 Mypy 为 401 errors / 90 files（625 checked、退出码 1）：原始数减 2、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T43 live trading 实例只读 Mapping 批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/portfolio/api.py`、`src/backend/app/services/trading_workspace_service.py`、两处直接测试与本迭代文档。没有改 runtime shim/sibling stub、canonical manager、`app/types/live_trading.py`、asset-info persistence、API/schema、模型、配置、依赖或迁移。
- 所有 manager record consumer 改为只读 `Mapping[str, object]`；`start_units()` 显式统一已运行实例、StartResult 和 refresh 实例，未新增 manager/read gateway 调用。`persist_asset_specs()` 仅获得局部浅拷贝，unit metadata sync/状态/snapshot/run_count 的既有顺序保持。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 根代理目标 Mypy 的 11 条精确合同诊断为 0（命令仍有 15 条既有非 T43 错误）；5 项直接/相邻 pytest 为 5 passed、1 条既有 warning，Ruff/format、target diff whitespace、全迭代文档 whitespace 和新增 suppression 扫描均通过。完整 Mypy 为 403 errors / 90 files（625 checked、退出码 1）：原始数净减 19、标准化差分无新增；QD-200-01 继续 FAIL / NO-GO，未连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T42 动态 live trading manager shim 静态入口批次边界（2026-09-21）

- 修改仅限新增 `src/backend/app/services/live_trading_manager.pyi`、新增 `src/backend/tests/test_live_trading_manager_runtime_shim.py` 与本迭代文档。未修改 runtime shim、canonical manager、调用方、singleton、gateway/交易、API、模型、配置、依赖、数据库 schema 或迁移。
- stub 只精确 re-export `LiveTradingManager` / `get_live_trading_manager`，没有 `Any`、`__getattr__`、wildcard import、`cast`、`type: ignore` 或 `# noqa`。identity fixture 与根代理 raw import 均证明 module/class/factory 仍为 canonical 对象，且没有调用 factory 或构造 manager。
- stub Mypy 为 0；identity fixture 为 1 passed、1 条既有 warning；Ruff/format、untracked whitespace 及 diff 抑制检查通过。11 个 importer 独立 Mypy 为 47 条其他错误/6 文件，零 shim `[attr-defined]`、零新 class/factory 调用签名错误。全量 Mypy 为 422 errors / 90 files（625 checked、退出码 1）：移除 15 条 shim 误报、揭露 11 条 `InstanceData`/dict 真实合同（QD-200-48），净减 4；QD-200-01 继续 FAIL / NO-GO，未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T41 自定义因子一元正负精确分派批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/factor_lib/custom.py`、`src/backend/tests/test_factor_correlation.py` 与本迭代文档。未修改 AST allowlist、API/schema/registry、因子协议、配置、依赖、数据库 schema 或迁移。
- evaluator 仅对已经允许的 `ast.UAdd`/`ast.USub` 分别调用 `operator.pos`/`operator.neg`；递归 operand、四则/幂算术、缺值 `None` 降级、unsafe expression 的 degraded 行为保持。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 pycache 下完整 factor fixture 为 9 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 426 errors / 95 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 unary `[operator]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T40 网关合约正数判定可空值批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/gateway/runtime.py`、新增 `src/backend/tests/test_gateway_runtime_contracts.py` 与本迭代文档。未修改 gateway runtime、asset spec 选择、账户/订单/行情连接、交易、API、模型、配置、依赖、数据库 schema 或迁移。
- `_positive_spec_number()` 在转换前显式跳过 None，空字符串仍跳过，转换异常仍继续，零/负数仍不通过，候选键顺序与后续正数 fallback 保持；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 pycache 下直接 fixture 为 5 passed、1 条既有 warning，Ruff/format、tracked/untracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 427 errors / 96 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 float `[arg-type]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T39 run record pipeline 单次读取批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/research/run_records.py`、新增 `src/backend/tests/test_ai_research_run_records.py` 与本迭代文档。未修改 persist 流程、run record/paper/live handoff、API、模型、配置、依赖、数据库 schema 或迁移。
- helper 仅将 `raw.get("pipeline")` 读取一次；它是字典时读取 `current_stage`，否则使用既有空字典 fallback。force、状态、ready、live candidate 的短路顺序和返回值保持；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 pycache 下直接 fixture 为 8 passed、1 条既有 warning，Ruff/format、tracked/untracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 428 errors / 97 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 pipeline `[union-attr]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、模型供应商、行情或交易系统。

## T38 holdout journal lease 到期时间失败关闭批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/research/holdout_execution_journal.py` 与本迭代文档。未修改状态机、lease 比较、journal/record schema、evaluator、API、模型、配置、依赖、数据库 schema 或迁移。
- `prepare()` 将 live binding 的 `lease_expires_at` 保存为局部变量；为空继续抛出既有 `HOLDOUT_EXECUTION_PREPARE_DENIED`，只有非空值才送入 `_as_utc`。正常写入、幂等与拒绝边界保持不变；没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 pycache 下完整 journal fixture 为 7 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 429 errors / 98 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 lease `[arg-type]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、模型供应商、行情或交易系统。

## T37 LLM 成对用量 TypeGuard 批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/research/llm_gateway.py` 与本迭代文档。未修改 provider、quota settlement、审计/redaction、API、模型、配置、依赖、数据库 schema 或迁移。
- `_is_non_negative_token_count(value: object) -> TypeGuard[int]` 保持严格 builtin-int/非负判断，bool 仍拒绝；pair 仅在校验后直接相加，顺序、total 对照、未知用量失败关闭均不变。源文件的 `Any` 出现次数前后均为 26，且没有新增 `cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立完整 gateway fixture 为 70 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 430 errors / 99 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 `[arg-type]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、模型供应商、行情或交易系统。

## T36 文件系统回执 SHA-256 TypeGuard 批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/research/filesystem_dataset_resolver.py`、`src/backend/tests/test_ai_research_filesystem_dataset_resolver.py` 与本迭代文档。未修改 receipt schema、文件根/权限、路径、描述符、发布、API、模型、配置、依赖、数据库 schema 或迁移。
- `_valid_sha256(value: object) -> TypeGuard[str]` 精确表达既有 string/64-char/lowercase-hex 校验；compare_digest、失败关闭代码和所有运行时条件不变。源文件的 `Any` 出现次数前后均为 9，且没有新增 `cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立完整 resolver fixture 为 9 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 431 errors / 100 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 `[type-var]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、模型供应商、行情或交易系统。

## T35 日志 fallback 指标可空序列批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/log_parser_service.py`、`src/backend/tests/test_log_parser.py` 与本迭代文档。未修改 JSON/pipe/TSV parser 之外的代码、API、模型、配置、依赖、数据库 schema 或迁移。
- no-data.log fallback 的容器为独立 `bar_indicators: dict[str, list[float | None]]`，保持日期优先/索引回退、None 前缀补齐；TSV 的 `indicators: dict[str, list[float]]` 不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 pycache 下三文件日志解析 fixture 为 56 passed、2 条既有 warnings，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 432 errors / 101 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 4 条 fallback 错误，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T34 AI 策略改稿 metadata 异构值容器批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/research/generation.py` 与本迭代文档。未修改 AI 模型响应解析、策略改稿/代码参数校验、回退、API、schema、模型、配置、依赖、数据库 schema 或迁移。
- `_merge_ai_improvement()` 的 metadata 仅从隐式 string dict 推断改为 `dict[str, object]`，准确容纳已有字符串字段和可选 int token。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`；其他既有 `Any` 契约未改。
- 精确 Mypy 为 0；根代理独立既有 AI 改稿回归节点为 1 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 436 errors / 102 files（625 checked、退出码 1），标准化差分无新增诊断、只移除 1 条 `[assignment]`，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、模型供应商、行情或交易系统。

## T33 压力测试 scenarios 协变 Sequence 合同批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/risk_analytics/stress_test.py` 与本迭代文档。未修改 API、schema、built-in scenario、指标计算、输出、模型、配置、依赖、数据库 schema 或迁移。
- run_scenarios/_normalize_scenarios 均以 `Sequence[dict | StressScenario]` 表达已有只读消费；dict 输入兼容和所有运行时计算保持不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- service/API 联合精确 Mypy 为 0；根代理独立 stress-test fixture 为 5 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 437 errors / 103 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T32 legacy evidence-gate target Iterable 合同批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/market_data/legacy_stock_daily_evidence_gate_adapter.py` 与本迭代文档。未修改 source provenance、fail-closed 授权、read/source-batch/permit、store、API、模型、配置、依赖、数据库 schema 或迁移。
- `_assert_isolated_unverified_targets(targets: Iterable[...])` 只表达函数已有的一次遍历能力；两处 `dict.values()` 继续逐目标执行相同 source binding。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立隔离 SQLite harness 为 16 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 438 errors / 104 files（625 checked、退出码 1），标准化差分无新增诊断、一个重复签名移除但完整 errors 减少 2，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T31 AkShare engine kwargs 异构值容器批次边界（2026-09-21）

- 修改仅限 `src/backend/app/db/akshare_data_database.py` 与本迭代文档。未修改 URL 解析、MySQL/非 MySQL 分支、engine/sessionmaker singleton、调用方、API、配置、依赖、数据库 schema 或迁移。
- `extra_kwargs: dict[str, object]` 只表达已有 `poolclass: NullPool` / `pool_pre_ping: bool` 互斥值形状；实际传递参数和连接行为不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0，Ruff/format、tracked whitespace 及 diff 抑制检查通过。默认 pycache 的历史 co_filename 污染造成 141 setup errors，未清理或改写缓存；根代理以新隔离 pycache 获得 66 passed、79 skipped、2 warnings。全量 `mypy app` 为 440 errors / 105 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实 MySQL、网络、行情或交易系统。

## T30 calendar manifest 默认 literal 类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/market_data/calendar_importer.py` 与本迭代文档。未修改 strict model、calendar loader、日期/时区/coverage 验证、事务/publication、API、模型、配置、依赖、数据库 schema 或迁移。
- `MANIFEST_VERSION: Literal["market-data-calendar-v1"]` 仅让默认值与字段 literal 合同一致；wire value 和所有运行时校验/流程不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立 calendar importer fixture 为 13 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 441 errors / 106 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T29 缓存单例 Redis/内存联合类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/db/cache.py` 与本迭代文档。未修改 cache key/TTL/序列化、Redis/Memory 实现、调用方、配置、依赖、API、数据库 schema 或迁移。
- `_cache_instance: RedisCache | MemoryCache | None` 和 factory 联合返回只表达既有两分支状态；REDIS_URL 选择、首次构造与后续复用保持不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立 cache fixture 为 17 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 442 errors / 107 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实 Redis、数据库、网络、行情或交易系统。

## T28 主数据 manifest literal 与类别计数类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/market_data/master_data_importer.py` 与本迭代文档。未修改 identity writer、publication、schema、模型、API、配置、依赖、数据库 schema 或迁移。
- `ManifestVersion` 与常量仍描述同一个 `market-data-master-v1` wire value；`Counter[str]` 仍按每个 prepared identity 的 asset_type 计数。strict validation、七类计数、排序输出、事务和 publication 行为不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立 importer fixture 为 8 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 443 errors / 108 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T27 股票研究兼容层 reconciliation payload 类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/asset_research/stock_compat.py` 与本迭代文档。未修改 stock signal service、schema、模型、API、配置、依赖、数据库 schema 或迁移。
- `legacy: dict[str, object]` 只恢复已声明 pairs 容器的静态合同；legacy/generic 字段值、mapping version、记录顺序和 `reconcile_batch()` 调用不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立 compatibility fixture 为 2 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 445 errors / 109 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T26 市场数据授权 principal 类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/data/deps.py`、`src/backend/tests/test_data_management_deps.py` 与本迭代文档。未修改授权器、权限/用户模型、查询服务、路由、配置、依赖、数据库 schema 或迁移。
- helper tuple 的第一个元素从 object 收紧为 `MarketDataPrincipal`；`principal_for_user()`、`require_read_data()`、授权失败 HTTP 映射和同一对象传递顺序不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立授权依赖 fixture 为 4 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 446 errors / 110 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T25 监控规则可空 description 契约批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/monitoring_service.py`、`src/backend/tests/test_monitoring_api.py` 与本迭代文档。未修改 schema、AlertRule 模型、API 实现、配置、依赖、数据库 schema 或迁移。
- `create_alert_rule(..., description: str | None, ...)` 与既有 schema/nullable column 对齐；省略值继续为 None，不转换为空字符串。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`，未改变默认通知、调度或日志流程。
- API 精确 Mypy 为 0；服务文件仍有 15 条本批前历史诊断。根代理独立监控 API fixture 为 49 passed、7 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 447 errors / 111 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T24 版本参数 diff 容器类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/version_diff_service.py` 与本迭代文档。未修改策略版本调用方、模型、API、配置、依赖、数据库 schema 或迁移。
- `diff: dict[str, dict[str, Any]]` 与函数原有返回合同一致，只为四个空分类容器建立精确推断；参数集合、四分类键、值比较和 `{from, to}` payload 行为不变。没有新增 `cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立版本 diff fixture 为 18 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 448 errors / 112 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T23 日志查询参数脱敏类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/middleware/logging.py`、`src/backend/tests/test_logging_middleware.py` 与本迭代文档。未修改中间件执行、日志设施、敏感键集合、配置、依赖、数据库 schema 或迁移。
- `sanitized: dict[str, str | list[str]]` 只表达既有 redaction string/普通单值 string/普通重复值 list 行为；parse_qs 参数、`***REDACTED***` 文本、空 query 的 None 和 `str(dict)` 输出不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立日志 middleware fixture 为 8 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 449 errors / 113 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T22 分析服务复利与均线类型批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/analytics_service.py`、`src/backend/tests/test_analytics_service.py` 与本迭代文档。未修改计算公式、schema、API、配置、依赖、数据库 schema 或迁移。
- `total: float = 1.0` 与 `result: list[float | None]` 仅显式化已有运行时值；复利乘积/六位精度、MA 输出长度/前置 None、空输入和短序列 MA60 语义不变。没有新增 `Any`、`cast`、`type: ignore` 或 `# noqa`。
- 精确 Mypy 为 0；根代理独立分析服务 fixture 为 22 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 450 errors / 114 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T21 增强回测请求服务契约批次边界（2026-09-21）

- 修改仅限 `src/backend/app/api/backtest_enhanced.py`、`src/backend/tests/test_backtest_enhanced.py` 与本迭代文档。未修改 BacktestService、两个 schema、配置、依赖、数据库 schema 或迁移。
- 路由继续接收并验证增强请求，先按 `model_fields_set` 拒绝任意 client runtime_dir；仅成功路径把 `request.model_dump()` 交给基础 `BacktestRequest.model_validate()`。没有新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`，没有放宽服务签名。
- 精确 Mypy 为 0；完整增强回测 fixture 为 52 passed、5 条既有 warning，根代理独立转换/拒绝 fixture 为 2 passed、1 条既有 warning，Ruff/format、tracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 452 errors / 115 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T20 动态策略服务 shim 静态接口批次边界（2026-09-21）

- 修改仅限新增 `src/backend/app/services/strategy_service.pyi`、新增 `src/backend/tests/test_strategy_service_runtime_shim.py` 与本迭代文档。未修改 legacy shim、canonical core、调用方、配置、依赖、数据库 schema 或迁移。
- sibling stub 从 canonical core 显式 re-export 全部八个 `__all__` 名称；runtime fixture 断言 module identity、`__all__` 顺序和每个 export identity。没有新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、`__getattr__` 或 wildcard import。
- stub/core 精确 Mypy 为 0，shim 加既有策略扫描 fixture 为 9 passed、1 条既有 warning，Ruff/format、tracked/untracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 453 errors / 116 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T19 参数优化 FAILED 回测结果批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/param_optimization_service.py`、`src/backend/tests/test_optimization_api.py` 与本迭代文档。未修改 BacktestService、优化 API/schema、任务持久化、配置、依赖、数据库 schema 或迁移。
- 初始/轮询 FAILED 都通过同一 async helper 形成消息：结果存在且 error_message 为非空 string 时保留原消息，否则返回稳定 fallback。COMPLETED、CANCELLED、PENDING/RUNNING 和 timeout 语义不变；没有新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- 目标 `[union-attr]` 消失，完整优化 API fixture 为 48 passed、1 条既有 warning，Ruff/format、tracked diff、抑制扫描通过。全量 `mypy app` 为 473 errors / 120 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T18 比较创建可空回测结果批次边界（2026-09-21）

- 修改仅限 `src/backend/app/services/comparison_service.py`、`src/backend/tests/test_comparison_service.py` 与本迭代文档。未修改 BacktestService、Comparison 模型/API/schema、指标算法、配置、依赖、数据库 schema 或迁移。
- 创建循环在每个输入位置只读取一次回测结果，`None` 继续抛既有 `ValueError`，非空结果在同一窄化作用域构造既有 payload；不去重、不排序，重复 task ID 保持原有逐项读取和最终 dict 覆盖语义。没有新增 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- 原 12 条目标 `[union-attr]` 消失，余下 18 条 comparison-service 历史错误未扩张修复；本地 fixture 为 30 passed、1 条既有 warning，Ruff/format、tracked diff、抑制扫描通过。全量 `mypy app` 为 474 errors / 120 files（625 checked、退出码 1），标准化差分无新增诊断，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T17 动态回测服务 shim 静态接口批次边界（2026-09-20）

- 修改仅限新增 `src/backend/app/services/backtest_service.pyi`、新增 `src/backend/tests/test_backtest_service_runtime_shim.py` 与本迭代文档。未修改 runtime shim、canonical BacktestService、调用方、Mypy/Ruff 配置、依赖、数据库 schema 或迁移。
- sibling stub 只显式 re-export canonical `BacktestService`；运行时 identity fixture 证明 legacy import 与 canonical service 模块及 class 相同。没有新增 `Any`、`cast(Any)`、`type: ignore`、`# noqa`、`__getattr__` 或 wildcard import。
- stub 精确 Mypy 为 0；runtime identity 与既有 backtest-service fixture 为 46 passed、1 条既有 warning，Ruff/format、tracked/untracked whitespace 及 diff 抑制检查通过。全量 `mypy app` 为 486 errors / 120 files（625 checked、退出码 1）：11 条目标误报消失，但暴露 14 条真实调用方错误，因此 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T16 告警规则配置与类型失败关闭批次边界（2026-09-20）

- 修改仅限 `src/backend/app/services/alert_evaluation.py`、新增 `src/backend/tests/test_alert_evaluation_type_boundaries.py` 与本迭代文档。没有修改 `AlertRule` 模型、MonitoringService、API、数据库 schema、迁移、配置、依赖或下游指标服务。
- 评估入口的 Protocol 只提供 trigger type/config 和 alert type 的 scalar 视图；JSON 配置先经 Mapping 验证并复制字符串键。非 Mapping 不调用 metric getter；cross 或 current_value 的 `None`、未知 alert type 都在对应服务调用前受控返回 `False` / `None`。
- `alert_evaluation.py` 精确 Mypy 从 6 errors 到 0；Ruff check/format、tracked/untracked whitespace check 与新增 diff 抑制扫描通过。新增 boundary、既有 alert-evaluation、exceptions/alerts fixture 为 96 passed、1 条既有 warning。全量 `mypy app` 为 483 errors / 121 files（625 checked、退出码 1），所以 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络、行情或交易系统。

## T15 认证服务 ORM 标量与 logout token ID 批次边界（2026-09-20）

- 修改仅限 `src/backend/app/services/auth_service.py`、新增 `src/backend/tests/test_auth_service_type_boundaries.py` 与本迭代文档。没有迁移 `User` / `RefreshToken` 模型，没有修改 SQL、事务、JWT 结构、路由、配置、依赖、迁移或 schema。
- 两个局部 Protocol 只描述仓储/SQLAlchemy 已返回实例所需的 scalar 字段，`cast` 不跨越输入或未加载对象边界；原 ORM instance 仍完成密码哈希、撤销标记和 flush。logout 对缺失、空、`None`、数值或 list `jti` 在调用撤销仓储前返回 `False`，有效非空字符串保持原调用路径。
- `auth_service.py` 精确 Mypy 从 9 errors 到 0；Ruff check/format、tracked/untracked whitespace check 与新增 diff 抑制扫描通过。新增 boundary、auth-service、refresh-token、JWT fixture 为 24 passed、1 条既有 warning；auth API 回归为 15 passed、7 条既有 warning。全量 `mypy app` 为 489 errors / 122 files（625 checked、退出码 1），所以 QD-200-01 继续 FAIL / NO-GO；未连接真实数据库、网络或交易系统。

## T1 后端类型债务批次边界（2026-09-20）

- 修改范围为 `process_supervisor.py`、`market_data/multi_record_contracts.py`、`ctp_tunnel.py`、`instance_store.py`、`stock_analysis/pipeline.py`、`research/model_budget.py`、`research/http_holdout_executor.py`、`research/http_discovery_sandbox.py`、`research/openai_compatible_provider.py`、`research/holdout_worker_process.py`、`research_deployments/holdout.py`、`research_deployments/discovery.py`，以及直接运行时依赖声明 `src/backend/pyproject.toml`。未修改 Mypy/Ruff 配置；未新增测试豁免、`Any` cast 或 `type: ignore`。
- 为保留 Python `>=3.10`，三个网络执行器以同步 `with anyio.fail_after(...)` 统一超时控制，并新增直接依赖 `anyio>=3.7.1,<5.0`；超时捕获和错误码语义保持不变。
- 目标 12 文件精确 Mypy 为 0 errors，Ruff lint/format check 通过；process/instance/multi-record/gateway、HTTP/provider/model_budget、holdout/deployment/stock-analysis 三组现有测试分别为 113、88、55 passed。完整 `mypy app` 仍有 1072 errors / 168 files，QD-200-01 继续开放。

## T2 动态 API shim 静态接口批次边界（2026-09-20）

- 仅新增 `src/backend/app/api/deps.pyi` 与本迭代文档。stub 显式转发 `_dependencies.py` 的安全对象、token protocol、认证/权限 helpers 与常量，以及 `_extract_websocket_token`、`decode_access_token`；未使用 `Any`、`__getattr__`、ignore 或 wildcard import。
- `src/backend/app/api/deps.py` 和 `_dependencies.py` 未修改。已有运行时 shim 继续用 `sys.modules` 指向 `_dependencies`，且 `deps is _dependencies` 的身份测试通过。
- 以 `deps.pyi` 为 Mypy 静态入口并覆盖 37 个直接导入它的 API 模块和 `api/data/deps.py`，没有 `app.api.deps` 缺属性错误；范围内仍有 55 个其他真实类型错误 / 15 个文件。全量扫描从 T1 后 1072 / 168 降至 1027 / 145，但 QD-200-01 仍开放。

## T3 数据抓取 MySQL 核心类型债务批次边界（2026-09-20）

- 修改仅限 `src/backend/app/data_fetch/core/database.py`、`src/backend/app/data_fetch/core/mysql_base.py`、`src/backend/tests/test_data_fetch_common_utils.py` 与本迭代文档；未触及外部数据脚本、依赖/静态检查配置或全局工具配置。
- `Database` 的连接和游标字段保持 Optional，以保留现有采集脚本基于 `connection is None` 的状态判断；其静态接口改由窄 Protocol 描述。`MysqlBase.connect_db` 只在 connector 返回真实连接、连接状态有效并取得游标后设置字段；核心操作经显式非空 helper 获取连接/游标。mysql-connector pool connection 用委托适配器保留连接池 close 语义，并对 cursor 做 `MySQLCursorAbstract` 运行时类型检查；没有使用盲目 cast。
- `save_data` 与抽象基类准确声明 `int | Literal[False]`，保留成功实际写入行数和空/不可写返回 `False` 的既有运行时行为。查询 `fetchone()` 的 `None`/空行、`description` 的 `None`/空列表均被安全处理；未改 SQL、自动补列、事务提交/回滚顺序或既有异常捕获边界。
- 两个目标源文件 Mypy 从 49 errors 降为 0；目标 3 文件 Ruff check 与 format check 通过；`tests/test_data_fetch_common_utils.py` 11 passed、0 failed，包含仅使用 fake connector/cursor 的边界用例。未连接真实 MySQL，真实服务器/网络事务行为未验证。
- 本批次全量 `mypy app` 扫描 625 个源文件，结果为 984 errors / 143 files（退出码 1）；较 T2 的 1027 / 145 观测净减 43 个错误、2 个报错文件。其后续 consumer 对齐由单独的 T4 限定批次处理；QD-200-01 保持开放。

## T4 AkShare data-fetch consumer 类型债务批次边界（2026-09-20）

- 修改仅限三个指定 consumer/provider/proxy 源文件、两个现有直接测试、新增 `test_akshare_provider_storage.py` 与本迭代文档；未编辑 `app/services/akshare/script.py`、T3 核心文件、依赖版本或静态检查配置。
- 使用核心窄 Protocol 的非空连接/游标 helper；legacy PyMySQL provider 使用明确的连接选项 TypedDict、游标/连接 Protocol 与运行时结构校验，保护空 `fetchone()` / `fetchall()` 并保留连接关闭/事务路径。`save_data` 成功仍返回实际行数，空/不可写输入返回 `False`。代理 Session 使用显式 typed 请求参数。
- 三文件精确 Mypy 从 55 errors 收敛到 0；Ruff check 与 format check 对 6 个改动源码/测试文件通过；指定 fake-only tests 23 passed、0 failed、1 条既有 deprecation warning。未连接真实 MySQL，未调用 AkShare，未发出网络请求。
- T4 后唯一一次全量 `mypy app` 扫描 625 个源文件，结果为 929 errors / 140 files（退出码 1）；相较 T3 观测值 984/143，净减少 55 errors / 3 个报错文件。QD-200-01 继续 FAIL / NO-GO；局部结果不得替代全量门禁。

## T5 股票分析 ORM 实例字段类型批次边界（2026-09-20）

- T5 主范围仅为 `src/backend/app/models/stock_analysis.py`、`app/models/stock_signal.py`、`app/services/stock_analysis/tasks.py`、直接相关 stock-analysis/stock-signal 测试和本迭代文档。父代理批准的最小扩展仅涉及 `app/models/knowledge_base.py` 的 `ChatMessage.metadata_json` 映射注解；其他 knowledge-base 字段/调用方、迁移、DB 核心和配置均未改。
- ORM 字段使用精确 `Mapped[...]`/`mapped_column(...)`；存在嵌套 JSON 的 config/freshness/feature/policy snapshots 使用递归 `JSONMapping`，其余 universe/error/reasons 保持符合 producer 的窄类型。任务服务仍使用显式 ORM 实例属性赋值。五个股票分析表的 SQLAlchemy metadata signature SHA-256 修改前后相同；ChatMessage 属性仍指向数据库列 `metadata`，JSON，nullable=True。未改业务协议、表/列语义或迁移。
- 初始 3 文件精确 Mypy 为 58 errors，最终四文件为 0；目标 Ruff check/format 通过；直接 in-memory SQLite/fake 测试为 26 passed、1 条既有 deprecation warning。没有连接真实数据库、运行迁移、调用外部 AI 或网络。
- T5 后唯一一次全量 `mypy app` 扫描 625 个源文件，结果 849 errors / 136 files（退出码 1）；较 T4 后观测值 929/140 减少 80 errors、4 个报错文件。全量静态门禁仍 FAIL / NO-GO，且不据净减少量推断其他错误原因；QD-200-01 继续开放。

## T6 仿真交易 ORM 与服务快照类型批次边界（2026-09-20）

- 修改仅限 `src/backend/app/models/paper_trading.py`、`app/services/paper_trading_service.py` 与本迭代文档；未修改迁移、API、配置、依赖、Mypy/Ruff 设置或范围外模型。模型所有 67 个 legacy `Column`/`relationship` 调用在归一化 AST 比较中与 HEAD 同参数；四张 `paper_trading_*` 表当前 metadata 的列、SQL 类型、nullable、PK/FK 与索引保持预期。
- 服务层以不可变 `PositionSnapshot` 和可选快照的 `PositionEvent` 约束权益/通知计算，数值转换和日期处理有显式边界；测试 Mock 的动态缺失日期被规范化为 `None`，真实 `datetime`/`None` 保持。没有用 `Any`、`cast(Any)`、ignore、动态 `setattr` 或静态配置豁免规避错误。
- 两文件精确 Mypy 从 60 errors / 1 file 到 0；Ruff check/format 通过，服务/API 定向 pytest 为 142 passed、1 条既有 deprecation warning。未连接真实交易、外部数据库或网络。
- T6 后全量 `mypy app` 为 789 errors / 135 files（625 checked、退出码 1）；相对 T5 849/136 净少 60 errors / 1 file，但全量门禁仍 FAIL / NO-GO，QD-200-01 继续开放。

## T7 市场数据平台 ORM 类型批次边界（2026-09-20）

- 修改仅限 `src/backend/app/models/market_data_platform.py` 与本迭代文档；未修改 Store、迁移、服务/API、配置、依赖或测试。220 个 legacy `Column` 和 25 个 `relationship` 调用分别经 HEAD/工作区 AST 参数比较，均无 missing/extra/changed；21 张 `md_*` 表的 schema 摘要 hash 前后均为 `9b5a93f18df29c7b2b364c09691f36a33c442fdb8358a02058e145e7d55761b5`。
- 所有 JSON 实例字段使用递归 `MarketDataJSONMapping`，跨模型关系以 `TYPE_CHECKING` 前向引用保持静态精确性和运行时字符串关系解析；SQLAlchemy mapper 实际配置为 21 tables、220 columns、25 relationships。未新增 `Any`、`cast(Any)`、ignore、`# noqa`、迁移或规则豁免。
- 模型精确 Mypy 从 2 errors 到 0；Ruff check/format 与 diff check 通过，`test_store.py` 为 47 passed、1 条既有 deprecation warning。Store 精确 Mypy 从 43 errors 到 9，剩余均为可空性、容器协变/迭代或数据流错误，不由 `Column[...]` 误推断产生，未越界修复。
- T7 后全量 `mypy app` 为 662 errors / 129 files（625 checked、退出码 1）；相对 T6 789/135 减少 127 errors / 6 files，但全量门禁仍 FAIL / NO-GO，QD-200-01 继续开放。

## T8 工作空间 ORM 与递归 JSON 类型批次边界（2026-09-20）

- 修改仅限 `src/backend/app/models/workspace.py` 与本迭代文档。39 个列与 3 个 relationship 的 HEAD/工作区 AST 参数无差异；mapper 配置为 2 tables / 39 columns / 3 relationships。没有新增 `Any`、`cast(Any)`、ignore、`# noqa`、迁移、服务/API、依赖或规则豁免。
- 模型精确 Mypy 为 0；Ruff/format/diff check 通过；相关服务/API 测试 159 passed、1 条既有 deprecation warning。直接服务的测量从 60 errors 降至 18。
- T8 后完整 `mypy app` 为 625 errors / 131 files（625 checked、退出码 1）。相较 T7 少 37 条错误、报错文件多 2；严格递归 JSON 使三个直接消费者的真实错误可见，一个 lifecycle 文件同时消失，因此不把净差值视为单一根因证明。QD-200-01 继续开放，直接消费者由 T9 处理。

## T9 工作空间 JSON 消费者批次边界（2026-09-20）

- 修改仅限 `src/backend/app/services/stock_analysis/tasks.py`、`app/services/workspace/optimization.py`、`app/services/workspace/reports.py`、新增 `tests/test_workspace_json_consumers.py`、现有保存报告兼容测试与本迭代文档。合法 mapping 做顶层拷贝；保存路径保留合法旧记录并过滤非法项，报告层只消费字符串日期和有限数值。模型、迁移、API、配置、依赖和 Mypy/Ruff 设置均未改；没有新增 `Any`、`cast(Any)`、ignore 或 `# noqa`。
- 三目标文件精确 Mypy 从 10 errors 到 0；目标 Ruff check/format、diff check 与抑制扫描通过。定向 fake/SQLite fixture 5 passed、1 条既有 warning，覆盖合法聚合、畸形 JSON 安全退化和保存去重。
- T9 后完整 `mypy app` 为 615 errors / 128 files（625 checked、退出码 1），相对 T8 减少 10 errors / 3 files；三个 T9 消费者无剩余错误。完整静态门禁仍 FAIL / NO-GO，QD-200-01 继续开放。

## T10 市场数据查询回执和 cursor 类型边界批次（2026-09-20）

- 修改仅限 `src/backend/app/services/market_data/query_service.py`、`src/backend/tests/market_data_platform/test_query_service.py` 与本迭代文档。没有修改 Store、模型、迁移、API、配置、依赖或 Mypy/Ruff 设置；新增 diff 没有 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- `_Store` Protocol 现在如实表示 `PersistedProviderFetch | DeferredProviderFetch`。deferred receipt 在构造 response fetch、更新 knowledge cutoff / visibility anchor 或 post-persist local reread 前抛出 `PROVIDER_RECEIPT_NOT_VISIBLE`；异常仍经过 fetch lease 的 `finally` release。cursor 先收窄 object / digest / sequence 类型，故有效 HMAC 也不能绕过 `CURSOR_INVALID` 的形状与标量校验。
- 精确 Mypy 从 34 errors 到 0；目标 Ruff check/format、tracked diff check、diff 抑制扫描通过。完整 `test_query_service.py` 为 69 passed、1 条既有 deprecation warning，覆盖 deferred 无 reread/重锚、同一 lease release 和 8 类 signed malformed cursor 的 pre-read rejection。未连接真实数据库、网络、数据供应商或交易系统。
- T10 后全量 `mypy app` 为 581 errors / 127 files（625 checked、退出码 1），相对 T9 减少 34 errors / 1 file；QD-200-01 保持 FAIL / NO-GO。

## T11 Scanner plan ORM 实例字段批次（2026-09-20）

- 修改仅限 `src/backend/app/models/scanner_plan.py` 与本迭代文档；未修改 Service、API、数据库兼容逻辑、迁移、依赖或 Mypy/Ruff 设置，新增 diff 没有 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- 两个 ORM 模型的 32 个列和两个 relationship 改为 typed SQLAlchemy 2 映射；每个调用保留原 Column/relationship 参数。递归 `JSONValue` 描述 list、mapping 与 scalar JSON，不改变既有 payload 序列化或动态结果表 SQL。
- 模型/服务精确 Mypy 从 25 errors 到 0；目标 Ruff check/format、tracked diff check、diff 抑制扫描通过。运行时 mapper 为 15/17 columns、4/5 indexes、2 relationships；scanner-plan API fixture 为 2 passed、4 deselected、1 条既有 deprecation warning。未连接真实数据库、网络或交易系统。
- T11 后全量 `mypy app` 为 556 errors / 126 files（625 checked、退出码 1），相对 T10 减少 25 errors / 1 file；QD-200-01 保持 FAIL / NO-GO。

## T12 仓位估值数值回退类型批次（2026-09-20）

- 修改仅限 `src/backend/app/services/position_valuation.py`、新增 `src/backend/tests/test_position_valuation.py` 与本迭代文档；未修改估值公式、服务/API、配置、依赖或 Mypy/Ruff 设置，新增 diff 没有 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- `safe_float` 以 overload 区分 float 与 `None` fallback；dict 递归以显式 fallback 分支调用同一运行时转换逻辑，list/tuple 仍只聚合有效数值。该改动消除静态 false positive，不改变费率、保证金、佣金、价格、notional 或 PnL 结果。
- 精确 Mypy 从 20 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace check、diff 抑制扫描通过。3 个新增 helper 测试及 21 个 workspace 估值场景通过，各有 1 条既有 deprecation warning；未连接真实数据库、网络、账户或交易系统。
- T12 后全量 `mypy app` 为 536 errors / 125 files（625 checked、退出码 1），相对 T11 减少 20 errors / 1 file；QD-200-01 保持 FAIL / NO-GO。

## T13 市场标的 snapshot 与指标类型批次（2026-09-20）

- 修改仅限 `src/backend/app/services/market_instrument.py`、新增 `src/backend/tests/test_market_instrument_type_boundaries.py` 与本迭代文档；未修改 online/warehouse 路由、服务/API、数据源、配置、依赖或 Mypy/Ruff 设置，新增 diff 没有 `Any`、`cast(Any)`、`type: ignore` 或 `# noqa`。
- 五个仓库 payload 的名称只接受非空 string，数字、空字符串或缺失值使用既有 symbol/code fallback；`_first_present` 以只读 Mapping 中的精确字符串键读取 Pandas 可哈希键 row；指标仅累积有效 float，仍忽略缺失 close，且在没有 close 时计算有效 volume 平均。
- 精确 Mypy 从 20 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace check、diff 抑制扫描通过。5 个新增 fake/Pandas 回归与 15 个既有 API fixture 通过，合计 20 passed、1 条既有 deprecation warning；未连接真实数据库、网络、供应商或交易系统。
- T13 后全量 `mypy app` 为 516 errors / 124 files（625 checked、退出码 1），相对 T12 减少 20 errors / 1 file；QD-200-01 保持 FAIL / NO-GO。
