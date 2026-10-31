# 迭代204子代理任务清单

本清单把 IMPLEMENTATION_PLAN.md 的35个工作包细化为2026-10-29计划快照中的98个子任务。该日记录的8个DEV_DONE、11个IN_PROGRESS、79个PLANNED，以及旧WAVE文档中的87项任务统计，均是历史状态快照；本清单尚未按之后合入的代码逐项重算。下方五张表原有任务的状态列均以2026-10-29为as-of，不是实时状态；本轮新增的 `204-B05-03` 标为2026-10-30计划任务，不纳入原98项或10/29状态分布。本文是执行拆分，不是当前完成报告。后续局部PR只更新其精确代码/离线范围，不自动完成对应子任务或父工作包，也不代表已部署或真实数据已验证。当前可核对基线和近期可执行顺序见下节；实际验收收据见 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)。

第二批已按独占文件集成11条开发任务，第三批按6个控制任务拆成7条执行任务，跨多个父工作包推进；其实际交付与剩余验收面见 [WAVE2_STATUS.md](WAVE2_STATUS.md)。下表保留完整任务验收门槛，库内能力或局部链路完成不会自动关闭要求外部证据、生产worker或完整业务场景的任务。

第三批逐条状态、额外wire身份修正及外部限制见 [WAVE3_STATUS.md](WAVE3_STATUS.md)。第四批5条并行执行流与独占文件见 [WAVE4_PLAN.md](WAVE4_PLAN.md)，模块交付、追加审查任务与最终组合见 [WAVE4_STATUS.md](WAVE4_STATUS.md)。第五批首个图表直读与MySQL worker局部开发见 [WAVE5_PLAN.md](WAVE5_PLAN.md)，没有关闭整行验收。

## 验收边界与并行约定

- `CODE/OFFLINE` 表示代码、静态资料、fixture、mock、owned SQLite 或离线对账可验收；它不证明真实源可用、全历史完整或生产部署成功。
- `REAL_SOURCE` 需要真实供应商/交易所请求或真实返回证据，记录数据集、标的/业务键、参数、观测时间、来源和许可边界；fixture不能代替。
- `DEPLOYMENT` 需要目标部署环境中的运行/权限/恢复/切换证据；本地启动不算部署验收。`NATURAL_CYCLE` 必须等真实源的约定发布周期到达并观察到结果；手工触发、mock和缩短等待不能代替。
- 混合类型的子任务只有分别完成对应验收面后才算该子任务验收。真实源不可得、历史保留不足或许可未知时，产出限制证据和复查条件，需求保留开放，不能填造成功状态。
- M1可由股票日线、标的目录、日历、覆盖、一个补数任务、一个自然调度和一个研究快照的代表样本启动。20个代表案例、首批六个子任务和本清单不要求先把2026-10-26历史快照所记的1,066个候选文件全盘完毕；先刷新当前资产分母，批量盘点与M1并行。代表样本覆盖之外的文件仍留在刷新后的范围分母中。
- `owner/建议代理` 的 A–E 对应 IMPLEMENTATION_PLAN.md 的职责；括号内为已知子代理名。root负责总集成和跨仓裁决。默认复用每仓现有主`dev` checkout，先分配互不重叠的文件清单；不为每人建立工作树或长期分支。每仓只有root/指定集成人负责暂存、提交、短期PR分支和合并；按小而可验收的变更开PR到`dev`，合并后回到`dev`。只有有明确隔离需要的任务才另建工作树。第四批以冻结合成fixture解耦离线代码与真实源验收：提交SPI和执行SPI独立开发，真实源不得阻塞纯离线worker/CLI。禁止多个代理同时修改同一共享文件；共享schema、总路由、依赖锁和Alembic序列由指定owner排队集成。发生接口变化先更新契约并让消费者同步，不把数周后的大批量合并作为计划。
- 前置依赖仅写本清单任务ID；空表示可直接开始。依赖链无环，部分任务可并行。工作包整体状态按 IMPLEMENTATION_PLAN.md 单独管理，子任务状态不可推导成父包 ACCEPTED。

证券/衍生品长尾任务进入开发时继续按一个模型族或不超过20个源条目拆执行批次，每批绑定独占文件清单和台账行；98项是截至2026-10-29的计划拆分规模，不代表当前有效控制任务数量，也不要求把2026-10-26快照的607/449个候选文件塞给一个长期子代理。源脚本、运行任务和数据集分属不同分母，需在本轮只读清单刷新后再报告当前数量。并行数量依据依赖和资源预算调整。

## 当前基线与近期执行矩阵（2026-10-31 更新，Asia/Shanghai）

**2026-10-31 基线**：AFI `dev` HEAD 为 `b825f921476b6e698881e1be68993c8a4ac610e1`，OpenData `dev` HEAD 为 `373211d246ab3099ac8c551681c0f1703fcbd964`；该基线不包含本次文档改动，开始任何后续改动或验收时仍须重取实际 HEAD 并记录脏文件哈希。

OpenData #134–#152 把一次性 source gate/配额与 THS transport 逐步绑定到 v3 scope（#134–#143），并新增隔离 CSI500 样本 CLI（#144）、可作为补采规划输入的离线股票日线缺口对账（#145）、股票日线 v2 读取路由（#146，默认配置下仍 404）、THS job 请求预算传递（#147）、MySQL 反射 CHECK 校验（#148）、DWD diff 标记修正和模拟 THS 的 MySQL 竖向验收夹具（#149）、默认关闭的 digest-pinned 容量门禁与仅执行回补执行器/CLI（#150）、Fuyao 六 scope 真实样本离线回放（#151）以及离线当前 A 股 universe 候选（#152）。AFI #201–#204 新增精确 snapshot grant 存储、固定股票日线 publication 读取器、按真实数据闭环排序的迁移计划，以及股票日线 grant 扩展与授权 adapter（#204）。上述提交信息未逐项记录测试通过数/覆盖率；#150–#152/#204 的定向证据见下节。它们只覆盖各自的代码/离线范围，没有真实 THS/Fuyao 请求、生产 MySQL、AFI 业务接线、自然周期、单写者切换或全历史验收。逐项范围、SHA 与非声明见 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) 的 2026-10-31 条目。

**2026-10-30 历史快照**：本轮编辑这些计划文档之前 AFI `dev` 与 `origin/dev` 的 HEAD 为 `73c7b2f7537cacab2ab75daf4381e850a0977b9b`，OpenData `dev` 与 `origin/dev` 的 HEAD 为 `cc79654171bd00b00d9909f7973547a10790a945`；当时两仓工作树均干净。该基线不包含当时的文档改动。

OpenData PR #132 在限定隔离范围有487项通过、1项既有OpenAPI检查deselect；follow-mypy仍有3项既有诊断。它增加签名恢复日志，但任务disabled、unregistered、无scheduler/生产签名器，且账本提交与日志发布非原子。OpenData PR #133 的限定合成对账回归68项通过、statement+branch覆盖率96.77%、0项排除；它不验证真实CSI500来源、交易日历、授权/保留、生产运行或实际全历史。AFI PR #193 仅实现纯授权策略；本地授权持久模型和迁移仍在开发中，未合入当前 AFI HEAD、未验收，不构成可信grant registry。尚无持久签发/撤销、业务路由或报告保存前复核。上述PR只证明各自声明的代码/离线范围，不能自动更新或完成矩阵中的父工作包。**2026-10-31 更正**：AFI PR #201 已合入精确 snapshot grant 的 ORM 模型与迁移 `20261030_stock_analysis_snapshot_grants`，但存储默认为空，该合并范围未接可信 adapter、签发/撤销认证、业务路由或读取前复核，因此仍不构成可信 grant registry。详细边界见 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)。

用户已声明AkShare和Fuyao可用于自动采集、保存及两内部服务间使用，不重复询问这三项用途。仍须把AkShare每个函数映射至实际上游产品/endpoint，并将market、dataset、历史范围、限额、保留及撤销行为落到可审计grant；没有独立登记的端点或范围保持UNKNOWN。

下表是从现有任务ID形成的近期分工，不增添总任务数，不把任何行预记为完成。A持有共享schema、registry、总路由和Alembic序列；其余各人仅改互斥模块，由root串行集成。真实来源请求统一登记到D的预算，避免多人并行重复请求。

