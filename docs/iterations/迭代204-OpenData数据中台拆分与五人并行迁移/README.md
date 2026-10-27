# 迭代204 OpenData数据中台拆分与五人并行迁移

编制日期：2026-10-27（Asia/Shanghai）。当前状态：**AFI PR #52/#53 与 OpenData PR #5 已合入 `dev`。PR #5 只交付默认不接生产的 Sina 离线 enqueue/journal 组件：132 项 SQLite/scheduler-stub 测试通过，fanout pipeline 覆盖率 94%、journal pipeline 98%、合计 96%；0013 迁移仅有 SQLite 专项 44 项通过、覆盖率 79%，MySQL/PostgreSQL 未验证。真实 job 仍禁用且未经审查，grant 为 UNKNOWN，固定 manifest 只覆盖 SH/SZ；这些测试不是新浪真实采集或生产验收。** PR #53 的定向 21 项测试中，Provider HTTP 使用 `httpx.MockTransport`，其他依赖使用隔离 SQLite/stubs；隔离运行禁用了 timeout 插件，并产生 `timeout`、`timeout_method` 两项 pytest 配置警告。Sina 停机漏槽、日历对账/告警、全局配额、来源权利、BSE 和全历史仍开放；qfq 因子、成交量质量也未验收。详细进展见 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)。

AFI PR #56 已合入：新增默认关闭的 OpenData 上证50 benchmark reader；23 项 scoped 测试使用 HTTP mock/SQLite，并出现两项 timeout 配置警告。该范围尚未上线；`score_pending` ORM 持久化、生产数据源授权与落库、逐日历史覆盖及 Eastmoney 对比均未验证。个股 20 日收益可算、但 benchmark 不可用时，`outcome_status` 仍可能为 `scored`，相应的 `benchmark_*_return` / `excess_*_return` 字段可能为 null；原因只写日志，没有持久化原因或告警。此增量不改变全 A 与逐标的全历史仍待验收的状态。

波次历史摘要：W8—W11 的局部隔离验证及归档仍按对应状态文件保留；此前列出的覆盖率、收据和静态检查是历史范围证据，不代表当前 HEAD 整仓门禁或生产验收。当前 PR 与未完成范围以 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) 为准。

目标：将 ai-for-investor 的市场及研究基础数据采集、清洗、仓储、质量治理、调度和运维管理迁入 `/home/yun/Documents/opendata`。ai-for-investor 保留投研、策略、回测、交易和用户业务，通过 opendata REST API 消费数据。

**五人并行可行。采用“契约先行、五条工作流、小批持续集成、按数据集切换”的方式。** 建议核心链路分阶段交付，全部长尾脚本仍保留在总范围内；不能以七类资产页面可用代替每项脚本、任务、历史数据需求迁移完成。

用户已在本次讨论中确认：**沿用 opendata 自研 Provider 架构，不引入 OpenBB SDK 运行时依赖。** “适配 OpenBB”在本迭代中指对齐能力映射，将旧脚本改造成 opendata 的 Provider、Fetcher、数据契约和可恢复任务。实际数据源仍要逐项识别，AKShare 和 OpenBB 名称不能代替上游来源、许可及覆盖证据。

## 交付文件

