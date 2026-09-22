# 迭代 200：代码质量门禁修复与可复现开发环境

> 状态：本轮本地代码质量门禁已收口：canonical dev lock Mypy 为 0 errors / 630 source files、ratchet 为 0→0，本地非性能后端回归为 7,864 passed / 123 skipped / 24 deselected；Python/npm registry audit、warning-free 前端 lint、manifest bundle 预算和源码尺寸棘轮均通过。七个结构性巨型编排器已明确转入迭代 201。CI workflow、浏览器 e2e/网络节流、真实数据库、行情、供应商、交易和共享 Redis 滚动发布验收仍未运行，不构成发布批准。
> 编制日期：2026-09-20。

> 历史说明：T1–T61 中的全量 Mypy 错误数及 `FAIL / NO-GO` 标签均是各批次当时的快照；T62–T64 的 0/625 同样是历史快照，不代表当前状态。当前本地门禁状态见 T69。

## 目标

修复本轮代码质量审计中可明确定位、影响门禁或类型契约的问题：前端依赖锁冲突、三个 Python 文件格式不一致、THS 限流器时钟类型错误、六个服务包的 __all__ 缺少注解、多记录完整性 helper 的 expected manifest 类型不匹配、happy-dom 与 DOMPurify 的 Node.prototype.nodeName 语义不兼容、jsdom 测试中非被测 Monaco 模块的导入隔离、工作空间 ORM/递归 JSON 契约及其直接消费者的类型安全、市场数据查询的延迟回执可见性和签名 cursor JSON 边界、scanner plan ORM 实例字段类型，以及仓位估值数值回退类型契约。

## 审计基线

- 前端 npm ci --ignore-scripts 在安装前失败：@vitest/coverage-v8 5.0.0 要求 Vitest 5.0.0，而当前依赖范围和锁文件解析的 Vitest 为 1.6.0。
- 后端 Ruff lint 检查通过；格式检查命中三个文件，见 CQ-200-02。
- 全量 mypy app 扫描了 625 个源文件，发现 188 个文件中的 1120 个错误。此数字是本次修改前的审计基线，不代表本迭代已解决全项目类型债务。

## 范围和边界

迭代处理 REQUIREMENTS.md 中 CQ-200-01 至 CQ-200-05、CQ-200-07 至 CQ-200-23 的具体缺陷，并记录 CQ-200-06 全量 Mypy 状态。CQ-200-07 仅为四个 Markdown 测试文件切换到 jsdom；CQ-200-08 使用模块级 mock 在 SFC 加载前隔离非被测 MonacoEditor。CQ-200-14/15 仅收紧工作空间 ORM 递归 JSON 类型及其直接消费者，非法历史 JSON 走安全降级，合法 JSON 语义不变。CQ-200-16 仅处理市场数据查询服务的已发布/延迟回执联合类型、局部读取参数和签名 cursor 的 JSON 窄化；延迟回执不得进入可见查询结果。CQ-200-17 仅迁移 scanner plan 的模型实例字段与关系映射；不得触及 API、迁移或动态建表业务。CQ-200-18 仅收窄仓位估值 `safe_float` 的默认值返回契约；不得改变估值公式。CQ-200-19 仅收紧市场标的仓库快照名称、Pandas 行和指标聚合的类型边界；不得改变在线/仓库切换、数据源或行情计算语义。CQ-200-20 仅收紧新闻情报的可选数据库 session、已加载 ORM 标量和 feed 元数据 JSON 边界；不得改变公开工厂的无 session helper 契约。CQ-200-21 仅在认证服务的已加载 User/RefreshToken ORM 实例边界建立精确标量视图，并让登出路径对缺失、空或非字符串 JWT `jti` 失败关闭；不得改模型、JWT、路由、数据库 schema 或认证协议。CQ-200-22 仅在告警评估服务入口收窄已加载 AlertRule 的配置和告警类型，并让异常配置或类型不明规则失败关闭；不得改模型、监控调度、API、schema 或下游服务协议。CQ-200-23 仅为动态 `backtest_service` runtime shim 增加静态同级 stub，并以身份测试锁定其转发语义；不得修改 runtime shim、回测服务、调用方、配置或依赖。不得通过关闭 Ruff/Mypy 规则、排除模块或放宽配置制造通过结果。

T18 追加 CQ-200-24：仅修复 `comparison_service` 对 `BacktestService.get_result()` 可空返回值的验证后重复读取竞态，保持缺失任务的 `ValueError` 协议、重复 task ID 的原有逐项读取语义以及全部比较 payload 字段；不得触及回测服务、模型、API、schema、配置或依赖。

T19 追加 CQ-200-25：仅收敛参数优化回测等待器的 FAILED 结果读取，首次和轮询后失败必须遵循相同的 `RuntimeError` 协议；缺失/空错误信息采用稳定 fallback，不得改变 COMPLETED、CANCELLED、PENDING/RUNNING 或 timeout 行为。

T20 追加 CQ-200-26：仅为动态 `strategy_service` runtime shim 增加精确 sibling stub，并通过 runtime identity 测试锁定其 8 个公开导出；不得修改 shim、canonical core、调用方、配置或依赖。

T21 追加 CQ-200-27：增强回测 API 必须在既有客户端 `runtime_dir` 字段拒绝后，显式将增强请求验证为基础 BacktestService 请求模型；不得放宽服务签名、绕过安全拒绝或改变 WebSocket/响应语义。

T22 追加 CQ-200-28：仅显式化分析服务月度复利累计值和均线前置结果列表的数值类型；不得改变复利精度、MA 长度、前置 None 或短序列 MA60 语义。

T23 追加 CQ-200-29：仅显式化日志查询参数脱敏容器的 string/list 值联合类型，并锁定敏感参数遮蔽和普通重复参数保留；不得改日志流程或敏感键集合。

T24 追加 CQ-200-30：仅显式化版本参数 diff 的四分类嵌套字典返回结构；不得改变新增、删除、修改、未变或嵌套 from/to payload 语义。

T25 追加 CQ-200-31：监控规则 description 的 service 契约必须与 nullable 请求 schema 和数据库列一致；省略描述继续传递 None，不得被改写为空字符串。