| Owner/互斥文件范围 | 现有任务入口 | 近期具体交付 | 依赖与验收判据 |
| --- | --- | --- | --- |
| A：共享合同、证券身份、授权和发布；独占共享registry/OpenAPI/Alembic | `204-A03-01/02`、`204-A04-01/02/03/04`、`204-A05-04/05/06/07`、`204-A06-02/04` | 排定唯一共享文件owner；定义交易所范围、稳定instrument identity、时态代码/板块crosswalk、当前与退市证券分母、分页回执、source grant revision、post-commit seal和固定snapshot vector契约。 | 对沪深北每个来源核验实际分页终止/总量/版本和退市生命周期；字段、目录、grant或seal证据缺失时保持UNKNOWN，不能宣称全A完整或打开cutoff查询。 |
| B：股票数据源和迁移；只改所属证券provider/映射/测试 | `204-B01-01/02`、`204-B02-01/02/03/04/05`、`204-B05-01/02/03` | 映射AkShare函数→实际上游产品/endpoint→参数/字段/单位；拆分Fuyao财报年度/季度、修订和时间语义；以有界样本留raw evidence并贯通ODS/DWD→发布→REST，随后经全市场分母、生命周期、数据源预算和可恢复worker，按 instrument×dataset 全历史回补。 | 依赖A提供的数据合同、授权范围、证券身份/日历和publication seal，D提供跨运行预算与可恢复worker；单票或CSI500合成回归不能替代全A分母及逐标的全历史验收。 |
| C：衍生品和其他资产；只改所属provider子模块与冻结批次 | `204-C01-01/02`、`204-C02-01/02`、`204-C03-01/02`、`204-C04-01/02`、`204-C05-01/02`、`204-C06-01/02`、`204-C07-01/02` | 复核449个历史候选而不把它当当前分母；按模型族或每批不超过20个源条目，记录provider、单位/日历、旧任务、consumer、许可边界和REUSE/EXTEND/CONSOLIDATE/SOURCE_LIMITED处置。 | 依赖A共享合同及D刷新后的实际运行任务清单；每批双向anti-join可复算，源限制和未知项留在清单，不报虚构迁移比例。 |
| D：运行入口、账本、配额、dry-run迁移、运维；只改执行层/ops | `204-D01-01/02`、`204-D02-04`、`204-D03-01/02/03`、`204-D05-02/03`、`204-D06-01/02` | 只读刷新actual task/run/claim、cron/systemd/进程、in-flight permit、checkpoint、sink及库身份；补Run service、worker、有限重试/并发/配额、统一入口与迁移dry-run。恢复quota V3时须有可信旧worker/permit排空及网络/凭证fence verifier，并先修复THS发送前绕gate和持久lease释放。 | 没有可信verifier时V3默认禁用并保留V2路径；人工声明不足以切换。任务清单和目标库身份没刷新/核验前不做apply或真实历史批量抓取。 |
| E：AFI consumers、async REST、数据管理UI；只改AFI客户端/业务/UI | `204-E01-01/02`、`204-E02-03/04`、`204-E03-01/02/03/04/05`、`204-E04-01/02/03`、`204-E05-01/02` | 盘点AFI的行情/财报/搜索/扫描器/页面/后台任务、本地库和直连SDK；先实现异步REST、deadline/有限重试/错误映射，再按冻结records/vector合同迁移业务路径。将数据管理入口指向OpenData需等待其受保护的管理API。 | #193纯策略需接真实user/grant revision，并在后台执行、读前及报告落盘前重验；不存在固定vector、可信coverage或权限时明确不可用，不写本地事实缓存、不回退旧源。 |

执行顺序：先重新核对任务/脚本/消费者输入清单并冻结共享合同；A/B分别推进证券身份与源字段语义，C独立处理其他域小批次，D盘点运行态并完善预算/worker，E并行完成consumer inventory及async client；合同就绪后做受预算约束的有界端到端样本；最后才逐证券补历史、自然周期、备份恢复和单写者切换。局部PR合入后只记录它通过的范围，不改变原要求的交易所、证券或历史分母。

### 2026-10-31 增量证据（不重算 98 项状态）

本节只登记可由 2026-10-31 合入提交直接支持的部分证据，不改变上方表格的历史状态列，也不据此推算当前完成数量或比例。未列出的子任务不因本批 PR 获得状态更新。Wave 15 新增的 Fuyao/universe 与授权 adapter 证据单列于下节，不回填本表。

| 子任务 | 本批可引用的部分证据 | 仍开放的范围 |
| --- | --- | --- |
| `204-A05-04` | OpenData #146 实现了股票日线 v2 records 合同形状：显式 `publication_id`、半开窗口、snapshot/cursor 固定同一 publication/窗口/选择/grant scope，并校验 schema、单位、币种和 `adjustment_basis=raw`。 | 路由由依赖强制返回 404 且不在 OpenAPI 中；无容量验收、生产启用、真实 publication/visibility seal 读取或授权；不能视为该合同已验收。 |
| `204-A05-05` | AFI #201 新增用户读授权、来源研究授权和审计三类持久表及精确 scope 约束；OpenData #146 路由参数包含读 grant 依赖。 | 存储默认为空、不签发/认证/强制审计链，未接可信 adapter、registry revision 比对、后台执行/读取/保存前复核；无真实 grant 或撤销验收。 |
| `204-B02-04` | #145 提供离线 head/interior/tail 缺口对账（可作为补采规划输入）；#146/#202 提供固定 publication 的读取合同。 | 仍缺 AkShare 函数→上游产品/endpoint→字段/单位的有界真实样本、真实来源 ODS/DWD→v2 REST→AFI 的链路；不能关闭真实源验收。 |
| `204-B02-05` | 仅共享 #136–#140 的一次性 gate/quota/transport 基础。 | Fuyao 财报数据集本身没有新实现或证据；六查询、单位/币种、修订语义和真实返回仍未验收。 |
| `204-B05-03` | #145 的离线对账 CLI 可作为逐 `instrument_id × dataset_id` 回补前的缺口输入工具；#149 提供模拟 THS 的 MySQL 竖向夹具。 | 无权威全市场/退市分母、无回补执行、持久 checkpoint、真实 MySQL 或自然周期；全历史仍 OPEN。 |
| `204-D02-04` | #147 允许可信调用方向单个 THS `stock_daily` job 传入进程内请求预算；#149 夹具覆盖 job→ODS/DWD→v1 REST。 | Run service/worker 未接该预算，无多进程竞争、租约恢复或崩溃后旧 token 拒绝证据。 |
| `204-D03-02` | #136–#140 提供一次性 gate、quota provisioning 和 transport 限定；#147 提供 job 级共享请求预算。 | 重试/退避、并发上限、跨运行额度、Retry-After 和 WAF 停止规则仍未完成；本地 bucket 不是持久一次性上限。 |
| `204-D03-03` | #144 新增隔离运维 CLI（`init/migrate/authorize/prepare/preview`）。 | 它不是统一 Run 提交入口，不接 APScheduler/手工 API/CLI/systemd；仅能说明存在一个隔离 CLI，不构成统一入口证据。 |
| `204-E03-04` | AFI #202 新增独立固定 publication 读取器并校验请求/行/单位/coverage。 | reader 未接任何股票分析业务路径、授权或 fallback 策略；上游路由硬禁用，无真实跨仓读取或报告调用。 |
| `204-E03-05` | 无直接证据；#201 的 grant 存储与 #202 的 reader 只是未来报告溯源所需的部件。 | 报告必需数据/coverage 门槛、publication vector 持久化与重放、保留期均未实现或验收。 |

### 2026-10-31 Wave 13/14/15 合入证据（OpenData #150/#151/#152、AFI #204，不重算 98 项状态）

以下证据来自两仓 `dev` 已合入提交：OpenData #150 `a76b48580c2f71ac3dc6a045a05edafba1f896e5`、#151 `56d4cb38869c0fb8114c917be78e720506f659de`、#152 `373211d246ab3099ac8c551681c0f1703fcbd964`；AFI #204 `b825f921476b6e698881e1be68993c8a4ac610e1`。合入不改变上方表格的 as-of 状态，也不把局部证据计为子任务或父工作包验收；对应父任务（A03/A05、B01/B02/B05、D02/D03、E03/E06）保持开放。

