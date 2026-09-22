# 迭代 200：实施计划

> 历史说明：S0–S67 / T1–T61 中记录的 Mypy 错误数及 `FAIL / NO-GO` 反映各阶段执行时的观察值；T62/T63 是此前 base Conda 的本地复验。T64 的 Mypy 1.20.2 fresh-cache 全量复验为 0 errors / 625 source files，ratchet 基线为 0；当前 T69 在 canonical dev lock 中复验为 0 errors / 630 source files，ratchet 为 0→0。远端 CI、浏览器 E2E、真实外部系统和共享 Redis 滚动发布仍为 NOT_RUN。

## 阶段

| 阶段 | 内容 | 需求 | 完成条件 |
| --- | --- | --- | --- |
| S0 | 保存代码质量和依赖安装审计基线 | CQ-200-01、CQ-200-06 | 已记录 peer 冲突及完整 Mypy 数量 |
| S1 | 对齐 coverage-v8 版本线并更新锁文件 | CQ-200-01 | npm clean install 成功 |
| S2 | 格式化三个审计命中的 Python 文件 | CQ-200-02 | Ruff format check 和 lint 成功 |
| S3 | 修复 THS clock、六处 __all__ 和 expected manifest 类型 | CQ-200-03 至 CQ-200-05 | 精确 Mypy 与指定 fixture 测试成功 |
| S4 | 汇总本地验证及未解决债务 | CQ-200-06 | ACCEPTANCE.md 记录当时全量 Mypy 的 FAIL / NO-GO 快照及外部未验收边界；当前状态见 T62–T68 |
| S5 | 用 jsdom 隔离四个 DOMPurify Markdown 测试 | CQ-200-07 | Node 24.2.0 下四个目标测试文件 35 项通过；全量 Vitest 154 files / 1687 tests 通过，见 ACCEPTANCE.md |
| S6 | 在 SFC 导入前 mock 非被测 MonacoEditor 模块 | CQ-200-08 | StrategyDetailDialog 单文件 1/1 通过；不修改生产组件或 shared setup |
| S7 | T1：修复 12 个后端源文件的精确类型错误；维持 Python >=3.10 超时兼容；复跑相关测试和全量 Mypy | T1 / QD-200-06；CQ-200-06 全量复验 | 目标 Mypy 0 errors、Ruff check/format 通过、相关测试 256 passed；全量 Mypy 仍为 1072 errors / 168 files（625 files checked），继续 FAIL / NO-GO |
| S8 | T2：为 `app.api.deps` 动态模块别名新增显式 PEP 484 stub；保持运行时模块身份不变 | T2 / QD-200-07；CQ-200-06 全量复验 | 39 文件 importer 检查无 deps 缺属性错误；stub Ruff/Mypy 与指定测试通过；全量 Mypy 更新为 1027 errors / 145 files，继续 FAIL / NO-GO |
| S9 | T3：修复 MySQL data-fetch 核心连接/游标/行返回类型契约；验证空查询边界并刷新全量 Mypy | T3 / QD-200-08；CQ-200-06 全量复验 | 两个核心文件精确 Mypy 0 errors，目标 Ruff 与 11 个 fake-based 测试通过；全量 Mypy 984 errors / 143 files（625 checked）仍 FAIL / NO-GO；真实 MySQL 未验证 |
| S10 | T4：对齐 AkShare data-fetch consumers 与 T3 的连接/游标、row、save_data 返回合同；修复 requests probe 参数类型 | T4 / QD-200-09；CQ-200-06 全量复验 | 三个 consumer 文件精确 Mypy 0 errors；定向 Ruff 与 fake-only tests 通过；刷新完整 Mypy 并记录 FAIL / NO-GO；真实 MySQL、AkShare 和外网均不运行 |
| S11 | T5：将股票分析/信号 ORM 实例字段改为精确 SQLAlchemy 2 类型映射，修复任务服务类型合同 | T5 / QD-200-10、CQ-200-11；CQ-200-06 全量复验 | 四个目标源文件最终精确 Mypy 0 errors，schema metadata 与 SQLite/fake 用例通过；唯一一次全量 Mypy 观察值为 849 errors / 136 files（625 checked，在最后 JSON 注解修正前），按指示不重跑，仍 FAIL / NO-GO |
| S12 | T6：迁移仿真交易 ORM 实例字段并收紧持仓快照/事件类型合同 | T6 / QD-200-11、CQ-200-12；CQ-200-06 全量复验 | 两个目标源文件精确 Mypy 0 errors，67 个 `Column`/`relationship` 调用参数与 HEAD 一致，服务/API 定向测试 142 passed；全量 Mypy 789 errors / 135 files，继续 FAIL / NO-GO |
| S13 | T7：迁移市场数据平台 21 表 ORM 实例字段和 25 个关系声明 | T7 / QD-200-12、CQ-200-13；CQ-200-06 全量复验 | 模型 Mypy 0，220 个列调用和 25 个关系调用与 HEAD 参数一致，`test_store.py` 47 passed；store 从 43 降为 9 个非 ORM 错误，全量 Mypy 662 errors / 129 files，继续 FAIL / NO-GO |
| S14 | T8：迁移工作空间两表 ORM 实例字段与递归 JSON 契约 | T8 / QD-200-13、CQ-200-14；CQ-200-06 全量复验 | 模型 Mypy 0，39 个列调用与 3 个关系调用和 HEAD 参数一致，mapper 2/39/3，相关测试 159 passed；全量 Mypy 625 errors / 131 files，继续 FAIL / NO-GO |
| S15 | T9：收窄工作空间 JSON 的三个直接消费者并验证有效/畸形数据路径 | T9 / QD-200-14、CQ-200-15；CQ-200-06 全量复验 | 三文件 Mypy 从 10 errors 到 0，Ruff/format/diff check 和 5 个本地 fixture 通过；全量 Mypy 615 errors / 128 files，继续 FAIL / NO-GO |
| S16 | T10：收窄市场数据查询的 delayed receipt、Store 参数与 signed cursor JSON 边界 | T10 / QD-200-15、CQ-200-16；CQ-200-06 全量复验 | `query_service.py` Mypy 从 34 errors 到 0；Ruff/format/diff check 通过，69 个本地 query-service fixture 验证 deferred fail-closed、lease release 与 signed malformed cursor；全量 Mypy 581 errors / 127 files，继续 FAIL / NO-GO |
| S17 | T11：迁移 scanner plan 两个 ORM 模型的实例字段与关系 | T11 / QD-200-16、CQ-200-17；CQ-200-06 全量复验 | 模型/服务 Mypy 从 25 errors 到 0；Ruff/format/diff check 通过，2 个 scanner-plan API fixture 与 mapper 15/17 columns、4/5 indexes、2 relationships 通过；全量 Mypy 556 errors / 126 files，继续 FAIL / NO-GO |
| S18 | T12：收窄仓位估值 `safe_float` 的 float/None fallback 类型契约 | T12 / QD-200-17、CQ-200-18；CQ-200-06 全量复验 | `position_valuation.py` Mypy 从 20 errors 到 0；Ruff/format/diff check 通过，3 个直接 helper 测试和 21 个既有估值场景通过；全量 Mypy 536 errors / 125 files，继续 FAIL / NO-GO |
| S19 | T13：收窄市场标的仓库 snapshot、Pandas 行与指标聚合类型边界 | T13 / QD-200-18、CQ-200-19；CQ-200-06 全量复验 | `market_instrument.py` Mypy 从 20 errors 到 0；Ruff/format/diff check 通过，5 个新增 fake/Pandas 测试与 15 个既有 API fixture 通过；全量 Mypy 516 errors / 124 files，继续 FAIL / NO-GO |
| S20 | T14：收窄新闻情报的可选 session、loaded ORM 标量与 feed JSON 边界 | T14 / QD-200-19、CQ-200-20；CQ-200-06 全量复验 | `news_intelligence.py` Mypy 从 18 errors 到 0；Ruff/format/diff check 通过，3 个新增 boundary 测试与 5 个既有新闻 fixture 通过；全量 Mypy 498 errors / 123 files，继续 FAIL / NO-GO |

| S21 | T15：收窄认证服务 loaded User/RefreshToken 标量视图，并使异常 logout `jti` 在仓储前失败关闭 | T15 / QD-200-20、CQ-200-21；CQ-200-06 全量复验 | `auth_service.py` Mypy 从 9 errors 到 0；Ruff/format/diff check 通过，6 个新增 token-ID 边界 fixture、18 个 refresh/JWT/auth-service fixture 和 15 个 auth API fixture 通过；全量 Mypy 489 errors / 122 files，继续 FAIL / NO-GO |