T26 追加 CQ-200-32：市场数据授权 helper 必须保留已验证的 MarketDataPrincipal 类型至访问上下文；不得改变授权器重读、read check 或 fail-closed 异常语义。

T27 追加 CQ-200-33：股票研究兼容层 reconciliation 的 legacy payload 容器必须保持已声明的 `dict[str, object]` 合同；不得改变 legacy/generic 字段、映射或批量核对语义。

T28 追加 CQ-200-34：市场数据主数据 manifest version 必须用实际 literal 类型表达，资产类别计数器必须以 `str` 键满足输出合同；不得改变 manifest wire value、严格校验、计数或排序语义。

T29 追加 CQ-200-35：可选 Redis/内存缓存单例必须表达两种既有实现的联合类型；不得改变 Redis_URL 选择、单例复用或缓存运行时行为。

T30 追加 CQ-200-36：市场日历 manifest 默认 version 必须保持其固定 literal 类型；不得改变默认 wire value、严格校验、日历载入、事务或发布语义。

T31 追加 CQ-200-37：AkShare 数据库引擎的可变 kwargs 容器必须表达 `poolclass` 与 `pool_pre_ping` 两种既有值；不得改变 URL 解析、分支选择或 engine/sessionmaker 行为。

T32 追加 CQ-200-38：legacy evidence-gate 中只迭代 target 的私有 helper 必须接受 `Iterable`；不得改变 source binding、fail-closed 授权、permit 或写入顺序。

T33 追加 CQ-200-39：压力测试服务只读 scenarios 输入必须使用协变 `Sequence` 合同；不得改变 API/schema、内置场景、归一化或压力指标计算。

T34 追加 CQ-200-40：AI 策略改稿元数据局部容器必须同时表达既有字符串字段和可选整型 token 计数；不得改变模型响应解析、改稿、回退、metadata 字段或工作流行为。

T35 追加 CQ-200-41：日志解析 fallback 的指标序列必须表达既有缺失日期 `None` 补齐，且不得与 TSV 分支复用推断不兼容的局部变量；不得改变日期优先/索引回退对齐、OHLCV 或输出 payload。

T36 追加 CQ-200-42：文件系统数据集回执 SHA-256 校验必须以字符串 TypeGuard 表达既有失败关闭判断；不得改变回执 schema、恒定时间比较、文件控制边界或公开错误代码。

T37 追加 CQ-200-43：LLM 用量成对计数必须以严格非负内置整数 TypeGuard 在求和前收窄；不得接受 bool、改变未知用量失败关闭或配额结算/审计行为。

T38 追加 CQ-200-44：holdout execution journal 在持久化前必须保留 live binding 的非空 lease 到期时间；不得改变状态机、幂等性、错误代码或外部 evaluator 边界。

T39 追加 CQ-200-45：投研 run record freshness helper 必须只读取一次 pipeline，并将缺失、null 或非字典 pipeline 保持为空字典语义；不得改变 force、状态、ready 或 `live_candidate` 判定。

T40 追加 CQ-200-46：网关合约正数 helper 必须在转换前显式跳过 None；不得改变空字符串、非法值、零/负数或候选键 fallback 的结果。

T41 追加 CQ-200-47：自定义因子 evaluator 必须对已允许的正负一元 AST 节点作精确分派；不得扩大 AST 白名单、改变算术/缺值降级或 unsafe expression 结果。

T42 追加 CQ-200-48：动态 `live_trading_manager` 必须以 sibling stub 精确镜像 canonical class/factory，且 runtime module identity 不变；15 条 shim 误报与新揭露的 `InstanceData` 调用合同必须分开记录。

本迭代的测试和静态检查是本地代码及 fixture 证据，不构成生产验收、数据完整性验收或外部供应商验收。Node 20.20.2 与 Node 24.2.0 下全量 Vitest 各为 154 个文件、1687 项测试通过，前端 lint 均为 0 errors / 0 warnings，typecheck/build 结果见 ACCEPTANCE.md。后端 T8 将 `workspace.py` 的 39 个列和 3 个关系迁移为精确映射，模型 Mypy 为 0、相关测试 159 passed；T9 随后关闭三个直接 JSON 消费者的 10 条错误，目标 Mypy 为 0、定向测试 5 passed；T10 将 `query_service.py` 的 34 条精确错误收敛为 0，并用 69 项本地查询服务 fixture 验证延迟回执、lease 释放和 cursor 失败关闭边界；T11 将两个 scanner plan 模型的 32 个列和 2 个关系迁移为精确映射，并以 2 项 API fixture 验证动态结果表管理路径；T12 以 overload 明确 `safe_float` 的 float/None fallback 返回边界，3 个直接测试和 21 个现有估值场景通过；T13 将 `market_instrument.py` 的 20 条精确错误收敛为 0，并以 20 项本地 fake/Pandas/API fixture 验证仓库名称回退、异构行取值和缺失指标聚合；T14 将 `news_intelligence.py` 的 18 条精确错误收敛为 0，并以 8 项本地新闻 fixture 验证无 session helper、持久化拒绝和异常 JSON 降级；T15 将 `auth_service.py` 的 9 条精确错误收敛为 0，并以本地令牌 fixture 验证无效 `jti` 不访问撤销仓储、有效字符串继续撤销；T16 将 `alert_evaluation.py` 的 6 条精确错误收敛为 0，并以 96 项本地告警 fixture 验证非 Mapping 配置、空数值和无效 alert type 都不触发；T17 为动态 `backtest_service` shim 建立静态入口并以 46 项本地测试锁定运行时身份。T17 清除了 11 条 `BacktestService` 缺属性误报，但暴露了 14 条原先被动态 shim 遮蔽的真实调用契约错误，因此 T17 当时完整 Mypy 为 486 errors / 120 files（扫描 625 个源文件，退出码 1）；该阶段不能宣称净错误数下降，其 FAIL / NO-GO 仅是历史快照，当前状态见 T62–T68。该阶段记录的 production npm audit 为 2 项、全量 audit 16 项（14 项 dev-only）；旧的 1357 warnings/20 项 audit 数字仅是早期历史结果，不代表当前状态。