| 子任务 | 合入后新增的可确认子范围 | 仍开放的范围 |
| --- | --- | --- |
| `204-A05-04` | OpenData #150 合入：默认关闭的 digest-pinned 容量门禁，绑定 dataset/source/semantic/contract/publication/窗口/页大小/有效期；合成 route 测试 40 项通过；跨仓合成 wire 9 项通过；真实捕获字节回放 9 项通过。 | 目标部署的操作者证明、时钟/数据库/容量核验；生产 grant/API key；真实来源与 visibility seal；不能把门禁或合成 wire 当作生产启用。 |
| `204-B05-03` | OpenData #150 合入：可恢复回补执行器/CLI——计划摘要校验、ledger 幂等跳过、失败停止、dry-run 默认、`execution_only` 任务、离线 fixture 与真实捕获字节回放；49 项定向测试，容量/执行器/共享回归合并 434 项通过。 | 权威全市场/退市分母、逐 `instrument_id × dataset_id` 全历史、生产 MySQL、真实预算/worker 部署、自然周期；执行器不是调度器，不授权实时发送。 |
| `204-E03-04` | AFI #204 合入：精确 grant 存储/策略扩展到 `cn-equity-stock-daily`/`akshare.daily`；新增读取前/响应后授权 adapter（默认关闭，138 项定向测试通过）；真实捕获字节回放使用真实 reader 读取固定 publication，授权开启 **11 passed、1 skipped**。 | 真实用户 grant 的签发/撤销/审计认证、生产 registry revision、业务任务接线、报告保存前复核；adapter 未接业务路径，测试 grant/principal 为合成。 |
| `204-E03-05` | AFI #204 合入：固定 publication/content SHA、reader 严格校验与离线回放证据。 | 报告必需数据/coverage 门槛、publication vector 持久化/重放、保留期、真实数据/PIT；回放不构成报告验收。 |
| `204-E06-03` | OpenData #150 与 AFI #204 合入：跨仓合成 publication wire（9 项通过）与真实捕获字节离线回放（9 项通过）均通过真实 OpenData 路由 + 真实 AFI reader。 | 实时来源、生产部署、真实 grant、影子对账与自然周期；合成 principal/grant/API key 不是生产授权。 |
| `204-B02-04` | OpenData #150 合入：真实 Eastmoney 捕获 body 经 job→publication→v2 路由→AFI reader 回放，10 行字段/单位通过 reader 校验；公开证据记录 body SHA 和 publication content hash。 | 未重新请求来源；未验证实时来源、授权/保留、全历史、复权/单位独立校准；不能作为 `REAL_SOURCE` 验收。 |
| `204-B02-05` | OpenData #151 合入：opt-in Fuyao 六 scope（三表 × annual/quarterly）真实样本离线回放，**1 passed、52 项观察（13/13/7/7/6/6）**，六个 manifest 实体 hash 校验一致。 | 回放的是此前捕获的真实字节，未重新请求 Fuyao；六查询的实时闭环、单位/币种、修订语义、报告期覆盖和 PIT 仍未验收。 |
| `204-A03-02` | OpenData #152 合入：离线当前 A 股 universe 候选保留市场限定身份，报告重复/冲突而不合并；真实 SZSE 样本 **2,905 条候选、0 冲突**，synthetic **20 passed、1 skipped**。 | 分页终止仍 `UNKNOWN`、无退市生命周期、`universe_census_attested=false`；SSE/BSE/Fuyao 真实响应体 `NOT_RUN`；不是上市/退市或稳定身份的权威证据。 |
| `204-B01-01/02` | OpenData #152 合入：捕获目录驱动的当前 A 股候选可作为证券分母与来源能力盘点的候选输入（真实 SZSE opt-in **21 passed**）。 | 它不刷新 2026-10-26 的脚本候选台账（607/449 口径），也不替代 B01-02 的 10 个真实证券案例；权威全市场分母、分页完整性与退市集合仍未证明。 |
| `204-D02-04`/`204-D03-02`/`204-D03-03` | OpenData #150 合入：回补执行器复用现有 RunLedger/RunService/RunDispatcher，新增 `execution_only` 提交路径；容量/执行器/共享 one-shot/worker 回归合并 434 项通过。 | 生产 worker/调度、跨进程预算、租约/崩溃恢复、Retry-After/WAF、统一入口与 systemd 接线仍未验收。 |

**CI 不是绿色**：以上 PR 在 CI 清理前合入，已知失败与后续修复计划见 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) 的 Wave 15 节；不能据此把这些合入写成 CI 已通过。

## A：平台与数据契约