| S22 | T16：收窄 AlertRule 配置/类型边界，并让异常规则在下游指标调用前失败关闭 | T16 / QD-200-21、CQ-200-22；CQ-200-06 全量复验 | `alert_evaluation.py` Mypy 从 6 errors 到 0；Ruff/format/diff check 通过，4 个新增 boundary fixture 与 92 个既有告警/异常 fixture 通过；全量 Mypy 483 errors / 121 files，继续 FAIL / NO-GO |
| S23 | T17：为动态 `backtest_service` shim 建立静态 `BacktestService` 入口并锁定 runtime identity | T17 / QD-200-22、CQ-200-23；CQ-200-06 全量复验 | stub Mypy 为 0，runtime identity 加既有回测服务 fixture 为 46 passed、1 warning；11 条 shim `[attr-defined]` 误报消失，但静态真实合同暴露 14 条调用方错误，全量 Mypy 为 486 errors / 120 files，仍 FAIL / NO-GO |
| S24 | T18：将比较创建的回测结果验证与 payload 构造收敛为一次读取 | T18 / QD-200-23、CQ-200-24；CQ-200-06 全量复验 | 12 条 comparison `get_result()` `[union-attr]` 消失；30 项 fixture、Ruff/format/diff check 通过；全量 Mypy 474 errors / 120 files，去行号差分无其他诊断变化，仍 FAIL / NO-GO |
| S25 | T19：统一参数优化初始/轮询 FAILED 的回测结果错误边界 | T19 / QD-200-24、CQ-200-25；CQ-200-06 全量复验 | 1 条 param optimization `get_result()` `[union-attr]` 消失；48 项优化 API fixture、Ruff/format/diff check 通过；全量 Mypy 473 errors / 120 files，去行号差分无其他诊断变化，仍 FAIL / NO-GO |
| S26 | T20：为动态 `strategy_service` shim 建立 8 名称静态入口并锁定 module/export identity | T20 / QD-200-25、CQ-200-26；CQ-200-06 全量复验 | stub/core Mypy 为 0，9 项 shim/策略扫描 fixture、Ruff/format/diff check 通过；20 条 shim `[attr-defined]` 误报消失，标准化全量差分无新增诊断，Mypy 453 errors / 116 files，仍 FAIL / NO-GO |
| S27 | T21：在增强回测 API 的安全拒绝后显式转换为基础服务请求合同 | T21 / QD-200-26、CQ-200-27；CQ-200-06 全量复验 | 目标 Mypy 为 0，完整增强回测 fixture 52 passed，根代理新增转换/拒绝测试 2 passed、1 warning；标准化全量差分仅移除 1 条 `[arg-type]`，Mypy 452 errors / 115 files，仍 FAIL / NO-GO |
| S28 | T22：显式化月度复利与均线前置结果的数值类型 | T22 / QD-200-27、CQ-200-28；CQ-200-06 全量复验 | `analytics_service.py` Mypy 从 2 errors 到 0，22 项分析服务 fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 2 条推断错误，Mypy 450 errors / 114 files，仍 FAIL / NO-GO |
| S29 | T23：显式化日志查询参数脱敏容器的 string/list 值联合类型 | T23 / QD-200-28、CQ-200-29；CQ-200-06 全量复验 | `logging.py` Mypy 为 0，8 项日志中间件 fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条推断错误，Mypy 449 errors / 113 files，仍 FAIL / NO-GO |
| S30 | T24：显式化版本参数 diff 四分类嵌套字典的返回结构 | T24 / QD-200-29、CQ-200-30；CQ-200-06 全量复验 | `version_diff_service.py` Mypy 为 0，18 项版本 diff fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条推断错误，Mypy 448 errors / 112 files，仍 FAIL / NO-GO |
| S31 | T25：对齐监控规则可空 description 的 schema/service/model 合同 | T25 / QD-200-30、CQ-200-31；CQ-200-06 全量复验 | API Mypy 为 0，49 项监控 API fixture 覆盖省略 description 的 None/null 往返；服务文件仍有 15 条无关历史错误，标准化全量差分仅移除 1 条 API `[arg-type]`，Mypy 447 errors / 111 files，仍 FAIL / NO-GO |
| S32 | T26：保留市场数据授权 principal 的精确类型至访问上下文 | T26 / QD-200-31、CQ-200-32；CQ-200-06 全量复验 | API deps Mypy 为 0，4 项授权依赖 fixture 验证 principal identity 和 read check；标准化全量差分仅移除 1 条 access `[arg-type]`，Mypy 446 errors / 110 files，仍 FAIL / NO-GO |
| S33 | T27：收紧股票研究兼容层 legacy reconciliation payload 的局部容器类型 | T27 / QD-200-32、CQ-200-33；CQ-200-06 全量复验 | `stock_compat.py` Mypy 从 1 error 到 0，2 项 compatibility fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 append `[arg-type]`，Mypy 445 errors / 109 files，仍 FAIL / NO-GO |
| S34 | T28：修正主数据 manifest literal 表达和类别计数器键类型 | T28 / QD-200-33、CQ-200-34；CQ-200-06 全量复验 | `master_data_importer.py` Mypy 从 2 errors 到 0，8 项 importer fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 2 条 `[valid-type]`/`[arg-type]`，Mypy 443 errors / 108 files，仍 FAIL / NO-GO |
| S35 | T29：标注缓存单例与 factory 的 Redis/内存联合类型 | T29 / QD-200-34、CQ-200-35；CQ-200-06 全量复验 | `cache.py` Mypy 从 1 error 到 0，17 项 cache fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 singleton `[assignment]`，Mypy 442 errors / 107 files，仍 FAIL / NO-GO |
| S36 | T30：标注 calendar manifest 常量的固定 literal 类型 | T30 / QD-200-35、CQ-200-36；CQ-200-06 全量复验 | `calendar_importer.py` Mypy 从 1 error 到 0，13 项 calendar importer fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 default `[assignment]`，Mypy 441 errors / 106 files，仍 FAIL / NO-GO |
| S37 | T31：收紧 AkShare engine 可变 kwargs 容器的值类型 | T31 / QD-200-36、CQ-200-37；CQ-200-06 全量复验 | `akshare_data_database.py` Mypy 从 1 error 到 0；隔离 pycache 下 66 passed、79 skipped、2 warnings，Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 kwargs `[assignment]`，Mypy 440 errors / 105 files，仍 FAIL / NO-GO |
| S38 | T32：对齐 legacy evidence-gate 私有 target helper 的 Iterable 合同 | T32 / QD-200-37、CQ-200-38；CQ-200-06 全量复验 | target Mypy 从 2 errors 到 0，16 项隔离 SQLite harness、Ruff/format/diff check 通过；标准化差分移除 1 个重复两次的 `[arg-type]` 签名，Mypy 438 errors / 104 files，仍 FAIL / NO-GO |
| S39 | T33：将压力测试只读 scenarios 参数改为协变 Sequence 合同 | T33 / QD-200-38、CQ-200-39；CQ-200-06 全量复验 | service/API Mypy 为 0，5 项 stress-test fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 API `[arg-type]`，Mypy 437 errors / 103 files，仍 FAIL / NO-GO |
| S40 | T34：标注 AI 改稿 metadata 局部容器的字符串/整型值域 | T34 / QD-200-39、CQ-200-40；CQ-200-06 全量复验 | `generation.py` Mypy 从 1 error 到 0，既有 AI 改稿 fixture 断言 token 元数据，Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 `[assignment]`，Mypy 436 errors / 102 files，仍 FAIL / NO-GO |
| S41 | T35：隔离日志 fallback 可空指标序列与 TSV 指标容器 | T35 / QD-200-40、CQ-200-41；CQ-200-06 全量复验 | `log_parser_service.py` Mypy 从 4 errors 到 0，56 项日志解析 fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 4 条 fallback `[list-item]`/`[assignment]`/`[attr-defined]`/`[no-redef]`，Mypy 432 errors / 101 files，仍 FAIL / NO-GO |
| S42 | T36：把回执 SHA-256 校验声明为字符串 TypeGuard | T36 / QD-200-41、CQ-200-42；CQ-200-06 全量复验 | `filesystem_dataset_resolver.py` Mypy 从 1 error 到 0，9 项 resolver fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 compare_digest `[type-var]`，Mypy 431 errors / 100 files，仍 FAIL / NO-GO |
| S43 | T37：收窄 LLM 成对用量计数并保留失败关闭结算 | T37 / QD-200-42、CQ-200-43；CQ-200-06 全量复验 | `llm_gateway.py` Mypy 从 1 error 到 0，70 项 gateway fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 usage pair `[arg-type]`，Mypy 430 errors / 99 files，仍 FAIL / NO-GO |
| S44 | T38：在 holdout journal 写入点重复验证 lease 到期时间 | T38 / QD-200-43、CQ-200-44；CQ-200-06 全量复验 | `holdout_execution_journal.py` Mypy 从 1 error 到 0，7 项 journal fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 lease `[arg-type]`，Mypy 429 errors / 98 files，仍 FAIL / NO-GO |
| S45 | T39：单次读取并收窄 run record pipeline 字典边界 | T39 / QD-200-44、CQ-200-45；CQ-200-06 全量复验 | `run_records.py` Mypy 从 1 error 到 0，8 项直接 pipeline-shape fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 pipeline `[union-attr]`，Mypy 428 errors / 97 files，仍 FAIL / NO-GO |
| S46 | T40：显式收窄网关合约正数判定的可空值 | T40 / QD-200-45、CQ-200-46；CQ-200-06 全量复验 | `gateway/runtime.py` Mypy 从 1 error 到 0，5 项直接 spec-number fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 float `[arg-type]`，Mypy 427 errors / 96 files，仍 FAIL / NO-GO |
| S47 | T41：精确分派自定义因子一元正负操作 | T41 / QD-200-46、CQ-200-47；CQ-200-06 全量复验 | `factor_lib/custom.py` Mypy 从 1 error 到 0，9 项 factor fixture、Ruff/format/diff check 通过；标准化全量差分仅移除 1 条 unary `[operator]`，Mypy 426 errors / 95 files，仍 FAIL / NO-GO |
| S48 | T42：为动态 live trading manager shim 建立静态入口 | T42 / QD-200-47、CQ-200-48；CQ-200-06 全量复验 | stub Mypy 为 0，identity fixture 为 1 passed，11 个 importer 不再含 shim `[attr-defined]`；全量移除 15 条 shim 误报、揭露 11 条 `InstanceData`/dict 真实合同，Mypy 422 errors / 90 files，仍 FAIL / NO-GO |
| S49 | T43：将 live trading 实例记录的消费边界收紧为只读 Mapping | T43 / QD-200-48、CQ-200-49；CQ-200-06 全量复验 | 11 条 `InstanceData`/`StartResult` 到可变 dict 合同错误为 0；同根 8 条 portfolio params `[union-attr]` 一并消失，5 项根代理回归、Ruff/format/diff check 通过；Mypy 403 errors / 90 files，标准化差分无新增诊断，仍 FAIL / NO-GO |
| S50 | T44：将合约 metadata 收窄为单次读取后的浅拷贝 | T44 / QD-200-49、CQ-200-50；CQ-200-06 全量复验 | 两个重复 `dict()` `[arg-type]` 为 0，instance/spec 两条直接与 3 条相邻回归共 5 passed；Ruff/format/diff check 通过。Mypy 401 errors / 90 files，原始数减 2、标准化差分无新增，仍 FAIL / NO-GO |
| S51 | T45：隔离 position-log 不同 tuple 状态表的局部候选 | T45 / QD-200-50、CQ-200-51；CQ-200-06 全量复验 | 两端 6 条 tuple `[assignment]` 为 0，8 项既有 latest-row fixture通过；Ruff/format/diff check 通过。Mypy 395 errors / 90 files，恰减 6、标准化差分无新增，仍 FAIL / NO-GO |
| S52 | T46：收窄 portfolio 资产规格持久化的 metadata 二次读取 | T46 / QD-200-51、CQ-200-52；CQ-200-06 全量复验 | 一条 `dict()` `[arg-type]` 为 0，gateway asset-spec persistence fixture为 1 passed；Ruff/format/diff check 通过。Mypy 394 errors / 90 files，恰减 1、标准化差分无新增，仍 FAIL / NO-GO |
| S53 | T47：显式化 portfolio equity 策略序列的浮点容器 | T47 / QD-200-52、CQ-200-53；CQ-200-06 全量复验 | 两条 `[var-annotated]` 为 0；6 项既有 equity curve fixture 为 6 passed、1 条既有 warning，Ruff/format/diff check 通过。Mypy 392 errors / 90 files，恰减 2、标准化差分无新增，仍 FAIL / NO-GO |
| S54 | T48：收窄两个 position-log 方向 parser 的动态数值代码转换 | T48 / QD-200-53、CQ-200-54；CQ-200-06 全量复验 | 两条 `float()` `[arg-type]` 为 0；两端 direct numeric-code/invalid-fallback/Bybit dual-side fixture 合计 6 passed、1 条既有 warning，Ruff/format/diff check 通过。Mypy 390 errors / 90 files，恰减 2、标准化差分无新增，仍 FAIL / NO-GO |
| S55 | T49：收窄 attested paper runtime anchor 的 WorkspaceJSON 读取 | T49 / QD-200-54、CQ-200-55；CQ-200-06 全量复验 | 一条 WorkspaceJSON `[assignment]` 为 0；non-Mapping anchor fail-closed/no-sync/no-manager、live risk-gate 和普通 paper-start fixture 为 3 passed、1 条既有 warning，Ruff/format/diff check 通过。Mypy 389 errors / 90 files，恰减 1、标准化差分无新增，仍 FAIL / NO-GO |
| S56 | T50：收窄 portfolio `_first_number()` 的候选数值协议 | T50 / QD-200-55、CQ-200-56；CQ-200-06 全量复验 | 目标 `float()` `[arg-type]` 消失且目标文件 Mypy 为 0；三项直接 fixture 与既有 portfolio fixture 129 passed、1 条既有 warning，Ruff/format/diff check 通过；完整 Mypy 388 errors / 89 files，恰减 1 条与 1 个报错文件，继续 FAIL / NO-GO |
| S57 | T51：迁移 alerts 三模型 ORM 实例字段并清除 monitoring 服务挂账错误 | T51 / QD-200-56、CQ-200-57；CQ-200-06 全量复验 | 两文件精确 Mypy 为 0，AST 对比 59 声明零差异，mapper 3 tables（26/15/8 列）；定向测试 198 passed、7 条既有 warning；完整 Mypy 373 errors / 88 files，标准化差分恰移除 15 条、新增 0，继续 FAIL / NO-GO |
| S58 | T52：迁移 comparison 两模型并清除比较服务 T18 挂账错误 | T52 / QD-200-57、CQ-200-58；CQ-200-06 全量复验 | 两文件精确 Mypy 为 0，AST 对比 21 声明零差异，mapper 11/5 列含时间戳 nullable 核验；定向测试 84 passed；完整 Mypy 355 errors / 87 files，标准化差分恰移除 18 条、新增 0，继续 FAIL / NO-GO |
| S59 | T53：迁移 akshare_mgmt 七模型并清除脚本/执行/调度/表 API 与 registry 连带错误 | T53 / QD-200-58、CQ-200-59；CQ-200-06 全量复验 | 五文件精确 Mypy 为 0，AST 对比 114 声明零差异，mapper 7 tables/105 列/9 关系含 Enum/nullable 探针；定向测试 178 passed、79 skipped（既有）；完整 Mypy 323 errors / 82 files，移除 32 条（30 预期 + registry 2 条同根因连带）、新增 0，继续 FAIL / NO-GO |
| S60 | T54：修正 live trading 执行器异步上下文与动态属性边界 | T54 / QD-200-59、CQ-200-60；CQ-200-06 全量复验 | 目标文件精确 Mypy 为 0；live_trading 定向测试 208 passed、1 条既有 warning；Ruff/format/diff check 通过；完整 Mypy 307 errors / 81 files，error 级差分恰移除 16 条、新增 0，继续 FAIL / NO-GO |
| S61 | T55：迁移 data_governance 八模型并清除连接器注册表及 store/bootstrap/quant 连带错误 | T55 / QD-200-60、CQ-200-61；CQ-200-06 全量复验 | 模型与 registry 精确 Mypy 为 0，AST 对比 91 声明零差异，mapper 8 tables/78 列含时间戳探针；定向测试 148 passed、20 条既有 warning；完整 Mypy 287 errors / 79 files，error 级差分恰移除 20 条、新增 0，继续 FAIL / NO-GO |
| S62 | T56：清除市场数据存储 T7 挂账非 ORM 边界错误 | T56 / QD-200-61、CQ-200-62；CQ-200-06 全量复验 | 目标文件精确 Mypy 为 0；market_data_platform 全套 1254 passed、137 条既有 warning；Ruff/format/diff check 通过；完整 Mypy 279 errors / 78 files，error 级差分恰移除 8 条、新增 0，继续 FAIL / NO-GO |
| S63 | T57：清除 db 基础设施泛型仓库与引擎边界错误 | T57 / QD-200-62、CQ-200-63；CQ-200-06 全量复验 | 两文件精确 Mypy 为 0，泛型实例化探针兼容；db 影响面回归 147 passed；完整 Mypy 260 errors / 76 files，error 级差分恰移除 19 条、新增 0，继续 FAIL / NO-GO |
| S64 | T58：清除 discovery 试验物化发布的三处可空边界 | T58 / QD-200-63、CQ-200-64；CQ-200-06 全量复验 | 目标文件精确 Mypy 为 0；定向测试 22 passed、1 条既有 warning；完整 Mypy 247 errors / 75 files，error 级差分恰移除 13 条、新增 0，继续 FAIL / NO-GO |
| S65 | T59：补完 knowledge_base 七模型迁移并清除 reqdocs 与 rag 连带错误 | T59 / QD-200-64、CQ-200-65；CQ-200-06 全量复验 | 模型与 reqdocs 精确 Mypy 为 0，AST 零差异；定向测试 44 passed；完整 Mypy 234 errors / 73 files，error 级差分恰移除 13 条、新增 0，继续 FAIL / NO-GO |
| S66 | T60：清除 live trading 管理器动态边界与回调合同错误 | T60 / QD-200-65、CQ-200-66；CQ-200-06 全量复验 | 目标文件精确 Mypy 为 0；live_trading 定向测试 151 passed、1 条既有 warning；完整 Mypy 226 errors / 72 files，error 级差分恰移除 8 条、新增 0，继续 FAIL / NO-GO |
| S67 | T61：清除 fetch lease 与 publication 的游标/时钟/动态模型边界错误 | T61 / QD-200-66、CQ-200-67；CQ-200-06 全量复验 | 两文件精确 Mypy 为 0；定向测试 141 passed、1 条既有 warning；完整 Mypy 214 errors / 70 files，error 级差分恰移除 12 条、新增 0，继续 FAIL / NO-GO |
| S68 | T62：修复最终四处动态 facade 可调用类型边界，并重新执行冻结缓存全量 Mypy | T62 / QD-200-01、CQ-200-06 | `trading_workspace_service.py` 改为从具名资产实现模块导入 helper；145 项回归、目标 Ruff/format/Mypy 通过；全量 `mypy app` 为 0 errors / 625 source files，静态门禁 PASS。 |
| S69 | T63：复审后修复订单/工作空间数值边界与 THS dry-run/保存点事务缺口，并重新执行完整验证 | T63 / QD-200-01、CQ-200-06 | 484 项合并 fixture 通过；17 个文件 Ruff/format 通过；新隔离缓存全量 `mypy app` 为 0 errors / 625 source files。 |
| S70 | T64：将已归零的全量 Mypy 结果写入 CI ratchet，并校正历史状态说明 | T64 / QD-200-01、CQ-200-06 | base Conda 上使用临时 PYTHONPATH 运行与 CI 锁定版本相同的 Mypy 1.20.2，新隔离缓存全量检查为 0/625；guarded baseline update 将 `baseline_errors` 设为 0；本地常规 ratchet 输出 `errors=0 baseline=0 delta=+0`。 |
| S71 | T65：升级并重建可审计 Python dev/prod lock，保留 Python 3.10 AkShare 兼容解析 | T65 / QD-200-03 | canonical lock 同步与 registry `pip-audit` 通过；Git 来源依赖的 advisory 覆盖边界明确保留。 |
| S72 | T66：建立前端 entry、路由闭包和初始 JS bundle 硬预算，并验证异步模块回退 | T66 / QD-200-04 | manifest gate、Node 20/24 构建及关联异步边界测试通过；浏览器网络与真实首屏验证保持 NOT_RUN。 |
| S73 | T67：收紧前端 lint 并以受保护基线维护源码尺寸棘轮 | T67 / QD-200-70 | `npm run lint -- --max-warnings 0`、生产构建、Node helper 与普通尺寸门禁通过；大型编排器结构债务转入 Iteration 201。 |
| S74 | T68：关闭响应缓存租户隔离和本地测试运行时不确定性 | T68 / QD-200-67、QD-200-68（QD-200-72 为运营残余） | ASGI 缓存隔离、测试运行时修复、全量 Mypy/ratchet 与本地非性能回归通过；共享 Redis 发布 runbook 保持 NOT_RUN。 |
| S75 | T69：在 canonical dev lock 中重验 Mypy，统一告警 wire value，并收口 lint 格式化引起的尺寸冲突 | T69 / QD-200-69、QD-200-70、CQ-200-68 至 CQ-200-70 | 170 个锁定包一致、全量 630/0、四个 CI scope 0 errors、监控/告警 204 passed（含有效 webhook 缺失 `created_at` 的安全投影）、Node helper 17/17、最终后端非性能回归 `7864 passed, 123 skipped, 24 deselected`；远端 CI、浏览器 E2E、真实外部系统和共享 Redis 发布仍为 NOT_RUN。 |