T18 以单循环将“验证后再读取”改为“读取、验证、立即构造 payload”，12 条由真实 `get_result() -> BacktestResult | None` 合同暴露的可空错误全部消失；30 项比较服务 fixture 通过，且完整 Mypy 为 474 errors / 120 files（扫描 625 个源文件，退出码 1）。按去除行号后的错误清单比较，除这 12 条外没有新增或消失的诊断；全量仍 FAIL / NO-GO。

T19 将参数优化的初始/轮询 FAILED 分支统一为受控失败，清除 1 条可空错误；48 项优化 API fixture 通过，且完整 Mypy 为 473 errors / 120 files（扫描 625 个源文件，退出码 1）。与 T18 的标准化清单差分仅移除该错误，全量仍 FAIL / NO-GO。

T20 为动态 `strategy_service` shim 建立静态镜像，清除 20 条缺属性误报；9 项 shim/策略扫描 fixture 通过，且完整 Mypy 为 453 errors / 116 files（扫描 625 个源文件，退出码 1）。与 T19 的标准化清单差分没有新增诊断；全量仍 FAIL / NO-GO。

T21 在增强回测路由的安全拒绝之后转换为基础服务请求，清除 1 条真实 `[arg-type]` 契约错误；完整增强回测 fixture 为 52 passed，根代理独立复验新增的转换/拒绝测试为 2 passed、1 条既有 warning，且完整 Mypy 为 452 errors / 115 files（扫描 625 个源文件，退出码 1）。与 T20 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T22 以显式浮点累计值和 `list[float | None]` 前置结果类型清除 2 条局部推断错误；22 项分析服务 fixture 通过，且完整 Mypy 为 450 errors / 114 files（扫描 625 个源文件，退出码 1）。与 T21 的标准化清单差分只移除该两条错误；全量仍 FAIL / NO-GO。

T23 为日志脱敏 helper 的 local dict 明确 string/list 值联合类型，清除 1 条局部推断错误；8 项日志中间件 fixture 通过，且完整 Mypy 为 449 errors / 113 files（扫描 625 个源文件，退出码 1）。与 T22 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T24 为版本参数 diff 的 local 四分类容器明确返回结构，清除 1 条局部推断错误；18 项版本 diff fixture 通过，且完整 Mypy 为 448 errors / 112 files（扫描 625 个源文件，退出码 1）。与 T23 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T25 将监控规则创建服务的 description 契约对齐为 nullable，清除 1 条真实 API 参数错误；49 项监控 API fixture 通过，且完整 Mypy 为 447 errors / 111 files（扫描 625 个源文件，退出码 1）。与 T24 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T26 令市场数据授权 helper 保留精确 principal 类型，清除 1 条访问上下文参数错误；4 项本地授权依赖 fixture 通过，且完整 Mypy 为 446 errors / 110 files（扫描 625 个源文件，退出码 1）。与 T25 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T27 为兼容层 legacy reconciliation payload 补充既有 `dict[str, object]` 注解，清除 1 条 append 参数错误；2 项本地兼容层 fixture 通过，且完整 Mypy 为 445 errors / 109 files（扫描 625 个源文件，退出码 1）。与 T26 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T28 以 literal alias 固定主数据 manifest version，并显式将类别计数器收紧为 `Counter[str]`，清除 2 条类型错误；8 项本地主数据 importer fixture 通过，且完整 Mypy 为 443 errors / 108 files（扫描 625 个源文件，退出码 1）。与 T27 的标准化清单差分只移除这两条错误；全量仍 FAIL / NO-GO。

T29 为缓存单例及 factory 标记 Redis/内存联合合同，清除 1 条赋值错误；17 项本地缓存 fixture 通过，且完整 Mypy 为 442 errors / 107 files（扫描 625 个源文件，退出码 1）。与 T28 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T30 将 calendar manifest version 常量标注为其既有 literal，清除 1 条默认值错误；13 项本地 calendar importer fixture 通过，且完整 Mypy 为 441 errors / 106 files（扫描 625 个源文件，退出码 1）。与 T29 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T31 为 AkShare 引擎局部 kwargs 容器补充对象值类型，清除 1 条分支赋值错误；使用隔离字节码缓存的本地管理 API fixture 为 66 passed、79 skipped，且完整 Mypy 为 440 errors / 105 files（扫描 625 个源文件，退出码 1）。与 T30 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T32 将 legacy evidence-gate 的 target iterable 合同对齐为 `Iterable`，清除两处 `dict.values()` 参数错误；16 项隔离 SQLite harness 通过，且完整 Mypy 为 438 errors / 104 files（扫描 625 个源文件，退出码 1）。与 T31 的标准化清单差分只移除一个重复出现的错误签名；全量仍 FAIL / NO-GO。

T33 将压力测试 scenarios 的只读参数收紧为协变 `Sequence`，清除 API 传入 `list[StressScenario]` 的错误；5 项本地压力场景 fixture 通过，且完整 Mypy 为 437 errors / 103 files（扫描 625 个源文件，退出码 1）。与 T32 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T34 将 AI 改稿 metadata 的局部容器显式为 `dict[str, object]`，清除可选 `total_tokens` 写入 int 的错误；既有 AI 改稿回归节点通过，且完整 Mypy 为 436 errors / 102 files（扫描 625 个源文件，退出码 1）。与 T33 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T35 将日志 fallback 指标容器收紧为独立的 `dict[str, list[float | None]]`，清除缺失补齐和同作用域变量复用的 4 条错误；56 项日志解析 fixture 通过，且完整 Mypy 为 432 errors / 101 files（扫描 625 个源文件，退出码 1）。与 T34 的标准化清单差分只移除这 4 条错误；全量仍 FAIL / NO-GO。

