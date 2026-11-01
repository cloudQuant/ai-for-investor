# 股票日线 v2 交付计划

本文件补充迭代204的股票日线交付步骤，不改变 `SUBAGENT_TASKS.md` 的任务状态、分母或 `DEVELOPMENT_STATUS.md` 的计数。目标是让 OpenData 以 `market + symbol` 为明确查询主键提供固定版本的股票日线 records；AFI 只在显式启用后消费该 v2 合同。**现状**：market-symbol profile REST 当前硬关闭；records DTO 尚未携带成对市场/代码；现有 store 在创建 pair snapshot 时，会对截至该 publication sequence 的 dataset 历史（含 tombstones）执行 NULL/漂移 fail-closed 预检，命中则拒绝创建 snapshot；既有 snapshot 的 page read 不重复执行这次全 dataset 扫描。该检查只能排除已识别的 NULL/漂移，不能发现所有记录以同一方式错配 pair；现有证据也不能按单 pair、单身份有效期证明既有版本。覆盖证据目前只到指数；AFI v2 消费仅到指数；`stock_daily` job 尚未审查，`market=cn` / BSE 的语义也未验证。**本计划目标**：在保留上述 fail-closed 行为的基础上，为有界、时态身份明确的 pair snapshot 固定并呈现全量检查及独立来源/主数据核对证据，扩展覆盖与 AFI raw v2 消费；不把尚未实现的 DTO、REST、逐证券覆盖和跨 pair 历史聚合写成现有能力。实际授权文书、生产 grant、完整查询计划及数据范围尚无可核验收据。任何代码合并、合成测试或少量真实样本都不能代替这些边界。

## 1. 目标与交付边界

首个可交付切片是**单一证券 pair 的、未复权日线数据 v2**：

- `instrument_id` 是稳定证券身份；`market + symbol` 是带有效区间的时态标识，不是永久证券主键。同一 pair 在不同时段可能对应不同身份；按 pair 查询必须指定单一有效区间，遇到身份歧义或区间重叠就拒绝。按 `instrument_id` 查全历史时，由 AFI/调用客户端汇集该证券历任 pair 的多个独立单-pair snapshots，并保留身份链；当前不假设存在能把全身份链绑定成一个原子 snapshot 的 descriptor。不得仅按代码前缀推断市场，不得把 `cn`、沪深、北交所或全国股转当作同义值，也不得只凭裸代码合并证券。
- v2 的每个 records snapshot 与 cursor 仅绑定一个 pair、一段身份有效期、一个数据集、publication、过滤条件及稳定排序。跨多个 pair/有效期的全历史结果由客户端合并多个分别固定的 snapshots；每个子 snapshot 独立验收和留据，不能声称这些 publication 构成同一时点的原子视图。分页不能读到后续发布或其他 pair 的记录。
- 对每个 pair，完整性依赖可信证券生命周期、市场交易日历、停牌/无成交等例外证据及逐行 record-set 对账；无法证明时返回 `UNKNOWN` / `PARTIAL`，不把缺行解释成零成交，也不以全表最大日期证明完整。
- AFI 对请求和**每一行响应**都做严格 pair/日期/分页/版本校验。v2 缺失、错误或不支持时明确失败；不隐式回退到 v1、AFI 本地库、缓存或其他 provider。
- 默认 feature flag 为关闭。只有离线验收、真实来源验收、目标部署数据库验收、逐证券覆盖证据及回滚演练全部通过后，才由明确的运维变更启用。

本计划以全 A 股为最终业务范围，但不假定目前已有权威全集、北交所支持或每个证券从真实起点开始的完整历史。先冻结沪深/北交所等市场的具体边界；不具备独立主数据和数据来源证据的证券与市场保持不可用。行情范围是 raw 日线；复权、分钟线、财务、指数及其他数据集不由本计划顺带验收。

## 2. 开工前的只读基线和准入门

集成负责人先在两个仓库记录脱敏基线：checkout/commit、未提交文件清单及哈希、OpenData schema migration head、运行时/依赖版本、接口合同版本、生产与隔离数据库身份标签、配置项存在性（不读出密钥）及当前 feature-flag 值。任何采集、DDL、调度启停、生产写入均不得作为基线盘点的一部分。

在真实来源请求或部署操作前，数据负责人需要拿到可审阅的准入收据，至少明确：

