# 股票信号结果评分的日期与来源基准设计

> 状态：设计建议，尚未实现，也未完成数据或生产验收。本文只定义股票信号未来结果如何确定日期、来源与可复算版本，不代表 OpenData 已具备所需覆盖或数据发布能力。

## 1. 目的与边界

股票信号的未来收益只有在“哪一天的价格、来自哪个固定发布、按哪套交易日和价格口径”都能复核时，才适合进入胜率或超额收益统计。本设计把这三项证据与预测本身分开保存：预测快照保持原样，结果评分按 horizon 和版本追加保存，任何来源修订都能找到受影响的评分并重新计算。

本设计适用于 AFI 的 `stock_signal_predictions` 及其后续 OpenData REST 消费。它不证明信号有预测能力、来源许可充分、市场历史完整或数据适合交易，也不包括下单、实际成交、资金账户或投资建议流程。

## 2. 已确认的现状

以下为代码和迭代文档能够确认的事实：

1. [`outcomes.py`](../../../src/backend/app/services/stock_signal/outcomes.py) 先按 `next_trading_date` 找入场行；之后以 `entry_index + horizon - 1` 取第 1、5、20 行。因而 horizon 目前由返回行情列表中的行序号决定，而不是由版本化交易日历生成的目标交易日决定。若列表漏了一个预期交易日，后续 horizon 就可能向前错位。
2. [`StockSignalPrediction`](../../../src/backend/app/models/stock_signal.py) 在单条预测行保存 1/5/20 日个股、benchmark、超额收益和 20 日成功标记。`source_snapshot_hash` 是创建预测时输入快照的哈希；模型没有独立保存评分所用行情、benchmark、日历或 publication 的版本标识。
3. [`score_pending`](../../../src/backend/app/services/stock_signal/batch.py) 查询 `pending` / `partial` 预测，并通过 `MarketInstrumentService.lookup(..., refresh_online=False)` 读取 AFI 当前本地行情。它对整批待评分预测只取一份 `000016` 上证50 benchmark 行情，没有按每条记录的 `universe_code` 选择或校验 benchmark；因此当前行为是所有股票共用这一份 SSE50 基准。上证50 benchmark 的 OpenData reader 是可选开关；OpenData 读取失败时不会改用另一个来源，但现有流程仍会将空 benchmark 传给评分器。默认路径仍保留 AkShare benchmark 读取。
4. [`TradingCalendar`](../../../src/backend/app/services/stock_signal/calendar.py) 当前从 AkShare `tool_trade_date_hist_sina()` 取 A 股日期，并在 runner 实例内缓存日期集合，没有持久化日历版本、publication 或内容 hash。`score_pending` 遇到缺失的 `next_trading_date` 时会调用该日历补值。因此这条 legacy 路径可用当时可取得的 AkShare 日历填补旧记录，不能证明该日期由预测生成时采用的日历得出；legacy 写入没有完整的 date/source basis fail-closed 门禁。
5. `score_pending` 的 `through_date` 未提供时使用 `date.today()`，没有显式转换/校验为 `Asia/Shanghai` 的业务日期。新流程需为截止业务日定义明确时区，不能依赖宿主机本地日期。
6. [`outcomes.py`](../../../src/backend/app/services/stock_signal/outcomes.py) 对缺失成本和 BUY/SELL 成功阈值默认取 `0`；成本非法时也降为 `0`，负成本被截为 `0`，阈值解析失败则同样用 `0`。新评分不得继承此降级策略。
7. [`apply_outcome`](../../../src/backend/app/services/stock_signal/service.py) 会把本次评分值写回预测行。当前调度查询不包含已 `scored` 或 `unscorable` 的记录，因此没有面向来源更正的正式重评分队列；重复运行也不是可审计的评分版本。
8. 迭代204当前记录说明：股票日线逐标的 coverage、真实来源和历史 head/interior/tail 完整性仍未验收；OpenData 已有成功查询或域级 freshness 都不能证明逐标的目标日期完整。[消费者迁移记录](CONSUMER_MIGRATION.md) 与 [研发状态](DEVELOPMENT_STATUS.md) 也明确将生产 source、逐日历史 coverage 和 benchmark 对照列为未完成。

