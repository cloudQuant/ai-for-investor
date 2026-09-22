# 迭代 200：设计

> 历史说明：本设计中的全项目 1120 错误基线是 T1 前快照。T64 的 Mypy 1.20.2 复验为 0 errors / 625 source files，是当时快照；当前 T67/T68 以同一固定版本在 fresh-cache 复验为 0 errors / 630 source files，ratchet 为 0→0。T1–T61 的失败结果不代表当前门禁状态，也不代表 CI workflow 已运行。

## 修复方案

### 前端安装图

保留 Vitest 1.6.0 的依赖线，将 @vitest/coverage-v8 从 5.x 降至兼容的 1.6.x，并根据 package.json 重新生成 package-lock。验证顺序为锁文件更新、清洁安装、lint、类型检查和 Vitest fixture。

### 后端格式与类型

- Ruff 只处理审计发现的三个格式文件。
- ThsRateLimiter 的可注入时钟明确为无参返回 float 的 Callable，默认实现保持 time.monotonic。
- 六个空导出列表增加 list[str] 注解。
- _plan_completeness 接受公开契约允许的 Iterable，入口复用 _normalize_expected_record_key_sha256s；后续集合差集和结果对象继续使用归一化后的 frozenset。

## 失败关闭与兼容性

期望 manifest 归一化沿用已有实现，因此 None 仍代表未声明，重复 digest、非法 digest、非 iterable 输入及超限输入仍被拒绝。外部 selector 类型及其 tuple/generator 使用方式保持不变。

## 验证边界

局部 Mypy 和 fixture 仅为目标模块提供证据。全项目 1120 个错误基线不会通过关闭检查规则来规避。所有本轮测试都在本地运行，不连接生产数据库或外部供应商。

## CQ-200-07：Markdown 测试的 DOM 环境

全局 Vitest 环境继续为 happy-dom。DOMPurify 3.4.15 在该测试替身上对 Node.prototype.nodeName 的处理会移除本应允许的标签，Node 24.2.0 下已在四个 Markdown 测试文件复现。因此仅在这些文件上使用 Vitest 官方 file-level jsdom 指令，并把 jsdom ^27.0.0 列为直接开发依赖。

此设计让测试使用符合 DOMPurify 遍历预期的 Node 语义，不接触生产净化代码、DOMPurify/marked 版本或其他测试的环境，也不跳过安全相关断言。

最初 Node 24.2.0 复验时，前三个指定文件的 34 个测试通过；StrategyDetailDialog 测试在 mount 之前加载 Monaco Editor，jsdom 未实现 `document.queryCommandSupported`，导致 suite import 失败。该失败由 CQ-200-08 通过测试模块 mock 定向隔离，不向共享环境添加 polyfill，也不改变 Monaco 或生产组件。

## CQ-200-08：在 SFC 导入前隔离 Monaco

mount-level `global.stubs.MonacoEditor` 只有在组件 mount 时才替换子组件，不能阻止 Vitest 在测试执行前加载 StrategyDetailDialog.vue 的静态依赖。jsdom 下 Monaco Editor 模块初始化访问未实现的 `document.queryCommandSupported`，因此测试在 mount 前就失败。

在测试模块中使用 `vi.mock('@/components/common/MonacoEditor.vue', ...)`。Vitest 会提升该 mock，使它在 SFC 及其依赖导入前生效；组件仍保留通用 Element stubs。StrategyDetailDialog 测试继续在 file-level jsdom 中执行，因为它同时验证 DOMPurify Markdown 输出。此方案只替换测试中非被测的 MonacoEditor 模块，不向 shared setup 添加 polyfill，不改生产 Monaco/StrategyDetailDialog/Markdown 清洗代码，也不影响其他测试的 happy-dom 环境。

Node 24.2.0 本地复验：StrategyDetailDialog 1/1、四个 Markdown 相关文件 35/35、全量 Vitest 154 files / 1687 tests 均通过。完整记录及残留门禁债务见 ACCEPTANCE.md。

## CQ-200-12：仿真交易实例字段与不可变快照

`paper_trading.py` 将每个表字段从 legacy `Column(...)` 改为同参数的 `Mapped[...] = mapped_column(...)`，关系改为带前向引用的 `Mapped[...] = relationship(...)`。这样使服务读取的属性被标注为真实标量/模型实例，而非 SQL expression。四张既有表的 schema 不是迁移目标：在改动前后对所有 67 个字段/关系调用做 AST 参数结构对比，并在当前 SQLAlchemy metadata 中核验列面。

服务层不把 ORM `Position` 直接变成无类型字典。它用不可变 `PositionSnapshot` 描述账号权益计算与通知所需的标量视图，用 `PositionEvent` 描述现金变化、已实现盈亏与可选快照；与真实持仓共用窄联合类型。数值转换只接受可转换的运行时数值，日期字段只接受 `datetime | None`。为保留现有 Mock 的兼容性，动态生成的非 `datetime` 缺失日期属性视为未提供；真实 ORM 的 `datetime`/`None` 保持原值。该规范化只发生在快照边界，不改变订单、保证金、手续费或仓位计算。

## CQ-200-13：市场数据平台的完整 ORM 映射面

