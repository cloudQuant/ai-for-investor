# 迭代204：按真实数据集闭环推进的迁移计划

本文把迭代204从“做了哪些代码和平台部件”改成“每类旧能力是否有可验证的新去向”。它补充执行顺序和五人分工，不覆盖或改写原始任务清单；任务状态只能按本文的验收证据逐项更新。

## 目标与现状基线

目标仍是把 ai-for-investor（AFI）的基础数据采集、清洗、仓储、治理、任务管理和数据查询迁到 `/home/yun/Documents/opendata`。OpenData 复用当前自研 Provider 架构，通过 REST 为 AFI 提供数据；AFI 保留投研、策略、回测、交易和用户业务。用户已确认 AkShare 与 Fuyao 可用于本项目，不在本计划中重复征求授权确认。供应商/产品、具体函数或接口、字段语义、市场和历史边界仍须逐数据集登记，用户声明也不能代替运行证据。

现有盘点不能作为当前实时分母：2026-10-26 的逐文件 CSV 有 **1,066** 个脚本条目，其中 **0** 项标为完成（1,056 项为待盘点/待映射，10 项待辅助审查）。历史数据库快照为 **1,103** 个任务；历史迁移 dry-run 为 **1,103 BLOCKED、0 ready**。之后的记录指出这仍是历史快照，且部分盘点没有重新查询数据库。因此不能据此断言当前仍恰有这些脚本/任务，也不能断言现实中“绝对没有”已迁项目；开工先只读刷新运行清单，再建立各自日期和环境绑定的当前分母。

当前有已合入的 Provider、采集/归档、REST、AFI reader 等局部代码和合成联调；涉及迭代204的新采集/消费路径保持默认关闭，未证明生产部署和定时运行。已有 THS 单股票日线 R7 隔离结果只覆盖模拟链路，尚无真实 THS 请求、真实目标 MySQL、v1 REST 返回和 AFI 实际业务调用串成的闭环，也未据此切换旧任务（2026-10-31 补充：已有实现但硬禁用的 v2 日线读取路由和 AFI 固定 publication reader，二者仍未接通真实链路）。Fuyao 财报已有原始归档合同和 AFI raw-only 消费设计；mock/合成或已有样本回放不等于六个真实查询端到端验收。**当前不能把代码已合入、API 已存在、合成测试通过或少量历史样本等同于生产迁移完成。**

本计划将范围明确为两个先行垂直切片；每个切片完成真实单标的闭环后再扩展标的和任务。全 A 股含北交所、退市证券及从各证券实际起点开始的完整历史仍为目标，不因首批切片而缩小。

## 五人分工与协作边界

五人并行开发可行，采用冻结接口、单一文件 owner、单一集成人。每个任务先分配唯一负责人；共享契约和迁移文件不可由多人并改。除根负责人外，其余四人各自负责一个清晰边界；代码 owner 不自动取得真实运行或切换批准权。

| 人员 | 唯一负责范围 | 不负责/交接约束 |
| --- | --- | --- |
| A：集成与台账 | 只读刷新 AFI/OpenData 的脚本、任务、数据集、消费者、调度与 writer 清单；定义统一迁移记录、冻结最小接口契约、维护分母和逐项状态；集成顺序、PR 和证据链接 | 不执行旧任务，不改 B/C/D 的实现文件，不因代码合并把任务标完成；契约改动先发布版本并通知其他 owner |
| B：股票日线采集 | OpenData THS 单股票日线 provider/job 接线、请求预算传递、数据转换以及 ODS/DWD 写入；保持现有任务 disabled，提供有界真实采集方案和样本血缘 | 不改 REST route、AFI 文件或共享 migration；REST 端字段/单位不一致先交给 A/D 冻结，不在 collector 内临时改合同 |
| C：Fuyao 财报采集 | OpenData 单股票利润表、资产负债表、现金流量表的 annual/quarterly 六查询编排、原始响应归档和失败/部分成功状态 | 不做财报标准化评分、PIT 推断或 AFI 代码；不与 B 共用并发真实采集额度；不改 D 的 route/store |
| D：持久化、发布和 API | OpenData 目标 MySQL schema/migration、ODS/DWD 或 raw archive 持久化边界、publication/REST 查询合同、MySQL 代表性读写及备份/恢复证据 | 不决定策略或财务评分语义；数据库/API 文件由 D 唯一修改，B/C 通过冻结 schema/API contract 交接 |
| E：AFI 消费与切换验证 | AFI OpenData client、真实业务调用点、读取身份、稳定错误、无静默旧源回退、旧读写点与每数据集切换清单；对已发布内容做受控影子对账 | 只改 AFI 消费端；不改 OpenData 生产代码或自行启用任务；读路径不把 raw 财报送入评分/回测 |