因此，新评分流程必须在缺行、重复日期、覆盖未知、来源未固定或日历不可验证时失败关闭：不按数组长度猜目标日，不用自然日/周末推交易日，不用相邻来源补洞，也不把空值变成零。当前 legacy 路径尚无完整 date/source basis 门禁；它不能据此宣称已失败关闭，存量结果一律继续标明为 `legacy_unpinned`，待新门禁和迁移对账验收后再切换。

## 3. 建议冻结的评分身份

每项结果使用独立且稳定的 `outcome_spec_version`。建议规格至少固定以下内容：

| 项目 | 建议定义 |
| --- | --- |
| 入场 | 使用预测中已持久化且严格晚于 `as_of_date` 的 `next_trading_date`；该交易日开盘价为理论入场价，并保存生成该日期所用 calendar id/version/hash。缺失时只可从可验证且与预测时点绑定的日历证据恢复；新流程不得照搬 legacy 的 AkShare 当前缓存日历补猜。证据不能恢复时保持阻塞。 |
| 截止业务日 | 每次评分的 inclusive `score_through_date` 明确按 `Asia/Shanghai` 解释。若调用方未传日期，由可信、带时区时钟转换到 `Asia/Shanghai` 后生成；不得使用宿主机 `date.today()`。请求、工作项和评分 revision 均保存该业务日及其来源。 |
| Horizon | **待产品/投研确认，不是已定规则。** 一个候选定义是 1、5、20 个适用交易所 session，且把入场日计作第 1 个 session（H1 目标为入场日收盘）。是否包含入场日、停牌期间如何处理以及“交易时段”按哪个交易所日历计算，必须在 `outcome_spec_version` v1 冻结前确定；冻结前不得对新链路产生可进入统计的 `scored` 结果。 |
| 目标日期 | 由已验证、版本化的市场/交易所日历产生目标业务日期集合；评分逐一按 `instrument_id + business_date` 精确匹配，不以第 N 个返回行代替。目标及截止日期的交易所业务日按 `Asia/Shanghai` 解释；无可靠时区/日历版本时保持未知。 |
| 标的身份 | 固定 `instrument_id`、代码/别名映射版本、市场和生命周期证据。证券代码变更不能靠字符串替换拼接历史。 |
| 行情来源 | 固定 `dataset_id`、来源/产品、`publication_id` 和 sequence、contract/schema hash、内容 hash、visibility seal 与源/授权 revision。只允许请求中台已发布的精确版本。 |
| 价格口径 | 固定原始/复权/总回报口径、币种、OHLC 单位、公司行动与分红处理版本，以及交易成本定义。缺少必要公司行动或转换证据时，不把 raw-price change 标成完整经济收益。 |
| Benchmark | 由版本化 outcome policy 按 universe/策略明确指定 benchmark instrument、数据集、来源、publication vector、日期边界与价格口径。当前整批共用 000016 的行为是已确认的 legacy 限制；不能将其复制为新合同，也不能自动套用于其他 universe 或全 A 股。 |
| 成本与阈值 | `round_trip_cost_bps`、`buy_success_threshold_bps`、`sell_success_threshold_bps` 必须显式提供并通过冻结规格的严格验证（有限、非负、类型正确且在批准范围内）。字段缺失、非法、非有限或越界时，整项对应 horizon 不评分，不用 0、当前默认值或配置回退。 |
| 结果语义 | 分开存储个股收益、benchmark 收益、超额收益和 BUY/SELL 成功判定；各自有状态和缺失原因。收益率、benchmark 及行动成功阈值从冻结规格/预测策略快照读取。 |

日期与价格公式写入版本化规格，而不是只存在于 Python 行号计算中。规格变更会建立新的评分版本；不得静默改写旧评分的 horizon 含义。

## 4. 逐 horizon 的成熟与缺数规则

每个 horizon 独立到期和评分。H1 可以先完成，H5/H20 仍处于未成熟状态。建议为个股、benchmark 与超额收益分别记录状态，避免把“个股收益可算”误读为“benchmark 也完整”。