市场数据平台的类型错误在多处 service 中出现，但共同根因是其模型仍把所有实例属性暴露为 `Column[...]`。修复在模型边界一次性完成：每个 legacy `Column(...)` 改为同参数的 `Mapped[T] = mapped_column(...)`，每个 `relationship(...)` 改为 `Mapped[T | None]` 或 `Mapped[list[T]]`，并保留关系调用参数。外部 `DgProvider`、`DgDataset`、`AssetInstrument` 只在 `TYPE_CHECKING` 导入，运行时仍由关系字符串解析，避免引入循环导入。

所有 JSON 列使用递归 `MarketDataJSONMapping`，而不是无界 `Any`。验证分两层：先用 AST 归一化比较完整列/关系调用参数，再让 SQLAlchemy 配置 mapper 并统计真实 metadata；这覆盖迁移本身不能证明的 relationship 解析风险。`store.py` 仅作为下游测量对象：Column 传播消除后仍保留的 9 条可空性、容器协变和数据流错误属于另一个服务批次，不能混入模型迁移。

## CQ-200-14：工作空间模型与递归 JSON 边界

`Workspace` 和 `StrategyUnit` 的表定义采用与原有参数一一对应的 `Mapped[...] = mapped_column(...)` 和带前向引用的 `relationship(...)`。JSON 列不使用 `dict[str, Any]`：以递归 `WorkspaceJSONScalar`、`WorkspaceJSONValue`、`WorkspaceJSONMapping` 表达合法 JSON，既让 ORM 实例是实际 Python 值，也让调用方必须在 mapping/列表/标量之间做区分。

验证同时比较 HEAD 与工作区的 39 个列调用、3 个 relationship 调用参数，并执行 SQLAlchemy mapper 配置；模型迁移不改迁移文件或数据库 schema。T8 对四个直接服务的测量从 60 条错误降到 18 条，但严格 JSON 类型也让三个此前未报错的消费文件显形，因此完整 Mypy 仅可记录为 625 errors / 131 files，仍非全仓通过。

## CQ-200-15：JSON 消费者的受控降级

三个直接消费者各在读写边界使用相同语义的递归 TypeGuard：只接受字符串键、递归 JSON 值的 mapping，并在写入前做顶层副本。报告保存丢弃不合法的旧条目而保留合法条目；优化配置只合并已验证 mapping；报告层把日期收窄为 str、指标收窄为有限 int/float（明确排除 bool、NaN 和 Infinity）。因此合法历史 JSON 输出不变，畸形 JSON 不再进入算术、排序或字典访问。

验证用 fake session/workspace 覆盖两类路径：畸形 mapping/数值的安全退化，以及正常数据下的日期、simple 年化、按 initial_cash 的 custom 权重、合计交易数和 best/worst 选择。模型递归类型不被放宽，且没有新增静态检查豁免。

## CQ-200-16：查询回执可见性与 cursor JSON 收窄

查询层的 `_Store` Protocol 必须反映真实 Store：持久化调用可返回已可见 `PersistedProviderFetch`，也可返回等待受控发布的 `DeferredProviderFetch`。前者才有可用于页面 PIT 的 `received_at` 和可见性序列。T10 在回执写入后、构造 fetch / 更新 fresh revision / knowledge cutoff 之前执行联合类型分支：deferred 回执立即抛出 `PROVIDER_RECEIPT_NOT_VISIBLE`。该分支位于既有 lease `try/finally` 内，因此不会把 staged 事实装入响应，且会在异常离开时释放精确的 lease handle。

局部状态读取不再把 `dict[str, object]` 展开为 Store 的具名参数。允许来源列表缺失时显式调用 legacy 兼容签名；存在 allow-list 时显式调用带 `allowed_source_registry_ids` 的生产签名。这样保留覆盖/响应两次 observation read、snapshot 绕过 calendar 与普通 window calendar read 的原有顺序，同时将调用端的可选参数类型保持精确。

cursor 的 HMAC 只证明字节未被未知密钥篡改，不替代 JSON 形状校验。解码先把 JSON narrowing 为字符串键的 object mapping，再验证完整字段集；digest 均以 `_require_sha256` 收窄，anchor 则明确拒绝 bool、负值与非 `int` 的 sequence。所有 `TypeError` / `ValueError` 继续归一化为 `CURSOR_INVALID`，发生在 resolver、local Store 或 provider 之前。测试刻意重新签发有效 HMAC 的错误 payload，证明不是仅靠签名失败掩盖字段边界。

## CQ-200-17：Scanner plan 的精确 ORM 映射面

两个 scanner plan 表的静态错误不是服务流程的真实类型歧义，而是 legacy `Column(...)` 声明把 ORM 实例属性暴露为 SQL expression。T11 只在模型边界将 15 个 `scanner_plans` 列、17 个 `scanner_plan_runs` 列和两个 relationship 改为同参数的 `Mapped[...] = mapped_column(...)` / typed `relationship(...)`；Service、API、动态结果表 SQL、迁移和数据库兼容逻辑不变。

JSON 列由递归 `JSONValue` 表达 JSON scalar、list 和 string-key mapping，替代模型层无界 `Any`。`indicator_rules` 与 `matches` 保持 list 形状，`metrics` 保持 string-key mapping；该注解仅描述 ORM 返回的 Python JSON 值，不新增输入过滤或改变已存在的 JSON 序列化。关系继续使用运行时字符串 target，前向注解由 future annotations 延迟解析；`runs` 是 list、`plan` 是单值，保持 `back_populates`、cascade、order_by 和 FK delete 语义。

