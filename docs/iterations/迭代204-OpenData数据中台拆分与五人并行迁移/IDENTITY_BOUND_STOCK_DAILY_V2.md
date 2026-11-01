# Identity-bound 股票日线 v2：架构与迭代方案

本方案补足迭代204股票日线 v2 的证券身份链路。目标是让每条行情、公司行动和复权因子都能追溯到稳定 `instrument_id`、带有效期的交易所/代码、来源批次及固定版本；AFI 只消费 OpenData 已发布的 REST 数据。**这是后续设计，不代表功能已实现，也不代表全 A 股或北交所数据已覆盖。**

## 已确认的基线和边界

- OpenData 的 `0001_ods_dwd_p0` 以裸代码和日期作为旧数据键：`ods_stock_daily_akshare` 为 `(股票代码, 日期)`，`dwd_stock_daily` 为 `(symbol, trade_date)`，`dwd_stock_action` 为 `(symbol, ex_date)`。`0005_dwd_stock_adjust` 的旧因子键是 `(symbol, trade_date)`；`0007_affine_stock_adjust` 只加了可空的 affine 系数、`adjustment_version` 和 `legacy_source`，没有加入交易所或稳定证券身份。
- `0019_publication_market_symbol_scope` 给发布事实和读取快照加了可空 `market/symbol` pair，并禁止与旧 `instrument_id/capture_id` 选择器混用。历史 NULL 保持 NULL，migration 不从 `record_json` 猜值。这不是旧 DWD 行的身份回填，也不足以证明股票 REST 已按交易所隔离。
- `0021_temporal_identity_snapshot` 建立不可变、分块存储的身份快照；运行时 pin 把 `dataset_id/source_id/authority_id/registry_id/reference_version/snapshot_sha256` 绑定到指定快照。SHA-256 只证明字节一致，不证明来源真实性、授权或全集完整。
- `POST /api/v2/identity/resolve` 可对 operator pin 的身份注册表做有限日期区间解析；未知区间明确返回未知。它不写入身份、不验证数据源，也不证明某个行情行正确。
- `stock_daily_mapper.py` 已能把 AkShare/Eastmoney source-native 行映射为带 pin、身份 assignment、exchange 和 `instrument_id` 的 `identity_bound_candidate`。它保留原始 token；自身仍将来源身份、单位、授权、历史范围和覆盖标为未验证，也不负责 canonical 持久化或发布。当前 native request 只接受 SH/SZ；北交所请求与来源链尚未验收。
- AFI 现有股票读取请求未传交易所。若仅用裸 `symbol + date` 接入 v2，会把代码复用和跨市场同码当成同一证券，故新消费者必须显式传 pair 或稳定 ID，并校验每一行返回身份。

以上基线可在 OpenData 下列文件复核：`alembic_data/versions/20260923-0001_ods_dwd_p0.py`、`20260923-0005_dwd_stock_adjust.py`、`20260930-0007_affine_stock_adjust.py`、`20261028-0019_publication_market_symbol_scope.py`、`20261029-0021_temporal_identity_snapshot.py`、`opendata/data/providers/akshare/stock_daily_mapper.py`、`opendata/api/temporal_identity.py`。

## 目标数据链

```text
原始来源响应
  → source-native raw candidate（原值、请求/响应摘要、来源版本、精确身份 pin）
  → verified canonical bars / corporate actions（有效身份、单位/语义和质量均通过）
  → versioned adjustment factors（固定行动集、计算版本和复权锚点）
  → immutable publication + coverage receipt
  → identity-scoped OpenData REST
  → AFI strict v2 client
```