T36 将回执 SHA-256 验证 helper 标注为 `TypeGuard[str]`，清除恒定时间比较前已验证 hash 的错误；9 项文件系统 resolver fixture 通过，且完整 Mypy 为 431 errors / 100 files（扫描 625 个源文件，退出码 1）。与 T35 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T37 将 LLM 用量 pair 的严格整数验证显式为 `TypeGuard[int]` 并以具名值求和，清除混合 `Any | None` 的错误；70 项 gateway fixture 通过，且完整 Mypy 为 430 errors / 99 files（扫描 625 个源文件，退出码 1）。与 T36 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T38 在 holdout journal 持久化前显式对 lease 到期时间重复执行原有失败关闭检查，清除可空时间参数错误；7 项 journal fixture 通过，且完整 Mypy 为 429 errors / 98 files（扫描 625 个源文件，退出码 1）。与 T37 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T39 将 run record freshness helper 的 pipeline 保存为一次局部读取，只对字典读取 `current_stage`，保留缺失、null、非字典和 force/状态/ready 的既有语义；8 项直接参数化 fixture 通过，且完整 Mypy 为 428 errors / 97 files（扫描 625 个源文件，退出码 1）。与 T38 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T40 将网关合约正数 helper 的 None 检查显式化，保留空字符串、异常转换、零/负数和后续候选值的既有回退；5 项直接参数化 fixture 通过，且完整 Mypy 为 427 errors / 96 files（扫描 625 个源文件，退出码 1）。与 T39 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T41 将自定义因子 evaluator 的一元正负分派显式化，保留 AST 白名单、四则/幂运算、缺值降级与 unsafe expression 行为；9 项 factor fixture 通过，且完整 Mypy 为 426 errors / 95 files（扫描 625 个源文件，退出码 1）。与 T40 的标准化清单差分只移除该错误；全量仍 FAIL / NO-GO。

T42 为动态 live trading manager shim 增加只转发 canonical class/factory 的静态入口；identity fixture 为 1 passed，15 条 shim `[attr-defined]` 消失，但揭露 `api/portfolio/api.py` 与 `trading_workspace_service.py` 的 11 条 `InstanceData`/dict 真实合同错误。完整 Mypy 为 422 errors / 90 files（扫描 625 个源文件，退出码 1）；全量仍 FAIL / NO-GO。

T43 将 portfolio/workspace 对 manager 实例记录的消费收紧为只读 `Mapping[str, object]`，并只在已有 `persist_asset_specs()` 写入边界创建局部浅拷贝；启动路径继续分别承接已运行 `InstanceData`、`StartResult` 和 already-running 刷新实例。根代理的 5 项直接/相邻回归通过（1 条既有 Backtrader Quandl warning）。完整 Mypy 为 403 errors / 90 files（扫描 625 个源文件，退出码 1）：T42 的 11 条合同错误和 portfolio 的 8 条同根 `params` `[union-attr]` 均消失，标准化差分没有新增诊断；全量仍 FAIL / NO-GO。

T44 将两个 contract-metadata 同步 helper 的动态值收窄为单次读取后的浅拷贝，保留 instance/spec 两条 metadata merge、兄弟标的和 source 组合语义。根代理的 5 项直接/相邻回归通过（1 条既有 Backtrader Quandl warning），目标文件中两条 `dict()` `[arg-type]` 为零，仍保留 5 条无关历史错误。完整 Mypy 为 401 errors / 90 files（扫描 625 个源文件，退出码 1）：原始计数较 T43 减少 2，标准化差分无新增（相同签名去重后移除 1 条）；全量仍 FAIL / NO-GO。

T45 将 portfolio 与 workspace 的 position-log latest-row 选择器中不同 tuple 状态表的候选变量分离，保持 timestamp/index 比较、双向持仓、无方向/方向性平仓和输出排序语义。根代理的 8 项既有双边、Bybit、flat、directional-flat 回归通过（1 条既有 Backtrader Quandl warning），6 条 tuple `[assignment]` 为零，仍保留 7 条无关历史错误。完整 Mypy 为 395 errors / 90 files（扫描 625 个源文件，退出码 1）：恰移除 6 条目标诊断，标准化差分没有新增；全量仍 FAIL / NO-GO。

T46 将 portfolio 资产规格持久化路径的 contract-metadata 收紧为单次局部读取后的浅拷贝，保持 user/workspace/ownership 保护、alias merge/source 与事务语义。根代理的本地 SQLite/fake gateway 持久化回归通过（1 条既有 Backtrader Quandl warning），目标文件该条 `dict()` `[arg-type]` 为零，仍保留 4 条无关历史错误。完整 Mypy 为 394 errors / 90 files（扫描 625 个源文件，退出码 1）：恰移除 1 条目标诊断，标准化差分没有新增；全量仍 FAIL / NO-GO。

T47 仅为 portfolio equity 中由空 list 初始化的两个实例序列容器声明 `dict[str, list[float]]`，不改变 aggregation、`_safe_round()` 追加、统一采样或 response payload。根代理的 6 项既有 equity 回归通过（1 条既有 Backtrader Quandl warning），目标两条 `[var-annotated]` 为零，目标文件仅余两条无关的数值转换错误；Ruff、format 和 target diff check 通过。完整 Mypy 为 392 errors / 90 files（扫描 625 个源文件，退出码 1）：相对 T46 恰移除两条目标诊断，标准化差分没有新增；全量仍 FAIL / NO-GO。

T48 将 portfolio 与 workspace 两个同构 direction parser 的动态数值转换收窄为既有 `_safe_float()` 配合 NaN 哨兵，保留文本 alias、数值代码、Bybit `positionIdx=0` 和非法 code 的 signed-size fallback。根代理的 6 项直接/双向路径回归通过（1 条既有 Backtrader Quandl warning），两条目标 `float()` `[arg-type]` 为零；Ruff、format 和 target diff check 通过。完整 Mypy 为 390 errors / 90 files（扫描 625 个源文件，退出码 1）：相对 T47 恰移除两条目标诊断，标准化差分没有新增；全量仍 FAIL / NO-GO。

T49 将 server-attested paper runtime 的 JSON anchor 收窄为 dict 或 `None`，保持 verifier 的非 Mapping 失败关闭与原 provenance-invalid 错误码。根代理的本地 fake-manager 回归确认标量 anchor 不同步运行时、不创建实例；相邻 live 风控拒绝和普通 paper 启动通过（3 passed，1 条既有 Backtrader Quandl warning）。目标服务 Mypy 为零，完整 Mypy 为 389 errors / 90 files（扫描 625 个源文件，退出码 1）：相对 T48 恰移除一条目标诊断，标准化差分没有新增；全量仍 FAIL / NO-GO。