## T62 最终门禁收敛（2026-09-22）

T62 只收敛最后四条 `Any? not callable`：将 `query_local_asset_spec`、`persist_asset_specs` 和 `normalize_gateway_position` 从动态兼容 facade 改为从其实际定义模块显式导入，保留其余兼容 facade helper 和全部调用语义。先运行 145 项工作空间服务 fixture、目标 Mypy、Ruff check/format 和 diff whitespace 检查；随后在新的隔离 Mypy 缓存中运行完整 `mypy app --show-error-codes`，625 个源文件零错误。此步骤关闭静态质量门禁，不修改 Mypy/Ruff 配置，不新增忽略或豁免。

本计划的静态门禁完成不等同发布验收：全量后端 pytest、真实数据库、网络、行情、供应商和交易系统未运行；依赖审计与前端 bundle 债务保持在台账中。

## T63 复审修复与最终重验（2026-09-22）

只读复审发现：方向码 `int(float(...))` 对无穷值会越过预期拒绝路径；工作空间的 `dict(instance)` 会丢失 `persist_asset_specs` 对原 manager instance 的内存更新；THS CLI 的默认 dry-run 仍使用 runner 默认批量 commit；逐标的失败会回滚整个外层事务但继续累加成功计数。T63 以既有有限数值 helper、原 dict 透传、dry-run 的 `commit_every=None`、每标的已启动 savepoint 和 SQLite 物理外层事务守卫分别收敛，正常 0/1/2/3 方向码及显式 apply 的 200/100 批量提交语义保持。

根代理执行 484 项跨模块 fixture，结果 `484 passed, 1 warning`；17 个相关文件 Ruff check/format 均通过。新的隔离 Mypy 缓存再次扫描 625 个源文件并以 0 errors 通过。真实生产数据库、网络、行情、供应商及交易系统、全量后端 pytest 均未运行。

## T64 CI Mypy ratchet 基线收敛（2026-09-22）

T64 历史验收使用 base Conda 与 `/tmp/iter200-mypy-1202.nKPLri` 临时包目录提供的 CI 固定 Mypy 1.20.2（`mypy 1.20.2 (compiled: yes)`），不是 base 自带的 Mypy 1.16.1。执行全量检查时使用新缓存 `/tmp/iter200-mypy-1202-cache.Puw5hr`，输出 `Success: no issues found in 625 source files`。随后以同一 `PYTHONPATH` 执行 `ALLOW_BASELINE_UPDATE=1 ... python scripts/ci/mypy_ratchet.py --update`，受保护脚本输出 `baseline updated -> 0 errors (mypy 1.20.2 (compiled: yes))`；未带 `--update` 的实际 ratchet 输出 `errors=0 baseline=0 delta=+0`。T68 在新的临时 target/cache 以同一版本复验 `Success: no issues found in 630 source files` 和 `errors=0 baseline=0 delta=+0`，并完成 `7859 passed, 123 skipped, 24 deselected` 的本地非性能后端回归且无 warning summary。仓库没有 mypy ratchet 的合成错误回归测试，因此按项目已有机制验证实际 ratchet。`src/backend/3.10/` 缓存原样保留，仅新增精确 ignore。此本地静态门禁验证不构成生产或外部系统验收。

## 变更边界

修改限制在需求列明的后端源文件、直接相关测试、三个 Ruff 格式目标、前端 package.json/package-lock.json，以及本迭代文档。T4 另严格限定为三个 AkShare consumer/provider/proxy 源文件、直接 fake 测试与文档。不得提交、推送或暂存文件；不得修改静态检查配置；如遇与本范围无关的既有失败，仅记录，不扩张修复范围。

T5 范围仅为 `app/models/stock_analysis.py`、`app/models/stock_signal.py`、`app/services/stock_analysis/tasks.py`、直接相关股票分析/信号测试及本迭代文档。经父代理明确批准，最小扩展为仅修改 `app/models/knowledge_base.py` 的 `ChatMessage.metadata_json` ORM 注解；禁止改同模型其他字段、其他知识库模型、迁移、调用方、DB 核心和配置。保持所有 ORM schema 和任务运行时语义。

CQ-200-07 仅允许新增 jsdom 开发依赖，并在四个指定测试文件使用 file-level 环境标记。生产 DOMPurify、marked、Markdown 清洗代码和 Vitest 全局环境均保持原状；不跳过失败测试。

CQ-200-08 仅修改 StrategyDetailDialog 测试中的模块级 MonacoEditor mock，替代因执行时序过晚而无效的 mount-level stub。保持 file-level jsdom、通用 Element stubs 和生产模块不变；不在 shared setup 加 polyfill，不修改 package dependencies/lock，不提交、推送或暂存文件。

## T14 新闻情报 session 与 feed 元数据类型批次（2026-09-20）

范围仅为 `src/backend/app/services/news_intelligence.py`、新增 `src/backend/tests/test_news_intelligence_type_boundaries.py` 与迭代文档。构造函数、公开 `db` 属性和 factory 仍支持 optional session；持久化路径经 `_require_db() -> AsyncSession` 取得局部非空 session，保留无 session 时的 `RuntimeError("database_session_required")`。由于这会显露 legacy NewsSourceModel 的 loaded-instance Column 误推断，服务内仅以窄 Protocol/cast 描述已加载实例的实际标量字段；不迁移模型、不改 SQL、API、依赖或静态规则。

feed 解析只在 metadata 为 Mapping 时读取 `tickers`，其他 JSON 形状安全退化为空默认 ticker；可迭代 ticker 的逐项字符串清理保持。精确 Mypy 从 18 errors 到 0；目标 Ruff check/format、tracked/untracked whitespace 检查和 diff suppression 扫描通过。3 个新增边界测试与 5 个既有新闻 API/classifier fixture 为 8 passed、1 条既有 Backtrader Quandl deprecation warning；全部使用 fake HTTP、未持久化 ORM instance 或本地 fixture。随后全量 `mypy app` 为 498 errors / 123 files（625 checked，退出码 1），较 T13 减少 18 条错误、1 个报错文件；完整门禁仍 FAIL / NO-GO，未连接真实数据库、网络或交易系统。