1. 每个实际来源产品/API、适用账户/主体、允许的市场和数据集、自动采集、保存期限、内部 API 服务范围、请求/并发/日额度、单次最多行数/字节数/查询跨度、数据再使用限制及授权有效期。已有口头授权声明可作为调查线索，不能代替具体来源 grant 和适用范围核验。
2. 全 A 股范围定义：所含交易场所（含/不含 BSE 和其他市场）、当前与退市证券、证券类别、稳定 `instrument_id`、市场/代码变更历史、来源版本与生效时间。证券全集的生成方法、更新时间及其自身完整性证明必须记录。
3. 每一来源可回取的历史起点、分页/限额/调整方式、历史修订与删除行为、交易日历及生命周期来源、单位和空值语义。来源最早返回日期只说明可观察边界，不等同上市日或全历史起点。
4. 目标生产 schema、数据库产品/版本、只读查询账号及允许的隔离性能验证环境；生产 read/write 角色、备份/PITR、恢复负责人和回滚窗口。本计划只验收股票日线写入、migration 与 REST 查询在实际目标 SQLite/MySQL 路径上的行为；这些股票链路在 PostgreSQL 下尚未验收，PostgreSQL 不属于本次目标。这不对应用其他数据域的 PostgreSQL 支持状态作判断。没有明确的数据库身份、数据授权和只读边界时，不运行真实查询或 explain。

准入项缺失时仍可完成脱敏代码盘点、合同设计和合成 fixture 开发，但真实采集、生产 grant、生产数据写入及切换标记为 `NOT_RUN` / `SOURCE_LIMITED`，不开启功能。

## 3. 五人并行分工与文件所有权

并行在现有 `dev` checkout 按明确文件域进行，由一名集成负责人维护基线、契约冻结、跨仓合并和发布裁决。下列路径是所有权边界；开工前由负责人根据仓库实际目录映射到精确文件清单。新增或跨域文件先指定唯一 owner，其他人不并发编辑。

| 人员 | 独占文件域 | 交付物 | 复核重点（建议） |
| --- | --- | --- | --- |
| A：v2 API、迁移和共享合同 | OpenData `published_data.py`（其中 DTO 与 route 同文件）、其余 v2 records DTO/OpenAPI；唯一拥有 Alembic migration 文件及共享合同 fixtures 的人 | pair/identity API 合同、迁移 revision、错误码、共享 golden fixtures 和兼容性测试 | D 复核 query/snapshot 接线；E 复核 AFI 契合；集成负责人确认唯一 migration head |
| B：证券主数据与历史基线 | OpenData instrument reference、时态 market-symbol identity 模型、生命周期/别名/交易日历映射、只读历史基线扫描及差异工具；只提交 migration 需求，不编辑 Alembic 或 D 所有文件 | 权威 universe 证据清单、时态映射、NULL/漂移/重复/孤儿行分类及逐 instrument/pair baseline receipt | C 复核 provider 映射；D 复核 coverage 期望键和扫描一致性 |
| C：来源适配与运行任务 | OpenData 股票日线 provider、字段/单位映射、`stock_daily` job/历史回补与增量执行器及其专属 fixtures；不编辑共享注册表/合同 fixture | 脱敏来源映射、请求/行数/体积限额、持久分片/断点/幂等策略、可重放 raw batch 与 run receipt | B 复核市场和时态证券身份；A 复核记录满足冻结 DTO |
| D：publication store、pair selection、coverage 与查询性能 | OpenData `publication_store.py`、`market_symbol_selection.py`、coverage service 及 stock store 查询层；不编辑 `published_data.py`；隔离数据库计划/性能收据 | 固定版本存取、pair identity 选择、逐证券 coverage、并发改写拒绝、record-set digest/计数、EXPLAIN 和容量收据 | A 复核 API 描述一致；B 复核 coverage 期望键；运维复核目标数据库行为 |
| E：AFI 消费端 | AFI OpenData v2 client/stock_daily 新路径、业务读路径及其专属合同/回归测试；不改 OpenData 或共享 OpenData fixtures | 默认关闭的 raw v2 reader、strict row checks、稳定错误呈现及禁止 v2→v1/本地/缓存 fallback 的测试 | A 复核合同映射；集成负责人复核旧 v1 路径与新 raw v2 路径隔离 |