| 子任务ID | 父WP | 状态（as of 2026-10-29） | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-A01-01 | A01 | PLANNED | A / root | CODE/OFFLINE | 记录两仓基线提交、脏文件路径与哈希、运行时/依赖版本、数据库迁移head、工具版本；秘密只记录存在性，不读出或复制。 | — | 脱敏基线清单可重现；两个仓库身份和采集时间明确，脏改动有保留位置与恢复步骤。 |
| 204-A01-02 | A01 | PLANNED | A / root | CODE/OFFLINE | 建立所有权与ADR索引，标记共享契约、总路由、公共依赖、迁移序列、provider域、客户端和UI文件owner。 | 204-A01-01 | 每个共享文件有唯一集成owner；文档写明两个仓库的PR目标分支和集成责任。 |
| 204-A02-01 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 冻结v1兼容约束和v2 OpenAPI骨架：端点、认证、闭/半开区间、分页、错误信封、版本字段。 | 204-A01-01 | OpenAPI可解析；每项拟议能力标明现存或待实现；v1既有响应语义有契约测试。 |
| 204-A02-02 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 逐数据集身份、instrument、业务时间/事件时间/可得时间、单位/币种、Decimal、空值、质量和许可schema。 | 204-A02-01 | schema示例覆盖股票日线、基金NAV、曲线或财务修订中的不同语义；非法单位/日期可被验证器拒绝。 |
| 204-A02-03 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 提供黄金fixture、错误fixture和可本地运行的mock服务，供opendata API及AFI client并行开发。 | 204-A02-01, 204-A02-02 | 同一fixture能驱动服务端与客户端合同测试；含空结果、部分覆盖、越权、过期cursor和分页样例。 |
| 204-A02-04 | A02 | DEV_DONE（代码/离线门禁） | A / wave3_contract_gate | CODE/OFFLINE | 加入OpenAPI兼容性门禁、schema版本规则和破坏性变更检查。 | 204-A02-03 | actual main v1共140路径、v2共6路径冻结，24项行为测试覆盖破坏/兼容变化；固定hash的检查器已接入make gate，现有CI调用该gate。远端CI尚未运行，整仓gate不通过；不自动更新baseline，兼容扩展路径有说明。 |
| 204-A03-01 | A03 | PLANNED | A / 元数据代理 | CODE/OFFLINE | 定义dataset/schema版本、来源、负责人、许可和域注册表的元数据模型及首个迁移提案。 | 204-A02-02 | 唯一共享registry owner确认迁移序列；升级/降级或备份恢复边界有离线验证记录。 |
| 204-A03-02 | A03 | IN_PROGRESS | A / wave4_reference | CODE/OFFLINE | 定义instrument稳定ID、别名生效区间、上市/退市/到期生命周期和交易日历版本接口。 | 204-A03-01 | fixture覆盖换码、退市、基金份额类别、到期合约、节假日及未知边界；不以当前代码回填历史身份。 |
| 204-A04-01 | A04 | IN_PROGRESS | A / 存储代理 | CODE/OFFLINE | 增加raw响应证据引用与受控artifact manifest合同，包含请求摘要、内容hash、采集时刻、状态和保留策略。 | 204-A03-01 | 单测证明密钥/Cookie不会进入manifest或日志；ODS记录可定位证据或明确SOURCE_LIMITED。 |
| 204-A04-02 | A04 | PLANNED | A / 存储代理 | CODE/OFFLINE | 建立ODS到DWD的来源血缘、转换版本、修订链、可得时点和固定publication/snapshot版本字段。 | 204-A04-01, 204-A03-02 | fixture中修订前后值可追踪；严格PIT未知的数据不能伪装成已知。 |
| 204-A04-03 | A04 | PLANNED | A / 存储代理 | CODE/OFFLINE | 定义候选分区验证、原子publication指针和跨metadata/warehouse receipt/outbox的可重放提交。 | 204-A04-02, 204-D02-01 | 故障注入证明提交状态不领先事实数据，重复receipt可幂等重放；不宣称跨库原子事务。 |
| 204-A04-04 | A04 | PLANNED | A / visibility-ledger代理 | CODE/OFFLINE+DEPLOYMENT | 新增post-commit publication visibility seal及持久单调visibility sequence。只有publication涉及的warehouse事实分区、publication指针和跨库receipt均提交，且read-after-commit确认可读后才封存；保留现有事务内`published_at`为非证明性字段，使用可信UTC时钟并检测回拨/不可信时钟，失败时不封存。 | 204-A04-03, 204-D02-01 | 单测覆盖提交前不可见、所有事实/指针/receipt提交后封存、提交与封存之间崩溃/重试、并发序列唯一单调、时钟回拨/失真失败关闭和UTC RFC3339格式；目标环境验证时钟与提交可见边界前，cutoff API保持关闭。 |
| 204-A05-01 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现兼容v1只读端点及固定latest-view行为，沿用既有闭区间和count语义。 | 204-A02-03, 204-A03-01 | 合同测试验证旧请求/响应；普通读身份不能触发provider抓取或写入。 |
| 204-A05-02 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现v2目录、标的、日历、records、coverage和snapshot只读服务的首批端点。 | 204-A04-03, 204-A03-02 | fixture验证publication固定、业务日期半开窗口、逐标的覆盖和稳定排序cursor；未发布分区不可见。 |
| 204-A05-03 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现分页/行数/响应体/超时边界、异步大导出入口、scope/许可门禁及稳定错误码。 | 204-A05-01, 204-A05-02 | 超限明确报错或返回导出状态，不静默截断；scope隔离测试通过，429/503语义稳定。 |
| 204-A05-04 | A05 | PLANNED | A / OpenData records合同代理 | CODE/OFFLINE | 为股票日线新增reviewed v2 records合同；当前v2 publication sequence本身不足以构成股票日线接口。固定publication_id/sequence和可验证visibility seal，返回instrument、`business_date`、`observed_at`、`visibility_sealed_at`、来源、原生字段/单位及schema既有枚举`adjustment_basis=raw`；不提供虚构的逐行`available_at`，v1保持不变。`business_date`按交易所日历`Asia/Shanghai`解释，instant按带时区RFC3339归一为UTC。 | 204-A02-02, 204-A04-04, 204-A05-02 | OpenAPI与行为fixture验证所有分页固定在同一publication、cursor绑定publication/主体/过滤条件；业务日期和采集/封存instant不混淆；无时区instant拒绝或标UNKNOWN，缺visibility seal/未审查schema时明确拒绝；不触发采集。 |
| 204-A05-05 | A05 | PLANNED | A / OpenData auth代理 | CODE/OFFLINE | 给研究读取增加双重授权：实际用户对目标dataset/标的/研究用途具有精确`READ_DATA`，且用户的source research grant覆盖实际来源、dataset、市场和用途；后台调用须携带委托用户身份并在执行、读取和结果发布前重新校验授权版本。 | 204-A02-01, 204-A03-01, 204-A05-03 | 合同测试覆盖未认证、错误用户、缺失/过期/撤销grant、scope缩小和后台重授权；任何失败均在读数据前拒绝且不降级到宽权限服务身份。 |
| 204-A05-06 | A05 | PLANNED | A / financial records合同代理 | CODE/OFFLINE | 定义并实现股票财务v2 dataset/records合同：annual/quarterly report_type，statement_type，instrument、报告期起止业务日期与稳定metric/business key；修订作为可追溯观察版本，不静默覆盖历史。保留来源原始字段、单位/币种，source timestamp缺失时为UNKNOWN；固定publication查询并分页，返回post-commit `visibility_sealed_at`。所有instant按RFC3339时区规则保存原值及版本化转换规则，`business_date`按对应市场日历定义。 | 204-A02-02, 204-A03-02, 204-A04-04, 204-A05-02 | 合同测试覆盖annual/quarterly键区分、报告期边界、同一期多次修订、source timestamp未知、原生单位/币种、NULL与零、固定publication与cursor绑定和不带时区时间；未知公告时间不得推算为PIT。 |
| 204-A05-07 | A05 | PLANNED | A / snapshot与visibility查询代理 | CODE/OFFLINE+DEPLOYMENT | 为研究查询提供cutoff与visibility sequence双约束及固定多dataset snapshot vector；vector固定每个dataset的publication_id/sequence、visibility seal、content/contract hash和过滤条件。snapshot临时ID不承担报告保留；定义publication/vector长期保留期并提供稳定可解析引用。 | 204-A04-04, 204-A05-04, 204-A05-06 | 离线测试证明cutoff与sequence任一不匹配即拒绝、cursor翻页不漂移、回填数据仅从实际seal时刻可见、缺历史vector不做历史as-of推断；验收publication/vector保留期覆盖报告声明复现期。现有最多7天snapshot TTL不够时必须拒绝长期重放承诺。 |
| 204-A06-01 | A06 | DEV_DONE（仅代码/离线） | A / dev_coverage | CODE/OFFLINE | 实现逐标的日粒度head/interior/tail缺口纯函数；输入预期交易日/生命周期边界和观测业务日期，输出缺口段及状态，不接数据库、不抓源、不判定上市边界真伪。 | 204-A02-02 | 纯函数单测覆盖首尾缺口、内部缺口、停牌/不适用、退市、空观测、重复输入和未知边界；父WP A06仍未完成。 |
| 204-A06-02 | A06 | PLANNED | A / 质量代理 | CODE/OFFLINE | 为首批dataset配置主键、重复、单位、时间、跨表和发布质量规则及严重级别。 | 204-A03-02, 204-A06-01 | 每条规则有数据集适用范围与失败样例；未知不被转换为默认0或COMPLETE。 |
| 204-A06-03 | A06 | PLANNED | A / 质量代理 | REAL_SOURCE | 为源受限/缺历史记录真实请求参数、最早可回溯点、许可/保留证据、责任人及复查触发条件。 | 204-B01-02, 204-C01-02 | 证据指向可审查的源响应/官方说明；未回传记录清楚标为未知或SOURCE_LIMITED并保留历史需求。 |
| 204-A06-04 | A06 | PLANNED | A / coverage与主数据代理 | CODE/OFFLINE | 建立股票分析按`instrument_id × dataset_id × publication × 窗口`的分数据族coverage合同。日线预期键由每个目标交易所经验证的`Asia/Shanghai`交易日历及上市/退市边界决定；财报预期键由annual/quarterly类型、报告期集合和经review的数据源/数据集披露周期决定，不能套用交易日历。无法独立证明证券目录分母、分页完整性、日历、生命周期、报告期或周期时为UNKNOWN。当前API尚不支持BSE是实现现状，不得将北交所从全A股目标范围中排除。 | 204-A03-02, 204-A05-06, 204-A06-01, 204-A06-02 | 单测分别覆盖日线与财报期望键、交易所分母/分页缺失、日历/上市/报告周期缺失、head/interior/tail缺口、停牌/退市、publication变化和4/8/920拒绝；当前未支持venue返回明确NOT_SUPPORTED并保持总体coverage UNKNOWN；无证据不得推COMPLETE，MAX日期、市场总行数和源最早返回日均不构成覆盖证明。 |
| 204-A07-01 | A07 | PLANNED | A / root | CODE/OFFLINE | 形成跨仓发布manifest和合同/依赖兼容门禁，绑定opendata commit、AFI commit、client版本、schema及数据publication。 | 204-A02-04, 204-A05-03, 204-E06-02 | manifest可重现这组二进制/契约组合；未验证的数据面单独标NOT_RUN。 |
| 204-A07-02 | A07 | PLANNED | A / root | DEPLOYMENT | 汇总最终范围、未迁项、源限制、回滚条件、运营owner与阶段发布说明，提交关闭/阶段发布评审。 | 204-A07-01, 204-B07-03, 204-C07-02, 204-D07-03, 204-E07-02 | 逐WP、数据域、源/仓/API、部署、自然周期和历史覆盖分别给证据；任何未通过项不被描述为全量完成。 |