## T15：认证服务 ORM 标量与 logout token ID 批次（2026-09-20）

范围仅为 `app/services/auth_service.py`、新增 `tests/test_auth_service_type_boundaries.py` 与本迭代文档。未迁移 `User` 或 `RefreshToken` 模型，未修改 SQL query、事务、JWT payload、路由、配置、依赖、迁移或数据库 schema。两个局部 Protocol 只描述仓储/SQLAlchemy 已返回实例的实际 scalar 字段；所有 `cast` 均处于 loaded-instance 边界，密码变更和 token 撤销仍写回原 ORM instance，并沿用既有 session flush/commit 路径。

`logout` 在解码 refresh payload 后，仅当 `jti` 为非空 `str` 才调用 `revoke_refresh_token`；缺失、`None`、数值、空字符串和 list 均在仓储调用前返回 `False`。新增无数据库 fixture 覆盖这些失败关闭情况和有效字符串撤销路径。精确 Mypy 从 9 errors 到 0；Ruff check/format、tracked `git diff --check`、untracked test whitespace check 和新增 diff 抑制扫描通过。根代理独立复验新增边界、auth-service、refresh-token 和 JWT fixture 共 24 passed、1 条既有 Backtrader Quandl deprecation warning；`tests/test_auth.py` 另为 15 passed、7 条既有 warning（同一 Quandl 以及 Starlette 422 常量弃用）。未连接真实数据库、网络或交易系统。

T15 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 489 errors in 122 files (checked 625 source files)`。相较 T14 减少 9 errors、1 个报错文件；目标 `app/services/auth_service.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T61：fetch lease 与 publication 游标/时钟/动态模型边界批次（2026-09-21）

范围仅为 `src/backend/app/services/market_data/fetch_lease.py`、`app/services/market_data/publication.py` 与本迭代文档。六处 rowcount 经各文件单点 `_cursor_rowcount` helper（T57 同款，`Result[tuple[object, ...]]` 参数无 Any）；fetch lease 时钟 None 早退与原 `_stored_utc` ValueError→同码路径等价；publication 的 `found` 以 `{row[0]: row[1] for row in ...}` 重建（二元 Row 为 tuple 子类，与 `dict(rows)` 运行时等价）、`model.__dict__["id"]` 直接映射（T57 模式）、B2 可空哈希清单按 T56 同款先 None 抛 `B2_COMPLETENESS_RECEIPT_INVALID` 经既有 except 归一。没有改 lease 状态机、发布事务顺序、完整性校验语义、schema、API、配置、依赖或静态检查设置。

根代理复验：两文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。定向测试五文件（test_fetch_lease、test_publication_recovery、test_deferred_publication、test_multi_record_evidence、test_store + test_query_service）141 passed、1 条既有 Backtrader Quandl warning。完整 `mypy app` 为 214 errors / 70 files（625 checked、退出码 1）：error 级标准化差分恰移除 12 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T60：live trading 管理器动态边界与回调合同批次（2026-09-21）

范围仅为 `src/backend/app/services/live_trading/manager.py` 与本迭代文档。四处修复：三处二次 `get` 改单次局部读取（instance params、workspace_unit、contract_metadata，运行时等价）；`RuntimeError` 的动态 `open_order_cancel` 属性改 `__dict__` 直写（仓内无读取方、属性保留以防外部消费者，与 T54 读取侧 `__dict__` 模式对称）；server-attested 私有字段的 pop 从 `StartResult`（TypedDict）移至既有 `cast(StartResult, ...)` 之前的原始 dict——TypedDict 不可赋给可变 dict 类型，pop 位置前移作用于同一 dict、异常路径（finally 清理独立）与返回身份完全等价，未新增 cast；两个批量回调变量以 `Callable[[str], Awaitable[StartResult|StopResult]]` 显式注解，绑定方法与包装函数均满足窄合同。没有改启动/停止流程、server-attested 清理时序、schema、API、配置、依赖或静态检查设置。

根代理复验：目标文件精确 Mypy 为 0；Ruff check/format（含 I001 自动整理 import 顺序）与 tracked `git diff --check` 通过，新增行零 `Any`/`type: ignore`/`# noqa`（唯一 cast 命中为既有 cast 的等价重排：cast 目标从 await 表达式改为结果变量）。live_trading 定向测试四文件（manager、manager_runtime_shim、service、api）151 passed、1 条既有 Backtrader Quandl warning。完整 `mypy app` 为 226 errors / 72 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T59：知识库 ORM 补完迁移与 reqdocs 导入边界批次（2026-09-21）

范围仅为 `src/backend/app/models/knowledge_base.py`、`src/backend/app/services/reqdocs_migration_service.py` 与本迭代文档；`rag_service.py` 的 4 条为模型迁移同根因连带消除，未改该文件。七模型剩余 legacy 列全部迁移为精确映射：时间戳按 T8/T51 先例 `Mapped[datetime | None]`（baseline 的 knowledge_bases 等表时间戳列均无 nullable=False），JSON 字段沿用 `dict[str, object] | None` 先例与递归 `JSONValue`，T5 既有 `settings: dict[str, Any]` 与 `metadata_json` 注解原样保留。reqdocs 的六个 dict comprehension 改单次读取循环（等价：isinstance 与非 None 条目保持，int() 转换同一值），ChatMessage 块以独立 `message_entity` 变量与 KBDocument 块分离。没有改导入/合并语义、幂等键、schema、API、配置、依赖或静态检查设置。

根代理复验：模型与 reqdocs 精确 Mypy 为 0；AST 归一化对比声明零差异；定向测试（test_iteration129_reqdocs_migration_service、test_iteration129_knowledge_base_api、test_knowledge_base_api）44 passed、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `cast`/`type: ignore`/`# noqa`（`typing.Any` 为既有 import 保留）。完整 `mypy app` 为 234 errors / 73 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条（reqdocs 9 + rag_service 4 连带）、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T58：discovery 试验物化发布可空边界批次（2026-09-21）

范围仅为 `src/backend/app/services/research/discovery_trial_materialization.py` 与本迭代文档。三处可空边界按相邻既有错误码显式失败关闭：两处 `journal.result_json` None 先行抛 `DISCOVERY_EXECUTION_RESULT_INVALID`（与 `DiscoveryExecutionResult.from_mapping` 对无效 payload 的既有拒绝路径完全等价，仅将同一失败提前到调用边界）；quota 行缺失抛 `DISCOVERY_PUBLICATION_QUOTA_DENIED`（与同一 if 块十项校验共享错误码，原路径为 AttributeError 崩溃）；dataset 快照缺失抛 `DISCOVERY_PUBLICATION_CANDIDATE_DENIED`（候选证据链不完整）。没有改物化/发布流程、候选完整性校验、配额结算语义、schema、API、配置、依赖或静态检查设置。

根代理复验：目标文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。定向测试 `test_ai_research_discovery_trial_materialization.py` 22 passed、1 条既有 Backtrader Quandl warning。完整 `mypy app` 为 247 errors / 75 files（625 checked、退出码 1）：error 级标准化差分恰移除 13 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T57：db 基础设施泛型仓库与引擎边界批次（2026-09-21）

范围仅为 `src/backend/app/db/sql_repository.py`、`src/backend/app/db/database.py` 与本迭代文档。`sql_repository.py`：四处 `Result.rowcount` 经单点 `_cursor_rowcount` helper 以 `CursorResult` isinstance 收窄（运行时 DML 结果恒 CursorResult，rowcount 为 None/不可用时归 0 与原 `or 0`/`if not` 语义等价）；七处 `type[T].id` 收敛到单点 `_id_column()` 的 `__dict__` 直接映射访问——Protocol bound 方案（`ColumnElement[str]` 与 `Mapped[str] | Mapped[int]` 两种声明）经探针证实均被拒绝（前者把类属性当实例属性、后者被 mutable 协议成员不变式拒绝），`getattr` 常量形态被 Ruff B009 既有门禁拒绝；`type[T]` 保持无 bound，`SQLRepository[AlertRule]`/`[Comparison]`/`[DataScript]` 实例化探针通过。`database.py`：`extra_kwargs` 按 T31 先例注解 `dict[str, object]`；六处 `__table__.create` 收敛到单点 `_create_table_if_missing`（FromClause 静态宽类型运行时恒 Table）；`get_db` 注解修正为 `AsyncGenerator[AsyncSession, None]`（async generator 既有形态）。没有改仓库语义、DML 行为、建表流程、会话生命周期、schema、API、配置、依赖或静态检查设置。

根代理复验：两文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。db 影响面回归（test_monitoring_api、test_comparison_api、test_auth、test_exceptions_and_alerts、test_auth_service_extra、test_refresh_token）147 passed、既有 warnings。完整 `mypy app` 为 260 errors / 76 files（625 checked、退出码 1）：error 级标准化差分恰移除 19 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T56：市场数据存储 T7 挂账非 ORM 边界批次（2026-09-21）

范围仅为 `src/backend/app/services/market_data/store.py` 与本迭代文档。七处修复：B2 完整性证据可空哈希清单断言前 None 失败关闭（`B2_COMPLETENESS_RECEIPT_INVALID`，经既有 except 归一 `B2_COMPLETENESS_EVIDENCE_INTEGRITY`）；`source_observed_at` None 早退与 `_stored_utc` 内部行为完全等价（同码 `LOCAL_OBSERVATION_INTEGRITY`）；`publication.visibility_sequence` None 改为显式 `DEFERRED_LEGACY_IMPORT_PUBLICATION_INTEGRITY` 失败关闭（行为收紧：原路径把 None 放入 receipt）；registry 授权断言的 `allowed_uses`/`jurisdictions` 非容器值改为显式 `SOURCE_AUTHORIZATION_INVALID`（行为收紧：原路径迭代 object 必然 TypeError）；semantic record key 的 `dimensions` 非 Mapping 经 ValueError 走既有 `LOCAL_OBSERVATION_INTEGRITY` except 路径；shared payload 引用改单次局部读取加双非空条件；calendar 选择元组列表以显式联合注解表达。没有改 B2 证据协议、deferred legacy 发布流程、授权断言语义、semantic key 规范、calendar 组合算法、schema、API、迁移、配置、依赖或静态检查设置。

根代理复验：目标文件精确 Mypy 为 0；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。market_data_platform 全套定向测试（62 个文件）1254 passed、137 条既有 warning。完整 `mypy app` 为 279 errors / 78 files（625 checked、退出码 1）：error 级标准化差分恰移除 8 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T55：数据治理 ORM 实例字段与连接器注册表边界批次（2026-09-21）

范围仅为 `src/backend/app/models/data_governance.py`、`src/backend/app/services/data_connectors/registry.py`、`app/services/market_data/store.py` 的两处容器注解与本迭代文档。八模型 78 列 + 13 关系迁移为精确映射：时间戳保持显式 `nullable=False`、`Enum(DgJobStatus)` 无 `values_callable` 的既有存储语义经 AST 对比保持、JSON 列按 `default=dict/list` 语义、`DataTable` 跨模型关系经 `TYPE_CHECKING` 前向引用。registry.py 两处 `Row` 返回经 `tuple(row)` 适配既有 tuple 合同（调用方仅解包）；`_PROVIDER_SEEDS` 以 `dict[str, str | int]` 注解并对 `provider_id` 单次读取 isinstance 收窄。store.py 的 provenance/authorization 容器以与下游 `Mapping[str, object]` 合同一致的注解表达模型收紧暴露的自由 JSON 形态。没有改种子内容、preview/job 流程、载荷字段、schema、API、迁移、配置、依赖或静态检查设置。

根代理复验：模型与 registry 精确 Mypy 为 0（store.py 剩余为 T7 挂账非 ORM 错误）；AST 归一化对比 91 声明零差异；mapper 核验 8 tables/78 列且时间戳 nullable=False 保持。定向测试五文件（data governance compat + market_data catalog/research_binding/legacy_contract/store）合跑 148 passed、20 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。完整 `mypy app` 为 287 errors / 79 files（625 checked、退出码 1）：error 级标准化差分恰移除 20 条（registry 14、模型 2、bootstrap 2 与 quant_tools_runtime 1 连带、store 1 条暴露后修复）、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T54：live trading 执行器异步上下文与动态属性批次（2026-09-21）