共享约束：`published_data.py`（DTO 与 route 同文件）、其余 v2 records DTO/OpenAPI、Alembic revisions 及共享 API 合同 fixture 唯一归 A；instrument reference/时态身份模型唯一归 B；`stock_daily` Provider/job 与来源 fixture 唯一归 C；`publication_store.py`、`market_symbol_selection.py` 和 coverage service 唯一归 D；AFI client/consumer 代码与其测试唯一归 E。仓库中这些核心路径的实际位置须在开工基线中逐个映射并登记，不能仅按上述文件名推定路径。公共注册表、依赖锁、公共 fixture 若不属于上述所有权，由集成负责人指定唯一提交者。跨域签名/迁移先停下并重新分派，不在同一 checkout 交叉覆盖。每个 PR 绑定精确 HEAD、列明改动路径/验收证据/未验证项；作者按仓库规则提交 self-review；跨域 review 用于发现契约问题，不新设强制的独立审批门槛。集成负责人逐项检查依赖顺序、migration head 和合并后的 dev 状态后才合入。审查授权遵循仓库当前流程及用户对审批流程的明确指示。

## 4. 分阶段实施、依赖和合并顺序

| 阶段 | 负责人 | 具体步骤与冻结产物 | 出口条件 |
| --- | --- | --- | --- |
| S0：盘点和准入 | 集成负责人、B、D | 保存脱敏双仓基线；只读盘点已有 stock_daily schema、行级 pair 来源、全 dataset as-of snapshot 的 NULL/漂移预检（含 tombstones）及拒绝行为、job 配置、market 枚举及部署数据库身份。建立 `UNKNOWN` 项账本和数据范围草案。 | 预检须覆盖该 as-of dataset 的全部历史行和 tombstones；发现 NULL/漂移即拒绝创建/返回 snapshot，不把坏行混进 records。当前实际行为须记录证据；未实现或未证明时保守禁用 pair completeness。无证据则不进入真实数据阶段。 |
| S1：合同冻结 | A，E/D 评审 | 冻结 v2 market-symbol 请求/响应 DTO、规范化 pair、dataset/profile、日期半开窗口、稳定顺序、错误语义、v1 字节/行为兼容边界；明确定义数据集和 schema 版本。 | OpenAPI 与 golden fixtures 同时表达 pair；完整请求响应不含猜测值；兼容性评审通过后方可并行实现。 |
| S2：证券主数据和历史基线 | B，A/D 支持 | 新建具有效时间的证券 reference 模型，允许稳定 `instrument_id` 在时间上关联多个 market-symbol pair；迁移旧生命周期/presentation 模型时不假设它已具备时态 pair。运行只读全 dataset baseline，分类 NULL pair、pair 漂移、重复 key、身份冲突、无主数据映射和无法归属行；按 universe 版本、`instrument_id`、pair 有效区间输出 sorted business key、行数和内容 digest。 | 每个 pair 的有效区间至多映射一个 `instrument_id`；冲突区间拒绝发布/查询。所有未解决行隔离；每 pair baseline 可复算。全市场或历史边界未证实则明确 `PARTIAL/UNKNOWN`。 |
| S3：schema 与 immutable publication | A、D，B 提供迁移需求 | 为时态 identity、成对 selector/profile 与 publication 绑定增加前向兼容 schema。旧行 NULL 不推测回填；旧生命周期/presentation 行只在独立证据映射后迁移。建立已发布记录/既有 snapshot 不可被后续 run 静默改写的约束。 | migration 升级与恢复保护通过离线检查；未证明的 NULL/漂移/时态冲突不进入可查询 publication；同一 publication 的身份与 business key 不可变。 |
| S4：pair 查询与证明 | D store/coverage、A `published_data.py` route/DTO | 实现单一 pair、单一身份有效期的 records 查询、snapshot 描述、coverage 和 cursor；查询使用同一一致性读视图/固定 publication。cursor 必须绑定该 pair、单一身份有效期、dataset、publication id/sequence、profile/schema、日期窗口、过滤条件、排序版本和身份主体。跨多个 pair/有效期的请求必须拒绝或拆分；不得创建貌似原子的一体化快照。按 `instrument_id` 的全历史读由客户端先取得经版本固定的身份链，再分别创建各 pair/有效期的 snapshots 并合并；每个 cursor 只续用自己的子 snapshot。 | 两证券交错分页仍只读指定 pair；新 publication 不改变旧 snapshot；换 pair/有效期/窗口/排序/主体或篡改 cursor 一律拒绝；页内与页间 record-set digest 可核验。客户端合并必须保留各子 snapshot receipt 和身份链，并明确多 publication 之间无原子 as-of 保证。 |
| S5：provider、全历史和增量任务 | C、B、D | 明确日期边界转换：来源闭区间 `[source_start, source_end_inclusive]` 映射为 REST 半开区间 `[start, end)` 时 `start=source_start`、`end=source_end_inclusive + 1 calendar day`；反向调用来源时 `source_end_inclusive=end_exclusive - 1 calendar day`。按来源合同验证边界；每行强制 `trade_date == business_date`，不做隐式时区/日期修正。单次来源请求和回补分片最多 3,660 个日历日，且不得超过当前行数、响应体积、planner/query 预算任一既有上限。全历史拆为持久化、可恢复、幂等的分片；按 `instrument_id` 跨该证券历任有效 pair 采集，身份区间交界拆请求，歧义时拒绝。增量从每 pair 已验证 watermark 继续并做重叠校验。 | 每个请求/分片/pair 有持久 run receipt；返回、插入、更新、重复、拒绝、缺口、截断和错误均对账。部分失败可独立重放；所有分片和预期日通过前不推进 complete watermark。 |
| S6：AFI v2 严格消费 | E、A | 保留现有 AFI qfq/display v1 路径及语义，新增独立、默认关闭的 raw stock_daily v2 reader/API 调用，不直接替换或混用旧路径。验证响应 envelope 和每行 pair、instrument、trade_date/business_date、单位、publication/cursor。清点所有消费者。 | 显式启用的新路径只请求 v2；任何 v2 缺失/错误都中止，不回退 v1 或本地数据。旧 v1 按原合同单独运行，不被误当 v2 证据。 |
| S7：离线集成与安全验收 | 五人；集成负责人主持 | 使用合成 fixture + 隔离 SQLite 及项目实际支持/目标数据库（SQLite 或 MySQL）的版本矩阵；执行合同、迁移、并发、snapshot/cursor、分页、回填/增量、权限与 AFI 回归。固定当前 snapshot row/byte/page/TTL 与 planner limits；无界集合拒绝或分页，不静默放宽上限。分别记录离线证据与未运行项。 | 证据指向精确 dev commit、合同 hash、migration head、工具/DB版本；SQLite 证据只适用于 SQLite，MySQL 证据独立记录；测试不连接供应商或生产。未完成项继续 OPEN。 |
| S8：受控真实来源及部署验收 | B/C/D/E 与运维授权人 | 仅在 S0 准入完成后，以有界获准 cohort 和请求额度验证真实来源→ODS/DWD→post-commit publication→v2 REST→AFI；先用隔离目标库，再按单写者与监控方案在目标部署验证。逐证券扩大 cohort，达到范围再评估全 A 切换。 | 每条证据链完整且差异清零；目标数据库性能、安全、备份恢复、自然周期和 rollback 通过。此阶段审批独立于代码合并；未执行不称为生产验收。 |