T50 将 portfolio `_first_number()` 的动态候选收窄为 `object` 局部读取（nested 候选为 `object | None`），并新增 `_is_float_input()` TypeGuard 仅放行 `float()` 的既有输入协议（str/bytes/bytearray/memoryview/`SupportsFloat`/`SupportsIndex`）；非协议值沿用下一候选键语义，与旧 `float()` TypeError 路径运行时等价，`(TypeError, ValueError)` 捕获、nested 字段优先级、string trim/逗号移除和 NaN/Infinity 保留均未改。直接 fixture 由本工作区已建立的三项 `_first_number` 回归（nested numeric text/trim/逗号、invalid-first-key 到 next-key fallback、Decimal 数值协议与 NaN/bytearray）承担，完整 portfolio fixture 为 129 passed、1 条既有 Backtrader Quandl warning；目标文件精确 Mypy 为 0，Ruff check/format、target `git diff --check` 与 diff 抑制扫描通过（累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解）。完整 Mypy 为 388 errors / 89 files（扫描 625 个源文件，退出码 1）：恰较 T49 减 1 条错误、1 个报错文件，`api/portfolio/api.py`（T49 清单中该文件唯一错误即本批目标）退出完整清单；全量仍 FAIL / NO-GO。

T51 将 `app/models/alerts.py` 三模型（Alert 26 列、AlertRule 15 列、AlertNotification 8 列，声明关系 10 个）迁移为精确 SQLAlchemy 2 `Mapped[...]`/`mapped_column(...)` 类型，JSON 字段用递归 `JSONValue` 表达（`trigger_config: dict[str, JSONValue]`、`notification_channels: list[JSONValue]`、`details: JSONValue | None`）；外部关系目标仅经 `TYPE_CHECKING` 前向引用。AST 对比确认 59 个列/关系调用参数与 HEAD 零差异，运行时 mapper 核验 3 tables（26/15/8 列）；独立审查揭露初版把 5 个时间戳列 nullable 从 legacy 默认 True 翻转为 False，已按 T8 先例修正为 `Mapped[datetime | None]` 并对三处 `.isoformat()` 消费点加等价守卫。`monitoring_service.py` 同批清除 T25 挂账的 15 条错误：显式 `AlertRule | None` 守卫（与原 getattr 短路等价）、两处 `filters: dict[str, str | bool]` 容器注解、webhook url/headers 单次读取加 str/dict 收窄（非字符串 url 从 try 块外崩溃改为既有 "missing webhook url" 失败关闭记录），并修复模型迁移揭露的真实运行时缺陷：`_send_websocket_alert` 的 `alert.alert_type.value`/`alert.severity.value` 对 str 属性必然 `AttributeError`，改为直接使用字符串值。定向测试 198 passed、7 条既有 warning；两文件精确 Mypy 为 0，Ruff/format、`git diff --check` 与 diff 抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 373 errors / 88 files（扫描 625 个源文件，退出码 1）：标准化差分恰移除 monitoring_service 15 条、新增 0 条，`paper_runtime_service`/`risk_control`/`alert_evaluation` 等其它 alerts 模型消费者无新增诊断；全量仍 FAIL / NO-GO。

T52 将 `app/models/comparison.py` 两模型（Comparison 11 列/3 关系、ComparisonShare 5 列/2 关系）迁移为精确 SQLAlchemy 2 映射：`backtest_task_ids: list[str]` 与 schema 既有 `list[str]` 合同一致、`comparison_data: dict[str, JSONValue]`、时间戳按 T8/T51 先例为 `Mapped[datetime | None]`（baseline nullable=True 佐证，mapper 探针核验通过）；association table 的 `Column` 保持原样。`comparison_service.py` 同批清除 T18 挂账的 18 条错误：四个比较容器的局部注解与各自既有 `-> dict[str, Any]` 返回签名一致（T24 先例口径）、`best_metrics` 以 `dict[str, dict[str, str | float | None]]` 消除 5 条 dict-item、`filters: dict[str, str | bool]` 消除 2 条、`update_dict: dict[str, object]` 消除 4 条 assignment、update 后的 `Comparison | None` 显式守卫（原 `_to_response(None)` 必然 AttributeError，改为返回 None 失败关闭）、1 条 `Column[str]` 随模型迁移消失。定向测试 84 passed（service 30 + comparison/api 54）、既有 warnings；AST 对比 21 声明零差异，两文件精确 Mypy 为 0，Ruff/format、`git diff --check` 通过。完整 Mypy 为 355 errors / 87 files（扫描 625 个源文件，退出码 1）：标准化差分恰移除 comparison_service 18 条、新增 0 条；全量仍 FAIL / NO-GO。

T53 将 `app/models/akshare_mgmt.py` 七模型（DataScript/DataTable/InterfaceCategory/DataInterface/InterfaceParameter/ScheduledTask/TaskExecution，105 列 + 9 关系）迁移为精确 SQLAlchemy 2 映射：五个 `Enum(..., values_callable=_enum_values)` 列以对应 enum 类型注解、`metadata_json` 保留显式列名 "metadata"、全部显式 `nullable=False` 时间戳保持、JSON 列按语义用 `JSONValue`/`dict[str, JSONValue]` 表达。AST 对比 114 声明零差异；mapper 核验 7 tables 共 105 列、Enum/nullable 探针通过。`akshare/script.py` 同批清除 17 条错误：`_script_timeout_seconds` 改显式属性访问并以 `or "60"` 等价重写 getenv 链、约 1100 行的 `safe_defaults` 巨型字面量以 `dict[str, dict[str, str | int | list[str]]]` 精确注解（Mypy 反向验证全量条目值域并揭露既有 list 值）、legacy 表名单次调用复用并以双 None 条件 fail-closed（审查证实 `normalize_existing_table_name` 不返回空串，该守卫加固不可达路径并消除旧代码可能静默同步 "data" 错表的隐患）；execution/scheduler/api-tables 的 8 条与 `data_connectors/registry.py` 引用 `DataInterface` 的 2 条同根因连带消失。定向测试 178 passed、79 skipped（既有）、1 条既有 warning；五文件精确 Mypy 为 0，Ruff/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）；独立审查代理复核 PASS、未发现缺陷。完整 Mypy 为 323 errors / 82 files（扫描 625 个源文件，退出码 1）：标准化差分移除 32 条 errors（30 预期 + registry 2 条同根因连带）、新增 0 条；全量仍 FAIL / NO-GO。