范围仅为 `src/backend/app/services/live_trading/execution.py` 与本迭代文档。`_optional_lock()` 返回注解改为 `AbstractAsyncContextManager[Any]`（签名参数与 `Any` 参数化为既有形态），六处 `async with` 调用点、锁获取/释放顺序与 null 分支语义不变；三个 `_bt_*` 动态句柄写入改为 `__dict__` 直写，与 `_close_subprocess_log_handles` 读取侧的 `__dict__.get` 对称，点号赋值语义严格等价；`_merge_runtime_contract_metadata` 的二次 `get` 改单次局部读取。没有改锁语义、子进程启动/清理、contract metadata 合并、API/schema、配置、依赖或静态检查设置。

根代理复验：`async with nullcontext()` 在运行时 3.11 与 Mypy `--python-version 3.10` 探针双重验证通过（Python 3.10+ 为 `nullcontext` 实现异步协议）；目标文件精确 Mypy 为 0，Ruff check/format（含 B010）与 tracked `git diff --check` 通过。live_trading 定向测试七文件合跑 208 passed、1 条既有 Backtrader Quandl warning。完整 `mypy app` 为 307 errors / 81 files（625 checked、退出码 1）：error 级标准化差分恰移除 16 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实网关、交易、数据库、网络、行情或供应商系统。

## T53：AkShare 管理 ORM 实例字段与脚本服务边界批次（2026-09-21）

范围仅为 `src/backend/app/models/akshare_mgmt.py`、`src/backend/app/services/akshare/script.py` 与本迭代文档；execution/scheduler/api-tables 与 registry 的错误为模型迁移的同根因连带消除，未修改这些文件。七模型 105 列 + 9 关系迁移为精确映射，五个 Enum 列保持 `values_callable` 参数与 enum 类型注解、`metadata_json` 保持显式列名 "metadata"、全部显式 nullable kwarg 与关系语义不变。script.py 仅四处：timeout helper 显式属性访问 + getenv 链 `or "60"` 等价重写、`safe_defaults` 精确注解（Mypy 反向验证并揭露既有 list 值）、legacy 表名单次调用复用加双 None fail-closed 条件。

根代理复验：五文件精确 Mypy 为 0；AST 归一化对比 114 声明零差异；mapper 核验 7 tables/105 列/9 关系，Enum 类型、nullable、显式列名探针通过。akshare 定向测试六文件合跑 178 passed、79 skipped（既有）、1 条既有 warning；Ruff check/format、tracked `git diff --check` 与抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。独立审查代理复核 PASS、未发现缺陷，并证实 legacy 守卫加固的是不可达路径（`normalize_existing_table_name` 不返回空串），同时消除旧代码可能静默同步 "data" 错表的隐患。完整 `mypy app` 为 323 errors / 82 files（625 checked、退出码 1）：标准化差分移除 32 条 errors（30 预期 + registry 2 条 `DataInterface` 同根因连带）、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T52：比较 ORM 实例字段与服务容器边界批次（2026-09-21）

范围仅为 `src/backend/app/models/comparison.py`、`src/backend/app/services/comparison_service.py` 与本迭代文档。Comparison/ComparisonShare 共 16 列 + 5 关系迁移为精确映射；`backtest_task_ids: list[str]` 对齐既有 schema 合同、`comparison_data: dict[str, JSONValue]`、时间戳按 T8/T51 先例 `Mapped[datetime | None]`（baseline nullable=True 佐证）；association table 的 `Column` 保持原样。服务侧仅做容器注解（四个比较容器与各自既有 `-> dict[str, Any]` 返回签名一致，T24 先例口径）、`best_metrics: dict[str, dict[str, str | float | None]]`、`filters: dict[str, str | bool]`、`update_dict: dict[str, object]` 与 update 后 `Comparison | None` 显式守卫（原路径必然 AttributeError，改为返回 None 失败关闭）。没有改比较算法、payload 字段、schema、API、迁移、配置、依赖或静态检查设置。

根代理复验：两文件精确 Mypy 为 0；AST 归一化对比 21 声明零差异；mapper 核验 11/5 列、3/2 关系且时间戳 nullable 保持。定向测试 `test_comparison_service.py` 30 passed、`test_comparison.py` + `test_comparison_api.py` 54 passed（1 条既有 warning）；Ruff check/format、tracked `git diff --check` 通过，新增行无 `cast`/`type: ignore`/`# noqa`，新增的 4 处 `dict[str, Any]` 局部注解按 T24 先例与既有返回签名一致。完整 `mypy app` 为 355 errors / 87 files（625 checked、退出码 1）：标准化差分恰移除 comparison_service 18 条、新增 0 条；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T51：告警 ORM 实例字段与监控服务边界批次（2026-09-21）

范围仅为 `src/backend/app/models/alerts.py`、`src/backend/app/services/monitoring_service.py` 与本迭代文档。三模型 49 列与 10 个声明关系迁移为精确 SQLAlchemy 2 映射；JSON 字段用递归 `JSONValue`，外部关系目标仅经 `TYPE_CHECKING` 前向引用。服务侧仅做显式 `AlertRule | None` 守卫、两处 `filters: dict[str, str | bool]` 注解、webhook url/headers 单次读取加 str/dict 收窄，并修复模型揭露的两处真实运行时缺陷（`_send_websocket_alert` 的 str 属性 `.value` 必然 `AttributeError`、非字符串 webhook url 在 try 块外崩溃改为既有 missing-url 失败关闭）。没有改迁移、API/schema、`_safe_dict` 类 helper、调度、通知渠道语义、配置、依赖或静态检查设置。

根代理复验：两文件精确 Mypy 为 0；AST 归一化对比 HEAD/工作区 59 个列/关系调用参数零差异；运行时 mapper 核验 alerts 26 列、alert_rules 15 列、alert_notifications 8 列及全部关系 target/uselist。独立审查揭露初版将 5 个时间戳列 nullable 从 legacy 默认 True 翻转为 False（AST 不可见、mapper/baseline 可证），已按 T8 先例修正为 `Mapped[datetime | None]` 并对三处 `.isoformat()` 消费点加等价守卫；修正后全数复验通过。定向测试六个 monitoring/alert fixture 文件合跑 198 passed、7 条既有 warning；Ruff check/format、tracked `git diff --check` 与 diff 抑制扫描通过，新增行零 `Any`/`cast`/`type: ignore`/`# noqa`。完整 `mypy app` 为 373 errors / 88 files（625 checked、退出码 1）：标准化差分恰移除 monitoring_service 15 条、新增 0 条，其它 alerts 模型消费者无新增诊断；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网络、行情或交易系统。

## T50：portfolio 候选数值协议收窄批次（2026-09-21）

范围仅为 `src/backend/app/api/portfolio/api.py` 与本迭代文档。`_first_number()` 的候选局部值注解为 `object`（nested 候选为 `object | None`），新增 `_is_float_input()` TypeGuard 仅对 `float()` 既有输入协议（str/bytes/bytearray/memoryview/`SupportsFloat`/`SupportsIndex`）放行转换；非协议值继续下一候选键，与旧 `float()` TypeError 路径运行时等价，`(TypeError, ValueError)` 捕获、nested 优先级、string trim/逗号移除、NaN/Infinity 保留和全部调用方未改。直接 fixture 由本工作区已建立的三项 `_first_number` 回归承担（nested numeric text/trim/逗号、invalid-first-key 到 next-key fallback、Decimal 数值协议与 NaN/bytearray），本批未修改测试模块。

根代理复验目标文件精确 Mypy 为 0；完整 `tests/test_portfolio_api.py` 为 129 passed、1 条既有 Backtrader Quandl deprecation warning；Ruff check/format、tracked `git diff --check` 与 diff 抑制扫描通过（新增 hunk 无 `Any`、`cast`、`type: ignore`、`# noqa`；累计差异唯一 `Any` 命中仍为 T43 已有的 `_runtime_config_for_instance()` 返回注解）。完整 `mypy app` 为 388 errors / 89 files（625 checked、退出码 1）：较 T49 的 389/90 恰减 1 条错误、1 个报错文件，`api/portfolio/api.py`（T49 清单中该文件唯一错误即本批目标）退出完整清单；全量门禁继续 FAIL / NO-GO，未连接真实数据库、网关、交易、网络、行情或供应商系统。

## T43：live trading 实例只读 Mapping 边界批次（2026-09-21）

范围仅为 `app/api/portfolio/api.py`、`app/services/trading_workspace_service.py`、`tests/test_portfolio_api.py`、`tests/test_trading_workspace_service.py` 与本迭代文档。两个模块以 `Mapping[str, object]` 表达 manager 记录的只读消费：portfolio 的 list/source/batch lookup 和 workspace 的 snapshot、metadata、asset-spec、gateway-position helper 全部保留原有 `get()` 读取；`persist_asset_specs()` 的唯一可变兼容调用改为局部 `dict(instance)` 浅拷贝。没有修改 runtime shim/sibling stub、canonical manager、`InstanceData`/`StartResult` 定义、asset-info persistence、API/schema、模型、迁移、配置或依赖。

`start_units()` 在既有三分支汇合前显式声明 `started: Mapping[str, object]`，故已运行/刷新实例和声明为 `StartResult` 的普通启动结果均按原有顺序进入 metadata sync、可选 gateway asset-spec、snapshot 和 run-count 路径，不新增 manager 读取或网关调用。portfolio 对动态 `params` 只读取一次后执行既有 dict gate；合法记录行为不变，非字符串 strategy id 在原有 strategy-dir fallback 处安全返回空 log/config。

根代理独立复验：目标两文件直接 Mypy 仍有 15 条先存非 T43 错误，但 T42 指定的 11 条精确错误为 0；5 项直接/相邻 pytest 通过（1 条既有 Backtrader Quandl deprecation warning），覆盖 TypedDict/bare-dict 批量 lookup、最小 StartResult snapshot、already-running、runtime contract sync 和 persistence。Ruff check/format、target diff whitespace 和新增 suppression 扫描通过；没有新增 `Any`（diff 中保留的 `_runtime_config_for_instance` 返回 `dict[str, Any]` 为已有注解）、`cast`、`type: ignore` 或 `# noqa`。

完整 `mypy app` 为 403 errors / 90 files（625 checked，退出码 1），从 T42 的 422 原始错误数净减 19：11 条 QD-200-48 合同错误及 8 条同根 `params` `[union-attr]` 消失。标准化清单差分没有新增诊断；QD-200-01 继续 FAIL / NO-GO，未连接真实 manager、网关、交易、数据库、网络、行情或供应商系统。

## T42：动态 live trading manager shim 静态入口批次（2026-09-21）

范围仅为新增 `app/services/live_trading_manager.pyi`、新增 `tests/test_live_trading_manager_runtime_shim.py` 与本迭代文档。stub 只从 canonical `app.services.live_trading.manager` 转发 `LiveTradingManager` 与 `get_live_trading_manager`；运行时 `.py` shim、canonical manager、调用方、singleton 和网关/交易行为均未改。

stub 精确 Mypy 为 0，identity fixture 为 1 passed、1 条既有 Backtrader Quandl deprecation warning；根代理另以原始 import 复验 legacy module/class/factory 皆与 canonical 同一对象。11 个直接 importer 的 Mypy 仍有 47 条其他历史错误/6 文件，但不再有 legacy shim 的属性误报或新 factory/class 调用签名错误。全量 `mypy app` 为 422 errors / 90 files（625 checked，退出码 1）：15 条 shim `[attr-defined]` 移除，静态真相同时揭露 11 条 `InstanceData | None` 传给 dict 接口的真实错误（`api/portfolio/api.py` 1 条、`trading_workspace_service.py` 10 条）。继续 FAIL / NO-GO。

## T41：自定义因子一元正负精确分派批次（2026-09-21）