A 先完成只读分母和合同初稿；B/C/D 可在该阶段分别盘点自己的实现边界。契约冻结后，B 与 C 并行做互不相交的数据集工作，D 独立准备对应持久化/API 接口，E 用固定 fixture 并行开发 AFI 适配。集成人按依赖顺序组合：合同 → OpenData 写入/发布/API → AFI 消费 → 隔离端到端 → 有界真实影子 → 自然周期 → 单写者切换。每个 PR 只承载一种可审阅交付，不将失败或未验收工作混进已验收代码。

## 两个优先数据集闭环

### 切片一：THS 单股票日线

目标路径：**THS provider → OpenData 请求预算与 job → 目标 MySQL ODS/DWD → 已有 v1 stock_daily REST → AFI 实际行情消费者**。先选一只已确认身份、交易所和有界日期窗口的证券；实现和隔离验证可用 synthetic fixture，真实运行单独记录，不扩大成全市场下载。先核对当前 DWD 字段、交易日、价格/成交量/成交额单位、复权基准和 v1 response contract；v1 是首批兼容路径，不应将其描述为 immutable historical snapshot。

R7 只作为隔离模拟的起点。完成此切片必须补齐真实来源响应、真实 MySQL 临时或隔离目标库提交、相同数据可通过 v1 REST 读取、AFI 真实 adapter/业务调用接到该响应的证据。真实调用的来源函数、请求参数和接口授权需与用户已确认的来源范围逐条映射；未能确认实际调用边界时将真实源步骤留为 `SOURCE_LIMITED/NOT_RUN`，不以 provider 名称或模拟结果代替。观察已有持久数据并完成受控差异解释后，才考虑停用该数据集的旧 writer；其余 AFI 数据读取仍按各自状态处理。

验收收据应固定：AFI/OpenData commit、provider/model 和调用版本、来源请求与响应摘要（不记录密钥）、主体/标的身份、日期窗口/交易日历、原始行数和 hash、字段/单位及转换版本、MySQL 产品/版本和目标 schema、写前后业务键、重复与回放结果、REST 请求 ID/响应摘要、AFI 消费调用点、旧/新差异及原因。来源分页或证券历史边界未知时，coverage 仍为 `UNKNOWN/PARTIAL`；单股短窗只关闭该次窗口的采集与消费验收。

### 切片二：Fuyao 单股票财报原始证据

目标路径：**Fuyao → OpenData transport/fetch → raw archive 持久化与固定 capture/publication → AFI 财报归档 REST consumer → 股票分析报告的 raw evidence**。对一个身份明确的标的分别执行利润表、资产负债表、现金流量表的年度和季度请求，合计六个查询。复用现有有界请求/响应限制和固定 selector/capture；逐查询保存成功、空、部分成功或失败，不将“六个都发起”视作“六个完整”。

AFI 当前 consumer 设计为 raw-only：年报/季报原始归档保留来源字段、报告期、披露日期、观察时间、原生数值文本和单位；不得自动转换为标准财务特征、评分、信号、回测输入或 PIT 历史。当前读取窗口不等于全历史；披露时点和修订/重述语义尚未证明前，分析结果继续标记不可用于决策或 PIT。任何查询失败、权限错误、字段变更或 archive 不可读都返回稳定状态并保留证据，不回退到 AFI 直连来源。

验收收据应固定：六个查询的 scope 和参数摘要、source_id/接口版本、主体与 grant revision、请求/响应时间和摘要、逐个响应体 hash 与大小、原始实体字节存储地址及校验结果、parser/schema 版本（若仅归档则明确无数值转换）、capture/publication 标识、失败/部分状态、REST snapshot/vector 和 AFI 报告工件 hash。报告确认 raw evidence 可见，并确认该内容未进入评分和 PIT 输入。此结果仅验收单标的六查询窗口，不说明财报完整历史或全 A 覆盖。

## 执行阶段和真实运行控制