| 情况 | 建议状态与处理 |
| --- | --- |
| 目标交易日还未发生 | `pending`；不读取未来数据，也不写结果数值。 |
| 目标日已过，但 publication/coverage/日历尚未证明该窗口完整 | `blocked_data` 或等价的可重试状态；保留机器原因，不判成功/失败。 |
| 精确日期行情缺失且中台覆盖未知 | `blocked_data`；禁止用后续行挪位或跨来源填充。 |
| 精确日期确认无交易，且有独立、版本化停牌/生命周期证据 | 按冻结规格记录 `unscorable` 和具体 maturity reason；不计胜率分母。单靠“没有行情行”不足以推断停牌。 |
| 个股 horizon 已具备完整来源与日期证据，benchmark 对应日期缺失/coverage 未知 | 个股结果可以独立为 `scored`；benchmark/excess 标记 `unknown` / `blocked_data`，不得填写 0，也不得把它计入可比较 benchmark 样本。 |
| 来源明确超过保留期，目标历史不能重建 | `source_limited`（或同等终态），保留证据和日期范围；不回退到今日最新数据。 |
| 数值非法、重复键冲突、单位/复权口径不符或身份冲突 | 整个受影响结果保持阻塞并告警；不发布部分推断值。 |

最终是否把“确认停牌”定义为延长 horizon 或不可评分，需由策略负责人按业务口径明确，并提升 `outcome_spec_version`。在该决策前，缺少目标日 bar 时一律不得擅自延长持有期。

## 5. legacy_unpinned 与兼容迁移

现有预测和评分列继续保留，以兼容旧 API/UI，但不把其来源身份补猜成 OpenData、AkShare 或任何具体版本。现有评分没有独立的 outcome publication vector；故推荐将旧分数标识为 `legacy_unpinned`，明确以下内容未知：目标日是否按真实交易日逐日核验、实际行情来源、具体发布版本、源修订版本、覆盖证明和公司行动口径。

迁移采取 expand-only，并设置明确的 legacy 数据核对门：

1. 新建按 prediction/horizon 保存的结果版本表。迁移必须将所有旧结果字段完整复制进对应的 `legacy_unpinned` revision，包括状态、原因、入场日/价、每个 horizon 的收益、benchmark、超额收益、成功标记和时间戳；所有 `NULL`、`0` 和精度按原样保留，lineage 明确为空/unknown，不用 today snapshot 回填。
2. 在切换任何 writer、API/UI 读取或旧字段 compatibility projection 前，先对迁移前后逐 prediction/horizon 做行数、键集合、每字段精确值、NULL 分布和确定性内容 hash 对账。只有完整复制与对账全部通过，才允许切换兼容列投影/current-head 读路径；任何差异都停止切换并保留原列/旧读路径。
3. 新代码只在新版本结果通过规格、日历、身份、来源和 coverage 校验后创建结果。legacy revision 不进入新版本胜率，也不能因新结果当前不可用而被重新解释为 pinned。
4. 引入新的 current-head 关联（或等价的只读查询规则），对每个 prediction、horizon、spec 指向一个当前认可的评分版本。评分记录本体 append-only；更正时新增记录并原子更新 head，不覆写之前证据。旧列只有在上述全量复制和核对后才能被声明为当前结果投影；投影行为要单独验收。
5. 新旧读路径并行阶段显示 `legacy_unpinned` 标签、旧版定义和“不可与已固定来源评分直接比较”提示；迁移失败不删旧行、不启用投影。兼容字段/API 的移除须另立版本化弃用计划。
6. Alembic upgrade/downgrade、SQLite/MySQL/PostgreSQL 所支持约束与并发语义分开验收；只在专用空库/临时库演练，禁止以开发/生产数据库实验代替迁移证据。

历史重放只有在同一信号原始输入快照、预测时点权限与来源证据均可证明时才可能被定义成 research backtest；它不属于本结果追分流程，不得回写成真正前瞻结果。

## 6. 建议数据结构

字段为设计建议，名称以实现前冻结的 schema/OpenAPI 为准。

### `stock_signal_outcome_revisions`（不可变结果事实）

建议主键和唯一身份为：

```text
(prediction_id, horizon_code, outcome_spec_version,
 evaluator_version, input_vector_hash)
```

至少保存：

