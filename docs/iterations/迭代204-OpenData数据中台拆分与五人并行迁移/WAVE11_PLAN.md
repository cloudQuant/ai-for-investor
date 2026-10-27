# 第十一批 Sina 单标的采集快照发布计划

日期：2026-10-27（Asia/Shanghai）。状态：**CONTRACT_FROZEN / SCOPED_OFFLINE_CLOSED / NOT_PRODUCTION_APPROVED**。13文件核心回归、scoped static、OpenAPI、A2、full-history secret、182文件私有归档、两个公开metadata、公开JSON复扫及独立归档审查均通过。本批按显式 `instrument_id + capture_id` 发布并读取单次Sina资产负债表响应；它不注册或启用采集任务，也不把有限快照提升为完整财务历史。当前收据索引见[WAVE11_STATUS.md](WAVE11_STATUS.md)。

## 冻结依据与范围

root冻结合同 `/tmp/od204-receipts/wave11-frozen-instrument-capture-contract.txt`，SHA-256 `92b93a1ac120afeb926106da91d98ebd908d8c541b4b76da7428fa6990da53b9`；合同评审 `wave11-root-contract-review-v2.txt` SHA-256 `8c45d607230c0d126108c4f3ee20c938294bc53c9ba23e8e8e276f910e6bb4aa` 为GREEN。评审只批准冻结该实现合同，不代表测试接受、来源使用/留存权利或生产批准。root决策所据OpenData runtime base为`1bd226690acd7e4bbd620a480f7e6271c38297fd`，W10 metadata closeout为`8b721c69c762659ea9f300497ad1695ff73eec5e`。此前v1/v2/v3架构稿及serializer可行性报告是历史材料；实现遵循冻结合同与decision，不另行兼容旧提案。

reserved profile仅由精确有序的 `filter_fields == ('instrument_id', 'capture_id')` 标记。它要求TABLE、temporal none、无time field、PIT unsupported，两个非空字符串字段进入business key与ordering。`instrument_id`为1–128字符并满足冻结ASCII标识正则，`capture_id`必须为小写64位SHA-256 hex；pair必须同时出现。其他filter tuple保持legacy行为。此标记只定义capture级选择，不能替代grant或成为行级授权。不得修改 `DatasetContract` 模型默认值、序列化或既有canonical hash。store中的pair必须作为显式metadata与顶层payload值一致；仅`ValidatedPublicationWriter`的reserved-profile路径可在生产适配层填入，legacy记录不得从相似payload字段推断。低层store API是可信内部SPI，不是授权边界。

migration为nullable成对selector列和有界复合索引；旧数据保持NULL，不从JSON猜测回填。对同一dataset/business key，selector tuple不可变，检查必须在unchanged-hash短路之前执行。未选择记录不序列化selection null键，保持旧发布hash、未选择snapshot hash和cursor-v1字节；selected snapshot hash和cursor-v2绑定精确pair。REST沿用现有授权检查，并在任何store访问之前完成；persisted snapshot续页可省略selector，若重复则必须成对且一致。selected响应在snapshot/page/meta描述中均携带同一`selection`；日期窗固定为`{start:null,end:null,end_exclusive:true}`且行的`business_date`为null，`report_period`只属于payload/business key，不是selector。legacy响应完全省略`selection`成员。API和client对profile错配、空pair snapshot、坏cursor等均fail closed。

W9 parser的正向录制样本含103个报告期和14,523个源行出现次数，全部属于**一次capture**。这不代表Sina、任何股票、所有报表或历史区间的总体，也不证明分页、留存、单位、修订、PIT、权利或历史完整性。producer只将捕获的response bytes解析为source-native `sina_fzb_report_observations` batch，保留源值/状态、时间、metadata、entry顺序与ordinal；不发HTTP、不依赖W10候选投影、不做provider/grant/task注册或激活，不接入`FinancialStatement`/DWD/PIT，也不声称W9 wire seam已连接raw-body IPC。

用户指定的股票cohort仍待明确。本批generic offline设计不假设录制样本对应标的、600519、全A股或其他实际生产范围。W12另行处理raw-body IPC、有限标的/请求预算、source rights/retention及归档容量；在这些条件解决前，不得将本批离线能力投入真实采集或对外提供数据。

## 当前集成检查点