验证同时检查精确 Mypy、两项 scanner-plan API fixture 和运行时 mapper：表列数量、名字和索引保持 15/17、4/5，关系参数保持原样。该本地 SQLite/fake 证据不替代真实数据库、网络或交易环境验收。

## CQ-200-18：Safe float 的依赖默认值类型

`safe_float` 的运行时语义已经区分两种契约：默认 0.0 或任意 float fallback 总能产生 float；只有显式 `None` fallback 才会让缺失/非法值保留为 `None`。T12 用两个 overload 让静态调用者也能区分这两种结果，实施签名仍保留联合实现类型，因而不改变对现有动态 payload 的接收范围。

递归 dict 分支在 `default is None` 时显式调用 nullable overload，在 float 分支调用 non-null overload；list/tuple 分支仍只累加有效数值，空有效集合仍返回传入 fallback。该分支化只提供类型收窄证明，和原有运行时递归、异常捕获、默认回退完全同义。所有依赖它的费率归一化、entry price、market notional 和 PnL 辅助函数因而能获得实际存在的 float 保证，无需插入伪默认值、cast 或修改计算公式。

验证包括 helper 的 float/None/default/嵌套 JSON 数值行为及 21 个既有仓位估值场景。没有连接真实账户、行情、数据库或交易通道。

## CQ-200-20：新闻情报的可选 session 与 loaded-row 合同

可选 session 是服务的有意公开契约，而不是所有方法都可在无数据库下运行。T14 将 guard 建模为返回 `AsyncSession`，每个持久化路径把它保存为局部变量后再执行数据库操作；这保留 `NewsIntelligenceService()` 的 `analyze()`、默认 RSS helper 和工厂调用方式，也保留缺失 session 时原有的 `RuntimeError("database_session_required")`。

NewsSourceModel 仍是 legacy `Column(...)` 声明，静态工具会将类属性类型投射到已加载实例。服务内的窄 Protocol 只列出本批实际读取或写入的 `id/name/url/tier/status/metadata_json` 标量字段，且只在数据库查询返回的 loaded instance 边界做显式 cast；它不改变 ORM 模型、SQL、序列化或运行时对象。这样可隔离模型迁移债务，避免无界 Any cast。

feed 解析不再把 JSON 直接当 dict：只有 Mapping 才读取 `tickers`，其值若可迭代则延续原有逐项字符串清理；list/scalar 等非 Mapping 元数据降级为空默认 ticker。验证全部使用 fake HTTP client、未持久化 ORM 实例和本地 API fixture。

## CQ-200-21：认证服务的 loaded-instance 与 JWT token ID 合同

认证服务不迁移 `User` 或 `RefreshToken` 模型：二者仍是 legacy `Column(...)` 声明，直接进行全模型 SQLAlchemy 2 映射会扩大到表 schema、关系和所有消费者。T15 仅定义两个窄 `Protocol`，分别列出服务实际读取/写入的 User 标量（ID、用户名、邮箱、密码哈希、启用状态、创建时间）和 RefreshToken 标量（过期时间、撤销状态、撤销时间）。显式 `cast` 仅发生在 `SQLRepository` 或 SQLAlchemy 查询已返回真实 ORM instance 之后，随后仍由同一个真实对象完成密码哈希赋值、撤销标记和 session flush；查询、事务、序列化和表定义均不变。

`decode_refresh_token` 的返回 payload 是外部边界，即使签名和 refresh token type 都有效，`jti` 仍可能缺失或不是字符串。T15 在调用撤销仓储之前要求它是非空 `str`；失败时直接返回 `False`，因此不会把 `None`、数字、空字符串或容器传到仓储。有效非空字符串保持原有 `revoke_refresh_token` 调用路径。回归通过 monkeypatch decoder 与撤销方法验证“无效不调用、有效仍调用”，无需真实数据库。

## CQ-200-22：告警评估配置与类型的失败关闭合同

T16 不迁移 `AlertRule` 模型，因为这会扩张到告警表、关系和 MonitoringService 的全体调用方。评估函数入口用一个窄 Protocol 表示实际读取的 `trigger_type`、`trigger_config` 和 `alert_type` 标量；静态 cast 仅为 legacy ORM descriptor 与已取回实例间的类型视图，不改变 ORM 对象、query 或写入路径。

触发配置是 JSON 边界而非可靠 dict：仅当它是 `Mapping` 时才构造字符串键的本地 dict 并调用既有 threshold/rate/cross helper。list、scalar 或只有非字符串键的 Mapping 都不会调用 metric getter，直接返回不触发。cross 的两个配置数值和 manual `current_value` 在转换为 float 之前先拒绝 `None`，保持原有其他可转换数值路径。alert type 只能转换成 `AlertType` 才能进入账户、仓位或策略的指标查找；未知值返回 `None`，防止兼容 fallback 把不明类型送往下游服务。

## CQ-200-23：动态 module replacement 的静态镜像