范围仅为 `app/services/factor_lib/custom.py`、`tests/test_factor_correlation.py` 与本迭代文档。evaluator 在已进入 `ast.UnaryOp` 分支后，仅对既有允许的 `ast.UAdd` 和 `ast.USub` 分别调用 `operator.pos` / `operator.neg`；validator、allowlist 和其他 AST 节点不变。算术、缺值 record 降级和 unsafe expression 的结果均未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下完整 factor fixture 为 9 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 426 errors / 95 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[operator]`，继续 FAIL / NO-GO。

## T40：网关合约正数判定可空值批次（2026-09-21）

范围仅为 `app/services/gateway/runtime.py`、新增 `tests/test_gateway_runtime_contracts.py` 与本迭代文档。`_positive_spec_number()` 以显式 `value is None` 跳过空值，再沿用既有空字符串跳过和转换异常回退。contract/margin key 顺序、零/负数拒绝、后续正数 fallback、spec 选择和 gateway runtime 行为均未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下直接参数化 fixture 为 5 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 427 errors / 96 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[arg-type]`，继续 FAIL / NO-GO。

## T39：run record pipeline 单次读取批次（2026-09-21）

范围仅为 `app/services/research/run_records.py`、新增 `tests/test_ai_research_run_records.py` 与本迭代文档。helper 先把 `raw.get("pipeline")` 保存为局部值；仅在该值是字典时读取 `current_stage`，其余形状使用既有空字典 fallback。`force`、过期状态、ready 与 live candidate 的短路判定、持久化与 run record 行为均未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下直接参数化 fixture 为 8 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 428 errors / 97 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[union-attr]`，继续 FAIL / NO-GO。

## T38：holdout journal lease 到期时间失败关闭批次（2026-09-21）

范围仅为 `app/services/research/holdout_execution_journal.py` 与本迭代文档。`prepare()` 只将 live binding 的 `lease_expires_at` 保存到局部变量；为空仍以 `HOLDOUT_EXECUTION_PREPARE_DENIED` 拒绝，非空才传给 `_as_utc`。状态机、lease 比较、幂等性、journal 写入、evaluator 和业务行为未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下完整 journal fixture 为 7 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 429 errors / 98 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[arg-type]`，继续 FAIL / NO-GO。

## T37：LLM 成对用量 TypeGuard 批次（2026-09-21）

范围仅为 `app/services/research/llm_gateway.py` 与本迭代文档。只以 `_is_non_negative_token_count(value: object) -> TypeGuard[int]` 表达已有 strict builtin-int/nonnegative 判断，并将 pair 的 tuple/sum 改为命名值校验后直接求和；bool、负数、缺项、总量不一致继续失败关闭，quota settlement、审计、redaction 和业务行为未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下完整 gateway fixture 为 70 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过；源文件的 `Any` 出现次数前后均为 26。全量 `mypy app` 为 430 errors / 99 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[arg-type]`，继续 FAIL / NO-GO。

## T36：文件系统回执 SHA-256 TypeGuard 批次（2026-09-21）

范围仅为 `app/services/research/filesystem_dataset_resolver.py`、`tests/test_ai_research_filesystem_dataset_resolver.py` 与本迭代文档。只将 `_valid_sha256(value: object)` 的返回声明为 `TypeGuard[str]`，并新增 non-string receipt_hash public resolve 失败关闭 fixture；运行时字符串/规范 hash 检查、schema、canonical hash、constant-time compare、根目录/权限/文件描述符信任边界和业务行为未改。

精确 Mypy 为 0；根代理独立完整 resolver fixture 为 9 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过；源文件的 `Any` 出现次数前后均为 9。全量 `mypy app` 为 431 errors / 100 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[type-var]`，继续 FAIL / NO-GO。

## T35：日志 fallback 指标可空序列批次（2026-09-21）

范围仅为 `app/services/log_parser_service.py`、`tests/test_log_parser.py` 与本迭代文档。只将 no-data.log fallback 的 indicators 改名为 `bar_indicators: dict[str, list[float | None]]`，并使该分支内部使用 bar_values；日期优先/索引回退、None 补齐、JSON/pipe 解析、OHLCV/volume、TSV 分支和业务行为未改。

精确 Mypy 为 0；根代理独立隔离 pycache 下完整三文件日志解析 fixture 为 56 passed、2 条既有 warnings（Backtrader Quandl deprecation、全 NaN drawdown RuntimeWarning），Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 432 errors / 101 files（625 checked，退出码 1）；标准化差分仅移除该 4 条错误，继续 FAIL / NO-GO。

## T34：AI 策略改稿 metadata 异构值容器批次（2026-09-21）

范围仅为 `app/services/research/generation.py` 与本迭代文档。只将 `_merge_ai_improvement()` 的 metadata 局部变量标注为 `dict[str, object]`；source、provider、model_id 字符串和可选 total_tokens int 的既有写入、策略改稿、代码/参数校验、回退和业务行为未改。

精确 Mypy 为 0；根代理独立既有 AI 改稿回归节点为 1 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 436 errors / 102 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 `[assignment]`，继续 FAIL / NO-GO。

## T33：压力测试 scenarios 协变 Sequence 合同批次（2026-09-21）

范围仅为 `app/services/risk_analytics/stress_test.py` 与本迭代文档。只将 run_scenarios 和 _normalize_scenarios 的 scenarios 类型从 list 改为 `Sequence[dict | StressScenario]`；API/schema、built-in scenarios、dict 归一化、equity 指标计算、输出和业务行为未改。

service/API 联合精确 Mypy 为 0；根代理独立完整 stress-test fixture 为 5 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 437 errors / 103 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 API `[arg-type]`，继续 FAIL / NO-GO。

## T32：legacy evidence-gate target Iterable 合同批次（2026-09-21）

范围仅为 `app/services/market_data/legacy_stock_daily_evidence_gate_adapter.py` 与本迭代文档。只将只遍历 targets 的私有 helper 参数从 `Sequence` 改为 `Iterable`，并补入相应 import；source binding、fail-closed 错误、read/source-batch/permit 顺序、store 和业务行为未改。

精确 Mypy 为 0；根代理以隔离 `PYTHONPYCACHEPREFIX` 独立完整 legacy import adapter harness 为 16 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 438 errors / 104 files（625 checked，退出码 1）；两处同文本诊断在去行号标准化后合并为 1 个移除签名，实际 errors 减少 2 条，继续 FAIL / NO-GO。

## T31：AkShare engine kwargs 异构值容器批次（2026-09-21）

范围仅为 `app/db/akshare_data_database.py` 与本迭代文档。只将 `extra_kwargs` 标注为 `dict[str, object]`，保留 MySQL 的 `poolclass=NullPool` 和非 MySQL 的 `pool_pre_ping=True` 两个互斥分支；URL 解析、engine/sessionmaker singleton、连接和业务行为未改。

精确 Mypy 为 0，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。默认 bytecode cache 的首次完整测试受旧 `co_filename` 指向已不存在 `/private/tmp/ai-for-investor-final.E0zN2K` 影响，出现 141 个 fixture setup errors；未改或删除该缓存。新建隔离 `PYTHONPYCACHEPREFIX` 后，根代理独立完整 management API fixture 为 66 passed、79 skipped、2 warnings（Quandl deprecation 与 pytest-rerunfailures thread warning）。全量 `mypy app` 为 440 errors / 105 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 kwargs `[assignment]`，继续 FAIL / NO-GO。

## T30：calendar manifest 默认 literal 类型批次（2026-09-21）

范围仅为 `app/services/market_data/calendar_importer.py` 与本迭代文档。只将 `MANIFEST_VERSION` 标注为 `Literal["market-data-calendar-v1"]`；MarketDataCalendarManifest 仍以同一个常量作默认值，strict validation、calendar loader、时区/coverage 验证、事务、publication 与业务行为未改。

精确 Mypy 为 0；根代理独立完整 calendar importer fixture 为 13 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 441 errors / 106 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 default `[assignment]`，继续 FAIL / NO-GO。

## T29：缓存单例 Redis/内存联合类型批次（2026-09-21）

范围仅为 `app/db/cache.py` 与本迭代文档。只将 module singleton 标注为 `RedisCache | MemoryCache | None`，并将 factory 返回标注为两种实际 cache 实现的联合；REDIS_URL 选择、首次初始化、单例复用、惰性 Redis import、TTL/序列化和业务行为未改。

精确 Mypy 为 0；根代理独立完整 cache/cached-extended fixture 为 17 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 442 errors / 107 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 singleton `[assignment]`，继续 FAIL / NO-GO。

## T28：主数据 manifest literal 与类别计数类型批次（2026-09-21）

范围仅为 `app/services/market_data/master_data_importer.py` 与本迭代文档。以 `ManifestVersion` literal alias 表达既有固定 wire value，并以 `Counter[str]` 更新原始 asset_type 计数；strict manifest 验证、七类计数、排序输出、导入事务、writer/publication 和业务行为未改。

精确 Mypy 为 0；根代理独立完整 master-data importer fixture 为 8 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 443 errors / 108 files（625 checked，退出码 1）；标准化差分仅移除该 2 条 `[valid-type]`/`[arg-type]`，继续 FAIL / NO-GO。

## T27：股票研究兼容层 reconciliation payload 类型批次（2026-09-21）

范围仅为 `app/services/asset_research/stock_compat.py` 与本迭代文档。只将 `legacy` local dict 显式标注为 `dict[str, object]`，使其与既有 pairs 声明一致；legacy/generic 字段、映射 version、记录顺序、reconcile_batch 调用和所有业务行为未改。

精确 Mypy 为 0；根代理独立完整 compatibility fixture 为 2 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 445 errors / 109 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 append `[arg-type]`，继续 FAIL / NO-GO。

## T26：市场数据授权 principal 类型批次（2026-09-21）

范围仅为 `app/api/data/deps.py`、`tests/test_data_management_deps.py` 与本迭代文档。仅将授权 helper 返回的第一项从 object 收紧为 `MarketDataPrincipal`；principal 生成、read check、403 异常映射、授权器/DB 行为、查询服务和路由未改。

精确 Mypy 为 0；根代理独立授权依赖 fixture 为 4 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 446 errors / 110 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 access `[arg-type]`，继续 FAIL / NO-GO。

## T25：监控规则可空 description 契约批次（2026-09-21）

范围仅为 `app/services/monitoring_service.py`、`tests/test_monitoring_api.py` 与本迭代文档。服务创建方法的 description 类型从 `str` 对齐为 `str | None`；API、schema、AlertRule 模型、数据库/迁移、默认通知、调度和日志未改。省略 description 继续传递 None，不转换为空字符串。

API 精确 Mypy 为 0；服务精确 Mypy 仍有 15 条既有 ORM/Optional/推断错误，未在本批修改。根代理独立完整监控 API fixture 为 49 passed、7 条既有 warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 447 errors / 111 files（625 checked，退出码 1）；标准化差分仅移除该 1 条 API `[arg-type]`，继续 FAIL / NO-GO。

## T24：版本参数 diff 容器类型批次（2026-09-21）

范围仅为 `app/services/version_diff_service.py` 与本迭代文档。修改仅为 local diff 加 `dict[str, dict[str, Any]]` 显式注解；四个分类、参数比较、嵌套 from/to payload、函数签名和所有调用方保持不变。

精确 Mypy 为 0；根代理独立 `tests/test_version_diff_service.py` 为 18 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 448 errors / 112 files（625 checked，退出码 1）；标准化差分仅移除该 1 条推断错误，继续 FAIL / NO-GO。

## T23：日志查询参数脱敏类型批次（2026-09-21）

范围仅为 `app/middleware/logging.py`、`tests/test_logging_middleware.py` 与本迭代文档。修改仅为 sanitized local dict 加 `str | list[str]` 值类型；parse_qs、敏感键 redaction、单值/重复值格式、日志流程和返回文本均保持不变。

精确 Mypy 为 0；根代理独立 `tests/test_logging_middleware.py` 为 8 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 449 errors / 113 files（625 checked，退出码 1）；标准化差分仅移除该 1 条推断错误，继续 FAIL / NO-GO。

## T22：分析服务复利与均线类型批次（2026-09-21）

范围仅为 `app/services/analytics_service.py`、`tests/test_analytics_service.py` 与本迭代文档。修改仅把复利累计值显式标为 float 并把 MA 前置结果显式标为 `list[float | None]`；未修改公式、round 精度、指标输出、schema、API、配置、依赖、数据库或迁移。

精确 Mypy 为 0；根代理独立 `tests/test_analytics_service.py` 为 22 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 450 errors / 114 files（625 checked，退出码 1）；标准化差分仅移除该 2 条推断错误，继续 FAIL / NO-GO。