## B：证券数据适配

| 子任务ID | 父WP | 状态（as of 2026-10-29） | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-B01-01 | B01 | PLANNED | B / 证券代理 | CODE/OFFLINE | 刷新证券候选资产清单并分批逐项处置；607是2026-10-26静态CSV历史候选数，不是当前总数。记录旧脚本hash、输入参数、数据集、provider、落库、消费者、许可和REUSE/EXTEND/CONSOLIDATE等决策。 | 204-A01-01 | 每个刷新后候选保留一个可追溯处置或待查原因；刷新清单与原快照anti-join解释一致，不把文件数当数据集数。 |
| 204-B01-02 | B01 | PLANNED | B / 证券代理 | REAL_SOURCE | 选10个证券代表案例，实测简单、复权、财报报告期/修订/来源时间语义、多表、源限流/失效等源能力与字段语义。 | 204-A01-01 | 每例记录真实源、参数、时间戳和时区、返回边界、许可/保留范围与成本；来源公告时刻无证据时明确UNKNOWN，不将样本解释为source/market-known PIT；作为M0输入，不等待历史快照中的607项候选完成映射。 |
| 204-B02-01 | B02 | IN_PROGRESS | B / wave4_stock_job | CODE/OFFLINE | 完成股票日线M1样板Provider、标准映射和fixture，采用schema枚举`adjustment_basis=raw`，分离价格、成交量/额单位与源字段。 | 204-A02-02 | 离线样板使用明确合成fixture，真实源另验204-B02-02；黄金fixture稳定重放，唯一业务键和空值/单位合同通过；源真实性另由下一任务验收。 |
| 204-B02-02 | B02 | PLANNED | B / 证券代理 | REAL_SOURCE | 对选定股票真实抓取日线，核对源参数、交易日、原始响应、字段及许可/历史保留边界。 | 204-B02-01 | 样本与真实源可逐字段比对；上市起点证据与源最早返回日分开记录，异常不被填平。 |
| 204-B02-03 | B02 | PLANNED | B / 证券代理 | CODE/OFFLINE | 形成股票universe/上市退市、公司行动和独立复权数据集方案。 | 204-A03-02, 204-B02-01 | fixture覆盖换码、退市、除权、复权锚点和因子版本；复权与raw不混表、不覆盖；来源公告时刻与平台visibility seal分开，无证据时source/market-known PIT标UNKNOWN。 |
| 204-B02-04 | B02 | PLANNED | B / 股票日线源代理 | CODE/OFFLINE+REAL_SOURCE | 将AkShare适配到OpenData股票日线Provider，首版只输出经源字段核对的raw价格和源端原生量/额单位；按AkShare函数→实际来源产品→字段登记映射证据，保留source、参数、`business_date`、`observed_at`、空值语义与raw evidence引用。用户已允许本迭代使用AkShare，无需再次索取授权。 | 204-A02-02, 204-A05-05, 204-B02-01 | 离线fixture覆盖真实列映射、单位、NULL/零及重试幂等；有界真实沪深样本的AkShare函数/实际来源产品/字段逐项对照，再从source→ODS/DWD→visibility seal→REST核验并留脱敏请求/版本/hash。不得以该样本声称全A、BSE或全历史完整。 |
| 204-B02-05 | B02 | IN_PROGRESS（仅预检和合成门禁切片；真实源/发布未验收） | B / 财报源代理 | CODE/OFFLINE+REAL_SOURCE | 将Fuyao已提供的财报数据接入OpenData reviewed v2 annual/quarterly dataset；按原样保留报告期业务日期、源字段、source、原生金额单位/币种、可核验的原始时间及平台visibility seal和raw evidence引用。没有可核验证据的公告时间保持UNKNOWN，不把本任务描述为PIT财报。用户已允许本迭代使用Fuyao，无需再次索取授权。 | 204-A02-02, 204-A05-05, 204-A05-06, 204-B01-02 | 离线fixture覆盖年度/季度、报告期key、多次修订、NULL与0、单位/币种、来源时间原文/时区转换规则；至少一组有界真实返回经采集、post-commit封存、发布、REST逐字段对照。覆盖范围和源保留边界逐标的/报告期记录；不推断全市场或任意历史PIT。 |
| 204-B03-01 | B03 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立基金/ETF交易价格、单位净值、累计净值、万份收益和七日年化的独立数据集及映射。 | 204-A03-02 | 合同测试证明字段不混用、单位与公布时点明确；缺失NAV不会由交易价格补值。 |
| 204-B03-02 | B03 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立可转债个券与国债/信用收益率曲线的分离模型及证券字段映射。 | 204-A03-02 | fixture验证曲线tenor/日期/单位和个券价格、收益率不是同一表义；源/历史证据列待核项。 |
| 204-B04-01 | B04 | PLANNED | B / 证券代理 | CODE/OFFLINE | 接入指数定义、历史成分有效期和估值分母，支持退市证券与历史universe回测。 | 204-A03-02 | fixture按as_of重建历史成分；当前成分不被反向套用到历史。 |
| 204-B04-02 | B04 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立证券事件及长尾Provider字段漂移隔离、映射版本和错误工单模板。 | 204-A03-02 | 故意新增/改名源字段会落入隔离并产生可读差异，既有已发布字段不被静默改写。 |
| 204-B05-01 | B05 | PLANNED（as of 2026-10-29） | B / 迁移协作代理 | CODE/OFFLINE | 制定证券历史ODS/DWD、成交额sidecar和旧复权数据的迁移映射/分区dry-run。 | 204-A04-02, 204-B02-01 | dry-run报告旧新行数、主键冲突、来源血缘、单位和复权基准差异；不写目标库。 |
| 204-B05-02 | B05 | PLANNED（as of 2026-10-29） | B / 迁移协作代理 | REAL_SOURCE | 对批准的证券分区执行迁移后逐标的/逐分区head、interior、tail与行级抽样对账；该迁移对账不替代 `204-B05-03` 的全历史回补。 | 204-B05-01, 204-A06-02 | 对账报告包含预期分母、差异/未知/源限制及证据；不能只以MAX日期、行数或成功运行判完整。 |
| 204-B05-03 | B05 | PLANNED（2026-10-30新增控制任务；未实现/未验收） | B / 全A历史回补owner；D提供预算/Run支持 | CODE/OFFLINE+REAL_SOURCE+DEPLOYMENT | 对冻结的全部必需股票数据集，按 `instrument_id × dataset_id` 分批从独立有证起点回补至每个标的/数据集的独立目标终点；范围包含沪深北在册及退市证券、跨板/换码生命周期。按来源/交易所/数据集/窗口设请求、行数、并发和时间预算；用持久checkpoint、幂等业务键和可审计重入收据续跑，禁止无限重试或以一个大请求绕过额度。 | 204-A03-02, 204-A06-04, 204-B02-04, 204-B02-05, 204-D02-04, 204-D03-02 | 先以权威全市场目录、实际分页终止证据和版本化生命周期冻结分母；活跃证券核至验收时按已证源发布周期应有的最新业务日/水位，退市证券核至独立证实的有效终止边界。每个 `instrument_id × dataset_id` 留起止边界依据、预期/观测业务键或报告期、head/interior/tail、分页游标及终页、source/grant revision、请求/响应/发布hash、checkpoint和未知/源限状态。`request_end`早于该标的目标终点只算有限窗口，不得关闭AC05；BSE当前API不支持或源保留不足时保持NOT_SUPPORTED/UNKNOWN/SOURCE_LIMITED，不缩小范围、不报全历史完成。 |
| 204-B06-01 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 把首批股票/基金共源脚本按业务模型合并为可版本化Provider模板和TaskDefinition映射。 | 204-A03-02, 204-B02-01 | 不同旧参数仍可追踪到新模型；共用文件有单一owner，provider不在业务读API里抓取。 |
| 204-B06-02 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 按批完成剩余证券候选文件处置，保存资产清单总分母及未决项。 | 204-B01-01 | 所有候选逐项有处置、负责人、依赖和阻塞证据；不把HELPER_ONLY误建为定时任务。 |
| 204-B06-03 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立旧证券task_id/参数hash到脚本hash、dataset、provider/model、job/version、sink和验收收据的映射。 | 204-B01-01, 204-D01-01, 204-D05-01 | 双向anti-join能发现未映射旧任务和无旧来源新任务；默认导入disabled。 |
| 204-B07-01 | B07 | PLANNED | B / 证券代理 | REAL_SOURCE | 对证券域样板及分批Provider做真实源/仓/API比对、质量核验与数据权利审查。 | 204-B02-02, 204-B03-02, 204-B04-02 | 每个数据集分别有源响应、落库和API证据；许可未知与历史边界缺失单独登记。 |
| 204-B07-02 | B07 | PLANNED | B / 运维协作代理 | DEPLOYMENT+NATURAL_CYCLE | 在目标环境运行证券代表日更/补数任务，观察至少一个源定义的自然发布周期。 | 204-B07-01, 204-D06-02 | worker、publication、API freshness及自然周期收据可关联；人工补跑不替代自然周期。 |
| 204-B07-03 | B07 | PLANNED | B / C交叉评审 | CODE/OFFLINE | 完成证券源语义交叉审查和运维/源受限runbook。 | 204-B07-02, 204-C07-01 | C审阅并记录异议关闭；runbook含限流/授权/漂移/恢复路径和数据限制。 |