`backtest_service.py` 的运行时 shim 直接把自己的 `sys.modules` 条目替换为 canonical service 模块。改写这一行为或在 stub 中复制整个 service 将扩大风险：前者会影响 import 身份，后者会造成静态接口与真实实现漂移。T17 因而只放置 PEP 484 sibling stub，将 `BacktestService` 显式 re-export 为 canonical class；Mypy 读取 stub，而 Python 仍运行原有 shim。

运行时测试同时断言模块对象和 class 对象都是同一身份，防止静态补丁悄然引入替代实现。stub 让 Mypy 看见真实的 `get_result() -> BacktestResult | None` 及 `run_backtest(..., BacktestRequest)` 合同；因此调用方暴露的 14 条错误是后续独立治理对象，而不是加入宽松签名、`Any` 或 `__getattr__` 来隐藏。

## CQ-200-24：一次读取的比较快照

T18 不以 `assert` 或 type cast 把 `None` 视为不可能，而是改变数据流：每个 `backtest_task_ids` 输入位置 await 一次 `get_result()`，立即检查 `is None`，然后在同一窄化作用域构建原有所有 payload 字段。由此既保存了缺失任务的公开 `ValueError`，也防止先验证后第二次读取之间的竞态。

循环不去重、不排序，因而重复 ID 仍按输入位置逐项读取，和原有调用次数/最后 payload 覆盖行为一致。回归测试将 mock 的第二个返回值设为 `None`，并断言成功路径只 await 一次，直接证明实现不会悄然恢复二次读取。

## CQ-200-25：FAILED 状态的单一失败消息路径

T19 将等待器中读取回测结果的逻辑收敛到一个 async message helper。这个 helper 只在 FAILED 状态调用：当结果和 `error_message` 均为有效非空字符串时保留既有用户可见消息；其余情况返回稳定的 `Backtest failed: result unavailable`。因此不存在把 `None` 解引用为属性的路径。

初始 status 已是 FAILED 与轮询中转为 FAILED 都调用同一 helper，修复了原有状态时序差异；COMPLETED、CANCELLED、PENDING/RUNNING 和 timeout 分支未动。测试用 fake service 而非真实任务/数据库验证这两个失败边界。

## CQ-200-26：动态 strategy module replacement 的静态镜像

T20 采用和回测 shim 相同的低风险 PEP 484 sibling stub：Python 继续运行 `sys.modules` 转发，Mypy 读取显式从 canonical `strategy.core` 导入的八个 public names。stub 不复制 service 实现、不会让静态接口与 core 漂移，也不把动态 fallback 或 `Any` 暴露给调用方。

运行时 fixture 先解析 legacy module，再断言它与 canonical core 同一模块，并对 core `__all__` 中八个名称逐一做 identity 断言。这同时保护 monkeypatch 依赖的 `STRATEGIES_DIR` 运行时别名语义；既有策略目录扫描测试继续覆盖该行为。

## CQ-200-27：增强入口到基础服务请求的显式适配

增强 API 保留更严格的输入验证职责，基础 `BacktestService` 保留单一的服务请求合同。T21 不让服务签名接受联合模型，也不以静态 cast 宣称两者可替换：路由先根据增强模型的 `model_fields_set` 拒绝任何客户端显式提交的 `runtime_dir`，再以 `ServiceBacktestRequest.model_validate(request.model_dump())` 创建基础模型。这使基础模型的服务器侧约束也会重新验证，同时不允许客户端绕过先行的字段集安全检查。

测试通过 FastAPI dependency override 注入本地 mock service，而不是 patch 动态 service shim；因此可直接观察 await 参数的运行时类型与字段。拒绝测试同时断言 mock 从未被 await，证明转换和服务调用均在安全拒绝之后；完成事件仍沿用现有 WebSocket payload。

## CQ-200-28：只修正分析函数的局部类型推断

T22 只给已存在的值加入精确类型：年复利累计值从 `1.0` 起始，并被标记为 `float`；均线初始占位列表被标记为 `list[float | None]`。两个变更不引入额外数据转换、空值过滤或默认值，所以月收益乘积、六位小数 round、MA 窗口计算及前置 None 的运行时结果保持不变。

直接回归既验证复利数值，也继续验证 MA 列表长度、前置 None 和短序列 MA60 为空。该批不接触行情、交易、数据库或外部服务。

## CQ-200-29：日志脱敏 helper 的既有异构值形态

T23 仅为 local `sanitized` 字典补充 `dict[str, str | list[str]]` 类型。它准确反映原流程：敏感键始终赋值遮蔽字符串，非敏感键在单值时取唯一字符串、重复时保留 parse_qs 的字符串列表；后续仍以 `str(dict)` 形成日志字段。

测试使用无效占位 token 验证结果不包含原值，同时确认重复普通参数仍以列表形式保留。未改变 request/response、中间件执行、日志设施或外部系统访问。

## CQ-200-30：版本参数 diff 的空容器类型证据

T24 只在 `generate_params_diff()` 的 local `diff` 初始化处声明它是 `dict[str, dict[str, Any]]`。该类型与函数既有公开返回合同完全一致：四个固定分类都映射到参数名与原值/嵌套 from-to mapping；执行时的 key 集合、赋值和比较控制流未变。