| 阶段 | 交付与负责人 | 通过后状态 |
| --- | --- | --- |
| 0. 只读刷新基线 | A 汇总，D 提供 OpenData 注册任务/调度器/worker/数据库表和运行版本快照，E 列 AFI 页面、API、后台任务、reader、直接源和仓库读取；B/C 对应数据集补充静态 provider 与 job 线索。只读数据库导出，禁止触发 task、启停 schedule、写库、调用供应商。 | 得到日期/环境绑定的四类清单：脚本、task/occurrence、dataset/sink、consumer/callsite，并有 anti-join 差异；历史 1,066/1,103 只作对照基线。 |
| 1. 合同和最小测试 | A 冻结两个 dataset 的字段、身份、时间、单位、错误和分页合同；D 确认 MySQL 表/索引/REST 读取；B/C 实现自己的 job；E 建 AFI 消费适配。 | synthetic 测试只标 `CODE/OFFLINE`；不得登记为真实迁移。接口冲突、身份不明、单位不明则阻止对应真实步骤。 |
| 2. 单标的真实闭环 | 先在隔离目标库逐个执行有界 THS 和 Fuyao 切片；每次运行由 A 分配 run identity，B/C 只各自运行自己的 source job，D 观察隔离库，E 仅通过 AFI client 读已发布 REST。任何真实请求使用预先登记的请求预算、只读/写入边界和停止条件。 | 一次闭环独立标记 `REAL_SOURCE`、`MYSQL_WRITE`、`REST_READ`、`AFI_CONSUME`；有步骤未运行就明确记录，不用部分成功打包成端到端通过。 |
| 3. 受控影子对账 | E 比较 AFI 当前读结果与 OpenData 固定 publication/API；A 记录业务键级差异。优先对照已归档/现存只读数据，避免为 shadow 并行触发另一套旧采集造成双写或重复源请求。价格、成交量、单位、调整基准、财报报告期、披露日期逐项解释，未知就保留未知。 | 影子差异有分母、差异数量、原因/责任人和接受标准；仅已验收数据集进入切换候选。 |
| 4. 单写者与自然周期 | D 与运维 owner 固定每个 `dataset × sink/partition` 唯一 writer 和 owner epoch；E 先将指定 AFI consumer 指向 OpenData；旧任务停止新 claim、排空在途任务并确认旧凭证/进程不能继续写同一目标。观察至少一个该任务真实预期的自然调度周期及对应 watermark/告警/重试恢复。 | 分数据集记录切换时间、旧 writer fence、OpenData run、publication、AFI 读、监控、回滚动作与自然周期收据。若未观察自然周期，仍是 `CUTOVER_PENDING`。 |
| 5. 扩围 | A 按新的权威证券分母、活跃/退市生命周期和数据集分别拆出 cohort；B/C/D 扩采集和容量；E 扩消费场景；D 评估数据库、索引和恢复。 | 每次只扩大有证据 cohort。全 A 完成要求包含北交所和退市证券且逐标的×数据集核验实际起点至目标终点的 head/interior/tail；缺一项就保持开放。 |

每个真实任务/run 的身份字段至少包括：legacy task ID（若有）、脚本路径及 hash、脱敏参数 hash、cron/timezone/calendar、active 状态和 occurrence、source/provider/model/endpoint、请求预算、canonical instrument 和身份版本、dataset/schema、业务窗口、run ID、worker/owner epoch、目标 DB/schema/table 标识（不含凭据）、raw/source receipt、转换版本、ODS/DWD 行数和业务键摘要、publication/capture/vector、REST request ID、AFI consumer/callsite 与请求主体/grant revision、结果/报告工件 hash、开始结束时间、状态和失败码。无 legacy task ID 的手工 run 也要有不可复用的 run identity。凭据只用受控引用，日志、manifest、工件中不存明文 key 或完整敏感响应。

影子观察期间同一 dataset/sink 只允许一个写者。不要通过同时运行旧新生产定时任务来“比较”；比较读取当前已提交旧数据或同一份获准的已归档来源响应。若必须向同一上游发两次请求，先满足预算、间隔和授权约束并单独记录，不能把两次请求当作独立来源真值。切换停止条件包括：身份/业务键冲突、单位或字段映射未知、缺口无法解释、publication 与数据库不一致、REST 超时/权限错误、旧 worker 未排空或重复 writer。回滚按既有 runbook 执行并留证，不删除已提交来源和 publication 证据。

## 进度分母与“迁移完成”口径

A 每次刷新后分别公布分母和状态，禁止把它们合成一个含糊的完成百分比：