1. **身份先于映射。** 每个 assignment 使用 opaque `instrument_id`、明确交易所、六位代码、`[valid_from, valid_to)`、身份来源/版本及证据引用。一个 pair 在一个有效日只能解析到一个身份；缺失或重叠区间、历史代码复用未分段、pin 不匹配均拒绝。不得从代码前缀、旧 symbol 或 provider 返回顺序推断交易所/身份。身份 registry 必须经审核后以现有 temporal identity snapshot 和 operator pin 固定；pin 不等于授权证明。
2. **候选保留来源原貌。** raw candidate 记录请求 pair、来源产品/adapter/endpoint、捕获时间、完整响应摘要、行序/原始 token、采集 run 及所用 registry pin。只有授权允许时保存原始响应；保留期受来源授权控制。若来源返回值本身不能证明交易所，只有请求 pair 与独立 pin 在该业务日唯一匹配时才可进入候选，不能把这种关联写成来源自报身份。
3. **canonical bars 单独建版本化数据集。** 新增 v2 表/数据集，至少保留 `instrument_id + trade_date`、有效的 `assignment_id + exchange + symbol`、OHLCV/金额原生字段、明确单位与 raw/adjustment basis、source/run/candidate digest、转换版本、质量状态。唯一约束和发布业务键以稳定 ID 为主，并保存当天有效 pair；pair 有冲突、未知单位、非法数值、重复日期、日期越窗时整批隔离，不覆盖旧发布。来源值只在单位/语义审查通过后转换，原始 token 与 canonical 值可逐字段对账。
4. **行动与因子同样绑定身份及点时版本。** v2 公司行动保存 `instrument_id + ex_date + reviewed event identity`、源事件键、`source_revision/revision_order`、来源公告时间及精度/时区、平台首次获知 `observed_at/available_at`、行动字段单位、前收/分红送转等来源依据和 candidate digest。公告时间和平台可用时间不可互相替代；任一时间语义未知时，该事件不能用于点时因子。`as_of` 查询只选 `available_at <= as_of` 的已知版本，并在相同 revision 的 digest 冲突时拒绝，不能用“当前最新版本”回填历史。payload hash 仅作内容追踪，不能当经济事件 ID。因子版本需固定 `instrument_id + trade_date + adjustment_version + directional_anchor + as_of_cutoff`，并记录一个不可变 input-set descriptor：精确的 bars publication ID 与其 `available_at`、bars coverage receipt、actions publication 与 coverage receipt、identity pin/version/hash、选中的 action revisions/digest、公式/转换版本和 coverage 截点。点时计算要求所选 bars publication 已在 `as_of` 前可用，且该证券的 bars coverage end 和 qfq 末端 anchor 均不晚于 `as_of`；不得将后来发布的 bars snapshot 即使其业务日期较早也用于历史 `as_of`。沿用的公式中 **qfq 锚定所选 bars publication/coverage 的末端，hfq 锚定其首端**；分别保存方向和 anchor 日期，并证明对应 bars/actions 区间覆盖完整；不得从运行时表的动态 `MAX/MIN` 推导锚点。逐来源核实 raw/qfq/hfq 输出与行动生效口径，未知或冲突的供应商语义不用于复权结果。变更 bars publication/可用时间、actions、coverage、方向锚点或 as-of 都产生新的 factor-set/publication。点时回测按决策时刻读取当时可用的 bars publication 和 action revision，禁止使用决策时刻之后才发布/获知的数据、公告或修订。当前 v1 以裸 symbol/date 保存因子，且事件读取有 current/latest 语义；其结果不能作为 v2 点时因子的证明。**在 bars/actions 的 publication-as-of 与 revision-as-of 语义、方向锚点、不可变 publication/coverage 绑定、来源调整口径和泄漏测试通过前，v2 只提供 raw bars，不输出可消费的 qfq/hfq。**
5. **REST 与 AFI 严格消费。** 新 v2 REST 查询只能使用 `(exchange, symbol)` 或 `instrument_id`，请求携带 operator pin 的身份版本/hash，且必须指定半开业务日期区间和数据/复权版本。响应逐行包含 instrument、assignment、exchange、symbol、trade date、单位/adjustment basis、publication 与 coverage 状态；分页 cursor 固定选择器、有效期、publication、窗口、排序和调用主体。AFI v2 client 显式传 pair/ID 并逐行核对，不接受缺失/漂移身份、过期 pin、未验证 coverage；失败时明确报错，不能回退 AFI 本地表、旧 v1、AkShare 或缓存。旧路径保留至独立切换评审完成。

## 兼容和迁移策略

- 全程 additive：新增 v2 canonical/action/factor 数据集、必要身份关联及 publication/coverage 证据；不改变旧表业务键，不重命名字段，不要求旧消费者同时升级。
- 以 OpenData 当前 migration graph 的实际 head 创建唯一后继 revision（代码中 `0021_temporal_identity_snapshot` 是已检查的身份快照 revision；实施前仍须核实唯一 head 和部署库版本）。旧 NULL pair、裸 symbol 历史行、旧 actions/factors 均不自动补交易所或 `instrument_id`。只有逐行可复核的独立身份映射才能形成新的 v2 candidate；不确定行隔离并登记为 `UNKNOWN`。
- migration 先允许 v1/v2 并存，migration 本身不回填或发布数据。SQLite/MySQL 各自验证 upgrade、约束、索引、唯一键和恢复路径；0021 的 SQLite 证据不代表生产 MySQL 已验收。禁止通过 destructive downgrade 删除历史；回滚使用默认关闭的 v2 feature flag 和保留旧表/旧 API。
- source-native mapper 是输入边界，不是覆盖或授权判定器。AkShare/Eastmoney SH/SZ 之外的市场需独立适配、字段语义核验及来源验收；当前不把北交所归入可用范围。

## 五人并行与文件所有权