T54 将 `live_trading/execution.py` 的 16 条错误全数清除：`_optional_lock()` 返回注解从同步 `AbstractContextManager` 修正为 `AbstractAsyncContextManager`（六处 `async with` 调用点的既有运行时语义——`nullcontext` 在 Python 3.10+ 实现异步协议，运行时与 Mypy `--python-version 3.10` 双重验证），消除 12 条 `__aenter__`/`__aexit__` 误报；三个 `_bt_*` 子进程句柄的动态属性写入改为与读取侧（`__dict__.get`）对称的 `__dict__` 直写（与点号赋值语义严格等价，且通过 Ruff B010 对常量 setattr 的既有门禁）；`_merge_runtime_contract_metadata` 的二次 `get` 改单次局部读取收窄。live_trading 定向测试七个文件合跑 208 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff check/format、`git diff --check` 通过（签名行的 `Any` 为既有参数化，非新增）。完整 Mypy 为 307 errors / 81 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 16 条、新增 0 条；全量仍 FAIL / NO-GO。

T55 将 `app/models/data_governance.py` 八模型（DgProvider/DgDataset/DgStorageTarget/DgDatasetStorage/DgEndpoint/DgEndpointParam/DgIngestJob/DgQualityRule，78 列 + 13 关系）迁移为精确 SQLAlchemy 2 映射：时间戳保持显式 `nullable=False`、`Enum(DgJobStatus)` 无 `values_callable` 的既有存储语义经 AST 对比保持、JSON 列按 `default=dict/list` 语义用 `dict[str, JSONValue]`/`list[JSONValue]`、跨模型关系（`DataTable` 互引）经 `TYPE_CHECKING` 前向引用。`data_connectors/registry.py` 同批清除 14 条：两处 `Row` 返回经 `tuple(row)` 显式适配既有 `tuple[DgEndpoint, DgProvider] | None` 合同（调用方仅解包，语义等价），`_PROVIDER_SEEDS` 巨型字面量以 `dict[str, str | int]` 注解并对 `provider_id` 单次读取加 isinstance 收窄（字面量恒 str，行为不变），其余 12 条 `Column` 误推断随迁移消除。模型收紧在 `market_data/store.py` 暴露的 provenance/authorization 自由 JSON 容器（推断窄化为 `Sequence[str]` 联合）当场以与下游 `Mapping[str, object]` 合同一致的注解修复，连带消除 `bootstrap.py` 2 条与 `quant_tools_runtime.py` 1 条。定向测试 148 passed、20 条既有 warning；三文件精确 Mypy 为 0（store.py 剩余为 T7 挂账的非 ORM 错误），AST 对比 91 声明零差异，mapper 核验 8 tables/78 列，Ruff/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 287 errors / 79 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 20 条、新增 0 条；全量仍 FAIL / NO-GO。

T56 将 T7 挂账的 `market_data/store.py` 非ORM错误全数清除（含 T55 已修的 3325 共 9 条）：B2 完整性证据的 `expected_record_key_sha256s` 在断言前 None 失败关闭（沿用既有 `B2_COMPLETENESS_RECEIPT_INVALID`，经既有 except 归一为 `B2_COMPLETENESS_EVIDENCE_INTEGRITY`）；deferred legacy 的 `source_observed_at` None 早退与 `_stored_utc` 内部行为完全等价（同码 `LOCAL_OBSERVATION_INTEGRITY`）；`publication.visibility_sequence` None 从构造含 None 的 receipt 改为显式 `DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY` 失败关闭；registry 授权断言的 `allowed_uses`/`jurisdictions` 非容器值从迭代 object 崩溃改为显式 `SOURCE_AUTHORIZATION_INVALID`；semantic record key 的 `dimensions` 非 Mapping 经 ValueError 走既有 `LOCAL_OBSERVATION_INTEGRITY` 路径；shared payload 引用的 validated 结构改为单次局部读取加双非空条件（与 `_get_or_create` 的 None-入-None-出契约一致）；calendar 选择的 tuple 列表以显式联合注解表达（CQ-200-51 模式）。market_data_platform 全套定向测试 1254 passed、137 条既有 warning；目标文件精确 Mypy 为 0，Ruff check/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 279 errors / 78 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；全量仍 FAIL / NO-GO。

