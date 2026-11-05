# 迭代204 验收矩阵逐条审计（AC01–AC18，2026-11-06）

本文是把 AC01–AC18 的每一行对照**现行实测状态**做一次独立审计，供属主直接据此派工。
它不改动任何既有台账，也不关闭任何验收行。

## 0 执行身份与方法

| 项 | 值 |
|---|---|
| 仓库基线 | AFI `origin/dev = 3e9f4a76e5a33a9493597d0e0fc4f77da87c6db0`（`git ls-remote` 现读）；本审计分支自该 HEAD 切出 |
| 定义文件 | `ACCEPTANCE_AND_CUTOVER.md:76-95` 为判据原文；`:97` 自然周期门槛是迭代建议值、月度任务可 `DEV_DONE` 而 `natural_cycle` 仍 `NOT_RUN`；`:99` 质量核验须用独立 oracle，实现的同一转换函数不能互作证明；`:39` 逐行重申矩阵无一通过 |
| 台账输入 | `RUNTIME_REPAIR_20261105.md`、`SUBTASK_RECONCILIATION_20261105.md`（均在 PR #274 head `835c43653137e9ef374fb92f28f102377707a1b4`，尚未并入 dev）；`DEVELOPMENT_STATUS.md` Wave 25/26（`:2003-2132`）；`INVENTORY.md`（2026-10-26 快照）；`INVENTORY_AUDIT_20261105.md` |
| 本轮实测 | 只读连库（`ai_for_investor@127.0.0.1`，读数见 §2 各行）；`git ls-remote` 逐个回读 PR head；GitHub API 回读 PR 文件与 OpenData 探针源码；`git cat-file`/`git log --all` 复核幽灵文件 |
| 判定词汇 | `PASSED`（本文一律不使用）/ `PARTIAL` / `DEV_DONE` / `NOT_RUN` / `UNKNOWN` / `NOT_SUPPORTED` / `BLOCKED_ON_OWNER` |
| 平面词汇 | `CODE/OFFLINE`、`REAL_SOURCE`、`DEPLOYMENT`、`NATURAL_CYCLE`；离线绿不得代真源或自然周期发言 |

PR head SHA 全部以 `git ls-remote` / API 现读回：#273 `0dbb3f25f5da86b94c449bb29625f227fce5561c`、#274 `835c43653137e9ef374fb92f28f102377707a1b4`、#278 `391398764bbd1b977e2fc605b14c47b27567619a`、#280 `cd25683c9401cb8354cd1c799319798546c5a950`、#281 `c59e5f25b3866683083f644f594a426781d99704`、#282 `550d66b696ee923a3130f15fd7a63966189e4044`、#283 `a8dca0486e0bc37ca23aa9a10a575cc7ebc7735b`、#284 `8971f3098822245ed7d83c7fe1e67c67ba5f7099`、#285 `d992d3d37b2f1803c0b5c3312be925158819b249`、#286 `75e5acf3ad07894c1b775b413656266faa5a10ae`；OpenData #195 `e7e25b0027b2…`、#196 `7c4c43f89a2b74bf4fa098649f985a96d7fb9366`、#197 `5a41a3284e7f…`（后三条为 API 读数，未逐一展开 40 位）。

## 1 汇总

| AC | 判定 | 归属主导 |
|---|---|---|
| AC01 | PARTIAL | 代码可推进 + 属主裁定幽灵行 |
| AC02 | DEV_DONE | 代码 |
| AC03 | DEV_DONE | 代码 + 部署后探测 |
| AC04 | PARTIAL | 代码（幽灵语义模块缺失）+ 真源 |
| AC05 | UNKNOWN | 属主动作 + 时间 |
| AC06 | DEV_DONE | 代码 + 故障注入待部署 |
| AC07 | DEV_DONE | 代码 |
| AC08 | PARTIAL | 代码；性能读数未做过 |
| AC09 | DEV_DONE | 代码 + 运行态证明 |
| AC10 | NOT_RUN | 属主/真源 |
| AC11 | PARTIAL | 代码可推进（处置仍 0/1057） |
| AC12 | PARTIAL | 代码 + 属主对幽灵迁移的裁定 |
| AC13 | NOT_RUN | 代码起步 + 属主动作（开旗标、清账） |
| AC14 | NOT_RUN | 需时间累计（自然周期钟） |
| AC15 | DEV_DONE | 代码 + 部署面复跑 |
| AC16 | PARTIAL | 代码 |
| AC17 | BLOCKED_ON_OWNER | 属主动作（MySQL 建库权限） |
| AC18 | NOT_RUN | 代码长线 + 撤权演练 |