| 口径 | 分母来源 | 一项何时记迁移完成 |
| --- | --- | --- |
| 脚本 | 当前全入口源文件清单，含主脚本、helper、动态调用、运维脚本和调度脚本；文件身份按路径+hash | 旧脚本用途已映射到目标 dataset/job，替代行为被相同业务场景验证，旧入口已禁用/移除或有明确暂留理由；单纯复制或登记不算 |
| 任务 | 当前真实任务 registry、systemd/crontab/worker/task occurrence 合并后去重的任务清单；active/inactive 均单列 | 有新 job/version、唯一 owner/writer、可恢复 run/checkpoint、自然周期和停止/回滚证据，旧任务处理明确 |
| 数据集 | 去重后的 `source × model × market/universe × frequency × schema × sink` 业务数据产品 | 真实数据语义、MySQL 持久化、质量/缺口状态、REST 发布/查询和读者验证均闭合；synthetic/API 单项通过不算 |
| 消费者 | 每个 AFI API、后台任务、页面、策略/研究/回测/扫描/信号 callsite，含缓存/文件/DB 直读 | 只按 OpenData REST 取得已声明范围的数据，错误和权限正确，语义/业务回归通过，无未授权源或仓库 fallback；raw-only 数据仍不得进入评分/PIT |
| 切换单元 | 每个 `dataset × sink/partition × writer` 的切换记录 | 单写者 fence、受控影子差异、真实自然周期、监控、备份/恢复和回滚证据齐全 |

每项使用 `NOT_INVENTORIED`、`MAPPED`、`CODE_OFFLINE`、`REAL_SOURCE_PENDING`、`MYSQL_PENDING`、`REST_PENDING`、`AFI_PENDING`、`SHADOW_PENDING`、`CUTOVER_PENDING`、`ACCEPTED`、`SOURCE_LIMITED` 或 `RETIRED_WITH_EVIDENCE` 等状态。`ACCEPTED` 只作用于具体对象与范围；记录证据链接、精确 commit、验证日期、负责人和限制。总进度用各类分子/分母分别呈现；一个脚本可对应多个任务/数据集，一个数据集可服务多个消费者，禁止跨口径相加或用 PR 数量当分子。

## 当前开放项和停止条件

- 当前任务/脚本/消费者运行态清单需要只读刷新；旧快照不足以声称当前总数与迁移比例。
- THS R7 是隔离模拟；待补真实来源、目标 MySQL、v1 REST、AFI consumer 的一条身份绑定证据链。
- Fuyao 三表六查询的端到端归档与 AFI raw evidence 需要真实闭环；既有 mock 和受限样本不能证明完整六查询、PIT 或全历史。
- 北交所接口/证券目录、退市与跨板生命周期、来源实际保留边界及真实数据质量仍未知。对 AkShare 的用户声明不自动确定每个底层 endpoint 或字段语义；逐项映射后记录。
- 定时任务是否部署、启用及何时成功，必须通过当前只读运行清单和后续自然周期证据证明；本计划本身不启用任何任务，也不代表已经部署。
- 财报 PIT、版本/修订规则、行业评分、成交量单位/复权语义等未验收前，保持限制并禁止静默归一化、评分或回测使用。

本迭代按可交付的真实数据闭环逐步推进。可以并行做有明确文件 owner 的工作，但优先级始终是先让一个真实数据集完整走完采集、存储、REST 和 AFI 消费，再扩展脚本、证券和任务范围；安全/测试基础设施只做到足以安全验收当前切片，不作为无限期推迟业务交付的理由。

## 2026-10-31 当前前沿与下一步

本节按 2026-10-31 两仓 `dev` HEAD 的合入内容记录，不包含工作树未提交改动；任何后续验收仍须重新绑定实际 HEAD。

### 已实现的代码/离线前沿

- 股票日线 v2 读取路由已实现但**硬禁用**：OpenData #146 的 `/api/v2/stock-daily/records` 固定 publication/snapshot/cursor 语义，但依赖强制返回 404，且不在 OpenAPI 中。
- AFI 已有**固定 publication 读取器**：#202 新增 provider 方法与独立 reader，校验请求、publication/sequence、行、单位与 coverage；未接业务任务、授权或 fallback，且上游路由仍禁用。
- 已有可作为补采规划输入的**离线缺口对账**：#145 从调用方证据目录输出确定性 head/interior/tail 报告，不访问数据库/网络，不生成补采计划，也不执行补采。
- 已有**模拟 THS 的 MySQL 竖向验收夹具**：#149 的 opt-in e2e 在专用 MySQL 8 上走 job→ODS/DWD→v1 REST，THS HTTP 仅用 `MockTransport`；提交/文档未记录其实际运行通过。
- 已有**请求预算传递**：#147 支持单个 THS `stock_daily` job 的进程内预算；#136–#140 提供一次性 gate、quota provisioning 和 transport 限定。