T57 将 db 基础设施双文件的 19 条错误全数清除：`sql_repository.py` 以单点 `_cursor_rowcount` helper 对 `Result` 做 `CursorResult` isinstance 收窄（运行时 DML 结果恒为 CursorResult，None/不可用时归 0 与原 `or 0`/`if not` 语义等价），七处 `type[T].id` 访问收敛到 `_id_column()` 的 `__dict__` 直接映射访问（Protocol bound 方案经探针证实被 Mapped 不变式拒绝后放弃；与文件既有 `_apply_filters` 的动态属性风格一致，`getattr` 常量形态被 Ruff B009 门禁拒绝）；`database.py` 的 engine `extra_kwargs` 按 T31 先例注解 `dict[str, object]`，六处 `__table__.create` 收敛到单点 `_create_table_if_missing` helper（`FromClause` 静态宽类型运行时恒为 Table，isinstance 收窄），`get_db` 返回注解修正为 `AsyncGenerator[AsyncSession, None]`。db 影响面回归（monitoring/comparison/auth/alerts/refresh-token）147 passed；两文件精确 Mypy 为 0，Ruff check/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`；TypeVar 恢复无 bound 保持全部泛型使用者兼容）。完整 Mypy 为 260 errors / 76 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 19 条、新增 0 条；全量仍 FAIL / NO-GO。


T58 将 `research/discovery_trial_materialization.py` 的 13 条错误全数清除：三处可空边界的显式失败关闭——两处 `journal.result_json` 为 None 时先行抛出 `DISCOVERY_EXECUTION_RESULT_INVALID`（与 `DiscoveryExecutionResult.from_mapping` 对无效 payload 的既有拒绝路径完全等价），`session.get` 取得的 quota 保留行为 None 时抛 `DISCOVERY_PUBLICATION_QUOTA_DENIED`（与同一 if 块的十项校验共享错误码，行为从 AttributeError 崩溃改为显式拒绝），dataset 快照缺失时抛 `DISCOVERY_PUBLICATION_CANDIDATE_DENIED`（候选证据链不完整）。定向测试 22 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff check/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 247 errors / 75 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 13 条、新增 0 条；全量仍 FAIL / NO-GO。

T59 补完 `app/models/knowledge_base.py` 的部分迁移状态（T5 曾单字段迁移）：七模型（KnowledgeBase/KBDocument/DocumentChunk/ChatConversation/ChatMessage/ModelConfig/ModelUsageLog）剩余 legacy 列全部迁移为精确映射，时间戳按 T8/T51 先例为 `Mapped[datetime | None]`（baseline nullable=True 佐证），JSON 字段沿用 ChatMessage.metadata_json 的 `dict[str, object] | None` 先例与递归 `JSONValue`，T5 既有 `settings: dict[str, Any]` 注解原样保留。`reqdocs_migration_service.py` 同批清除 9 条：六个 dict comprehension 的二次 `get` 改单次读取循环（CQ-200-50 根因），模型迁移消除 3 条 Column 误推断并暴露 `entity` 变量复用边界（KBDocument 与 ChatMessage 块分离变量，CQ-200-45 模式）；连带消除 `rag_service.py` 4 条同根因误推断。定向测试 44 passed、1 条既有 warning；两文件精确 Mypy 为 0，AST 对比声明零差异，Ruff/format、`git diff --check` 与抑制扫描通过（新增行零 `cast`/`type: ignore`/`# noqa`；`typing.Any` 为既有 import 保留）。完整 Mypy 为 234 errors / 73 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 13 条（reqdocs 9 + rag_service 4 连带）、新增 0 条；全量仍 FAIL / NO-GO。

T60 将 `live_trading/manager.py` 的 8 条错误全数清除：三处二次 `get`（instance params/workspace_unit/contract_metadata）改单次局部读取收窄（CQ-200-50 根因）；`_raise_on_failed_open_order_cancel` 的异常动态属性改 `__dict__` 直写（T54 模式，无仓内读取方、行为不变）；`StartResult` 上对动态注入私有字段的 pop 移到既有 `cast(StartResult, ...)` 之前的原始 dict 上执行（TypedDict 不可赋给可变 dict 类型，pop 位置前移对同一 dict 与同一异常路径完全等价，未新增 cast）；`start_instance_callback`/`stop_instance_callback` 以 `Callable[[str], Awaitable[StartResult|StopResult]]` 显式注解（绑定方法的完整签名与单参包装函数均满足该窄合同）。live_trading 定向测试四文件 151 passed、1 条既有 warning；目标文件精确 Mypy 为 0，Ruff check/format（含 I001 自动整理）、`git diff --check` 与抑制扫描通过（唯一 cast 命中为既有 cast 的等价重排）。完整 Mypy 为 226 errors / 72 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；全量仍 FAIL / NO-GO。

T61 将 market_data 的 `fetch_lease.py`（6 条）与 `publication.py`（6 条）全数清除，均为 T56/T57 模式复刻：六处 `Result.rowcount` 经各文件单点 `_cursor_rowcount` helper 以 `CursorResult` isinstance 收窄（运行时 DML 恒 CursorResult、rowcount 不可用归 0 与原 `!= 1` 判断等价）；fetch lease 数据库时钟的 `Any | None` 以 None 早退显式 `FETCH_LEASE_CLOCK_INVALID`（与原 `_stored_utc` 内 ValueError→同码的既有路径等价）；publication 的 `found` 字典以行索引 comprehension 重建（与 `dict(Row)` 运行时等价）、动态注册模型的 `model.id` 经 `__dict__["id"]` 直接映射（T57 模式）、B2 selector 的可空哈希清单按 T56 同款先 None 失败关闭（沿用 `B2_COMPLETENESS_RECEIPT_INVALID` 并经既有 except 归一 `PUBLICATION_ENTITY_INTEGRITY`）。定向测试五文件 141 passed、1 条既有 warning；两文件精确 Mypy 为 0，Ruff check/format、`git diff --check` 与抑制扫描通过（新增行零 `Any`/`cast`/`type: ignore`/`# noqa`）。完整 Mypy 为 214 errors / 70 files（扫描 625 个源文件，退出码 1）：error 级标准化差分恰移除 12 条、新增 0 条；全量仍 FAIL / NO-GO。

## T62 最终静态门禁收敛（2026-09-22）

在当前工作树快照中，使用 base Conda 环境和新建隔离缓存运行 `python -m mypy app --show-error-codes`，结果为 `Success: no issues found in 625 source files`（退出码 0）。这覆盖并关闭 QD-200-01 的全量静态类型门禁；未通过排除模块、关闭规则或新增忽略项取得结果。

最后的收敛工作包括：订单价格拒绝 NaN/无穷值、手工网关对 Decimal/非有限数量的失败关闭、可观测性队列容量的正整数配置收窄、工作空间前向引用抑制移除、THS 历史回填授权/事务边界，以及工作空间服务改从具名实现模块导入三个资产信息 helper，避免动态 facade 的 `Any` 可调用边界。

根代理复验的重点证据为：`test_trading_workspace_service.py` 145 passed（1 条既有 Backtrader warning），目标 Mypy/Ruff/format 通过；THS 历史相关 fixture 64 passed；直接订单与手工网关相关 fixture 56 passed；可观测性与工作空间 fixture 43 passed。未运行全量后端 pytest，未连接真实数据库、网络、行情、供应商或交易系统。THS 日历同日复用的断言使用 mock importer 验证 manifest 一致性；真实数据库 importer 的复用路径未实测。
## T63 复审后事务与数值边界收敛（2026-09-22）