18 行无一 `PASSED`；这与 `ACCEPTANCE_AND_CUTOVER.md:39` 的账面重申一致。

## 2 逐条审计

### AC01 范围与基线
- **判据摘要**：两仓与 dirty hash 重冻结；源文件、DB 任务（含 inactive）、systemd/cron/worker、进程、表、消费者、OpenData 重叠能力各有带环境身份/采集时间的清单，双向 anti-join 无未解释项；旧盘点的 1,066/1,103 只是历史快照。
- **当前判定**：PARTIAL。
- **已覆盖平面**：CODE/OFFLINE（脚本半区清单，`INVENTORY_AUDIT_20261105.md` 全篇）+ DEPLOYMENT 本机（运行入口/服务/进程读数，`RUNTIME_REPAIR_20261105.md` §0-1、§10，在 #274 head）。
- **本轮新增证据**：本会话只读连库复核 armed=1,098、`ak_data_scripts`=1,066、注册但无文件的脚本=9（逐名清点，见 §AC11 数值），与 `INVENTORY_AUDIT_20261105.md` 的口径一致；幽灵模块从孤例扩展为面：全仓 `__pycache__` 扫出 72 个 orphan pyc（约 2,274,034 B，清单在 `/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/MANIFEST.tsv`，本会话未重扫，属 wave28 读数）。进程/表/消费者/OpenData 重叠四项仍未刷新（`ACCEPTANCE_AND_CUTOVER.md:69-70`）。
- **未闭合项与精确闭合条件**：(1) 对 9 行幽灵登记给出可复核归类（未提交草稿/他机路径/生成错误三者之一并附证据），否则 anti-join 的「无未解释项」不成立；(2) 按同样带环境身份的方式刷新进程、表、消费者与 OpenData 重叠四项清单；(3) 对 72 个 orphan pyc 逐个给出「恢复/重建/宣告不可复现」三选一处置。
- **归属**：(2) 可由代码推进；(1)(3) 需属主动作。

### AC02 HTTP 契约与兼容
- **判据摘要**：v1 旧消费者 fixture 保持；v2 schema/错误/时间窗口/权限、空页、游标终止、版本兼容正反例通过；不静默截断。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：无（本轮 A 域无新合入）。既有：OpenData `origin/dev` 上 `opendata/api/published_data.py:605` 挂 v2 router、`:747` 起 datasets 端点、`:805` 页大小受 `MAX_PAGE_SIZE` 约束（本会话逐行开读）；v1/v2 OpenAPI 基线与检查脚本见 `SUBTASK_RECONCILIATION_20261105.md` §1（A05-01/02/03 行，其 file:line 为代理读数，本会话未复核）。
- **未闭合项与精确闭合条件**：对着**已部署**服务跑正反例：v1 消费者 fixture 全绿 + v2 空页/游标终止/422/410/429 各一例 + 版本兼容矩阵（旧客户端打新服务）通过并留环境身份。
- **归属**：需属主动作（部署一个可读的 OpenData 栈）后由代码推进。

### AC03 精确身份和范围
- **判据摘要**：错 symbol/venue/currency/频率/复权、超范围、重复键、混页 publication 均被拒；HTTP 200 不掩盖语义错误。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：本会话开读 `origin/dev:opendata/api/temporal_identity.py:231`（pin registry 取用）与 `:269`（`temporal_identity_unavailable` 失败关闭）。其余接线（`main.py` 装配、`TEMPORAL_IDENTITY_ENABLED` 默认 False）为 `SUBTASK_RECONCILIATION_20261105.md` A03-02 行读数。
- **未闭合项与精确闭合条件**：活栈上对同一端点注入错 symbol/混页/重复键各至少一例，断言非 200 或错误包体具名拒绝；200 响应逐条比对语义身份。
- **归属**：需属主动作（部署）。