## C：衍生品与其他数据适配

| 子任务ID | 父WP | 状态（as of 2026-10-29） | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-C01-01 | C01 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 刷新其他域候选资产清单并分批逐项处置；449是2026-10-26静态CSV历史候选数，不是当前总数。记录source/provider/模型、参数、sink、消费者、许可及文件关系。 | 204-A01-01 | 每个刷新后候选留处置或待查状态，common脚本按语义重新归属；刷新总分母与历史快照anti-join有解释。 |
| 204-C01-02 | C01 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 实测10个跨期货、期权、FX/crypto、宏观/归档代表源案例及访问/保留边界。 | 204-A01-01 | 每例记录真实源身份、UTC观测时刻、请求/响应摘要、源限制和许可待查项；不等待历史快照中的449个候选文件完成映射。 |
| 204-C02-01 | C02 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 定义期货/期权精确合约、连续/主力/TAS、结算/收盘、持仓与乘数的独立schema和转换。 | 204-A02-02, 204-C01-02 | fixture覆盖夜盘业务日、到期合约、连续拼接边界、负价合法性和单位；不得压成单一OHLCV语义。 |
| 204-C02-02 | C02 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 对指定期货/期权源进行真实参数和交易所日历/合约字段核对，含年度归档边界。 | 204-C02-01 | 源端合约身份、字段、返回起点/终点及授权证据逐项存档；源没有提供的历史留未知。 |
| 204-C03-01 | C03 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 建立FX base/quote、crypto venue/base/quote、小时/日桶、UTC边界及来源时区映射。 | 204-A03-02, 204-C01-02 | 跨UTC午夜/DST样例保持正确业务日；币对方向、计价单位和频率不能静默转换。 |
| 204-C03-02 | C03 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 对选定FX与crypto真实端点核对历史保留、时间戳、限速和日内/日线语义。 | 204-C03-01 | 真实响应与原生时间/币对对照可复现；源快照未覆盖时期不被生成。 |
| 204-C04-01 | C04 | PLANNED | C / 采集代理 | CODE/OFFLINE | 把浏览器capture、年度归档下载和商品期权文件解析封装成有界Provider/Run输入输出。 | 204-C02-01, 204-D03-01 | fixture测试验证超时/退出码/临时文件清理、hash和重复导入幂等；web worker无阻塞浏览器进程。 |
| 204-C04-02 | C04 | PLANNED | C / 采集代理 | REAL_SOURCE | 对获准的浏览器/年度归档入口执行真实拉取并确认许可、来源hash和可恢复点。 | 204-C04-01 | 保留真实响应/文件manifest与失败证据；登录/验证码/WAF阻断形成停止和人工处置规则。 |
| 204-C05-01 | C05 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 建立宏观/财务外部主题数据vintage、修订、公布时刻与可得时刻合同。 | 204-A03-02, 204-C01-02 | fixture可重放旧版/修订版；无历史vintage证据的回测数据标PIT_UNKNOWN。 |
| 204-C05-02 | C05 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 将宏观/财务主题与opendata迭代2模型清单交叉映射，裁定复用、扩展或保持独立。 | 204-C05-01 | 每个重叠项只有一个实现owner与schema；无需把全套迭代2模型重新实现。 |
| 204-C06-01 | C06 | PLANNED | C / 迁移协作代理 | CODE/OFFLINE | 生成原始文件、进度/cooldown/checkpoint和旧数据库映射，定义可回放迁移manifest。 | 204-A04-01, 204-C02-01 | manifest包含hash、时间范围、文件归属、source与旧任务关系；缺映射项显式保留。 |
| 204-C06-02 | C06 | PLANNED | C / 迁移协作代理 | CODE/OFFLINE+REAL_SOURCE | 对批准的衍生品/其他域分区dry-run并按业务键、日历、单位、覆盖做前后对账。 | 204-C06-01, 204-A06-02 | 报告将离线结构差异与真实源可得性分栏；无写操作的dry-run先通过，未解决差异不宣称迁移完成。 |
| 204-C07-01 | C07 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 汇总期货、期权、FX/crypto、宏观/长尾各域的source/warehouse/API实测及许可证据。 | 204-C02-02, 204-C03-02, 204-C04-02, 204-C05-02 | 每个dataset独立给出通过/受限/未知状态及起止范围证据；跨域汇总不能遮盖单项失败。 |
| 204-C07-02 | C07 | PLANNED | C / 运维协作代理 | DEPLOYMENT+NATURAL_CYCLE | 对选择的衍生品/其他域任务完成目标环境运行、自然周期观察、恢复演练和runbook。 | 204-C07-01, 204-D06-02 | 自然发布周期、UTC日桶、续跑收据可关联；B完成语义交叉评审后才申请该域切换。 |

## D：调度、迁移与运维