建议代码合并顺序：**S1 A 合同及共享 fixture** → **S2 B 时态主数据模型** → **A migration** → **D `publication_store.py` / `market_symbol_selection.py` / coverage** → **A `published_data.py` route/DTO 集成** → **C provider/job** → **E AFI 新增 raw v2 路径（含按身份链合并多子 snapshot）** → **S7 集成证据/文档**。C 可在 S1 后基于 fixture 并行开发，但需等待 B 冻结身份有效区间后实现真实映射。每个 PR 先做差异审查、合同/迁移影响 review、定向离线验收，再由唯一集成人按依赖次序合并并复核精确合并结果；依据用户当前决定，既有 CI 问题可暂时记录并忽略，但不得把未通过 CI 写成通过；合并后刷新 dev 基线再开下游 PR，不保留临时分支或工作区作为唯一成果。

## 5. 完整性与增量证据

### 全历史基线

基线分母必须来自版本化且可审阅的证券全集与各证券生命周期证据，而不是 DWD 当前已有代码。新增时态主数据至少保存稳定 `instrument_id`、market-symbol pair、`valid_from`（含）/`valid_to`（不含）、来源/版本/hash、核验时间及有效/更名/退市等状态。一个 `instrument_id` 可在不同时段关联多个 pair；某 pair 在同一有效区间不可映射到多个身份，区间端点规范化并拒绝重叠。代码复用必须拆出不同 `instrument_id` 与不重叠 pair 区间，API 不接受裸 symbol 作为唯一选择条件。按稳定 `instrument_id` 获取全历史时，调用客户端分别查询该证券所有已证明的历任 pair/有效期 snapshots 并合并，保留每条 row 对应的 pair 和有效区间及各自 snapshot 收据；多个 snapshot 不自动构成同一时点的原子视图。不能证明的身份或生命周期边界记录为 `UNKNOWN`，不得拿来源最早返回日期补作上市日期。旧生命周期/presentation 模型不具备时态 pair 能力，必须新增或版本化时态主数据表/模型；不以一次性重命名字段充当身份迁移。