### AC04 金融语义
- **判据摘要**：七类资产逐数据集验证字段/单位/日历/时区/复权/有效期/空值；NAV/收益/价格、精确合约/连续/TAS 分开。
- **当前判定**：PARTIAL。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：无新增合入。负面读数：语义层三个模块 `fund_metric_semantics`、`fund_nav_semantics`、`market_instrument_option_history` 只存在于 orphan 字节码，源码不在任何 ref（wave28 清单，本会话未复扫）；即「连续/精确合约/TAS 分开」这一半的实现从未入库，`SUBTASK_RECONCILIATION_20261105.md` §3（C02-01「缺连续/主力/TAS 身份」）与此吻合。
- **未闭合项与精确闭合条件**：每个数据集一份「源原始工件→独立解释→逐字段对照」记录（独立 oracle，`ACCEPTANCE_AND_CUTOVER.md:99`），且衍生品身份三态各有模块级合同测试；幽灵语义模块先「恢复或重建」再谈验证。
- **归属**：可由代码推进（重建语义模块、离线合同），真值对照需真源。

### AC05 全历史覆盖
- **判据摘要**：逐交易所当前+退市分母、分页完整性证据，逐 `instrument × dataset` 定起点/终点并核对 head/interior/tail；短窗口/样本请求不能冒充全历史；BSE 不支持保持 NOT_SUPPORTED。
- **当前判定**：UNKNOWN（且运行态此前为红，非未测）。
- **已覆盖平面**：CODE/OFFLINE + 本机 DEPLOYMENT；REAL_SOURCE 至今为红。
- **本轮新增证据**：#283（head `a8dca0486`）交付五个恢复控制器重建（181 项测试，属重实现非恢复：ghost/重实现符号集大部分不相交，wave28 实测对照）。本会话直查 `ak_task_executions`：2026-11-05 13:52 UTC 修复后累计 completed 80 / failed 5——采集面活着，覆盖分母仍是零。
- **未闭合项与精确闭合条件**：(1) 分母：每交易所有证券目录+退市集+换码表的带证据登记；(2) 执行者：#283 合入并部署后，五控制器各自完成一次真实源 `--plan`→`--apply` 且 progress 台账可复核；(3) 逐 instrument×dataset 的 head/interior/tail 对账报告，缺失分类非空即保持 UNKNOWN。
- **归属**：需属主动作（部署、源配额裁定）+ 长期时间。

### AC06 发布和崩溃一致性
- **判据摘要**：raw/ODS/DWD/publication/watermark 各边界故障注入读不到半批；重复提交不重复事实；跨库 outbox 可恢复。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：#280（head `cd25683c9`）修「失败记录后脚本仍在写库」的回归：子进程组可杀（`script.py` 同文件 `_kill_worker_group` :638-646、`start_new_session=True` :751）且把 `claim_key`/`fencing_token` 传进 worker（:2053-2055）（本会话按 API 回读逐行开读）；dev 现存旧路径仍是不可杀线程 `asyncio.to_thread`+`wait_for`（`src/backend/app/services/akshare/script.py:507/510`，`git grep -n "Script call timed out after"` 命中）。发布同事务面 `opendata/pipeline/publication_store.py:539 publish_in_connection` 本会话开读。
- **未闭合项与精确闭合条件**：部署形态下在五个边界各注入一次崩溃（kill -9 时刻表），断言无半批可读、重放幂等、outbox 恢复后事实不重复；`#280` 合入并重启服务后，`Script call timed out` 案例的台账行与 `rows_after` 必须一致（现台账 80/5 里 5 条 failed 即验证点）。
- **归属**：可由代码推进（合入 #280），注入演练需部署。

### AC07 PIT 与研究重放
- **判据摘要**：同 snapshot 两次运行输入哈希一致；未来披露/公司行动/修订不得进入过去 as_of；未知可得性不伪装已知。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：#278（head `391398764`）把研究工件绑定到精确 publication vector。既有：`financial_pit.py`（`SUBTASK_RECONCILIATION_20261105.md` A04-02 读数）。
- **未闭合项与精确闭合条件**：活库同一 snapshot 双跑哈希相等 + 三组未来信息注入用例（晚披露财报、事后修订、未来公司行动）在 as_of 查询下不可见 + 重放一次历史研究全链通过。
- **归属**：需属主动作（部署后重放窗口）。