既有测试覆盖相同参数、全部新增/删除、修改、空输入和嵌套容器值，所以不需要重写算法或改变调用方。该批不接触版本持久化、数据库、网络、行情或交易系统。

## CQ-200-31：可空监控规则描述的合同对齐

T25 以服务签名反映现有 schema 和 nullable 数据库列：description 可为 `str | None`。这不是把缺失描述规范化为 `""` 的行为修改；API 继续将 Pydantic 已验证的值原样传给服务，AlertRule 也继续持久化/序列化 None。

新增 API fixture 通过 mock service 观察实际 await keyword，并验证成功 response 的 description 为 null。创建流程的通知默认、调度启动和日志均未改变；服务内部其他历史 ORM 类型错误保留为独立债务。

## CQ-200-32：授权 principal 的静态连续性

T26 不修改授权算法，而是让 helper 返回值准确保留授权器的 `MarketDataPrincipal`。同一对象先由 `principal_for_user()` 得到，再送入既有 `require_read_data()`，最后作为 `MarketDataQueryAccess.principal`；对授权失败的异常翻译和数据库角色重读完全不动。

fixture 使用无数据库 fake authorizer 记录调用顺序和对象 identity，证明类型修复没有构造替代 principal 或绕过 read check。未访问行情、网络或真实数据库。

## CQ-200-33：兼容层 reconciliation payload 的对象值容器

T27 不改变 legacy record 到 generic research fact 的有损适配，而是让 `legacy` local dict 的静态类型与已声明的 pairs 合同一致。该容器原本就同时承载字符串字段和 `None` narrative，故 `dict[str, object]` 是原有运行时 shape 的准确上界；generic dict、字段转换、记录顺序和 `reconcile_batch()` 输入没有变化。

既有 compatibility fixture 同时覆盖 legacy facts 的保留及两条记录的 zero-defect reconciliation，因此足以防止此类型注解意外改变 mapping payload。该批不访问真实数据库、网络、行情或交易系统。

## CQ-200-34：主数据版本和计数器的静态精确表达

T28 让严格 manifest schema 的 type-level literal 和 wire-level constant 指向同一个固定字符串：`ManifestVersion = Literal["market-data-master-v1"]`，常量仍为该唯一值，Pydantic 的版本拒绝行为不变。它不以运行时常量拼接类型，也不放宽 manifest 输入。

类别统计仍从每个 prepared identity 的原始 asset_type 更新同一个 Counter；仅将容器键明确为 `str`，从而与 result DTO 的 `dict[str, int]` 输出契约一致。既有 eight-case importer fixture 已覆盖七类资产、严格 version 和排序统计；该批不改变事务、发布或外部系统访问。

## CQ-200-35：缓存单例的显式双实现状态

T29 只为既有 module singleton 和 factory 签名补足 `RedisCache | MemoryCache` 联合类型。初始化分支仍仅在实例为空时读取 `REDIS_URL`，有值时构造 RedisCache、否则构造 MemoryCache；后续调用仍直接复用第一次构造的对象。

测试以默认配置验证内存实例，以 patched RedisCache 构造器验证 Redis 分支，因此不需要连接真实 Redis。TTL、JSON 序列化、缓存实现和调用方没有改动。

## CQ-200-36：日历默认版本的固定类型和值

T30 仅在常量定义处将 `MANIFEST_VERSION` 标注为 `Literal["market-data-calendar-v1"]`。类字段继续直接以同一常量作为默认值，所以 schema 的固定 value、序列化和对其他 version 的拒绝行为保持原样。

现有 calendar importer fixture 覆盖严格 manifest、时间/coverage 守卫和持久化流程；本批没有改日历计算、事务、publication 或外部访问。

## CQ-200-37：引擎 kwargs 容器保留原有双分支形状

T31 只把空 `extra_kwargs` 标注为 `dict[str, object]`，反映它在互斥分支中可承载 `poolclass: NullPool` 或 `pool_pre_ping: bool`。到达 `create_async_engine()` 时仍传递相同单一分支参数，URL 选择、engine 缓存和 sessionmaker 构造没有变化。

完整管理 API fixture 的首次默认字节码缓存运行暴露历史 `co_filename` 指向已不存在临时路径；验证改用新的 `PYTHONPYCACHEPREFIX`，不删除或修改已有缓存。隔离后所有断言完成，且未连接真实 MySQL 或网络。

## CQ-200-38：只读 target 流的最小接口

T32 让 `_assert_isolated_unverified_targets()` 接受 `Iterable`，恰好匹配其只进行一次 for-loop 的实现。`dict.values()`、tuple 或 list 都提供这个能力；helper 内逐目标 source binding 校验、抛出的 fail-closed 错误和调用顺序不变。

隔离 SQLite harness 覆盖 read authorization 到 canonical write permit 的链路，证明这个静态接口收窄不让未验证 source 通过，也不触发任何真实网络或交易路径。

## CQ-200-39：压力场景输入的协变消费边界

T33 把两个仅消费 scenarios 的服务参数改为 `Sequence[dict | StressScenario]`。这允许 API Pydantic 已构造的 `list[StressScenario]` 进入服务，同时保留已有 dict literal 调用；实现继续只迭代并创建新的 normalized scenario list，没有任何原地修改。