以上均属 `CODE/OFFLINE`，不包含 `REAL_SOURCE`、`DEPLOYMENT`、`NATURAL_CYCLE` 或历史覆盖证据。

**2026-10-31 工作树增量（未提交，未合并）**：

- 容量/部署门禁已实现为默认关闭的 digest-pinned attestation（`opendata/api/stock_daily_capacity.py`），仍不是生产启用；40 项定向测试通过。
- 跨仓固定 publication wire 已用合成数据通过（9 项）；并用此前捕获的真实 Eastmoney 响应做离线回放，10 行经 job→publication→真实 v2 路由→AFI reader 通过（9 项）。回放没有重新请求来源。
- 股票日线精确 grant 存储/策略已扩展到 `cn-equity-stock-daily`/`akshare.daily`，并新增默认关闭的读取前/响应后授权 adapter（138 项定向测试）。仍无签发/撤销 API、生产 grant registry、业务任务接线或报告保存前复核。
- 回补执行器/CLI 已实现逐分片可恢复、失败停止、dry-run 默认和 `execution_only` 任务（49 项定向测试；容量、执行器与共享回归合并 434 项通过）。它只做本地 ledger/离线 fixture，不接真实来源、生产 MySQL 或调度。
- 上述结果只把股票日线切片推进到 `CODE/OFFLINE` + 真实捕获字节回放；容量门禁不是数据授权，回放不是实时来源，执行器不是调度器。

### 剩余关键路径（按顺序）

1. ~~显式的容量/部署门禁~~：代码已实现并默认关闭；仍需在目标部署环境完成操作者证明、时钟/数据库/容量核验后才能启用。
2. ~~跨仓固定 publication 的 wire 验收~~：合成 wire 与真实捕获字节离线回放已通过；仍需实时来源与生产部署下的同链证据。
3. 精确的 stock-daily grant/授权：存储与 adapter 已具备默认关闭的代码路径；仍需真实用户 `READ_DATA`、来源研究 grant 的签发/撤销、后台执行与报告保存前复核。
4. 真实且受限的来源样本：一次有界的 THS/AkShare 实时请求，记录参数、响应摘要、字段/单位、观测时间和来源边界；现有真实捕获回放不能替代。
5. 生产 MySQL/部署：在目标环境完成迁移、读写、权限与恢复证据。
6. 受控影子对账：只读比较旧数据与新 publication，逐项解释差异。
7. 单写者切换：停止旧 writer 新 claim、排空在途任务并 fence 旧凭证/进程。
8. 自然周期：观察真实调度周期及 watermark/告警/重试恢复。
9. 全 A 历史：按权威分母逐 `instrument_id × dataset_id` 核验实际起点至目标终点。

### 外部阻塞

- 实时 THS/Fuyao 的一次性 transport/额度集成与操作者批准；本地声明和 mock 不能替代。
- 真实来源的授权、保留期限与再分发范围证据；`USER_DECLARED_UNVERIFIED` 不是授权验收。
- 权威北交所/退市证券全集及跨板/换码生命周期。
- MySQL/InnoDB 生产行为（并发、崩溃恢复、备份/恢复、权限边界）。
- 自然调度周期与全历史回补的实际执行容量。
- 备份/恢复演练和单写者回滚证据。

在取得对应证据前，各步骤分别保持 `REAL_SOURCE_PENDING`、`MYSQL_PENDING`、`REST_PENDING`、`AFI_PENDING`、`SHADOW_PENDING`、`CUTOVER_PENDING` 或历史覆盖 `UNKNOWN/PARTIAL`；不得用代码合入、合成测试或单次短窗口样本替换这些状态。

## 依据

- [现有迭代总览](README.md)
- [实施任务与五人分工原表](IMPLEMENTATION_PLAN.md)
- [初始盘点及逐脚本 CSV 说明](INVENTORY.md)
- [逐脚本静态清单（2026-10-26 快照）](script_migration_inventory.csv)
- [消费者迁移现状](CONSUMER_MIGRATION.md)
- [财报 raw-only 消费边界](FINANCIAL_ARCHIVE_CONSUMER.md)
- [股票日线 v2 交付计划与生产门槛](STOCK_DAILY_V2_DELIVERY_PLAN.md)
- [验收与切换门槛](ACCEPTANCE_AND_CUTOVER.md)