先由集成负责人冻结 schema/API/fixture 合同，并维护 migration 序号、共享注册表、依赖锁、跨仓基线和合并顺序。五人可在现有 `dev` checkout 并行，按下表互斥文件清单工作；不因并行而新增工作区或分支要求。共享 DTO 和 golden fixtures 各由单一 owner（负责人1）维护；测试按具体文件分配，不共享编辑。migration 编号/唯一 Alembic revision、OpenData `opendata/main.py` 的 router 注册、AFI 现有 query/route 接线及依赖锁由集成负责人串行处理。按仓库既有 PR/self-review 流程验收，不另增独立审批门槛。每项交付经定向离线验收后再集成。

| 负责人 | 独占生产文件和测试文件 | 交付与依赖 |
| --- | --- | --- |
| 1. 合同与 schema | OpenData 新 `opendata/data/models/identity_bound_stock_v2.py`、`opendata/api/identity_bound_stock_v2_schemas.py`；共享 `tests/fixtures/contracts/identity_bound_stock_daily_v2/`、`tests/test_identity_bound_stock_v2_contract.py`、`tests/test_identity_bound_stock_v2_migration.py` | 唯一维护共享 DTO 和 golden fixtures。冻结身份键、行动/因子点时字段、REST DTO 与迁移需求；不分配 migration 编号、不编辑共享 router 入口、不改旧 v1 表键。 |
| 2. 来源采集 | 新 `opendata/data/providers/akshare/identity_bound_stock_daily_v2.py`、`opendata/data/providers/akshare/identity_bound_stock_action_v2.py`、`opendata/data/providers/ths/identity_bound_stock_daily_v2.py`、`opendata/data/providers/ths/identity_bound_stock_action_v2.py`、`opendata/pipeline/identity_bound_stock_candidate_v2.py`；仅 `tests/test_identity_bound_stock_candidate_akshare_v2.py`、`tests/test_identity_bound_stock_candidate_fuyao_v2.py` | 按负责人1合同分别产出 AkShare/Fuyao 原值 candidate、限额和 run receipt；保留公告/观察/修订元数据。两来源独立验收，测试与证据不能互相替代；未实现或未实测的来源单独标 `NOT_RUN`。北交所不能映射时报告 unsupported。 |
| 3. Canonicalize 与因子 | 新 `opendata/pipeline/identity_bound_stock_canonical_v2.py`、`opendata/pipeline/identity_bound_stock_adjustment_v2.py`；仅 `tests/test_identity_bound_stock_canonical_v2.py`、`tests/test_identity_bound_stock_adjustment_v2.py` | 消费 candidate 与 pin；实现幂等、隔离、coverage、event revision-as-of、publication/coverage-bound anchor 与泄漏防护；不编辑共享 DTO、golden fixture、migration 或 v1 factor builder。 |
| 4. 发布与 REST | 新 `opendata/data/identity_bound_stock_store_v2.py`、`opendata/api/identity_bound_stock_v2.py`；仅 `tests/test_identity_bound_stock_api_v2.py` | 依赖负责人1合同及负责人3 canonical output；固定 publication、cursor 和 coverage 证据。不改 `opendata/main.py` router 注册。 |
| 5. AFI 消费 | 新 `src/backend/app/services/market_data/opendata_identity_stock_daily_v2.py`；仅 `src/backend/tests/market_data_platform/test_opendata_identity_stock_daily_v2.py` | 依赖冻结 DTO；先 Mock/合成服务验证显式 pair、逐行身份校验、点时复权策略和 fail-closed，再等待 OpenData route 可集成。不改共享 query route/wiring。 |

表内新生产模块路径为预留新增文件；若开工时仓库已有同名文件，集成负责人先改派唯一 owner，再开工。OpenData migration 由集成负责人刷新当前 migration graph 后，串行指定唯一 revision 文件和 revision ID，并安排负责人1的 migration 测试文件；不预占可能与进行中 PR 冲突的编号。`opendata/main.py`、AFI `src/backend/app/api/data/queries.py` 与 `src/backend/app/services/market_data/query_service.py` 的共享接线，以及两个仓库的依赖锁，只由集成负责人逐项合入。其他测试文件保持表内单一 owner；需要新增共享 fixture 时由负责人1维护，其他人只读复用。

## 顺序、依赖和可测验收