日线预期记录集合由相应交易所业务日历与证券生命周期共同产生。按 `Asia/Shanghai` 业务日期检查 head、interior、tail 缺口；停牌、无成交、上市首日、退市后等缺行须由独立事件/源数据解释，不用虚构 bar 填洞。输出以 `instrument_id × 时态 market-symbol pair × dataset × publication × window` 为单位，列出期望键、实际键、重复键、NULL/漂移、身份冲突、未知状态、前后界及可解释的缺口。整批 counts 或 `MAX(business_date)` 不得替代逐 pair 核验。

对每个 `instrument_id` 和每段 pair 有效区间建立可复算 record-set 收据：规范化排序规则、记录总数、business key 数、重复数、首末业务日、NULL/漂移/拒绝数量、内容 digest、schema/conversion hash、source/run/response receipt、publication id/sequence 和 seal。digest 必须覆盖实际业务值及关键来源/版本字段，不能只哈希行数或日期范围。每次 dataset as-of snapshot 创建前，全量预检其历史记录集并包括 tombstones；任一 NULL、pair 漂移、重复或无法归属即拒绝整个 snapshot，不返回包含坏行的结果，也不允许其他 pair 绕过。全扫描只证明结构一致性，无法发现所有行都以同一方式错误归属；还需对照独立来源回执与独立证券主数据/交易日历做映射核验。仅在可信、版本固定且覆盖完整 dataset 的 integrity closure receipt 被固定引用后，才可省略重复全扫；没有可信全量证明时不能绕过扫描或声称 pair 正确。基线发现的旧版本错误只能生成隔离/修复计划；不得在快照扫描中静默覆盖、推断 pair 或把旧坏行认作正确历史。

### 增量与恢复

每个时态 pair 单独保存 `last_verified_publication`、verified watermark、上次 record-set digest 和源端支持的 revision/deletion 窗口。provider 使用闭区间输入时，转换为 REST `[start,end)` 时将 `end_exclusive` 设为 `end_inclusive + 1 calendar day`；REST 到来源闭区间转换为 `end_inclusive = end_exclusive - 1 calendar day`。本字段针对日线业务日期，不允许基于当地时区隐式换算。每行强制 `trade_date == business_date`，不一致直接隔离/拒绝，不能“修正”其中一方。单次源请求最多跨度 3,660 个日历日；全历史回补必须拆成具持久化状态的分片，并同时服从当前每请求行数、响应字节数、snapshot/query planner 预算等既有限额，任何 cap 不清楚先盘点而不放宽。分片有稳定 idempotency key、范围、身份区间、cursor/page receipt、输入/输出 hash 与 terminal 状态；worker 重启能从已确认页或上一个完整 shard 恢复，无法判断某页是否已提交时先对账再重放。水位只在完整请求窗口、预期交易日集合、分页终止标记、行数/hash 对账和质量门槛全部通过后推进。部分失败、超时、限流、截断、未知空响应或来源变更均保留旧 watermark，并以可重放 run receipt 恢复。

`COMPLETE` 表示对声明的 universe version、生命周期证据、来源能力边界、publication 和窗口满足逐证券逐预期键对账；不表示数据供应商能提供其保留期之前不存在的历史，也不自动表示 strict historical PIT。超出来源可回取边界的历史必须单列 `SOURCE_LIMITED`，不得改写成“已完整”。

### 数据库并发篡改与一致性