### AC08 性能和故障消费
- **判据摘要**：冻结硬件/数据量/并发/索引记录 p50/p95/p99 与内存；分页/导出守上限；超时/429/503 有界重试；API 故障不调用旧数据源。
- **当前判定**：PARTIAL。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：无。离线面（deadline/Retry-After/上限）为 `SUBTASK_RECONCILIATION_20261105.md` E02 行读数（`opendata_provider.py:62-66,206-234,351-363`，本会话未复核）。
- **未闭合项与精确闭合条件**：p50/p95/p99 从未在任何冻结环境记录过——这一半是 0 条读数，不是「未测到坏结果」；需一次带硬件指纹的负载跑 + 故障注入断言旧源零调用。
- **归属**：需属主动作（压测环境）。

### AC09 权限与许可
- **判据摘要**：普通读 Key 不能 ingest/执行脚本/看 ODS 敏感域；精确 READ_DATA 且 source grant 覆盖实际上游产品/endpoint/用途；grant 在排队执行、读取前、保存前逐级复核；吊销/轮换/过期实际生效。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：无新增合入。既有：`opendata/api/published_access.py:238` principal 维度失败关闭（本会话开读）；grant ORM/迁移自 AFI #201/#204 已在树（`ACCEPTANCE_AND_CUTOVER.md:15-17` 已记）。
- **未闭合项与精确闭合条件**：运行态四连：排队后吊销→执行失败；读取前失效→拒；保存前失效→回滚；跨租户越权探测全拒。每步带环境身份留档。
- **归属**：需属主动作（部署），用例可由代码推进。

### AC10 来源与质量
- **判据摘要**：每数据集有来源产品/endpoint/实际参数证据；源真实样本→原始字节/脱敏 manifest→规范库→发布 API 逐字段对照；分页终止/重复/遗漏/字段漂移可复核；无真源证据不标 verified；概括授权声明不代替逐函数映射。
- **当前判定**：NOT_RUN。
- **已覆盖平面**：仅 CODE/OFFLINE（录制夹具与 manifest 工具）。
- **本轮新增证据**：无新增。OpenData #196（head `7c4c43f89a2b…`）新增 `opendata/pipeline/visibility_seal.py`（1,376 行）+ 迁移 + 2,383 行测试，属 publication seal 面，不产出真源对照。
- **未闭合项与精确闭合条件**：2026-10-27 00:55 后没有任何真源成功采集可供对照；需先恢复采集（已恢复，80 completed），再按 `ACCEPTANCE_AND_CUTOVER.md:99` 的独立 oracle 对每个在用数据集做逐字段对照并留原始字节档案。另：AC-5|07 的 bandit 证据必须走 CI 侧重跑，不得用笔记本生成入账（`DEVELOPMENT_STATUS.md:2077` 时效类；§4 见下）。
- **归属**：需属主动作（源映射裁定）+ 代码。

### AC11 逐脚本与逐任务适配
- **判据摘要**：每个旧脚本/任务有映射与处置（七种词表），参数/频率/业务范围不漏；新任务默认 disabled；辅助文件不生成 task；合并任务保留旧身份映射。
- **当前判定**：PARTIAL。
- **已覆盖平面**：CODE/OFFLINE + 本机只读 DEPLOYMENT。
- **本轮新增证据**：#286（head `75e5acf3a`）交付处置仪器与诚实 batch-01 台账（`script_disposition_ledger.{csv,json}` + `scripts/ops/assign_script_dispositions.py`，1,309 行，API 文件清单回读）；#284（head `8971f3098`）静态参数审计：`binds 155 / unexpected_param:_ingest_mode 7 / missing 0 / script_file_absent 50 / accepts_var_kwargs 886`（合计恰 1,098）。本会话直查：9 个无文件注册脚本的 armed 任务 = **26+16+4+1+1+1+1 = 50**，与审计 `script_file_absent: 50` 独立吻合。runtime 交叉核对给出反向事实：8 个运行期绑定失败对里静态审计只预测了 1 个（wave28），所以诚实表述是「审计能预测少数」。
- **未闭合项与精确闭合条件**：(1) 处置分子仍为 0/1057（`INVENTORY_AUDIT_20261105.md:77-102`），按 #286 仪器分批分派并在台账可见；(2) 886 个 `**kwargs` 任务的参数不漏只能靠运行期字段对照（并入 AC10）；(3) 50 个 ghost-backed 任务：源文件恢复或重写，然后观察一次真实执行非失败；(4) 频率/族词表先经人工确认（`legacy_frequency` 有 5 个 unspecified）。
- **归属**：可由代码推进；(3) 需属主对幽灵源裁定。