service/API fixture 继续覆盖自定义 dict 场景和 API 的 StressScenario 场景，验证指标计算、degraded 结果和 response shape 均不改变。该批不触及数据、网络、交易或数据库。

## CQ-200-40：AI 改稿 metadata 的局部值域

T34 仅将 `_merge_ai_improvement()` 的局部 metadata 容器标注为 `dict[str, object]`。这准确表达已有初始化阶段的 source/provider/model_id 字符串以及可选分支写入的 int total_tokens；键集合、写入条件和 `StrategyImprovement` 构造均保持不变。

既有异步 AI 改稿 fixture 经 fake router 返回 token 计数后，继续断言 source、provider、model_id 和 `total_tokens == 123`。该批不修改公开 metadata 契约、模型响应解析、策略代码/参数改写、回退、数据库、网络、外部模型或交易路径。

## CQ-200-41：bar/indicator fallback 的可空序列隔离

T35 将 no-data.log 分支的指标容器改名为 `bar_indicators` 并标注为 `dict[str, list[float | None]]`。它只覆盖该 fallback 中“指标稍后出现时，以 None 补齐已见日期”的既有序列；TSV 路径仍持有自己的 `dict[str, list[float]]`，因而两条解析路径不再在同一函数作用域发生错误的静态变量合并。

新增 fixture 以首日只有 datetime 的 indicator 记录保留日期优先逻辑，并在第二日提供 fast_ma；这避免 index fallback 把第二日值误配到首日，确认输出仍为 `[None, 1.16]`。该批不改变 JSON/pipe/TSV parser、日期回退、OHLCV、volume、API、数据库、网络或交易路径。

## CQ-200-42：回执 hash 验证后的静态收窄

T36 把 `_valid_sha256(value: object)` 的返回声明为 `TypeGuard[str]`，精确反映已有运行时分支：只有字符串、64 位且为小写十六进制的值才通过。于是 `_validate_receipt_record()` 在原有失败关闭之后，`receipt_hash` 可以安全地进入已有 `secrets.compare_digest()`；比较算法、数据和值均未变化。

新增公共 resolver fixture 在保持字段集的情况下将 durable receipt 的 receipt_hash 改为 null，验证它仍映射为 `DATASET_OBJECT_RECEIPT_INVALID`，而不会调用或暴露任何私有绕过路径。该批不触及对象根、receipt store、文件描述符、权限、JSON schema、网络、数据库或交易路径。

## CQ-200-43：用量 pair 求和前的失败关闭类型证明

T37 把原有 `type(value) is int and value >= 0` 条件提取为 `TypeGuard[int]`，保持它比 `isinstance` 更严格，故 bool 继续被拒绝。每一对 usage 值先命名、校验再相加，替代仅改变静态类型信息的 tuple/sum 形式；pair 顺序、total 对照和 None 失败返回完全不变。

既有 gateway fixture 同时覆盖 12/5 成功结算、bool/负数/缺项/总量不一致失败关闭以及 prompt/completion 形式，因此该批不需要改变测试或配额模型。它不触及 provider、审计、redaction、数据库、网络或交易路径。

## CQ-200-44：journal 写入点的 lease 非空证明

T38 在 `_require_live_binding()` 返回后马上将 `binding.lease_expires_at` 读入局部变量；若异常数据令其为 null，则与上游相同地抛出 `HOLDOUT_EXECUTION_PREPARE_DENIED`，只有非空值才送入 `_as_utc` 和待写入的 journal model。这是重复的失败关闭边界，不改变 live binding 判定或正常路径数据。

既有 journal fixture 已覆盖 prepare 的持久化/幂等和无效 binding 拒绝，所以无需改变状态机测试。该批不修改 evaluator 调度、record 状态、lease 计算、数据库 schema、网络或交易路径。

## CQ-200-45：run record pipeline 的单次读取与字典边界

T39 将 `raw.get("pipeline")` 保存为一次局部读取，再在且仅在该值是字典时将其作为 pipeline 读取 `current_stage`；其他形状使用同样的空字典 fallback。这样静态收窄和运行时决策使用同一个对象，不会因为可变 mapping 或重复读取而让 guard 与使用对象脱节。

该 helper 只决定是否需要 refresh persist，不写入 raw payload，也不构造或修改 run record。`force`、状态、ready 和 `live_candidate` 三个原有条件、短路顺序及结果保持；不触及持久化、paper/live handoff、数据库、网络或交易路径。

## CQ-200-46：网关 spec 数值转换前的非空证明

T40 将 `_positive_spec_number()` 的 `None` 跳过条件从与空字符串合并的成员判断拆为显式守卫，使 `float(value)` 只接收已证明非空的值。空字符串继续跳过；其余运行时值仍由同一 `try/except (TypeError, ValueError)` 处理，所以 malformed mapping、零值和负数不会被提升为正数 spec。

此 helper 仅为已有 contract/margin spec 缺失判定提供布尔值，不改变 spec 来源、键优先级、gateway runtime、账户/订单/行情连接或交易执行。

## CQ-200-47：自定义因子 AST 的一元操作静态分派

T41 让 `_eval_node()` 在已经确认的 `ast.UAdd`/`ast.USub` 两个节点类型之间进行精确分派，而不是经推断不明的 callable 容器执行。每个分支继续先递归求 operand，再应用同一 `operator.pos` 或 `operator.neg`；因此数值结果、Python 算术异常和上层 record 级 `None` 降级路径不变。