- 对 baseline / coverage 的多步读使用目标数据库明确支持并实际验证的一致性快照；同一核验过程不能在不同事务中分别读 count、key 和 values 后拼成假一致结果。隔离级别、锁/快照保证及数据库版本写入验收收据。就本计划的股票写入、migration 与 REST 查询路径，分别核验实际目标 SQLite 或 MySQL 产品/版本；该股票链路尚未在 PostgreSQL 上验收，PostgreSQL 不作为本次目标，这不表示应用其他数据路径不支持 PostgreSQL。
- API 读取只针对 immutable publication。发布前将输入范围、排序、行数和 record-set hash 固定；事实提交后再执行 post-commit visibility seal。seal 与 publication 关联，之后若同一版本底层数据发生变化，读时校验失败并告警，不对旧 cursor 返回新值。
- 同一数据库中保存的 hash/manifest 可发现普通一致性错误，但数据库管理员若能同时改事实、hash 与 seal，就不能形成对该管理员的防篡改证明。若验收要求抵御 DB 管理员篡改，publication manifest 必须由不在 DB 控制域的密钥签名，并写入独立权限域的只追加/WORM 存储；读/审计时验证签名和锚点。未部署外部签名/独立存储时，结论只能称为“一致性检测”，不能称“防篡改”或“不可抵赖”，且应将其列为该验收的阻塞项。
- 通过唯一约束/事务检查保证同一 publication 下 pair/business key 不重复且不漂移。NULL pair、重复 pair、身份映射冲突、seal 缺失、publication hash 不符均拒绝发布或查询。
- 测试并发注入：在 snapshot 创建与后续分页之间插入/更改/删除行、修改 pair、重放旧 cursor、同时写入新 publication、在对账期间改写数据。旧 snapshot 要么稳定返回相同记录集，要么显式失效；绝不能悄悄改变内容。若底层数据库无法提供所需隔离/不可变约束，则该后端不能获生产通过。
- 测试中的 SQLite 结果只证明该 SQLite 配置。若目标股票链路运行于 MySQL，其产品/版本的 MVCC/锁、唯一索引、事务隔离、migration 和并发语义需另行验证；不得以 SQLite 外推。本计划不验收 PostgreSQL 下该股票写入、migration 与 REST 路径，也不据此判断应用其他路径的 PostgreSQL 支持。

### 独立数据库 EXPLAIN

查询计划和负载测量只在**与生产实例隔离**的 SQLite/MySQL 验证实例进行。由运维提供经脱敏的 schema/migration 与代表性合成分布，记录 DB 产品/版本、配置、索引、统计信息生成方法、数据规模、SQL 参数形态和 explain 输出。至少检查 instrument identity + 时态 pair + publication + business_date 半开区间及稳定分页顺序是否使用预期复合索引；检查扫描/排序/临时表和估算行数。不得对生产库运行 `EXPLAIN ANALYZE`、执行写入型 explain 或未授权的重统计。盘点并冻结当前 `max_snapshot_rows`、`max_snapshot_bytes`、`page_size`、snapshot TTL、max query window、单次行数和 planner/query budget；v2 在没有另行 review 前不提高既有限额。若某项现无显式值，先新增明确、可测的拒绝上限再开放路径。超界时拒绝或分页，不退化为无界全 dataset 扫描；snapshot/cursor TTL 不超过当前服务既定最长 7 天，长期研究重放须使用受控保留的 publication/vector 引用。EXPLAIN 收据是性能设计证据，不是生产数据正确性或容量承诺。

## 6. Snapshot、cursor 与 API 行为合同

每个单独 snapshot 必须只对应一个规范 pair、该 pair 的一个身份有效期、一个 dataset/profile、固定 publication/as-of 规则及半开日期窗；不能横跨同一 `market+symbol` 的代码复用区间。服务端只在精确权限/grant 通过后访问 store，并为该请求固定 snapshot descriptor。以 `instrument_id` 获取跨多个历任 pair 的全历史时，AFI/调用客户端先读取固定版本的身份链，再为每个 pair/有效期创建和读取独立 snapshot，校验每份子收据后在客户端合并。每个游标只能用于对应子 snapshot。除非未来新增并验收一个明确绑定整条身份链及所有子 publication 的 aggregate descriptor，计划不假设多个 snapshots 之间具备原子或同一 as-of 视图；合并后的报告必须记录所有子 snapshot/vector，并标明该限制。descriptor 至少绑定：