## T21：增强回测请求服务契约批次（2026-09-21）

范围仅为 `app/api/backtest_enhanced.py`、`tests/test_backtest_enhanced.py` 与本迭代文档。增强路由先保留 client runtime_dir 字段集的 422 拒绝；只有之后才用基础 `BacktestRequest.model_validate()` 转换并调用原有 `BacktestService.run_backtest(user_id, request)`。未修改两个 schema、BacktestService、WebSocket/响应逻辑、配置、依赖、数据库 schema 或迁移。

目标精确 Mypy 为 0。完整增强回测 fixture 为 52 passed、5 条既有 warning；根代理独立复验新增的转换/拒绝边界为 2 passed、1 条既有 warning，Ruff/format、tracked diff 与新增 diff 抑制扫描通过。全量 `mypy app` 为 452 errors / 115 files（625 checked，退出码 1）；标准化差分仅移除该 1 条请求模型 `[arg-type]`，继续 FAIL / NO-GO。

## T20：动态策略服务 shim 静态接口批次（2026-09-21）

范围仅为新增 `app/services/strategy_service.pyi`、新增 `tests/test_strategy_service_runtime_shim.py` 与本迭代文档。stub 从 canonical `strategy.core` 显式转发全部 8 个 public exports；Python 运行时继续执行原 module replacement，未修改 core、legacy shim 或任一调用方。

根代理独立复验 stub/core 精确 Mypy 为 0；runtime identity 加既有策略扫描 fixture 为 9 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked `git diff --check`、untracked whitespace 检查和新增 diff 抑制扫描均通过。fixture 同时断言 module identity、`__all__` 顺序和每个 public export identity；未连接真实数据库、网络、行情或交易系统。

T20 后完整 `mypy app` 为 453 errors / 116 files（625 checked，退出码 1）。20 条 `strategy_service` `[attr-defined]` 误报均消失，按标准化错误文本与 T19 比较无新增诊断；完整门禁继续 FAIL / NO-GO。

## T19：参数优化 FAILED 回测结果批次（2026-09-21）

范围仅为 `app/services/param_optimization_service.py`、`tests/test_optimization_api.py` 与本迭代文档。FAILED 状态的消息形成由共享 async helper 负责：非空字符串错误信息保留，缺失结果或空/None 消息落入稳定 fallback。初始 status 已 FAILED 与轮询后 FAILED 都通过这一条路径；其他状态路径不变。

根代理独立复验目标可空错误消失；目标文件仅保留一条无关的 `strategy_service.get_strategy_dir` 动态导出 `[attr-defined]`。完整优化 API fixture 为 48 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff check/format、tracked `git diff --check` 与新增 diff 抑制扫描通过。未连接真实数据库、网络、行情或交易系统。

T19 后完整 `mypy app` 为 473 errors / 120 files（625 checked，退出码 1）。按标准化错误文本与 T18 比较，没有新增诊断，唯一移除的是参数优化 FAILED 分支的 1 条可空结果错误；完整门禁继续 FAIL / NO-GO。

## T18：比较创建可空回测结果批次（2026-09-21）

范围仅为 `app/services/comparison_service.py`、`tests/test_comparison_service.py` 与本迭代文档。实现将验证和 payload 构造合并为一次循环：每个输入位置只读取一次回测结果，`None` 继续抛出既有 `ValueError`，非空结果立即填充保持不变的比较字段。没有去重或重排输入，因此重复 ID 仍保留原有逐项读取和最终 dict 覆盖语义。

根代理独立复验原第 78–89 行的 12 条 `[union-attr]` 全部消失；该文件余下 18 条既有非目标错误不在本批范围。完整 comparison-service fixture 为 30 passed、1 条既有 Backtrader Quandl deprecation warning，Ruff check/format、tracked `git diff --check` 与新增 diff 抑制扫描通过。新增 fixture 用第二次返回 `None` 的 mock 锁定一次读取路径；未连接真实数据库、网络、行情或交易系统。

T18 后完整 `mypy app` 为 474 errors / 120 files（625 checked，退出码 1）。按标准化错误文本（移除行号）与 T17 比较，没有新增诊断，唯一移除的是这 12 条可空回测结果错误。完整门禁继续 FAIL / NO-GO。

## T17：动态回测服务 shim 静态接口批次（2026-09-20）

范围仅为新增 `app/services/backtest_service.pyi`、新增 `tests/test_backtest_service_runtime_shim.py` 与本迭代文档。Python 运行时继续执行原 `sys.modules` replacement shim；stub 只将 canonical `app.services.backtest.service.BacktestService` 显式 re-export，不复制 service、放宽方法签名或改变任一调用方。

根代理独立复验 stub 精确 Mypy 为 0；runtime identity 和既有回测服务 fixture 合跑为 46 passed、1 条既有 Backtrader Quandl deprecation warning。Ruff check/format、tracked `git diff --check`、untracked whitespace 检查和新增 diff 抑制扫描均通过。模块与类 identity 断言表明 legacy import 与 canonical service 为同一对象；未连接真实数据库、网络、行情或交易系统。

T17 后完整 `mypy app` 为 486 errors / 120 files（625 checked，退出码 1）。11 条 `BacktestService` `[attr-defined]` shim 误报均消失；同时 static contract 暴露 14 条调用方问题：12 条比较服务 `get_result()` 可空结果、1 条优化服务可空失败结果、1 条增强回测请求 schema 不兼容。因此该批只关闭动态导出的静态可见性债务，完整门禁继续 FAIL / NO-GO，不报告为全局净错误数改善。

## T16：告警规则配置与类型失败关闭批次（2026-09-20）

范围仅为 `app/services/alert_evaluation.py`、新增 `tests/test_alert_evaluation_type_boundaries.py` 与本迭代文档。未修改 `AlertRule` 模型、MonitoringService、API、数据库 schema、迁移、配置、依赖或下游服务接口。局部 Protocol 仅覆盖已进入评估函数的 trigger type/config 与 alert type 标量；非 Mapping 配置在调用 metric getter 前退出，Mapping 只复制字符串键给既有 helper，不改变合法 dict 的 threshold/rate/cross 计算。

cross 的任一数值为 `None` 时不改变 trigger state 并返回 `False`；manual `current_value` 为 `None` 时返回 `None`；无法转换为 `AlertType` 的 alert type 在调用账户/仓位/策略服务前返回 `None`。精确 Mypy 从 6 errors 到 0；Ruff check/format、tracked `git diff --check`、untracked test whitespace check 与新增 diff 抑制扫描通过。根代理独立复验新增 boundary、既有 alert-evaluation 与 exceptions/alerts fixture 共 96 passed、1 条既有 Backtrader Quandl deprecation warning。未连接真实数据库、网络、行情或交易系统。