| 文件 | 用途 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统边界、数据生命周期、REST 契约、存储、调度、安全与可观测性 |
| [SUBAGENT_TASKS.md](SUBAGENT_TASKS.md) | 87个可分派控制任务、依赖与验收面；逐批子范围进展单列 |
| [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) | 双仓隔离分支、提交、测试、限制与后续接线 |
| [WAVE2_STATUS.md](WAVE2_STATUS.md) | 11条并行开发任务、真实运行清单、事务决定、审查与剩余范围 |
| [WAVE3_STATUS.md](WAVE3_STATUS.md) | 执行器/证据/主机清单/提交/迁移预演/兼容门禁和wire身份修正 |
| [WAVE4_PLAN.md](WAVE4_PLAN.md) | 股票日线离线运行切片的5条并行流、冻结接口与验收门槛 |
| [WAVE4_STATUS.md](WAVE4_STATUS.md) | 第四批提交、独立复核、跨模块验收及保留限制 |
| [WAVE5_PLAN.md](WAVE5_PLAN.md) | 股票图表直读、MySQL worker、静态类型边界及局部验证门槛 |
| [WAVE5_STATUS.md](WAVE5_STATUS.md) | 第五批局部收据、组合重跑状态、测试范围审计及未关闭边界 |
| [WAVE6_PLAN.md](WAVE6_PLAN.md) | HTTP边界、请求预算、股票进程切片及资源清理的工作流与验收顺序 |
| [WAVE6_STATUS.md](WAVE6_STATUS.md) | 第六批局部测试、静态/A2、冻结归档、公开证据扫描及开放边界 |
| [WAVE7_PLAN.md](WAVE7_PLAN.md) | 管理员reviewed-run离线接线的四条并行流、契约、权限与root验收边界 |
| [WAVE7_STATUS.md](WAVE7_STATUS.md) | 第七批分项验证、失败保留、组合与静态门禁、归档审查及开放范围 |
| [WAVE8_PLAN.md](WAVE8_PLAN.md) | 股票标的目录REST接线的独占工作流、冻结契约、实现及12条财报脚本映射 |
| [WAVE8_STATUS.md](WAVE8_STATUS.md) | 第八批专项验证、增量发布兼容修正、锁文件环境及仍开放范围 |
| [WAVE9_PLAN.md](WAVE9_PLAN.md) | 第九批Sina资产负债表raw wire切片：冻结合同、四条独占开发分支及独立审查 |
| [WAVE9_STATUS.md](WAVE9_STATUS.md) | 第九批focused验证、首轮失败保留、冻结归档与独立审查状态 |
| [WAVE10_PLAN.md](WAVE10_PLAN.md) | 第十批source-qualified七项财务候选投影：冻结合同、工作包与未完成验收 |
| [WAVE10_STATUS.md](WAVE10_STATUS.md) | 第十批候选投影精确测试、scoped static、coverage及开放边界 |
| [WAVE11_PLAN.md](WAVE11_PLAN.md) | 第十一批Sina单标的采集快照：冻结合同、五条实现流、测试责任与验收边界 |
| [WAVE11_STATUS.md](WAVE11_STATUS.md) | 第十一批失败历史、核心复跑/static/OpenAPI/A2/secret证据、独立归档审查及开放边界 |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 五人职责、35项工作包、依赖、工期、共享文件与合并规则 |
| [ACCEPTANCE_AND_CUTOVER.md](ACCEPTANCE_AND_CUTOVER.md) | 验收案例、数据迁移、单写者切换、回滚与退出条件 |
| [INVENTORY.md](INVENTORY.md) | 两仓现状、逐脚本台账口径、完整任务盘点要求和历史遗留事项 |
| [script_migration_inventory.csv](script_migration_inventory.csv) | 当前源码脚本逐文件迁移起始台账；未将静态识别等同任务运行认证 |

## 目标边界

| 能力 | 目标归属 | 迁移方式 |
| --- | --- | --- |
| 外部数据源、Provider、源凭证、采集脚本、补数工具 | opendata | 按源与数据集适配，保留原始证据和断点 |
| 主数据、日历、历史库、源数据、标准化数据、版本、质量、覆盖 | opendata | 迁移存量并独立对账，治理后发布 |
| 数据定时任务、手动补数、执行历史、失败恢复、数据运维页面 | opendata | 复用已有控制台，补齐持久运行状态和单写者机制 |
| 行情展示、研究数据预检、回测数据准备 | ai-for-investor | 后端通过 REST 访问；前端继续使用业务后端 |
| 用户、投资组合、订单、持仓、策略、研究权限与评估 | ai-for-investor | 继续由业务系统管理；数据许可也须在输出场景校验 |
| 已冻结研究输入、回测工件、HTTP 缓存 | ai-for-investor 可保留 | 仅保存 REST 获得的不可变副本和 manifest，不再维护独立市场事实库 |
| 券商交易连接及账户状态 | ai-for-investor | 交易控制链保留；公共行情、研究行情读取迁出。实时交易时延要求另设明确门槛，不能暗中直连行情源兜底 |