### AC12 存量迁移与环境防线
- **判据摘要**：先验包/环境/库身份；错误目标立即退出；dry-run 只读角色且无业务持久变化；分区行键/值/元数据/证据 hash 对账。
- **当前判定**：PARTIAL。
- **已覆盖平面**：DEPLOYMENT（本机）+ CODE/OFFLINE。
- **本轮新增证据**：#274 head 的 `RUNTIME_REPAIR_20261105.md` §0-4：备份身份（135,093,875 B、`gzip -t` 通过、sha256 前缀 `5bca70ab…`）、`stamp --purge 20261017_legacy_paper_import_cutover`→`upgrade head` 到 `20261101_stock_analysis_report_evidence_vector` 的单 head 序列、`alembic check` 漂移清单；§5 的 worker 恢复走「原样取回 + `--plan` 只读 + `source_or_database_calls: 0`」。本会话复核：`git log --all -- '*20261019_akshare*'` 为 0 命中——两个幽灵迁移在任何 ref 都不存在。
- **未闭合项与精确闭合条件**：(1) `20261019_akshare_enum_values` / `20261019_akshare_scheduler_claims` 必须重 authored 或正式宣告「不可复现」并写明库现状与仓库的永久分叉，禁止臆造 `upgrade()`；(2) dry-run 用只读角色在活副本上跑一次并证明零业务写；(3) 分区行键/值/证据 hash 对账一份完整报告。#285（`d992d3d37`，25 项测试）把「ExecStart 目标未入库」变成可检测项，是防线的现行推进。
- **归属**：(1) 需属主裁定 + 代码；(2)(3) 需属主动作（环境）。

### AC13 单写者与运行恢复
- **判据摘要**：两调度器竞争、跨进程/worker source 额度、租约过期恢复、手动/自然槽重叠、中途 kill、取消+重试、每域单有效 owner、过期 token 写失败；V3 配额启用需 V2 全停的可信证明；THS 入口预算前失败关闭。人工声明不算运行态证明。
- **当前判定**：NOT_RUN。
- **已覆盖平面**：CODE/OFFLINE（离线契约测试在途）；DEPLOYMENT 平面当前为**无实现**。
- **本轮新增证据**：本会话三连查实：`git cat-file -e origin/dev:` 对 `app/services/akshare/run_coordinator.py`、`write_fence.py`、`app/models/akshare_scheduler.py` 全部 NOT_IN_GIT，`git log --all` 对 run_coordinator 0 命中；当前开放 PR 清单（#262/273/274/278/280–286，API 列页）中**没有任何一条**含 claim/协调器实现。DB 现读：`ak_task_run_claims` 29,126 行（completed 24,345 / failed 4,781；非终态 0；lease 未过期 0；4,781 条 failed 的 `next_retry_at` 全为 NULL）；`ak_scheduler_control` 存在（wave28 `SHOW CREATE TABLE`）。修复后 80 条 completed 执行产生 **0** 条 claim 行——今天的采集是在无围栏下跑的。
- **未闭合项与精确闭合条件**：(1) 实现（model + coordinator + fence，默认 off 旗标）落 PR 并合入；(2) 属主核对旧 claim 表与新实现互不冲突后开旗标；(3) 活体七连测各留一次记录：双调度器竞争单 winner、跨 worker source 额度、租约过期接管、手动/自然重叠、中途 kill、取消+重试、过期 fencing_token 写被拒。此前把「自然 cron 验证过 AC13 围栏」记为结果的，描述的是**未提交的代码**（幽灵字节码平面），不是仓库——本文予以撤销。
- **归属**：可由代码推进（实现+测试）；开旗标与验收跑动需属主动作。