T16 后完整 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m mypy app --show-error-codes` 退出码 1：`Found 483 errors in 121 files (checked 625 source files)`。相较 T15 减少 6 errors、1 个报错文件；目标 `app/services/alert_evaluation.py` 不在完整错误清单。完整门禁继续是 FAIL / NO-GO。

## T1 追加批次（2026-09-20）

范围限定为 `src/backend/app/services/process_supervisor.py`、`app/services/market_data/multi_record_contracts.py`、`app/services/ctp_tunnel.py`、`app/services/instance_store.py`、`app/services/stock_analysis/pipeline.py`、`app/services/research/model_budget.py`、`app/services/research/http_holdout_executor.py`、`app/services/research/http_discovery_sandbox.py`、`app/services/research/openai_compatible_provider.py`、`app/services/research/holdout_worker_process.py`、`app/research_deployments/holdout.py`、`app/research_deployments/discovery.py`，以及 `src/backend/pyproject.toml` 的直接运行时依赖。修复只对齐数值窄化、Windows API 契约、B2 selector、CTP socket/callback、action label 类型和 Python 3.10 兼容超时；三处 `asyncio.timeout` 改为同步 `anyio.fail_after`，AnyIO 声明为 `anyio>=3.7.1,<5.0`。不改变业务协议/安全边界，不放宽静态规则，不添加测试跳过，不触及范围外的既有工作区改动。

验证顺序及结果：先精确 Mypy 12 文件（修复前 37 errors，修复后 0），再对相同文件 Ruff check 与 format check，然后将指定测试拆为三组逐用例输出（113 + 88 + 55 = 256 passed），最后执行一次全量 `mypy app`。全量结果 1072 errors / 168 files（扫描 625 files），仍为 FAIL / NO-GO；不得以目标子集通过代替全量门禁。环境及详细退出状态见 `ACCEPTANCE.md`。

## T2 追加批次（2026-09-20）

实施范围仅新增 `src/backend/app/api/deps.pyi` 与 Iteration200 文档；禁止编辑 runtime `deps.py`、`_dependencies.py` 和直接 importers。stub 使用显式 `from app.api._dependencies import ...` 重导出，补齐认证、WebSocket、权限 helpers/常量和测试所需的私有 token helper；不使用 `Any`、`__getattr__`、ignore 或 wildcard import。Mypy 必须以 `.pyi` 为静态入口，并覆盖 `app/api/data/deps.py` 及 `rg` 枚举的全部直接 shim importer；将 runtime `.py` 当作入口会绕过 sibling stub，不计为验收命令。

精确检查确认 0 个 `app.api.deps` 缺属性错误；相同 API 文件仍有 55 个其他类型错误 / 15 文件，单文件 stub Mypy、Ruff 和指定 4 个测试文件通过（62 passed、1 个已有 skip）。T2 后全量 Mypy 为 1027 errors / 145 files（625 files），仍未通过；完整证据见 `ACCEPTANCE.md`，不把 `_dependencies.py` 或 importer 的其他真实类型错误计入 T2 关闭结论。

## T3 追加批次（2026-09-20）

范围仅为 `src/backend/app/data_fetch/core/database.py`、`src/backend/app/data_fetch/core/mysql_base.py`、`src/backend/tests/test_data_fetch_common_utils.py` 和 Iteration200 文档。目标是修复两核心文件的 49 条 Mypy 错误，不触碰外部采集脚本、依赖声明、Mypy/Ruff 配置或真实 MySQL。

连接/游标字段保留 Optional 运行时状态以维持现有调用方 `is None` 分支；以窄 Protocol 描述 connector 操作，并在 `MysqlBase` 使用显式非空守卫。对 mysql-connector pool wrapper 做委托适配，保持 pool close 语义，并用真实 `MySQLCursorAbstract` 检查游标。`save_data` 契约为 `int | Literal[False]`，保留实际写入数量或 False；fetchone 的空返回和 description 缺失均有 fake-based 回归覆盖。禁止 blind cast、SQL/事务语义变化和真实数据库验收。

精确 Mypy 修复前为 49 errors，修复后 0；目标 Ruff check/format 通过，`tests/test_data_fetch_common_utils.py` 为 11 passed。T3 后一次全量 `mypy app` 为 984 errors / 143 files（625 checked，退出码 1），全量仍 FAIL / NO-GO；provider/script 消费方的静态契约错误留待后续有边界批次，真实 MySQL 未验证。完整退出状态见 `ACCEPTANCE.md`。

## T4 追加批次（2026-09-20）

范围仅为 `src/backend/app/data_fetch/providers/akshare_to_mysql.py`、`app/data_fetch/providers/akshare_provider.py`、`app/data_fetch/utils/akshare_network_proxy.py`、`tests/test_data_fetch_common_utils.py`、`tests/test_akshare_network_proxy.py`、新增 `tests/test_akshare_provider_storage.py` 与 Iteration200 文档。修改对齐 T3 的 `_require_connection()` / `_require_cursor()` 守卫和 `save_data: int | Literal[False]`；成功路径继续返回实际输入行数，空输入及无可写列返回 False。PyMySQL 使用窄 TypedDict、Protocol 与结构检查；requests probe 使用显式 Session.get 参数。没有新增 Any、cast(Any)、ignore、静态规则变化、驱动依赖升级或外部请求。

三目标文件初始精确 Mypy 为 55 errors（21 + 21 + 13），最终为 0；六个源/测试文件 Ruff check、format check 均通过；三份直接 fake-based 测试共 23 passed、0 failed、1 条既有 backtrader Quandl deprecation warning。唯一一次 T4 后全量 `mypy app` 为 929 errors / 140 files（625 checked，退出码 1），仍 FAIL / NO-GO；比 T3 后观察值 984/143 少 55 errors、3 个报错文件。测试未连接真实 MySQL、未调用 AkShare，也未发出网络请求。完整命令与退出码见 `ACCEPTANCE.md`。

## T5 股票分析 ORM 实例字段类型批次（2026-09-20）

目标模型将 legacy `Column[...]` 字段改为精确 `Mapped[...]`/`mapped_column(...)`：任务、报告、导出和信号模型的 SQLAlchemy metadata 签名修改前后相同（SHA-256 `5be915161e846230a3c84c51f95f1e6fffb38ce1f9b0fc11216adb37ec25a652`）。JSON 按实际内容使用递归/窄类型：run config 实际包含嵌套 `policy.snapshot()`，freshness/feature/policy snapshot producer 也允许嵌套结构，故这些字段使用递归 `JSONMapping`；universe、error summary 和 quality reasons 保留 list/map 窄类型。signal action 使用 `Literal["BUY", "SELL", "WATCH"]`。`tasks.py` 保留显式 ORM 实例属性读写；经批准扩展只更新 `ChatMessage.metadata_json` 的映射类型，数据库列仍名为 `metadata`、类型 JSON、nullable=True。没有改业务调用或 schema。

初始三文件精确 Mypy 为 58 errors（集中在 `tasks.py`）；最终四文件 Mypy 0 errors。目标 Ruff check/format check 通过；相关 in-memory SQLite/fake 测试 26 passed、1 条既有 Quandl deprecation warning。唯一一次 T5 全量 `mypy app` 为 849 errors / 136 files（625 checked，退出码 1），较 T4 后观察值 929/140 减少 80 errors、4 个报错文件；该扫描早于最后一轮递归 JSON 注解精确化，按指示未重跑，因此只作为最新全量观察值，不能视为最终源码复验。全量仍 FAIL / NO-GO。测试未连接真实数据库，未调用外部 AI 或网络。详细证据见 `ACCEPTANCE.md`。

## T6 仿真交易 ORM 与服务快照类型批次（2026-09-20）

范围仅为 `src/backend/app/models/paper_trading.py`、`app/services/paper_trading_service.py` 与 Iteration200 文档。模型把四张仿真交易表的 67 个 legacy `Column`/`relationship` 实例声明迁移为 SQLAlchemy 2 映射类型，所有调用参数经 AST 结构对比与 HEAD 完全一致；不产生迁移或 schema 行为修改。服务使用 `PositionSnapshot`、`PositionEvent` 和窄数值/日期规范化来消除列对象误推断，保留真实 ORM 和现有 Mock 的兼容边界。

精确 Mypy 初始为 `Found 60 errors in 1 file`，最终两文件为 0；Ruff check/format 通过；`test_paper_trading_service.py`、`test_service_edge_cases_113.py`、`test_paper_trading_api.py` 合计 142 passed、1 条既有 Quandl deprecation warning。T6 后全量 `mypy app` 为 789 errors / 135 files（625 checked，退出码 1），仍 FAIL / NO-GO；没有连接真实交易、外部数据库或网络。详细证据见 `ACCEPTANCE.md`。

## T7 市场数据平台 ORM 类型批次（2026-09-20）

范围仅为 `src/backend/app/models/market_data_platform.py` 与 Iteration200 文档。该文件中 220 个 legacy `Column` 字段和 25 个 relationship 逐一迁移为 SQLAlchemy 2 `Mapped[...]` 声明，调用参数不变；JSON 使用递归 `MarketDataJSONMapping`，外部关系类型使用 `TYPE_CHECKING` 前向引用。没有修改 Store、业务逻辑、迁移、依赖或配置。

模型精确 Mypy 从 2 errors 到 0；Ruff check/format 与 diff check 通过。HEAD/工作区 AST 对比显示 columns=220、relationships=25，均无 missing/extra/changed；同一摘要算法的 21 表 schema hash 改前后均为 `9b5a93f18df29c7b2b364c09691f36a33c442fdb8358a02058e145e7d55761b5`，mapper 配置为 21 tables / 220 columns / 25 relationships。`tests/market_data_platform/test_store.py` 为 47 passed、1 条既有 Quandl deprecation warning；Store 精确 Mypy 从 43 errors 降为 9，剩余错误未在本批扩张修复。T7 后全量 `mypy app` 为 662 errors / 129 files（625 checked，退出码 1），仍 FAIL / NO-GO；未运行迁移、真实数据库或外部数据源。

## T8 工作空间 ORM 与递归 JSON 类型批次（2026-09-20）

范围仅为 `src/backend/app/models/workspace.py` 与迭代文档。`Workspace`、`StrategyUnit` 的 39 个 legacy `Column` 和 3 个 relationship 都迁移为 SQLAlchemy 2 精确映射；JSON 字段使用递归 `WorkspaceJSONMapping`，不引入无界 `Any`。HEAD/工作区 AST 对比确认 39 个列和 3 个关系调用参数无 missing/extra/changed；当前 mapper 配置为 2 tables / 39 columns / 3 relationships。模型精确 Mypy 为 0，Ruff/format/diff check 通过，相关服务/API 测试为 159 passed、1 条既有 warning。

四个紧邻服务的测量从 60 errors 降至 18；由于递归 JSON 契约暴露三个直接消费者的真实不安全访问，同时一个既有 workspace lifecycle 错误消失，T8 后完整 Mypy 为 625 errors / 131 files（625 checked，退出码 1）。该结果不是全仓门禁通过，也不把错误总数变化全部归因于模型迁移；直接消费者由 T9 以独立范围处理。未运行迁移、真实数据库、外部数据或交易系统。

## T9 工作空间 JSON 消费者批次（2026-09-20）

范围仅为 `src/backend/app/services/stock_analysis/tasks.py`、`app/services/workspace/optimization.py`、`app/services/workspace/reports.py`、新增 `tests/test_workspace_json_consumers.py`、现有保存工作区报告的兼容测试及迭代文档。递归 TypeGuard 只接受合法 JSON mapping；保存报告保留合法旧项、替换同 report_id、保留最近 50 条并删除坏项；优化配置在写回前安全合并；报告层拒绝错误形状、bool、非数值和非有限数值。未弱化 `WorkspaceJSONMapping`，未改模型、迁移、API、配置、依赖或静态检查设置。

三目标文件精确 Mypy 从 10 errors 到 0；目标 Ruff check、format check、`git diff --check` 和抑制扫描通过。定向 fake/SQLite fixture 为 5 passed、1 条既有 Quandl deprecation warning，覆盖合法 JSON 聚合与畸形 JSON 的安全退化。T9 后完整 `mypy app` 为 615 errors / 128 files（625 checked，退出码 1），比 T8 减少 10 errors、3 个报错文件；全量仍 FAIL / NO-GO，未连接真实 DB、网络、外部数据源或交易通道。

## T10 市场数据查询回执和 cursor 类型边界批次（2026-09-20）

范围仅为 `src/backend/app/services/market_data/query_service.py`、`src/backend/tests/market_data_platform/test_query_service.py` 与迭代文档。生产代码把 `_Store.persist_provider_result` 的返回类型对齐真实 Store 的 `PersistedProviderFetch | DeferredProviderFetch`；deferred 分支在可见性推进、fetch 组装和局部重读前稳定失败，保留 `finally` 中的 lease release。局部 Store 读取把原来的 `dict[str, object]` 展开替换为 explicit typed calls，并按 allow-list 是否存在维持 legacy fake Store 与生产 source filter 的兼容。

cursor 解码将 JSON mapping、四个必需 digest、可选 grant digest 及两个 anchor sequence 全部在构造领域对象前收窄；错误结构、非 string digest、bool、负数、非 int sequence 均归一化为 `CURSOR_INVALID`。未修改 Store/模型/API/迁移、配置、依赖或静态规则，未新增 `Any`、`cast(Any)`、ignore 或 `# noqa`。先以精确 Mypy 建立 34 errors 基线并收敛到 0，再运行目标 Ruff check/format、diff/suppression 检查和完整本地 fixture；`test_query_service.py` 为 69 passed、1 条既有 warning。随后全量 `mypy app` 为 581 errors / 127 files（625 checked，退出码 1），较 T9 净少 34 条错误、1 个报错文件；完整门禁仍 FAIL / NO-GO，未连接真实数据库、外部网络、数据供应商或交易系统。

## T11 Scanner plan ORM 实例字段批次（2026-09-20）

范围仅为 `src/backend/app/models/scanner_plan.py` 与迭代文档。`ScannerPlanModel` 的 15 个列、`ScannerPlanRunModel` 的 17 个列和两个 relationship 均从 legacy 声明迁移为 SQLAlchemy 2 精确映射；`JSONValue` 递归描述 scalar/list/mapping，避免新引入无界 `Any`。每个 `mapped_column` / `relationship` 保留原调用参数，未修改服务、API、动态 SQL、迁移、数据库兼容层、依赖或静态规则。

先记录模型/服务精确 Mypy 的 25 errors 基线，迁移后为 0；再运行目标 Ruff check/format、diff/suppression 检查和 `tests/test_scanners.py -k scanner_plan -vv`。两项 API fixture 为 2 passed、4 deselected、1 条既有 warning，覆盖计划日报缓存、更新/删除、动态结果表创建/删除。运行时 mapper 显示 `scanner_plans` 15 列、4 个 index，`scanner_plan_runs` 17 列、5 个 index，两个 relationship 的 target/uselist/back_populates/cascade/order_by/passive_deletes 与迁移前定义一致。随后全量 `mypy app` 为 556 errors / 126 files（625 checked，退出码 1），较 T10 减少 25 条错误、1 个报错文件；完整门禁仍 FAIL / NO-GO，未连接真实外部数据库、网络或交易系统。

## T12 仓位估值数值回退类型批次（2026-09-20）

范围仅为 `src/backend/app/services/position_valuation.py`、新增 `src/backend/tests/test_position_valuation.py` 与迭代文档。两个 overload 将 `safe_float` 的 default 语义显式化：省略或传入 float 返回 float；传入 `None` 返回 float 或 None。实现仍接受现有动态值，dict 分支根据 fallback 分支递归调用，list/tuple 分支保持过滤/求和逻辑；没有修改位置、价格、乘数、保证金、佣金或 PnL 计算公式。

先记录精确 Mypy 20 errors 基线，overload 后收敛到 0；再运行目标 Ruff check/format、tracked/untracked diff whitespace 检查、diff suppression 扫描、新增 helper tests 及现有 workspace 估值筛选。直接 helper 为 3 passed，现有场景为 21 passed、119 deselected，均只有既有 warning。随后全量 `mypy app` 为 536 errors / 125 files（625 checked，退出码 1），较 T11 减少 20 条错误、1 个报错文件；完整门禁仍 FAIL / NO-GO，未连接真实数据库、网络、账户或交易系统。

## T13 市场标的 snapshot 与指标类型批次（2026-09-20）

范围仅为 `src/backend/app/services/market_instrument.py`、新增 `src/backend/tests/test_market_instrument_type_boundaries.py` 与迭代文档。五个仓库 lookup 的 payload name 使用局部 string-only 回退，合法非空字符串保持，数字、空字符串或缺失名称退回原有标的代码；不改变 snapshot、provider、市场、历史 rows 或 API 返回结构。Pandas 的可哈希键 mapping 以精确字符串列名只读检索，指标循环显式收集有效 float，保持缺失 close 忽略、无 close 时仍计算 volume 均值的已有逻辑。

先记录精确 Mypy 20 errors 基线，修复后为 0；再运行目标 Ruff check/format、tracked/untracked whitespace 检查和 diff suppression 扫描。新增测试为 5 passed，既有市场标的 API fixture 为 15 passed，合计 20 passed、1 条既有 Backtrader Quandl deprecation warning；所有数据源均为 fake、Pandas 内存表或既有 fixture。随后全量 `mypy app` 为 516 errors / 124 files（625 checked，退出码 1），较 T12 减少 20 条错误、1 个报错文件；完整门禁仍 FAIL / NO-GO，未连接真实数据库、网络、供应商或交易系统。