早期集成锚点`edfe1557adb0607945baab9678561fa3c82e7a69`包含七个production modules和六个新增测试文件；之后shared/helper、migration、producer、client及bridge修正已独立review并集成。最终13文件核心组合在source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`取得469 passed、1 deselected、0 warnings，八个production targets均达到模块coverage floor。当前source上的9 production+7 new test files scoped static和OpenAPI专项亦PASS；详细coverage、失败历史及收据见[WAVE11_STATUS.md](WAVE11_STATUS.md)。53-pin hermetic environment的安装审核和外部guard probe（9 passed、0.10秒）是独立结果，不替代核心运行。A2组件通过（1,222 complete-resolver files、796 unique mypy roots），Gitleaks full-history组件扫描976 commits、0 leaks；历史Ruff、blocked archived candidates与manifest errors仍按既有policy保持OPEN，不是完整`make gate`结果。W11私有归档、公开JSON复扫及独立归档审查均通过，档案与收据见[WAVE11_STATUS.md](WAVE11_STATUS.md)。本批source锚点是OpenData `fbec7066...`，不表示后续AFI W12集成在新的AFI HEAD上重新通过W11测试。Python 3.10 runtime、完整`make gate`、remote CI及生产接受仍OPEN。

## 独占开发流

实现流使用隔离worktree和独立branch。helper、store、API、producer与client各自只编辑owner文件；共享schema、migration、质量census、OpenAPI和集成由root串行控制。

| 流 | owner · branch · worktree | 独占实现面 | 当前情况 |
| --- | --- | --- | --- |
| selector helper与validated writer | `architecture_review` · `codex/od204-wave11-capture-contract` · `/tmp/od204-wave8-reference-publication` | `opendata/data/capture_selection.py`；`opendata/pipeline/contract_publication.py` | shared/helper独立review GREEN并集成；最终核心覆盖100.0000%/99.5327%，均达标。 |
| 发布store与snapshot | `dev_inventory` · `codex/od204-wave11-capture-store` · `/tmp/od204-wave2-publications` | `opendata/pipeline/publication_store.py` | 独立review GREEN并集成；最终核心覆盖94.1392%，达到模块floor。 |
| published-data REST | `review_http` · `codex/od204-wave11-capture-api` · `/tmp/od204-wave2-api` | `opendata/api/published_data.py` | 独立review GREEN并集成；最终核心覆盖89.6552%，达到模块floor。 |
| Sina source-native producer | `wave5_frames_review` · `codex/od204-wave11-sina-publication` · `/tmp/od204-wave8-table-api` | `opendata/data/providers/sina/financial_statement_publication.py` | 独立review GREEN并集成；仅从W9 parser结果构造bounded batch，不接HTTP/runtime注册；最终核心覆盖90.8088%，达到模块floor。 |
| typed client | `dev_coverage` · `codex/od204-wave11-capture-client` · `/tmp/od204-wave2-client` | `opendata_client/opendata_client/snapshots.py` | 独立review GREEN并集成；分页fixture修复经最终核心回归确认，覆盖90.0533%，达到模块floor。 |

分离的测试工作树由`wave6_http_boundaries`（producer，`/tmp/od204-wave6-http-boundaries`）、`wave6_budget_boundaries`（store，`/tmp/od204-wave6-budget-boundaries`）和`dev_ledger`（migration，`/tmp/od204-job-definitions-migration`）维护。root独占`alembic_data/versions/20261027-0012_instrument_capture_scope.py`（revision `0012_instrument_capture_scope`，parent `0011_publication_snapshots`）、census、OpenAPI基线、跨流集成和测试选择。最终核心运行覆盖13个精确文件（production targets及合同、bridge和既有回归），结果为469 passed、1 deselected、0 warnings；一项既有unclosed-Engine回归明确deselect。root审核并更新OpenAPI v2 baseline（v1保持不变），当前独立OpenAPI门禁24 passed。当前9 production+7 new tests的8项scoped static组件PASS。A2组件1,222 complete-resolver files、796 unique mypy roots全部exit 0；Gitleaks full-history组件扫描976 commits、0 leaks。历史Ruff/archived-corpus errors按既有policy保持OPEN，结果不构成完整`make gate`。W11归档及公开JSON扫描、独立归档审查均通过；归档审核收据与公开metadata见[WAVE11_STATUS.md](WAVE11_STATUS.md)。前序v2/v3失败及修正见[WAVE11_STATUS.md](WAVE11_STATUS.md)。新建53-pin hermetic environment review与实际安装审计通过；外部guard实际9 passed/0.10秒仅作guard结果。

## 任务顺序与验收条件

| 任务 | owner与依赖 | 退出条件 | 状态 |
| --- | --- | --- | --- |
| W11-01 冻结profile、storage、REST和producer合同 | root、独立review | 冻结文件、决策和review SHA一致；字段、hash或兼容语义变化须重新review与freeze。 | **CONTRACT_FROZEN** |
| W11-02 selector helper与validated writer | architecture_review；01 | 严格pair/profile校验、reserved profile fail-closed；legacy写入不推断selector。 | **REVIEWED_GREEN / INTEGRATED / CORE_PASS** |
| W11-03 store schema与capture不变式 | dev_inventory；01/02 | explicit pair与payload一致；同business key的pair变化在hash短路前原子拒绝；按pair缩小候选后再作版本排名。 | **REVIEWED_GREEN / INTEGRATED / CORE_PASS** |
| W11-04 migration及downgrade保护 | root；01/03 | 成对nullable列、CHECK与索引；不回填旧数据；有selected数据时在任何DDL前拒绝downgrade。 | **REVIEWED_GREEN / CORE_PASS；migration coverage 100%** |
| W11-05 snapshot hash与cursor兼容 | dev_inventory；03/04 | 未选择hash/cursor-v1字节不变；selected hash/cursor-v2绑定pair且版本不混用。 | **REVIEWED_GREEN / INTEGRATED / CORE_PASS** |
| W11-06 REST选择和授权顺序 | review_http；02–05 | 首次capture请求要求pair；snapshot-id续页只接受缺省或完整相等pair；错配和无pair reserved snapshot fail closed；授权先于store。 | **REVIEWED_GREEN / INTEGRATED / CORE_PASS** |
| W11-07 typed client | dev_coverage；06 | selector类型/响应/行校验；selected TABLE-none空时间窗、null business date及page/meta/row scope一致，legacy响应保持兼容。 | **REVIEWED_GREEN / CORE_PASS；client coverage 90.0533%** |
| W11-08 Sina source-native producer | wave5_frames_review；W9 parser + 01/02 | 固定schema、UTC retrieval与源+08:00更新时间、规范digest及大小/深度限制；整份输入验证后返回，不丢reports/items/markers/ordinals。 | **REVIEWED_GREEN / CORE_PASS；producer coverage 90.8088%** |
| W11-09 producer边界测试 | wave6_http_boundaries；08 | 正向覆盖单次录制capture全部103期和14,523次源行出现；负向覆盖身份、时间、格式/限额和无部分batch。 | **INCLUDED / CORE_PASS** |
| W11-10 store与snapshot测试 | wave6_budget_boundaries；03/05 | 双capture隔离、后续发布不改变旧snapshot、pair移动原子拒绝、retry scope/body冲突及legacy golden hash/cursor字节。 | **INCLUDED / CORE_PASS** |
| W11-11 migration测试 | dev_ledger；04 | owned临时DB验证upgrade、旧数据保留和selected数据下拒绝downgrade；不使用默认DB/Alembic环境。 | **INCLUDED / CORE_PASS** |
| W11-12 REST/client权限与兼容测试 | review_http、dev_coverage；06/07 | malformed/half pair、profile mismatch、snapshot续页、legacy字段省略和grant检查顺序；selected descriptor/page/row范围一致。 | **INCLUDED / CORE_PASS** |
| W11-13 root集成与独立复核 | root、reviewers；02–12 | 逐文件review/hash pin；root审核import graph、隔离环境、OpenAPI、census和精确组合结果，并冻结收据。 | **SCOPED_OFFLINE_CLOSED；所有批内QA与归档审查PASS** |

关键接受场景至少包括：两次capture不可串读；后续publication不改写已创建snapshot；改变同business key的selector被事务性拒绝；改变scope的retry key冲突；未选择旧hash/cursor保持golden bytes；查询/续页授权先于store；未选择响应不输出selection键、selected响应各descriptor一致；录制输入经真实`RunService`/`ValidatedPublicationWriter`路径保留全部行；坏响应或超限输入不生成部分发布或watermark；迁移升级和downgrade保护符合冻结合同。coverage按root冻结的现有规则报告，失败不得通过临时降低门槛或增加排除处理。

## 运行隔离与仍开放范围

测试作者只负责独占文件与静态检查。新建53-pin hermetic environment及独立安装审计通过；root已review shared/helper与bridge变更、锁定source pins并完成13文件核心回归。该运行使用有限环境变量allowlist、空工作目录和owned临时SQLite/ASGI或内存边界；不得导入`app.main`、触发默认数据库/调度器、读取`.env`、访问实时Sina/其他网络源或连接外部数据库。Migration使用owned测试库，不用默认Alembic环境。OpenAPI v2 baseline review与focused gate已完成，v1保持不变；当前scoped static、A2及full-history secret通过。W11归档、公开JSON复扫及独立归档审查均通过。A2已报告的历史Ruff与archived-corpus errors按既有policy保持OPEN；结果不构成完整`make gate`。外部guard 9 passed/0.10秒是单独guard结果，不计入核心测试。W12正处于并行实现与集成阶段，执行验证尚待完成，不在本批验收范围；v2/v3失败收据须原样保留，不能由后续运行覆盖。

本批不改变父级87项矩阵：8 `DEV_DONE`、9 `IN_PROGRESS`、70 `PLANNED`。1,103个旧任务、1,066个脚本候选、全部消费边界、source rights/retention、完整历史head/interior/tail、金融单位与revision/PIT、自然周期、备份恢复、生产凭证和单写者切换仍OPEN。整仓`make gate`、remote CI和Python 3.10 runtime也不由W11 scoped结果替代。完整历史只有在来源确实能提供并获得授权时才能验证；snapshot-only接口不能补造未归档历史。