### AC14 自然运行与 freshness
- **判据摘要**：小时任务连续 48 次、日任务连续 7 个应运行交易/发布周期、周/月各至少 2/1 次自然周期 + 确定性重放；每周期 source→published→coverage 可追踪。门槛是迭代建议值，不得事后缩短窗口。
- **当前判定**：NOT_RUN（时间累计型，开发不能代跑）。
- **已覆盖平面**：DEPLOYMENT（读数能力）；NATURAL_CYCLE 首读数全部 met=0。
- **本轮新增证据**：#282（head `550d66b69`）交付读数器：`report_iteration204_acceptance_window.py:37` 冻结目标 `{hourly:48, daily:7, weekday_daily:7, weekly:2, monthly:1}`，周期计数取 `ak_task_executions.created_at`（UTC）。首窗（2026-11-05T04:52→16:52Z）读数：hourly 任务 1 个、completed 0、最长连续 0；其余档全 0 met（wave28 表）。已知仪器缺陷：`classify_cadence` 在 `:173` 只接受 ⊆ Mon-Fri 的 dow 集，`tue-sat` 落 None，17 个任务成「unknown/slot-check unavailable」（本会话按 API 回读源码逐行确认）。`next_execution_at` 语义存疑：task 1049 连败 4 槽后列为 23:03，既非 UTC 也非下个小时槽；dev 源码只有 `scheduler.py:120/155` 直存 APScheduler `next_run_time`、`:109` 置 None，无 backoff 写路径——该列被记为未决仪器问题，不作证据。
- **未闭合项与精确闭合条件**：小时钟最早只能在 #280（超时 1800s 下限 + 可杀子进程）部署且 task 1049 起连续 48 槽 completed 后起算（≥2 天）；日 7 个交易周期、周 2、月 1 属纯日历时间（月度腿依 `:97` 可保持 `DEV_DONE`/`NOT_RUN` 分列）。closure 判据就是 #282 报告里 `met` 按档变非零且逐槽 trace 存在。
- **归属**：需时间累计（自然周期钟）；分类器修复可由代码推进。

### AC15 THS 旧缺陷接续
- **判据摘要**：D04 默认 dry-run 且独立连接证明无 ODS/DWD/发布/覆盖写入；D05 首/中/尾缺口续跑补齐、同输入幂等、部分失败可恢复；替代路径同样适用。
- **当前判定**：DEV_DONE。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：无（本轮无 THS 新交付；D04/D05 离线面维持 `SUBTASK_RECONCILIATION_20261105.md` §4 读数）。
- **未闭合项与精确闭合条件**：活库上各一次：dry-run 后五张目标表计数零变化；构造 首/中/尾 三种缺口各续跑成功且重复执行行数不变（幂等）；kill 中途后重启可恢复。
- **归属**：需属主动作（环境），用例可由代码推进。

### AC16 产品与管理 UI
- **判据摘要**：七类行情/搜索/主题/策略准备与缺失/过期/权限/故障场景；opendata 任务创建/暂停/取消/补数/日志/DQ；旧书签有迁移入口且权限不扩大。
- **当前判定**：PARTIAL。
- **已覆盖平面**：CODE/OFFLINE。
- **本轮新增证据**：#281（head `c59e5f25b`）前端覆盖状态不再折叠：新增 `src/frontend/src/api/openDataCoverage.ts`（268 行）、`OpenDataStockDailyFreshnessStates.vue`（140 行）、`useOpenDataStockDailyFreshness.ts`（95 行），API 文件清单回读；OpenData #197（head `5a41a3284e7f`）补 coverage/backfill-planning/capacity 三个运维页，未合入。结构性事实不变：审核运行时按设计未装配，后台页显式呈现「未装配」而非发必然 404 请求（`ACCEPTANCE_AND_CUTOVER.md:44`）——这不构成 AC16 进度。
- **未闭合项与精确闭合条件**：部署栈上七类行情逐类人检 + 任务全生命周期（创建/暂停/取消/补数/日志/DQ）各一次真实操作 + 故障场景页面状态正确；旧书签迁移入口在真实路由上可达。
- **归属**：可由代码推进（合入 #281/#197），验收判读需部署。