`_validate_node()` 的 AST 白名单仍是安全边界，既不接受新的 unary node，也不改变 Name/Constant/BinOp 的限制。新增本地回归只验证已允许的一元正负表达式，不触及 API、因子 registry、外部数据、数据库、网络或交易路径。

## CQ-200-48：legacy live trading manager 的静态镜像

T42 只增加 sibling `.pyi`：从 canonical `app.services.live_trading.manager` 精确 re-export `LiveTradingManager` 与 `get_live_trading_manager`。运行时 `.py` 继续只把 module identity 指向 canonical module，所以 stub 只服务 Mypy，不能改变 singleton 构造、网关加载或任何运行时导入顺序。

身份 fixture 只导入两个模块和这两个对象，断言 legacy module/class/factory 均与 canonical 相同，不调用 factory 或构造 manager。全量差分若使先前被 shim 遮蔽的调用方错误可见，将作为真实剩余债务记录，而不是当作本批失败或以宽泛静态接口隐藏。

## CQ-200-49：实例记录的只读消费与受控写入边界

T43 在 portfolio 和 trading workspace 的“读取实例记录”边界使用 `Mapping[str, object]`：TypedDict 与既有 dict fake 都实现这个只读协议，helper 继续仅以 `get()` 读取 `id`、状态、时间、params 和 runtime/log 目录。这样不会宣称 manager 的持久化实例是通用可变字典，也不要求改变 canonical manager 的 `InstanceData`/`StartResult` 注解。

workspace 启动分支先将已运行实例、正常 `start_instance()` 返回和 already-running 刷新实例共同承接为只读记录；随后继续执行原有 metadata sync、live asset-spec refresh、snapshot 和 run-count 路径。它不新增 manager 调用，因此不扩大 manager 的进程扫描、网关恢复或启动副作用。

`persist_asset_specs()` 是唯一需要可变字典的既有兼容 API；T43 在调用处构造局部浅拷贝。该 API 的 config 写入和本服务随后的 unit metadata sync 仍保持原有顺序，而对临时 record 的 `params` 写入不再被误表示为 manager 实例的持久化操作。

T43 的直接 fixture 以真实 `InstanceData` TypedDict 和 legacy bare dict 同时走 portfolio 的批量实例路径；另一 fixture 令 fake manager 按声明只返回最小 `StartResult`，证明 snapshot 仍从 unit id 回退、保持 running 状态并仅增加一次 run_count。根代理另复验 already-running、runtime contract sync 和 persistence 路径，未构造真实 manager 或连接外部系统。

## CQ-200-50：合约元数据的单次读取与浅拷贝

T44 不改变 metadata 的数据合同，而是在两个已有同步 helper 内把 `params.get("contract_metadata")` 保存为各自的局部读取值。仅当该局部值是普通 `dict` 时，才用 `dict(raw_metadata)` 保留原有浅拷贝语义；非字典、缺失或 null 仍得到空 `current_metadata`。这使 runtime 与静态分析都基于同一次已经验证的对象，不依赖两次动态读取恰好相同。

两条路径的下游 merge 仍分别以 instance 提供的 metadata 和已解析的 asset specs 为 update；对原来的 current metadata 取 alias、合并 core/aux 字段、组合 source、写回 unit 的先后次序都不变。直接本地 fixture 将分别覆盖两条路径，锁定已有兄弟 metadata 未丢失且目标 symbol 的新字段完成合并；无需调用 manager、gateway、持久化或数据库。

T44 根代理复验显示两个局部读取均只经已收窄值构造浅拷贝；两条直接 fixture 保留既有 `IF2609` multiplier/margin、加入 commission 和组合 source，并证明 `RB2610` 兄弟 metadata 未丢失。没有修改 `_safe_dict()`、merge helper 或任何外部 I/O。

## CQ-200-51：position-log tuple 状态表的局部身份

T45 保持两处 `_latest_position_rows()` 的四张状态表和所有 tuple 解构不变，仅让同一函数内不同形状的候选读取拥有不同的局部变量名：按 symbol 的 flat candidate 是三元组，non-flat candidate 是二元组，按 direction 的 non-flat entry 是四元组。这样每次比较仍读取同一张表、同一 tuple slot 和同一 timestamp/index 顺序，只是不再把独立容器的静态形状串联起来。

两端仍各自保留其现有实现，不抽取共享 helper，以避免让 portfolio API 与 workspace snapshot 的不同依赖边界在一次类型修复中耦合。既有本地 fixture 已覆盖 latest-row 选择的四种关键状态，T45 只需复验它们。

T45 根代理复验确认每个改名仍从同一状态表取得同一 tuple slot，并以原 timestamp/index pair 比较。8 项已存在的 latest-row fixture 同时通过，故未为纯局部身份变更添加重复 fixture。

## CQ-200-52：portfolio metadata 的局部快照

T46 与 T44 保持同一最小模式，但只作用于 portfolio 的持久化前 metadata merge：先保存一次 `params.get("contract_metadata")`，仅在局部值是 `dict` 时 shallow-copy。它不会改变 async session、ownership guard、asset spec 的 alias/merge/source 或 `unit.params` 写回；已有本地 SQLite/gateway fake fixture 继续作为端到端持久化覆盖。