T62 的只读复审发现并关闭了四类会绕过“本地检查通过”表象的缺口：订单方向码的非有限数值转换；工作空间持仓日志的溢出/非有限数值和资产规格写回原 manager instance 的语义；THS CLI dry-run 内部批量提交；THS 单标的失败回滚整批而使计数虚高。THS 日历 caller-owned dry-run 还以真实内存 SQLite 验证了已启动保存点、物理外层事务和嵌套写入回滚的组合边界。

根代理合并回归覆盖订单、手工网关、可观测性、工作空间、THS history/reference/contracts/calendar importer，共 `484 passed, 1 warning`；17 个相关文件 Ruff check/format 通过。随后使用新的隔离缓存完整运行 `python -m mypy app --show-error-codes`，再次得到 `Success: no issues found in 625 source files`（退出码 0）。全量后端 pytest 仍为 NOT_RUN；真实生产数据库、网络、行情、供应商和交易系统均未连接。

## T64 Mypy ratchet 基线归零（2026-09-22）

为匹配 CI，T64 在 base Conda 上通过临时 `PYTHONPATH` 使用固定版本 Mypy 1.20.2（`mypy 1.20.2 (compiled: yes)`），并以新隔离缓存运行全量 `mypy app --show-error-codes`，结果为 `Success: no issues found in 625 source files`。首轮 1.20.2 扫描曾发现纸面交易 helper 的一条 `memoryview(object)` 类型错误；相关修复完成后，本次新缓存复验通过。随后在同一 1.20.2 环境运行仓库 guarded baseline-update，CI ratchet 的 `baseline_errors` 更新为 0；常规 ratchet 输出 `errors=0 baseline=0 delta=+0`。仓库没有 mypy-ratchet 合成回归测试，因此验证了实际 ratchet 路径。`src/backend/3.10/` Mypy 缓存保留原样，并在 `.gitignore` 中精确忽略以避免再次作为未跟踪文件出现。

T64 当时仅更新静态质量门禁基线与迭代记录；当时未运行全量后端 pytest 和真实数据库、网络、行情、供应商、交易系统。后续 T68 的最终本地非性能回归见下节。

## T68 缓存隔离与最终本地非性能回归（2026-09-22）

`response_cache` 对回测结果和策略列表两个 owner-scoped 路由启用以 `SECRET_KEY` 域分隔的 HMAC 用户范围；原始用户 ID 不写入 key，缺失/畸形身份直接 bypass。真实 ASGI 覆盖了 Alice MISS/HIT、Bob 不能读取 Alice 数据、旧无分区 key 不命中和未知 principal 不缓存。全零权益曲线只在 drawdown 全 NaN 时早退为既有 0.0；混合零/负数路径仍沿用原有非有限 fallback。AkShare timeout fixture 不再执行真实代理探测，并等待后台 callable 收口；嵌套 pytest 配置已与上级的 strict markers、30 秒 thread timeout、marker 和 warning/logging 规则一致。

使用临时 target 的 CI 固定 Mypy 1.20.2，fresh-cache 为 `Success: no issues found in 630 source files`，ratchet 为 `errors=0 baseline=0 delta=+0`。随后以新 `PYTHONPYCACHEPREFIX` 执行 `python -m pytest -q -m "not performance" --maxfail=0`，得到 `7859 passed, 123 skipped, 24 deselected in 2986.46s (0:49:46)`，无 warning summary。该回归和 ASGI fixture 不证明共享 Redis 的滚动发布；发布前仍须 drain/stop 旧 worker、失效 `backtests:*` 与 `strategies:*` 后再切流。

## T69 未关闭代码质量债务收口（2026-09-22）

T69 使用 canonical dev lock 复验锁文件同步（170 个包）、全量 Mypy（630 个源文件零错误）、0-error ratchet 和四个 CI Mypy scope。告警服务现在只将三种已知告警枚举序列化为 `.value`，精确内置字符串保留原样，未知对象（含未知 `str, Enum`）走内置 `str(...)` 回退；有效 webhook 与摘要均安全处理缺失时间戳，监控/告警回归共 204 项通过。

前端 `npm run lint` 已强制 `--max-warnings 0`；Node 24 的 lint、typecheck、156 个 Vitest 文件/1695 项测试、生产构建、manifest bundle gate 和 17 项 CI helper 测试通过。Vitest 结束时输出过一条 `ECONNRESET` 诊断但退出码为 0、全部测试通过，未归因为项目代码缺陷；Vite 的大 chunk 信息仍是非阻断 advisory。为保持 lint 可读性，7 个 Vue 文件的纯模板换行增量经过逐项 diff 审查后才精确更新对应尺寸基线，未对脏工作树执行第二次全量 baseline 刷新。

最后以新的 `PYTHONPYCACHEPREFIX` 执行全量非性能后端回归：`7864 passed, 123 skipped, 24 deselected in 3206.49s (0:53:26)`。该回归之后修复了一处 webhook 缺失时间戳的 P2 兼容性问题；修复后的 204 项完整监控/告警影响面、目标 Mypy 与 Ruff/format 均通过，故不把先前全量结果误称为该最后一行补丁后的全量重跑。没有暂存、提交或推送；提交时需把当前未跟踪的 CI helper/test 文件与其引用一起纳入，否则干净 CI 会缺少引用文件。

## 阅读顺序

README → REQUIREMENTS → DESIGN → IMPLEMENTATION_PLAN → ACCEPTANCE → QUALITY_DEBT_REGISTER

## 后续质量债务

T64–T69 已关闭本地 Mypy、registry 依赖审计、manifest bundle、源码尺寸、缓存租户隔离、
告警 wire value 和前端 lint 门禁
与已定位的测试运行时债务；固定 Git `backtrader` 的 PyPI 审计不可见性、真实浏览器体验、
共享 Redis 的滚动发布和所有外部系统验证仍是明确边界。七个大型编排器的实际职责拆分计划见
[迭代 201](../迭代201-核心编排器职责拆分/README.md)，其余证据、优先级及后续
验收标准见[质量债务台账](QUALITY_DEBT_REGISTER.md)。