### AC17 切换、备份与回滚
- **判据摘要**：隔离环境恢复 metadata+warehouse+artifact 并校验；旧→新、新→旧 writer 双向演练；回滚不丢新已提交数据、不改旧 snapshot；测量 RPO/RTO。
- **当前判定**：BLOCKED_ON_OWNER。
- **已覆盖平面**：无（连演练的前置都不成立）。
- **本轮新增证据**：负面证据复验于 `RUNTIME_REPAIR_20261105.md` §11：`CREATE DATABASE afi204_restore_drill` 返回 (1044) Access denied；`docker` 未装；root 走 auth_socket；唯一可写库是明令不碰的 `backtrader_web`。另：该演练要恢复的 schema 本身含 `ak_task_run_claims`/`ak_scheduler_control`，而这两个 revision 在任何 ref 不存在（本会话 `git log --all` 0 命中）——即隔离副本无法由仓库重建这台机器。
- **未闭合项与精确闭合条件**：属主提供一个可 `CREATE DATABASE` 的账号或 owned MySQL（OpenData CI 的 `tests/test_afi204_owned_mysql.py` 模式）；然后：恢复备份→行数/hash 对账→双向 writer 演练→各步崩溃重入→RPO/RTO 数字入档。备份存在（135 MB dump）不等于可恢复。
- **归属**：需属主动作（MySQL 建库权限/实例 + 幽灵迁移的可复现性裁定）。

### AC18 最终只通过 API
- **判据摘要**：ai 构建/安装包无源 SDK/采集启动 hook/仓库 DSN；运行网络限制为 opendata 数据 API；DB 权限撤销后全部数据消费测试仍通过；代码、配置、cron、实际进程联合核验。
- **当前判定**：NOT_RUN。
- **已覆盖平面**：CODE/OFFLINE（清点与扫描器）。
- **本轮新增证据**：无。现行分母维持 `SUBTASK_RECONCILIATION_20261105.md` §5：`app/` 内非采集树仍有 77 个文件命中 akshare 字样，直连库消费者已具名 6 处（`app/db/akshare_data_database.py` 等）；采集调度本身仍在启动装配里（`INVENTORY.md` §2 行，含 2026-10-26 快照口径警示）。
- **未闭合项与精确闭合条件**：联合核验脚本一次跑通：安装包扫描 0 源 SDK/0 DSN + 出网白名单只有 opendata API + 在影子副本上撤销 DB 写权后数据消费全测试通过 + 实际进程枚举无残留采集 worker。在此之前该域连一轮都没跑过。
- **归属**：可由代码推进（消费者迁移），判定跑动需属主动作。

## 3 本轮被纠正的既有结论

1. **#273 的 `Check diff coverage` 红不是覆盖率不足。** 实因 `.github/workflows/ci.yml:698` 以 `--depth=1` 抓 base、`:699` 紧接 `diff-cover --compare-branch=origin/dev`，浅历史下报 `fatal: origin/dev...HEAD: no merge base`（行号本会话亲读；wave28 笔记写的 689-699 是同一区块）。`.coveragerc:2` 为 `source = app`，#273 只加 `scripts/`、`tests/`、`deploy/`，diff-cover 本就跳过。修法是把 base 合入 head（update-branch）而非「补测试」。
2. **「746 of 1,098 armed tasks 依赖幽灵脚本」是错的，真数是 50。** 原数字来自 `ak_scheduled_tasks LEFT JOIN ak_task_executions ... GROUP BY script_id` 的 task×execution 扇出。本会话以 `is_active=1` 无 join 逐 script 直查：26+16+4+1+1+1+1 = **50**，与 `SUBTASK_RECONCILIATION_20261105.md` §8 的 `script_file_absent: 50` 独立吻合。暴露面是 50/1,098（4.6%），但占那七套数据集的 100%。
3. **AC13「在自然 cron 运行中验证过围栏/claim」的记录撤销。** `run_coordinator.py`、`write_fence.py`、`app/models/akshare_scheduler.py` 本会话三连查（`git cat-file -e`、`git log --all`、开放 PR 清单）确认只存在于 orphan 字节码；该结果描述的是**未提交的代码**，不是仓库。且修复后 80 条 completed 执行产生 0 条 claim 行——当前部署根本没有 claim 写者。附带更正：wave28/属主队列前提「4,781 条 failed 带未来 `next_retry_at`」经现测为 **0 条**（4,781 条的 `next_retry_at` 全为 NULL，非终态 0，lease 未过期 0）；「先检查非终态 claim 再开协调器旗标」仍是闭合条件，但其风险面是 NULL 重试时间会不会被新实现当成可重试项，属主检查请按现测口径执行。
4. **OpenData #196 的 `quality gate` 红因是 accept­ance-probe 的新格，不是打印出来的 `VERDICT AC-1|05: gap`。** 本会话开读 `scripts/quality/acceptance_item_probe.py:20381-20406`（`reconcile_state`：台账非 proven 时 gap 读数是 `open`，只有台账 proven + 探针 gap 的 `stale-proof` 在 `--gate-check` 判红，`:20565-20575`）与台账 `docs/quality/acceptance-item-ledger.json`：`AC-1|05|db9002ff` state=`gap`（台账自己已记为缺口，故被容忍）；`AC-5|07|68f3347f`、`AC-17|08|e4388047` state=`proven`，而 `docs/quality/acceptance-gate-ratchet.json` 的 7 钉不含这两格——#196 head 让它们以未钉状态读出 gap，才是门禁红。红 run 的具体 CI 日志行本会话未重取（该 head 当前 run 为 queued），机制与台账状态均已核实。