`market + symbol + instrument_id + pair-validity interval + universe/reference-data version + calendar version + dataset_id + profile/schema version + publication_id/sequence + visibility seal + contract/content hash + date window + filters + ordering version + page-size/row/byte/window/TTL policy + principal/scope revision`。完整性声明还需引用该 publication 对应的全 dataset integrity closure receipt、独立 source/master-data reconciliation receipt 及二者的固定版本/签名状态；没有这组 pinned 证据时只能返回数据，不能返回 `COMPLETE`。

每页 records DTO 均包含可逐行校验的 pair 和 `instrument_id`，不得只在顶层回显 pair。cursor 是受完整性保护的不透明 token，至少引用 descriptor hash、页边界、稳定排序键及有效期；任何关键绑定项不一致、未知或无效时返回明确错误。后续页永远从创建时的 publication 读取，不能跟随“最新”。固定排序须使用唯一的 tie-breaker；跨页重复和漏行由 fixture 与 record-set digest 检查。

旧 dataset-wide snapshot 创建前须对该 as-of 历史全量预检，扫描范围包含 tombstones。发现任意 NULL/market-symbol 漂移、重复或无法归属行时，拒绝创建/返回整个 snapshot，不把坏行返回给任何 pair，也不允许请求 pair 绕过全量预检。若不能从原始证据确定旧行 pair，就不自动回填、不通过 symbol 规则猜测，也不复用旧 cursor；修复后在新的经核验 publication 下重新建立可寻址记录集。数据库整体 pair 值一致但一致地错配时，全量扫描本身发现不了，仍须用独立来源和时态主数据对账。v1 路由、cursor 与输出字段维持既有合同，不混入 v2 的 pair 语义。

## 7. AFI 每行严格校验与默认关闭

AFI 现有 qfq/display v1 路径保持独立、原语义保留；新增的未复权 raw v2 reader 使用单独路由/调用方法和独立 DTO，不直接替换 qfq/display，也不混用两条路径的缓存、单位或 feature flag。v2 client 在落入业务对象前验证：HTTP 成功且 JSON/schema 版本受支持；请求 pair 与顶层 descriptor、snapshot 和每行 `market`/`symbol`/`instrument_id` 及有效区间一致；日期在请求半开区间且 `trade_date == business_date`；business key 不重复；分页 cursor 与 publication/window 绑定且无循环；单位、raw adjustment basis、空值和时间字段符合冻结合同；coverage status 是可接受的逐证券状态。

任何一行缺少 pair、pair 不一致、instrument 映射不符、时态区间歧义、schema 不明、NULL/漂移记录、重复或跨页变化、cursor 异常、publication/pinned integrity evidence 不可验证、coverage `UNKNOWN/PARTIAL`、grant 过期/撤销、网络/HTTP/解析失败都使**v2 请求**失败。不得丢弃坏行后继续、不补零、不静默降低窗口、不读取 AFI warehouse/cache、不从 v2 切到 v1 或第二 provider。错误需带稳定错误类别与 `request_id`，不包含密钥、DSN 或原始敏感 SQL。v1 是否可供明确选择的既有业务路径使用，按其既有合同单独处理；它不是本次 raw v2 的兜底。

开关关闭时新增 raw stock_daily v2 功能对用户呈现为明确的不可用/维护状态；不以现有 qfq/display v1 实现 raw v2 的替代路线。每个部署环境显式配置新 flag，默认 `false`；启动和健康检查暴露当前状态及合同版本，但不泄漏秘密。只有 S8 的批准记录绑定 AFI/OpenData 精确 commit、feature flag、grant、部署配置和观察窗口后才允许设置为 true。AFI 仅为单次请求暂存事实行；持久化研究工件时保存 publication/vector、hash、业务窗口和合同版本，不将行情记录写入 AFI 可复用缓存。

## 8. 验收矩阵及测试边界