T46 根代理复验确认写回的 spec 仍将 stale metadata 与 gateway metadata 组合为同一 source，并保留 multiplier、margin 和 commission；本轮没有触及 session、模型或任何外部连接。

## CQ-200-53：portfolio equity 浮点序列容器

T47 只为两个实例 ID 到 list 的局部容器补上实际运行时形状 `dict[str, list[float]]`。从 strategy curve 建立空序列、每日期 append 的 `_safe_round()`、抽样重建和 response 中的 values/pnl_values 都保持原表达式和顺序；注解不改变任何曲线数值或公开 payload。

根代理审阅确认两个容器在赋值后只接收 `_safe_round()` 返回的浮点数，并在采样阶段保持同一键和同一值序列重建。T47 不扩大类型到 `Any`，也没有改动 portfolio 聚合、drawdown、时间轴或 API schema。

## CQ-200-54：position-log 数值代码回退

T48 保持两处 parser 的原有两阶段语义：文本 alias 先返回；其余值先按既有 `float()` 规则转换，再以 `int()` 识别 CTP/Bybit/trade-action 数字代码；若转换异常，则继续到函数末尾按 signed size 回退。调用各模块既有 `_safe_float(value, float("nan"))` 只把其原本捕获的异常映射为 NaN，随后的 `int()` 继续抛出并被原 `except (TypeError, ValueError)` 捕获，因此不把无效代码误作零。

该变更不会共用两个模块的 helper 或改动别名表、代码映射、flat 清除、latest-row 状态表及输出排序。两端以直接 fixture 锁定小数数值文本与非法值回退，已有 Bybit one-way fixture继续覆盖 `positionIdx=0`。

根代理复验确认 `_safe_float()` 本身仍以相同 `float(value)` 和同一组 `TypeError`/`ValueError` 捕获运行；无效输入取得 NaN 后由已有 `int()` 抛出 `ValueError`，所以仍抵达同一 signed-size fallback。两端的 `"2.0"`、invalid、Bybit one-way 和 hedge dual-side 行为均由本地 fixture 覆盖。

## CQ-200-55：attested paper runtime anchor 失败关闭收窄

T49 将 JSON mapping 的 anchor 读取分成 raw value 与已验证的 dict value：只有 dict 能写入既有 `paper_runtime_anchor`；str、number、list、bool、null 等均归一为 `None`。这是与 verifier 的已有 contract 对齐，因为 verifier 对任何非 Mapping 返回 `False`，调用点随后抛出相同 provenance-invalid 错误。

预检仍发生在 runtime sync、manager capability 和实例创建之前；有效 dict 继续进入同一 pre-sync/post-sync signature re-check 和 anchor refresh。直接 fixture 将以 scalar anchor 断言拒绝错误、无 runtime sync 和无实例创建，确保类型收窄不是安全边界放宽。

根代理复验确认 scalar anchor 在生产 predicate 之外仅由测试固定为 attested，从而精确覆盖 verifier 调用点而不改分类器；真实 verifier 收到 `None` 后返回 false，start path 保持同一错误码并在任何 materialization 前终止。有效 dict 的赋值表达式与原路径相同；本批未连接或验证外部运行时材料化。

## CQ-200-56：候选数值输入协议

T50 不把动态数据直接扩张为 `Any`。它将 `_first_number()` 内一次读取的候选值保存为 `object`，嵌套值也保存为 `object`，然后以 `float()` 已支持的文本、buffer、`SupportsFloat` 与 `SupportsIndex` 协议作为唯一转换入口。该 guard 失败时执行原有 `continue`，所以无效首选 key 仍可让后续 key 提供数值。

嵌套 `amount/value/balance/total` 的选取顺序、string 的 trim/comma cleanup、`float("nan")`/Infinity 的原返回值及 `TypeError`/`ValueError` 的候选回退均保持。直接 fixture 应分别锁定嵌套文本、invalid-to-next-key、Decimal/其他标准数值协议和 NaN，不修改 `_safe_float()` 或任何调用方。

## CQ-200-19：市场标的异构 snapshot 边界

仓库查询得到的 snapshot 是异构字段容器，因此 payload 的展示名称不能依赖 truthiness：数字虽是真值，却不是可展示的名称。T13 用一个只接受非空 `str` 的局部 helper 保留已有字符串名称，并在数字、空字符串或缺失时回退到调用方原有的 symbol/code；它不修改 snapshot 内容、provider 选择或历史行情路径。

Pandas `.to_dict()` 的键为可哈希值而非保证字符串。读取 helper 因而以泛型只读 `Mapping` 遍历并只匹配精确的字符串列名：原有字符串候选键和优先级不变，数值或其他非字符串键不能碰巧被解释成行情列。指标构建在转换每个 close/volume 后立即将非空值写入 `list[float]`，使平均、最大值、最小值与收益率只在有效数上计算；没有 close 时依旧返回空的价格指标、使用已有有效 volume 计算平均。

验证使用本地 fake warehouse、内存 Pandas DataFrame 和 API fixture，不导入真实 AkShare、数据库、网络或交易连接。