所有七类资产、指数/基准、宏观、财务、事件、目录和既有非行情主题均进入盘点；分钟线、小时线、日线、快照和 CSV 导入分别登记能力。发现不支持的频率或历史必须显式报出，不伪造或静默降级。

## 现状决定实施顺序

- ai-for-investor 已有 HTTP `OpendataProvider`，但当前审查契约仅股票 `1d`，最多50,000行，仍接本地 store/publication 流程。不能仅打开开关就称为七类资产全量切换。
- opendata 已有 FastAPI 查询、独立 client、Provider 框架、ODS/DWD、API Key 和管理前端；先扩展这些能力。原生 provider-model 的特定持久化映射目前只有3个模型，这不代表整个仓库只有3种数据，也不代表全部350项已能落库。
- opendata 的350项上游 provider×model清单与 ai-for-investor 的旧脚本清单是不同集合。建立交叉映射，重用既有迭代2工作；不重复承诺实现整个 OpenBB 功能全集。
- 2026-10-26 11:38 UTC 的真实只读快照确认：1,103个任务中1,098个启用、5个停用；全部1,066条脚本注册的路径可解析，1,056个静态入口均有运行态映射。69个仍仅是此前精选子集；启用不等于质量通过。
- 当前 ai-for-investor 有大量未提交数据修复与恢复工具。开工基线必须包含工作树，不能仅从旧 HEAD 拷贝代码。迁移需覆盖 systemd、shell、补数worker和旁路采集。

## 建议里程碑与投入

| 阶段 | 参考时间 | 交付结果 |
| --- | --- | --- |
| M0 基线和合同 | 第1周 | 全量台账、数据所有权、API/任务/数据契约、开发基线 |
| M1 端到端样板 | 第2–3周 | 股票日线从采集、落库到 REST、研究快照完整走通；控制面可恢复 |
| M2 七类核心和管理迁移 | 第4–7周 | 核心资产、目录、覆盖、管理操作、消费者接入与影子对账 |
| M3 核心切换 | 第8–10周 | 核心数据集单写者切换、自然调度观察、恢复演练；长尾仍开放 |
| M4 全量长尾收口 | 第11–20周 | 逐脚本、逐任务、逐数据集适配、验证和退役旧入口 |
| M5 整体验收 | 第21–24周参考窗口 | 完整消费边界、全部任务去向、回滚与旧依赖退出；未满足则不关闭 |

按5人全职、约75%时间可用于实现/验证估算：基础工作约230–335人日，含20%缓冲约276–402人日，对应约15–22周有效产能；排期留至24周。**这是盘点前估算，不是承诺。** B/C两条适配线可能成为关键路径，第一周抽取20个有代表性的脚本实测复杂度后重估；旧源失效、源限制、历史恢复和真实自然周期可能延长工期。核心8–10周是子里程碑，不能被解释为全量完成。

## 完成必须同时满足的条件

1. 全部生产入口有唯一去向和证据，旧调度器/worker不再为已迁移数据集采集或写入；全量迁移完成后 ai-for-investor 无数据源 SDK 或仓库直连依赖。
2. 采集成功、质量通过、发布成功、消费可用、全历史覆盖分别可核验，未知起点与源限制单独保留。
3. 服务间只通过版本化 REST 及其下载接口交换数据，不共享数据库凭证、表、Python内部包或可变共享目录。
4. 回测/研究可以用固定数据版本重放；现有七类资产及对应功能无静默丢失。
5. 每个交付工作包、源验证、部署、连续运行、历史完整性都有独立状态。阻塞项保留原始需求与责任人；代码合并不等于发布和数据就绪。

## 依据

初始计划阶段对两仓工作树做只读代码与文档检查，未连接生产数据库、执行数据采集或改动运行调度。ai-for-investor HEAD 为 `c720a261c`，opendata HEAD 为 `61800c18`；前者存在未提交改动，源码哈希见逐文件台账。源码引用和历史记录见 [INVENTORY.md](INVENTORY.md)。引用的 `.joyincode/rules/backend.md`、`frontend.md` 在本地两仓未找到，实施开工时由A核对恢复位置；本次按根 AGENTS.md 和现有架构编写规划。