- prediction id/key、horizon 代码和长度/是否包含入场日；`outcome_spec_version`、evaluator version；
- `entry_business_date`、`target_business_date`、`calendar_id/version/hash`、`instrument_id`/alias version；
- 个股行的 dataset/source/product、publication id/sequence、visibility seal、content/contract/schema hash；
- benchmark 选择策略版本和对应 publication vector；股票、benchmark 的日期边界与 price basis；
- entry/exit 可复算字段、币种/单位、gross/net return、cost、benchmark return、excess return 和成功标签；
- 各独立结果状态、maturity reason、缺少的精确 source key/date、coverage evidence reference；
- 输入向量 hash、来源 grant/source policy revision、`scored_at`、创建者/worker identity、attempt id、`supersedes_outcome_id`。

成功或最终不可评分的结果事实不做原位更新；修正/新 evaluator 产生新的 revision。含敏感访问信息的证据引用只存受控标识和摘要，不复制 API key 或机密授权正文。

### `stock_signal_outcome_heads`（当前读模型指针）

每个 `(prediction_id, horizon_code, outcome_spec_version)` 最多一个 current revision。head 只能在新 revision 校验和事务成功后原子切换；读路径展示当前版本，同时允许有权限的审计视图列出历史 revision。并发冲突采用数据库唯一键/CAS，不靠应用进程锁。

### `stock_signal_outcome_work`（成熟检查与重试工作项）

若未来自然调度/多实例需要持久队列，另建工作项记录 horizon、下次检查时间、lease/fencing token、attempt 计数、可重试错误码、`retry_after`、最后检查 publication vector 与最终状态。工作项可变，结果事实仍 append-only。工作项表和 revision/head 表不要合并成一个可覆盖行。

## 7. 数据更正和重评分

数据更正有两类：发布了新的数据版本；同一发布/身份下发现字段或归一化错误。两类都必须能通过新 `input_vector_hash` 或新 `outcome_spec_version` 形成新结果链，并保留旧证据。

建议流程如下：

1. OpenData 修订发布后，revision/change log 给出变更 dataset、instrument、business-date 范围、旧/新 publication id 和内容 hash。
2. 按精确键找出依赖这些标的/日期、且包含相同 publication vector 的 outcome revisions；只排队受影响的 prediction/horizon，避免无边界全量重算。
3. 重新校验当前用户/服务主体的 source policy、grant、固定 publication 可读性、coverage、calendar 和价基。任何门禁失败时保持原 current head，写入可观察的失败/重试原因。
4. 同一规格、同一向量的重复投递命中唯一键，保持幂等；新向量生成新 revision，记录 `supersedes_outcome_id`，原结果不删除。数据库事务成功后更新 head 并发出审计/告警事件。
5. 样本统计默认只统计同一 `outcome_spec_version`、当前 head 且 `scored` 的记录，并单独展示 coverage/可评分率、更新时间和更正影响量。legacy 与未知来源行不进入该分母。

没有 OpenData 可重放 publication 或留存证据的已封存结果，不可从最新 API 把历史数据“补成当时版本”。如业务希望用最新修正版重新评估，必须作为新版本评分，明确其观测/修订时间，且不声称当时已知。

## 8. 重试、限额和故障处理

重试分为“未成熟后的例行检查”与“失败请求重试”，并与数据修订触发的重评分分开计数。建议只对 timeout、连接中断、429、短暂 5xx 等暂时性错误做指数退避和有限次数重试；权限拒绝、grant 失效、schema/单位/身份不符、publication 不存在、coverage 未知等错误应阻塞并等待证据/人工恢复，不切换来源、不重试到假成功。

每次尝试必须先取得固定 publication vector 与 request budget，再按小范围拉取数据；每个证券、日期窗口、数据集、benchmark 设最大行数/页数/字节数/deadline。超过预算时拒绝当前 horizon 并记录原因。只有完整 horizon 的精确业务键/coverage 检查通过后才写结果。网络或 worker 在提交结果时状态不确定时，应按幂等键检查已写 revision，不可盲目重复创建。

运营指标至少包括到期 horizon 数、pending/blocked/source-limited 数、连续重试次数、最老未成熟时长、source/coverage/schema 错误率、修订重评分队列长度、head 切换数量与失败数量。人工 retry 必须有 actor/reason/idempotency key；不能通过删除 outcome 或修改状态绕过审计。

## 9. 实施依赖与并行拆分

该切片的实现顺序受数据合同依赖约束，可按互斥文件并行开发：