| 阶段 | 负责人/前置 | 可验收出口 |
| --- | --- | --- |
| I0 合同与范围 | 集成负责人 + 1；核对迁移图、目标市场及用户已声明的数据来源范围 | 冻结 identity pin、v2 schema/REST/OpenAPI/golden fixture；列明含退市股、市场和历史边界。用户已明确允许本项目使用 AkShare 与 Fuyao 数据；本计划按 OpenData 采集并供 AFI 内部 REST 调用的项目范围执行，不重复设置泛化授权询问。对用户声明未细化的具体端点/产品、字段、市场/历史范围、请求额度、原始数据留存期及派生数据共享限制，应从实际源端文档、运行配置或已有授权凭据中查明，并逐项记录 `KNOWN/UNKNOWN/NOT_TESTED`；未知项不推断为已许可或已验证，按最小请求、受限留存和未验证覆盖处理。若某项计划扩展超出用户声明范围，再针对该项确认。 |
| I1 身份与迁移 | 1；I0 | 合成数据验证同码跨交易所不串、代码复用不同有效期不串、区间端点唯一、重叠/缺失拒绝；新旧 schema 并存，既有 NULL/行数/hash 不变。升级与失败恢复在隔离 SQLite 和支持的 MySQL 版本验证。 |
| I2 候选与 canonical | 2、3；I0/I1 DTO 可先 mock 并行 | 同一 source response 重放幂等；错误 pin、错误交易所、重复 business date、未知单位、越界日期、损坏摘要全部隔离；candidate→canonical 每行可按 identity assignment 与原值 digest 对账。 |
| I3 行动与因子 | 3；canonical bars 合同稳定 | 同一 ex-date 多行动依 reviewed event identity 处理；每版保留公告时间精度/时区、首次 `available_at`、`revision_order/source_revision`；查询只选 `available_at <= as_of` 的无冲突修订。factor-set 不可变绑定 bars/actions publication、各自 coverage receipt、identity pin、action revision digest、qfq 末端或 hfq 首端 anchor 与 as-of cutoff；并断言 bars publication 的 `available_at <= as_of`、bars coverage end/anchor 不晚于 cutoff。测试构造公告晚于决策日、修订晚到、bars publication 在决策后才发布、bars coverage/anchor 晚于 cutoff、同 revision 冲突、coverage 截点变化、两种方向锚点变化及供应商复权口径不一致等样例，断言无未来泄漏且不会沿用旧 factor-set；时间精度未知、缺 coverage、缺前收、供应商口径未知或身份冲突均拒绝生成可消费 qfq/hfq。未过这些验收时只有 raw bars 可进入 REST。旧 v1 fixture 保持相同结果。 |
| I4 REST/AFI | 4、5；I0 DTO 冻结，I2 有合成 canonical snapshot | API 授权后只读 pinned publication；cursor 换 pair/ID/window/version/hash 或篡改时拒绝；AFI 检查请求和每行返回的交易所、symbol、instrument、日期及版本；旧 AFI 请求遗漏交易所时 v2 不可调用，无 fallback。 |
| I5 受控来源与切换 | 2、3、4、5 + 运维；所有离线出口通过 | 按用户已声明的 AkShare/Fuyao 项目使用范围分别执行有界 canary，保存脱敏 source/run/publication/coverage receipts，并记录用户声明与实际查明的端点、市场、字段、额度、留存期限及各项未知/未测试限制；不把未查明项写成已验证。核实实际返回市场、单位、历史边界、供应商复权口径及部署 DB。AkShare 和 Fuyao 分别交付 adapter 与来源验收；未实现、未实测或暂缓的来源单独标为 `NOT_RUN`，不得借用另一来源的结果。feature flag 默认关闭；逐市场/逐证券核验后才扩围，若用途超出已声明范围再针对该扩展确认。 |

测试至少覆盖：两个交易所同代码、一个 pair 的历史代码复用、SH/SZ/BSE 显式枚举和不支持路径、身份有效期边界、未知/重叠身份、source pin/hash 变更、同日重复 bar/action、公司行动修订、qfq 末端与 hfq 首端锚点版本、bars publication 在 `as_of` 后才可用、bars coverage/anchor 在 cutoff 后、供应商复权口径冲突、稳定分页、旧 snapshot 不受新 publication 影响、AFI 逐行身份错配和无 fallback。用合成 fixture 通过不等于供应商限额/留存等未知约束已核实、线上 MySQL、真实全历史或全 A 覆盖通过。

完整性按官方/可审阅的证券全集及各证券真实上市—退市生命周期建立分母，对每个 `instrument_id × pair 有效期` 分别核对 head、内部、tail 缺口、交易日历、停牌/无成交解释、重复及来源可回取边界。来源最早返回日不是上市日；快照或滚动窗口不是全历史。全集、来源或缺口解释任一不确定时标 `PARTIAL/UNKNOWN`，不得以表总行数、最大日期或成功任务状态声称完整。北交所只有在来源请求能力、身份映射、字段单位、真实样本和历史覆盖独立通过后才可纳入；在此之前保持 unsupported/unknown。

**切换门槛：** 离线合同与 migration 验收、逐行身份和来源语义验证、授权范围留据、目标数据库读写/恢复/性能验收、逐证券 coverage receipt、AFI v2 wire/回滚演练全部完成前，v2 保持关闭，旧 v1 行为不变。任一项未跑或失败均记录为 `NOT_RUN`/`OPEN`，不得宣传全 A 覆盖已完成。