| 子任务ID | 父WP | 状态（as of 2026-10-29） | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-D01-01 | D01 | IN_PROGRESS | D / 运维代理 | DEPLOYMENT/READ_ONLY | 只读导出实际task/run/claim、crontab/systemd/进程、checkpoint、脚本参数、目标库/表及版本。 | 204-A01-01 | 记录身份、时间、命令与读取边界；不触发生产任务、不暴露secret；与脚本资产清单差异列成待查。 |
| 204-D01-02 | D01 | PLANNED | D / 运维代理 | DEPLOYMENT | 记录目标环境/数据库指纹、允许目标白名单、账号权限分离和恢复基线。 | 204-A01-01, 204-D01-01 | 只读校验能拒绝错误仓库或数据库身份；备份恢复演练步骤有owner，不执行未批准写入。 |
| 204-D02-01 | D02 | DEV_DONE（仅合同/纯函数） | D / dev_runs | CODE/OFFLINE | 定义声明式Job/Run UTC canonical身份合同及规范化/幂等身份纯函数：job版本、UTC计划时刻、分片、运行类型；补数含明确范围和request id。 | 204-A02-02, 204-D01-01 | 固定向量覆盖时区等价时刻、DST、定时与补数不冲突、重试同身份；明确本任务不含durable repository/lease/worker接线。 |
| 204-D02-02 | D02 | DEV_DONE（仅ledger离线） | D / dev_ledger | CODE/OFFLINE | 在独立opendata-od204-ledger分支实现显式Engine注入的SQL持久Run ledger、幂等入队、CAS状态/租约/token、heartbeat、终态和取消；提供owned SQLite双实例行为测试。 | 204-D02-01 | 双ledger实例竞争同一Run时只允许一个有效claim；过期token不能推进状态，重复enqueue幂等，心跳/终态/取消有行为测试。当前不含Alembic接入、调度/worker运行接线或warehouse write fence；父WP D02未完成。 |
| 204-D02-03 | D02 | DEV_DONE（MySQL/SQLite迁移） | D / 运维代理 | CODE/OFFLINE | 为Run ledger分配唯一Alembic迁移序列并集成到目标数据库迁移体系，保持双库版本治理。 | 204-D02-02 | 迁移owner确认revision无多head；warehouse 0010唯一head承接至0011；literal up/down已在独立MySQL8.0.46与SQLite验证，metadata head0006保持独立。PostgreSQL行为未验证；父D02未关闭。 |
| 204-D02-04 | D02 | IN_PROGRESS | D / wave4_worker | CODE/OFFLINE | 把持久ledger接入统一Run service与worker入口，加入持久环境下多进程竞争/崩溃恢复测试。 | 204-D02-02, 204-D02-03, 204-D03-01 | worker只能经Run service领取和结算；重启后租约可恢复，旧token不能写入终态或事实数据。 |
| 204-D03-01 | D03 | IN_PROGRESS | D / 运维代理 | CODE/OFFLINE | 实现Provider task executor协议、统一日志/退出码和可终止的有界子进程执行器。 | 204-D02-01 | 使用冻结合成job/provider fixture推进离线开发；fake provider验证超时、取消、stdout/stderr截断和临时资源回收；API事件循环不被阻塞。 |
| 204-D03-02 | D03 | IN_PROGRESS（仅补数规划预算；重试、并发等未完成） | D / 运维代理 | CODE/OFFLINE | 实现重试/预算/并发/供应商限速/退避、自然槽与显式补数分流及分片规则。 | 204-D03-01 | fake时钟/源模拟证明限速共享、Retry-After受尊重、源WAF不无限重试、历史恢复有独立预算。 |
| 204-D03-03 | D03 | IN_PROGRESS | D / 运维代理 | CODE/OFFLINE | 让APScheduler、手工API、CLI、systemd外壳统一提交同一Run入口。 | 204-D02-01 | 入口只依赖提交SPI，不依赖worker或真实Provider；多入口相同任务映射同一occurrence身份；systemd不再直写warehouse或绕过fencing。 |
| 204-D04-01 | D04 | PLANNED | D / 运维代理 | CODE/OFFLINE | 提供管理员JobDefinition/Run/DQ/coverage后端接口、授权scope、操作者审计和安全取消。 | 204-A02-03, 204-D02-04, 204-A06-02 | 未授权请求被拒绝；审计包含操作者/对象/动作/request_id；取消不可中断阶段真实显示状态。 |
| 204-D04-02 | D04 | PLANNED | D / 运维代理 | CODE/OFFLINE | 实现opendata运维控制台的任务、执行、下次运行、覆盖、隔离、补数/取消/重放和容量页面。 | 204-D04-01 | 页面仅调用受权限保护API，关键操作有确认/结果反馈，失败原因可追踪，不内嵌任意脚本参数。 |
| 204-D05-01 | D01,D05,B01,C01 | DEV_DONE（仅静态盘点工具） | D / dev_inventory | CODE/OFFLINE | 实现opendata/migration_inventory.py、CLI与tests，把AST源文件和可选JSON任务映射整理成可重跑JSON/CSV及双向差异报告，拒绝输出覆盖源/输入；不查生产库、不执行脚本或抓源。 | 204-A01-01 | CLI对相同输入给稳定输出；单测覆盖入口/辅助/哈希、解析失败、重复/缺失映射、路径与输出保护；不宣称源、任务或数据迁移完成。 |
| 204-D05-02 | D05 | IN_PROGRESS | D / 迁移代理 | CODE/OFFLINE | 实现存量Job/执行/checkpoint迁移的只读dry-run、显式apply闸门、备份和目标指纹校验。 | 204-D01-02, 204-D02-03, 204-A04-03 | dry-run拒绝未知目标并汇报导入/跳过/冲突；默认disabled；apply必须检查部署身份与备份可恢复性。 |
| 204-D05-03 | D05 | PLANNED | D / 运维代理 | DEPLOYMENT | 在隔离恢复环境验证元数据/warehouse备份、artifact manifest和迁移后状态的恢复流程。 | 204-D05-02 | 记录RPO/RTO实测、缺失工件与恢复偏差；恢复演练不覆盖生产数据。 |
| 204-D06-01 | D06 | PLANNED | D / 可观测性代理 | CODE/OFFLINE | 连接request/run/source/publication的trace_id，建设低基数日志、trace和指标埋点。 | 204-D03-03, 204-A05-03 | 本地追踪可串起一笔mock查询到Run/publication；instrument维度明细放事件而非高基数标签。 |
| 204-D06-02 | D06 | PLANNED | D / 可观测性代理 | DEPLOYMENT | 配置按源周期的数据freshness告警、API/worker/磁盘/备份SLO仪表盘和故障演练。 | 204-D06-01, 204-D05-03 | 目标环境触发测试告警并可恢复；SLO标为初始目标且经实测校准，未演练前不写已达标。 |
| 204-D07-01 | D07 | PLANNED | D / root+运维代理 | DEPLOYMENT | 以dataset/sink为单位制订新旧单写者fence、影子读、切换清单和分波授权。 | 204-D05-02, 204-D06-02, 204-E06-01 | 每波明确唯一writer、回滚owner、断点和观测窗口；逐dataset检查对应B07/C07真实源、部署和自然周期收据，按单域门禁推进，不等待无关域全量完成。 |
| 204-D07-02 | D07 | PLANNED | D / 运维代理 | DEPLOYMENT | 对单波执行重复投递、worker崩溃/租约过期、源失败和回滚演练。 | 204-D07-01 | 证明旧/新写者不会并发产生重复事实，回滚后可按publication/Run追踪恢复。 |
| 204-D07-03 | D07 | PLANNED | D / 运维代理 | DEPLOYMENT | 在逐域切换验收后停用旧systemd/worker/凭据并保留可审计退役记录。 | 204-D07-02 | 每项旧入口有owner、最后运行和禁用证据；紧急恢复路径经评审，未覆盖域保留旧机制状态。 |

## E：ai-for-investor消费端与业务回归