| 工作项 | 交付 | 前置/接口依赖 |
| --- | --- | --- |
| O1 日期/来源结果合同 | OutcomeSpec、calendar session DTO、固定 publication/coverage 输入、错误和状态枚举 | OpenData 股票日线/日历/coverage contract；204-A06-04、相应 A03/A05；B02-04 日线源语义 |
| O2 结果存储与兼容迁移 | revision/head/work schema、Alembic、旧列 `legacy_unpinned` 投影 | O1 schema freeze；D02/D03 lease、幂等和 migration owner；不改预测快照 |
| O3 纯评分器 | 精确日期键映射、价格/公司行动 basis、benchmark 同窗对齐、逐 horizon 评估 | O1 fixtures、仪器身份和版本化交易日历；不访问 DB/HTTP |
| O4 OpenData 读取适配 | 只读精确 publication vector、按标的/日期核验 coverage、禁止 fallback | 204-E02 REST 客户端、A05 published records、A06 coverage；数据未 ready 时 fail closed |
| O5 调度/重试/更正 | due queue、有限重试、publication change fanout、原子 head 更新与监控 | O2/O4；D02/D03 durable run/lease；D06 observability |
| O6 AFI 集成/UI | 查询逐 horizon current result 与 history；兼容 legacy 标签、unknown 原因和新旧统计隔离 | O1/O2；204-E03-04/05 消费与报告合同；E06-03 跨仓回归 |
| O7 端到端验收 | 固定 vector 回放、一组有界授权样本、修订重评分及恢复演练 | O1–O6；204-E06-03；真实源/授权/coverage 数据证据 |

建议文件所有权：一个人负责模型/迁移，一个人负责纯日期/价格评分器，一个人负责 OpenData 契约/reader，一个人负责 durable retry/revision orchestration，一个人负责 AFI/UI 与端到端协调。共享 contract 与 migration revision 由单一 integrator 冻结；其他人基于 fixture/contract 并行实现，避免同时改 `stock_signal_predictions`、公共 API client 和 Alembic 序列。合并前对 O1 的字段、horizon 语义和错误行为做一次跨人接口评审。

## 10. 验收测试清单

以下全部是建议的离线/集成验收项，不是当前已通过的测试：

### 日期和键完整性

- 使用固定沪深交易日历覆盖周末、节假日、临时休市、交易日和跨年；H1/H5/H20 的日期按日历 session 生成，结果不受响应行顺序影响。
- 在 UTC 日期与 `Asia/Shanghai` 日期不同的边界时刻验证 cutoff：同一 instant 必须产生固定的上海业务日；未传 `through_date` 时不受运行主机时区或 `date.today()` 影响。
- 对已保存 `next_trading_date` 的 prediction 复用其绑定日历证据；旧 prediction 缺失该字段、且无法恢复生成时日历证据时保持阻塞，不能用当前 AkShare 缓存日历补猜。
- 缺失一个期望业务日、重复 `instrument_id + business_date`、排序颠倒、窗口外/未来日期、错误 alias 均不能挪用下一条记录； coverage UNKNOWN 时不产生 `scored`。
- entry session 不存在、next trading day 未冻结、calendar version 变化都有确定的 fail-closed 状态和 reason；不接受自然日 `+N` 逻辑。
- 20 个有效交易 session 行可计 H1/H5/H20；仅 19 个时 H20 不得评分。停牌只在停牌/lifecycle 证据和冻结策略允许时走既定结果。

### 来源、benchmark 与收益口径

- OpenData response 中每行精确匹配固定 instrument id、business date、dataset/contract、publication vector；任何相同代码、不同来源/调整 basis 的值不拼接。
- benchmark 入口和出口与个股完全对应相同定义的 entry/target 日期；benchmark publication 缺失时个股结果与 benchmark 状态分离，benchmark/excess 为 `NULL`，不是 0。
- 数值只接受有限正价格；布尔、NaN、无穷、零价、重复键和单位冲突被拒绝；cost/threshold 来自冻结 spec，不读取运行时可变默认值。
- 成本/成功阈值缺失、布尔/字符串、负值、非有限值或超出批准范围时，断言不生成 outcome head、不计算成功标签并记录稳定错误原因；不得降级到 0。
- 为不同 `universe_code` 固定不同 benchmark policy 的样例，验证不存在默认共用 000016 的路径；遗漏 universe→benchmark 映射时 benchmark/excess 保持 unknown。
- raw、adjusted、total-return、公司行动/分红口径组合不兼容时阻塞；跨货币无固定转换合同不评分。
- OpenData 不可用、403、schema 变更、coverage UNKNOWN/PARTIAL 时断言 AkShare/AFI DB/缓存零 fallback；响应分页/大小超预算可确定失败。