计划初稿校验记录：7份Markdown的本地链接与代码块检查通过；35个工作包、18个验收ID及其引用完整；1,066条CSV记录与源目录集合一致、路径唯一、逐文件SHA-256一致。两次独立方案复核已纳入能力边界、阶段依赖和交接崩溃恢复修正。此处是初稿时的校验记录；逐批当前收据和仍开放的门禁以 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)、[WAVE5_STATUS.md](WAVE5_STATUS.md) 与 [WAVE6_STATUS.md](WAVE6_STATUS.md) 为准。

OpenBB 官方明确其 Provider 是连接器，数据覆盖依赖具体来源；社区存在独立 AKShare 扩展。它们不能证明旧脚本逐项等价覆盖。[OpenBB Provider说明](https://docs.openbb.co/odp/v4/python/extensions/providers)、[AKShare扩展项目](https://github.com/finanalyzer/openbb_akshare)。官方V5文档还说明命名空间及部分Provider发生变化，故本项目能力映射须钉住参考版本。[OpenBB V5 Provider说明](https://docs.openbb.co/odp/python/extensions/providers)。本计划的组织和架构选择是针对现有两仓的设计建议，不宣称已通过外部标准认证。

第四批采用独立分支和worktree并行开发，root逐项复核、合并及组合验收；进度见 [WAVE4_STATUS.md](WAVE4_STATUS.md)。

第五批当前局部结果、最终组合与静态复跑、归档和范围审计见 [WAVE5_STATUS.md](WAVE5_STATUS.md)；没有任何局部结果关闭整仓门禁、全历史或生产切换条件。

第六批HTTP/request-budget边界组合为288 passed、1 deselected，两个目标模块覆盖率92.97%；worker资源清理专用测试21 passed。股票进程slice首轮root三文件测试161 passed、1 failed，测试fixture修复经review后合入；修复后三文件168 passed、两个目标覆盖均超过90%。root另运行69个显式文件组合，2529 passed、26 deselected，无报告warning。质量锚点`2464dd13839acc00f4102d551601af2de8d72a60`上Ruff/format、production mypy、Bandit、named gates及全量A2通过；A2范围之外的历史Ruff与证据缺口仍开放。821提交历史secret-check通过，两个新公开JSON随后由固定版本Gitleaks单独扫描，exit 0、0 findings；135文件私有归档和两个公开manifest已生成。详细范围与证据边界见 [WAVE6_PLAN.md](WAVE6_PLAN.md) 与 [WAVE6_STATUS.md](WAVE6_STATUS.md)。这些局部结果不改变第五批冻结收据，也不关闭完整任务清单、生产门禁或历史恢复要求。

第七批reviewed-run离线接线与证据归档已局部收口。OpenData前端6文件Vitest为29 passed，`npm run build`通过但保留chunk size warning；账本/身份9文件248 passed，runtime/API/app 4文件70 passed且各自目标覆盖达到门槛。Ruff/format覆盖120个Python文件、production mypy 61 core+3 client文件、Bandit 64个production文件、四个named gates、74文件combined（2,627 passed、26 deselected）及A2（1,200 resolver文件、786 roots全通过）均通过；861提交历史Gitleaks 8.30.1扫描0 leaks，两个公开JSON的后续独立扫描exit 0、0 findings。333个docs/evidence文件按既有A2策略排除，149,323条历史Ruff发现、5,130项support缺口和16项active-evidence缺失仍开放。106文件、10,544,281 bytes的Wave 7私有归档已生成，独立归档审查36项全部通过；3.10 grammar通过但3.10 runtime NOT_RUN，此前前端与API未达标尝试均保留。整仓`make gate`仍NOT_RUN。功能边界、具体收据和未关闭范围见 [WAVE7_PLAN.md](WAVE7_PLAN.md) 与 [WAVE7_STATUS.md](WAVE7_STATUS.md)。

第八批股票标的目录REST接线已局部收口：OpenData严格支持table/none参考表，AFI完整校验有界快照后搜索，并保持目录成员与行情可用性分离。OpenData专项112项、AFI锁文件子集环境专项203项、前端109项及真实producer/store/API/AFI跨仓bridge两项均通过，前端类型检查、构建和scoped static通过。增量发布中未变化行保留旧publication元数据的兼容问题已修复。当前A2静态1,203 resolver文件/787 mypy roots通过，历史secret扫描872提交0泄漏；162文件私有归档的25项独立核对全部通过。证据来自多个精确提交的分项运行，production字节pins一致，不是一轮current-HEAD组合测试。整仓make gate与生产验收仍开放；12条财报脚本仅完成静态映射。分工、证据与限制见 [WAVE8_PLAN.md](WAVE8_PLAN.md) 和 [WAVE8_STATUS.md](WAVE8_STATUS.md)。

第九批Sina资产负债表raw-wire切片已完成scoped offline gates：独立Python 3.13.5环境中的两个精确测试文件85 passed，三项新增data modules的statement+branch coverage均超过90%；scoped static、A2及894提交full-history Gitleaks也通过。80文件私有归档（2,064,005 bytes）已冻结，独立archive audit 24/24 checks通过；两个公开manifest的复扫为0 findings。来源权利、财务单位/修订语义、其他标的与完整历史、Python 3.10 runtime、remote CI及整仓`make gate`仍未验证。首轮失败和证据边界见 [WAVE9_STATUS.md](WAVE9_STATUS.md)。

第十批已完成scoped offline QA与归档审查：在root source `1bd226690acd7e4bbd620a480f7e6271c38297fd`上，唯一隔离测试文件65 passed，合同/projector coverage分别97.53%/95.36%；Ruff、format、mypy、Bandit、named gates及905提交Gitleaks组件均通过。49文件、766,405 bytes私有归档通过独立audit，复核此前W7/W8/W9共348个归档文件未变；两个公开manifest的secret scan为0 findings。Whole-resolver A2未为W10运行，整仓`make gate`、remote CI、Python 3.10 runtime与生产验收仍开放。合同和projector已集成，测试review与运行通过；候选始终是source-qualified、partial且保留原始证据的离线映射，不代表单位、权利、PIT或生产接入。**W10关闭时**，W11仍处设计阶段且合同未冻结；此后W11合同已冻结并进入实现，当前工作包与边界见 [WAVE11_PLAN.md](WAVE11_PLAN.md)。详情见 [WAVE10_PLAN.md](WAVE10_PLAN.md) 与 [WAVE10_STATUS.md](WAVE10_STATUS.md)。

第十一批最终核心回归在OpenData source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`通过：13文件469 passed、1 deselected、0 warnings，238.35秒；八个production targets的statement+branch coverage均达到模块floor。早期12文件运行332 passed、7 failed、1 deselected、6 warnings及producer/migration覆盖不足的结果仍保留为历史。最终source上9 production+7 new test files的8项scoped static组件通过；OpenAPI专项1文件24 passed、6.89秒，checker coverage 95.4693%，v1 baseline未变、reviewed v2 baseline已更新。A2通过（1,222 complete-resolver files、796 unique mypy roots），full-history Gitleaks通过（976 commits、0 leaks）。149,323条历史Ruff findings、5,055个blocked archived candidates及19项manifest errors按既有policy继续OPEN；不代表完整`make gate`。53-pin环境审计和external guard 9 passed、0.10秒为独立证据。W11私有归档`/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave11`共182文件、6,554,821 bytes、3个HTML ZIP，目录0700、文件0600；独立归档审查核验182/182文件、3个ZIP CRC与安全路径，共25项检查且0 findings，W7/W8/W9/W10既有397个归档文件未变。两个公开metadata已创建并复扫0 findings；metadata-only commit `aee076c83c1067a35da009fa2e8c061445401f72`与运行锚点分开记录。W11完成局部离线收口但未获生产接受。W10保持CLOSED；父级87项矩阵仍为8 DEV_DONE、9 IN_PROGRESS、70 PLANNED。W12目前并行实现与集成，执行验证待完成。source rights、生产cohort、全历史、完整切换、full `make gate`、remote CI及Python 3.10 runtime继续OPEN。详见[WAVE11_PLAN.md](WAVE11_PLAN.md)与[WAVE11_STATUS.md](WAVE11_STATUS.md)。