## 4 属主待办队列（去重排序，含所需资源）

1. **AC17 前置**：给一个可 `CREATE DATABASE` 的 MySQL 账号或 owned 实例（当前 `backtrader_web` 凭证 1044 拒绝建库；docker 未装）。没有它，隔离恢复演练在本机永远不可执行。
2. **两个幽灵 alembic revision** `20261019_akshare_enum_values` / `20261019_akshare_scheduler_claims`：重 authored 或正式宣告「不可复现」并归档库/仓永久分叉的说明——禁止臆造 `upgrade()`。资源：当时部署的知情来源或属主宣告。
3. **AC13 协调器开旗标前**：属主按现测口径检查 `ak_task_run_claims`（24,345 completed / 4,781 failed，`next_retry_at` 全 NULL，非终态 0），裁定旧行只读结转、新实现不得据此重试；随后部署默认-off 实现并跑 §AC13 七连测。资源：部署窗口 + 一次可控的双调度器演练环境。
4. **50 个 ghost-backed armed 任务**（fund_monetary_income_history 26、forex_hist_sina 16、fund_reviewed_unit_nav_history 4、三个 option_daily 各 1、etf_realtime_quote_sina 1）：源模块恢复或重写，否则它们在 2026-11-06 首个槽位起将持续失败；72 个 orphan pyc 逐个给「恢复/重建/宣告不可复现」。资源：幽灵代码档案（已存 `/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/`）+ 属主裁定。
5. **AC14 钟的启动**：合入并部署 #280（超时 1800s 下限 + 可杀子进程），确认 task 1049 连续 completed 后小时钟起算；同时接受「48/7/2/1」只能靠日历时间累计。资源：一次部署重启窗口（含约 70 s 冷启动）。
6. **OpenData AC-5|07**：走 CI 侧 bandit 证据重跑续期（24 h 时效窗口），**不得**用笔记本生成的档案入账（`DEVELOPMENT_STATUS.md:2077`、棘轮 sync 协议 `:2104-2108`）。资源：OpenData CI dispatch。
7. **6 个已裁定降级的验收棘轮钉**（AC-5|03、AC-11|04、AC-16|05、AC-16|06、AC-17|03、AC-17|06；dev 文件现含 7 钉，AC-16|08 待 #195 sync 后落为 6）：属主 2026-11-05 已逐项裁定维持，勿被后续代理当「待修代码」重开。资源：无（裁定已在册，见 Wave 25 §4 / Wave 26 §2-3）。
8. **1,098 armed 全量是否为制度本意**（`RUNTIME_REPAIR_20261105.md` §8 遗留）：源配额与 AC13 跨进程预算是活问题；`scheduler.py:132` 只按 `is_active` 武装，无白名单。资源：属主一句话 + 如需收敛则批量 `is_active` 变更审批。