### 不可变版本、幂等和重试

- 同 prediction/horizon/spec/evaluator/input vector 重复执行只得到同一 outcome revision；两个 worker 竞争只能有一个成功更新 current head。
- publication correction 只重算受影响日期/标的/horizon；新增 revision 保留旧值、内容 hash 与 `supersedes` 关联，事务失败则 head 不变。
- evaluator/outcome spec 改版生成独立序列，不覆盖旧版本；报表同一时点固定读取单一 spec 的 current head。
- 每项统计按该指标自己的组件状态确定分母并同时输出样本数：个股收益/BUY-SELL 成功率只纳入对应 horizon 的个股 outcome 为 `scored` 的记录；benchmark 与 excess-return 统计只纳入个股 outcome 已评分、benchmark 同一标的窗口/目标日期/价基可用且成功配对的记录。不得用个股可评分分母代替 benchmark/excess 分母，也不得将缺失配对计作零。
- 暂时网络错误按封顶退避重试；权限/授权/身份/schema/coverage 问题转为阻塞并产生操作原因；lease 过期恢复后无重复事实、无并行双 head。
- 确认历史数据超源保留期后成为 `source_limited`，不得以最新版本回填旧 publication。

### legacy、统计与迁移

- 每个 legacy prediction 的三个 horizon 都有对应 `legacy_unpinned` revision；按原样保存共享 status/reason、入场字段和所有 1/5/20 结果列，不推导 horizon 专属 status。逐 prediction/horizon 数量、键集合、每字段值、NULL 分布和 hash 完全核对后才允许切换兼容列投影；任一不一致都保持旧读写路径。
- legacy 迁移不访问 API/旧来源、不推断 lineage；upgrade/downgrade 与重复迁移不丢失原始列，验收完成前不运行新 writer 改写兼容列。
- 新统计只聚合一个 spec 的当前 revision，并逐指标组件状态计算分母：个股收益及行动成功率纳入对应 horizon 个股 outcome 为 `scored` 的记录；benchmark/excess 纳入个股 outcome 已评分且同一窗口/日期/价基下 benchmark 配对可用的记录。unknown/blocked/unscorable/source-limited/legacy 不进入相应指标分母，但在成熟率/覆盖率显示中可见；缺失 benchmark 不得把个股 outcome 从其个股收益分母里移除，也不得把该行加入 benchmark/excess 分母。
- SQLite fresh/upgrade/downgrade、MySQL/PostgreSQL 实际受支持版本、唯一键/锁/CAS、空表和已有数据迁移均有单独证据；数据量较大的 backfill 需另行做可中断、可恢复的容量演练。

## 11. 开工门槛与未决决策

在新评分器读取真实数据前，需要先取得并审阅：

- 每个目标市场/标的可验证的生命周期与交易日历版本；
- OpenData 对所需 instrument/date window 的 coverage status 和 publication identity，以及 REST 对固定历史版本的读取/保留保证；
- 股票日线字段单位、复权/公司行动和来源更正规则；
- benchmark instrument 与 universe 选择策略；
- 数据源和研究用途授权映射、读权限及 revoke 处理。

当前迭代材料没有提供足以证明所有股票日期可用的 coverage 证据，因此没有这些证据时，只能验收代码的 fail-closed 行为，不能开启新结果评分或宣称历史完整。全 A 股要求继续按真实交易所 universe、上市/退市生命周期和各证券日期的 head/interior/tail 缺口逐项评估；SSE50 样例、API 200、行数或 MAX(date) 均不能代替它。

需要产品/投研在 outcome spec v1 冻结前决定：H1/H5/H20 的精确计数定义、停牌时 horizon 是否延长、是否计算含分红总回报、BUY/SELL 的交易成本/成功阈值、benchmark 映射与样本统计规则。这些决定改变统计含义，必须提升 spec version；没有决定时相关指标保持 unknown，不以工程默认值代替业务口径。