| 验收面 | 合成/离线必须验证 | 真实来源/部署必须另行提供的证据 |
| --- | --- | --- |
| DTO/API | pair 缺失/半缺、时态 pair 重叠/代码复用、market 错配、BSE 未支持、v1 字节兼容、权限先于 store、稳定错误合同 | 已批准 grant 下实际请求范围与部署路由一致；不使用未批准市场/产品 |
| 旧数据基线 | 全 dataset NULL、漂移、重复、孤儿和不可判定行分类；坏行令所有 pair proof 失败；一致但错配的 fixture 由独立映射对账检出；不推断回填 | 经授权的真实 universe、独立证券主数据/日历、来源回执和生产只读库对账；差异有处置收据 |
| 生命周期/日历 | IPO/退市/更名/复用、同 pair 多身份有效区间、节假日、停牌、边界日和未知状态；未知结果保持 UNKNOWN | 每交易场所权威生命周期/日历来源、版本与时间窗；全 universe 对账 |
| Store/snapshot/cursor | 固定 publication、全量 integrity closure、pinned 证据、翻页稳定、pair/window/filter/principal 绑定、row/byte/page/TTL cap、hash 不符失败、并发篡改注入 | 目标 SQLite/MySQL 产品/版本的事务、索引、备份恢复与部署行为证据；要求管理员级防篡改时另验外部签名与独立只追加存储 |
| provider 与历史 | 闭区间/半开区间边界、3660日请求上限、`trade_date == business_date`、分页截断/持久分片恢复、限流/超时/部分页/重复键/修订/重跑幂等、watermark 不提前、原始单位/NULL | 有界真实样本逐字段 source→ODS/DWD→seal→REST 对照，记录函数/产品映射、脱敏参数、请求/响应摘要和 hash |
| AFI 消费 | 每行严格 pair/identity/日期校验；raw v2 与既有 qfq/display v1 隔离；错行拒绝且无业务副作用；任何 v2 失败都没有 v1/本地/cache fallback；默认 flag off | 端到端获准样本、目标 AFI/OpenData 部署、权限/grant 重验、真实报告工件 hash |
| 性能与运维 | 隔离 SQLite/MySQL explain、当前限额/页大小/响应大小、失败恢复演练、flag 回退 | 独立目标版本数据库容量、告警、自然调度周期、单写者、备份恢复和运维签字 |

离线结果标记 `CODE/OFFLINE`，真实来源收据标记 `REAL_SOURCE`，部署/自然周期/恢复标记 `DEPLOYMENT`。每项记录 commit SHA、合同与 schema hash、数据库/运行时版本、测试命令及输出文件、精确范围、未测项和 reviewer。mock、fixture、单标的样本不证明全 A 股、北交所、所有证券或完整历史。全局 quality gate 缺失或失败单独记录，不用 scoped 测试宣称整仓通过。

## 9. 上线切换与回滚

上线前为每个 dataset/sink 指定唯一 writer 和 owner，确认旧任务是否停用或仅 dry-run；禁止新旧任务同时写入同一事实表。首次启用采取小范围 cohort、限额、只读 shadow comparison 或受控写入，设告警阈值、观察窗口和停止条件。每次扩大范围都固定 universe version 与 publication receipt，先对账再推进。

回滚开关预置为一条可审计运维操作：立即关闭 AFI v2 feature flag、停止 OpenData `stock_daily` 调度/worker 的新 claim、保留已完成 publication/run/snapshot/cursor 与原始证据，确认无在途写者后恢复到已登记的旧生产配置。AFI v2 关闭时显示服务不可用，不能因回滚自动切到 v1 或本地数据。回滚不删除已提交事实、不回滚破坏性 migration、不重置 watermark；如数据质量异常，先隔离该 publication，标记不可读并以新修正 publication 重发。重启前由数据、运维和消费端负责人复核单写者、差异和告警。

允许切换的最终 gate：来源和用途 grant 明确且有效；market/universe/时态 identity/lifecycle/calendar 证据闭合；完整 dataset NULL/漂移扫描和独立 source/master-data reconciliation 均有 pinned 收据；baseline 的每个可支持 pair 有行级 record-set receipt；待发布 cohort 的所有缺口均已解释；v2 snapshot/cursor limits 与目标 SQLite/MySQL DB 并发测试通过；AFI 每行检查与 v2 无 fallback 证据通过，既有 qfq/display v1 单独回归通过；生产实例部署、EXPLAIN/容量、备份恢复、自然周期及 rollback 演练通过。若要求抵御 DB 管理员改写，外部签名与独立只追加存储也必须通过。任一条件未知或仅由 mock 支持时保持默认关闭，并将范围写成 `NOT_ACCEPTED`，不把该切片标为全 A 股已完成。