| 子任务ID | 父WP | 状态（as of 2026-10-29） | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-E01-01 | E01 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 清点AFI所有行情、数据库DSN、文件、直接源SDK、页面与任务读路径，记录调用点和旧功能。 | 204-A01-01 | 搜索结果与运行时路由/后台任务交叉核对；每个读路径归属具体业务场景和责任人。 |
| 204-E01-02 | E01 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 建立功能场景、频率、单位、日期边界、错误和权限回归矩阵。 | 204-E01-01 | 覆盖回测/优化、行情页、搜索、扫描器、信号和研究快照；标出旧行为与目标接口差异。 |
| 204-E02-01 | E02 | DEV_DONE（仅同步SDK v1分页） | E / dev_client | CODE/OFFLINE | 实现opendata同步SDK现有v1 GET的分页请求/响应校验、行/页预算和流式响应字节上限；保持latest-view，不提供固定版本或跨页快照保证。 | 204-A02-03 | mock测试验证页号/大小回显、count为当前页行数、终止条件、超页/超行及流式超限关闭；不含async、整体deadline、通用业务键去重或v2导出。 |
| 204-E02-02 | E02,E03 | DEV_DONE（仅AFI输入校验） | E / dev_consumer | CODE/OFFLINE | 在现有AFI股票日线v1适配器核对响应symbol、严格业务日期和分页元数据，拒绝重复页；流式读取并限制单响应/累计字节，保留原窗口转换与过滤。 | 204-A02-03, 204-E02-01 | 单测覆盖错/缺symbol、非法日期、首尾过滤、错误分页类型/回显/count、重复页/超行/超字节及关闭；不声称新增cursor/snapshot/其他资产支持。 |
| 204-E02-03 | E02 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 为async FastAPI读路径加独立Async HTTP适配器或薄REST层，确保不在事件循环调用同步SDK。 | 204-E02-01, 204-E02-02 | async并发测试确认无同步阻塞；请求使用共同OpenAPI fixture，适配层不复制provider/清洗逻辑。 |
| 204-E02-04 | E02 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 统一认证、单位/时区、deadline、有限重试、request_id、429/503/空结果错误映射。 | 204-E02-03, 204-A02-04 | 重试只覆盖幂等读且受总deadline限制；scope/许可错误不重试；可区分合法空、未覆盖、无权和中台不可用。 |
| 204-E03-01 | E03 | IN_PROGRESS | E / afi_inventory | CODE/OFFLINE | 将行情列表、搜索、覆盖/主题卡等首批业务读路径改到REST client。 | 204-E02-04, 204-A05-01 | API级测试证明业务路径无数据库直读/源SDK调用，页面字段/单位和分页行为符合场景矩阵。 |
| 204-E03-02 | E03 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 迁移单标的分析、扫描器、信号所需行情读路径并明确频率不可用时的业务响应。 | 204-E02-04, 204-A05-02 | 集成fixture验证symbol、日期、频率及缺口提示；不静默降频、换源或改变策略语义。 |
| 204-E03-03 | E03 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 补齐迁移业务页面和关键API回归，保持已有分析功能并标记暂不可用能力。 | 204-E03-01, 204-E03-02 | 既有场景矩阵逐项有通过/限制结果；错误提示可行动且不把质量部分数据冒充完整。 |
| 204-E03-04 | E03 | PLANNED | E / 股票分析REST消费代理 | CODE/OFFLINE | 把股票分析市场/财务事实读取改为OpenData REST固定publication vector；后台执行以实际请求用户身份重新取权并复核`READ_DATA`及source research grant。AFI只在单次请求内持有数据，不新建/写入可复用事实缓存，不保留直连SDK、仓库读或其他来源fallback。 | 204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-B02-04, 204-B02-05, 204-E02-04 | 单测验证只请求已支持dataset、cutoff/sequence固定、用户和grant在后台执行时有效；DB/cache写入、授权撤销、API 4xx/5xx、BSE或对应数据族coverage UNKNOWN/PARTIAL均停止分析，不访问fallback。 |
| 204-E03-05 | E03 | PLANNED | E / 股票报告契约代理 | CODE/OFFLINE | 定义首版股票分析报告的必需数据、字段/单位/质量/coverage门槛和可见限制；输出持久保存每个dataset的publication_id/sequence、可信cutoff/visibility vector、content hash、contract/schema hash、source/grant revision及业务窗口。临时snapshot ID可作调试引用，但不作为durable replay依据；确认publication/vector保留期覆盖报告复现期。只保存用户请求的分析工件，不把REST事实行或可复用衍生事实写回AFI。 | 204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-E03-04 | 离线用例验证完整输入产生带持久溯源报告；缺必需数据、visibility证据、时间/单位/来源证据、权限、保留期或可信coverage时不产生/保存报告；重放用publication vector而非临时ID；不声称source-known/market-known/严格历史PIT，也不把未接入新闻/情绪/同行标为已覆盖。 |
| 204-E04-01 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 为研究快照/导出增加publication、schema、过滤条件、内容hash与来源manifest引用。 | 204-A04-03, 204-E02-04 | 相同固定snapshot可重放同一工件；哈希/契约不匹配时拒绝加载。 |
| 204-E04-02 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 将回测/优化输入绑定固定snapshot、PIT要求、数据版本与明确的时间窗口。 | 204-E04-01, 204-A05-02 | 对冻结fixture重跑结果可核验；不满足严格PIT/缺口阈值时明确失败或降级为标注研究。 |
| 204-E04-03 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 实现sealed数据集、用户/租户研究权限和导出/工件访问控制。 | 204-E04-02, 204-A05-03 | 越权和跨租户测试拒绝读取/导出；授权缓存随权限变化失效。 |
| 204-E05-01 | E05 | PLANNED | E / UI协作代理 | CODE/OFFLINE | 将旧数据管理入口加兼容提示/跳转到opendata控制面，保留必要只读摘要入口。 | 204-D04-02, 204-E03-03 | 旧URL可解释地跳转或展示只读视图；无管理权限用户看不到操作入口。 |
| 204-E05-02 | E05 | PLANNED | E / UI协作代理 | CODE/OFFLINE | 为保留的AFI行情/可用性页面接入真实coverage/freshness状态。 | 204-E05-01, 204-A05-02 | 状态明确区分PARTIAL/UNKNOWN/SOURCE_LIMITED/NOT_APPLICABLE；无coverage时不显示“完整”。 |
| 204-E06-01 | E06 | PLANNED | E / 集成代理 | DEPLOYMENT+REAL_SOURCE | 对授权样本执行新旧影子读比对，记录行、字段、单位、来源、时间边界和差异。 | 204-E03-01, 204-E04-02, 204-D06-01 | 同一固定窗口能逐标的对照；影子阶段不重复触发全量真实抓取、不把旧错误当基准正确。 |
| 204-E06-02 | E06 | PLANNED | E / 集成代理 | DEPLOYMENT | 验证AFI在opendata超时、限流、源受限、权限失败和部分覆盖时的降级/恢复体验。 | 204-E06-01, 204-E02-04 | 目标环境的故障注入保留request_id并返回正确业务状态；服务恢复后可重试且无重复提交。 |
| 204-E06-03 | E06 | PLANNED | E / 跨仓股票研究验收代理 | CODE/OFFLINE+REAL_SOURCE | 在受控集成环境用一个或少量已授权沪深标的验证AkShare日线与Fuyao财报从真实返回、OpenData post-commit visibility seal、固定cutoff/sequence snapshot vector REST到AFI研究请求的端到端证据链；限制请求范围，不运行全A全历史下载。 | 204-A04-04, 204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-B02-04, 204-B02-05, 204-E03-05 | 记录请求主体/grant revision、数据集/标的/业务窗口、AkShare函数→实际来源产品→字段、source响应摘要与hash、原始时区文本/转换规则、`observed_at`、post-commit visibility seal、原生单位、publication/vector/content+contract hash和报告工件hash；同一固定vector重放一致，逐字段/缺口差异有解释。无法取得真实证据则该验收面保持NOT_RUN/SOURCE_LIMITED，合成测试不能替代；不代表生产部署、全市场或全历史验收。 |
| 204-E07-01 | E07 | PLANNED | E / 集成代理 | CODE/OFFLINE | 在对应业务路径切换并具备回滚条件后，移除AFI采集SDK、仓库DSN和采集启动hook。 | 204-D07-01, 204-E06-02 | 静态依赖/运行时扫描无未批准直连；保留的专有研究数据路径有单独归属声明。 |
| 204-E07-02 | E07 | PLANNED | E / 集成代理 | CODE/OFFLINE+DEPLOYMENT | 检查安装包、容器、CI secret、环境变量和启动配置边界，确认只保留必要opendata client与身份。 | 204-E07-01, 204-D07-02 | 构建产物不含opendata内部包/服务DSN/源密钥；目标环境AFI只持有最小读scope。 |

## 首批子任务精确范围

| 子任务 | 当前代理 | 本轮明确不包含 |
|---|---|---|
| 204-D05-01 | dev_inventory | 真实生产任务/数据库读取、执行脚本、真实源验证、完整迁移导入。 |
| 204-A06-01 | dev_coverage | 数据源边界背书、数据库/仓库接线、coverage API或历史数据完整性结论。 |
| 204-D02-01 | dev_runs | durable repository、Alembic、worker/调度接线、真实部署或warehouse write fence。 |
| 204-E02-01 | dev_client | AFI异步调用接线、v2 snapshot/export、大批量无界下载或源选择/清洗逻辑。 |
| 204-E02-02 | dev_consumer | 所有消费页迁移、真实源校验、绕过错误symbol时自动猜测/回退。 |
| 204-D02-02 | dev_ledger（独立分支 opendata-od204-ledger） | Alembic/运行接线/warehouse write fence；该ledger必须由root与dev_runs契约集成后再并入主线。 |

下一波可按接口和文件owner把PLANNED任务重分配给现有子代理或新代理。若任务依赖的合同尚未合入，可先用本清单的fixture/冻结接口推进离线代码；涉及共享文件、真实凭据、生产写操作、部署或自然周期的工作按对应owner和验收面排队，不能因代理空闲而并发改同一文件或提前标记通过。
