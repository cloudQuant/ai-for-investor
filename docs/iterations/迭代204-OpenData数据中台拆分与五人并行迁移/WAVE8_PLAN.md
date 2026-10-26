# 第八批 股票标的参考目录 REST 接线与财报脚本映射计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**DESIGN_READY / IMPLEMENTATION_NOT_STARTED**。本文件记录root已确定的接线方向、实施前契约冻结项、五条独占工作流和后续离线验收方案。没有开始实现或测试，也没有生产数据、来源授权或切换验收结论。Wave 5至Wave 7的隔离收据不作为Wave 8通过证据。

## 目标与边界

为AFI股票选择器设计一条可关闭的OpenData published-reference读取路径，使候选股票身份由已发布目录快照提供。启用后，该选择器的候选列表应来自OpenData REST；不得再从AFI本地warehouse、cache或seed拼接、补足或回退结果。独立的默认关闭配置必须控制此路径；关闭时现有选择器行为保持不变。

此切片只处理“目录中是否有一个经过审查的标的身份映射”。目录成员身份不表示行情快照或历史行情存在、可读或完整。`unknown`可用性必须继续表示未知，不能转换为`false`、`0`或“没有数据”。用户手工输入但尚未由目录确认的symbol也不能伪装成已验证成员。

本批不启用真实provider、production dataset、来源key、DatasetGrant或AFI OpenData selector flag；不写入行情表，不改变W5 K线接口或其`MARKET_DATA_OPENDATA_ENABLED`配置，不迁移财报脚本，不运行旧脚本，不改变87项控制任务或1,103任务/1,066脚本的既有分母，也不关闭逐标的全历史要求。

## 架构决策与设计依据

root最终决定是**扩展现有v2 records/snapshot路径，接纳窄化的`table + none + time_field=null`无时间窗分支**。首版不增加instrument专用搜索endpoint、不新增`reference` record kind、不制造时间字段，也不增加数据库迁移。根决策收据为`/tmp/od204-receipts/wave8-root-architecture-decision.json`，设计锚点为OpenData `f7aec5da6c30de03b48e88e7abbdcd748bde0934`和AFI `5225e947804bce32c51e2119dd25a40d651ac6f7`。

两份设计评审收据（`wave8-instrument-contract-proposal.txt`、`wave8-instrument-contract-independent-review.txt`）有一项建议为新建专用目录查询route；root的最终选择已否决该首版route方向，本计划以root决定为准。评审中关于完整快照读取、无部分结果、逐页授权、请求边界、alias日期语义和rights未证明等建议保留为设计约束。

现有OpenData `DatasetContract`已定义`record_kind="table"`和`temporal_semantics="none"`；`PublicationStore`的记录允许nullable `business_date`，也支持无日期边界的snapshot，并用null-date后接business-key的稳定排序分页。目前`opendata/api/published_data.py`的records校验仍要求`time_series + business_date + 两端日期窗`，payload校验也拒绝null `business_date`。实施时只增加显式的无时间table分支，原有time-series/date-window响应和拒绝条件保持不变。

AFI不能直接复用同步的`opendata-client SnapshotClient`：它要求日期窗并按business date校验，在async请求中同步调用也会阻塞事件循环。设计方向是AFI专用的小型async HTTP adapter，读取现有records/snapshot页并在AFI内完成完整快照校验与有限搜索；不引入sibling-checkout导入或未发布的本地client依赖。

现有`InstrumentReferenceRegistry`只是对显式注入的记录做验证/解析，不是持久发布目录或listing API；目前也没有已审查的生产标的snapshot、AFI display/query-symbol mapping、name/market projection或授权。不能把这个validator的存在描述为目录已经可消费。

## 开始并行开发前root必须冻结的共享契约

在以下事项形成可供所有流共同使用的精确schema、fixture和字段合同前，不开始生产代码分支；不允许各流自行命名字段、选择不同的symbol映射或构造不同的sample payload：

1. **发布profile与来源身份。** 明确fixture及未来profile的dataset/source identity、registry/profile version、schema/semantic version、stable instrument identifier、显式的AFI股票查询symbol映射，以及确有独立证据时才可包含的display name/market字段。还须定义alias、lifecycle、evidence reference、known-start boundary等概念的表达和缺值状态。确切字段名、数据类型、business key、ordering及hash绑定均由root冻结。
2. **共享published fixture。** root建立唯一确定性fixture，覆盖null business date、稳定business key、identity与AFI-symbol映射、alias有效期、lifecycle及未知边界。它只用于离线合同测试，不含真实source访问、production grant或权利声明。各流只消费root冻结的fixture，不复制出语义不同的本地fixture。
3. **API page/DTO及错误合同。** 冻结首次读取、continuation、snapshot元数据、contract/provenance字段、错误状态、exact `total`和`has_more`含义，以及何时返回unavailable。不得把完整snapshot的`content_sha256`描述成搜索子集hash。
4. **访问控制与运行配置。** 冻结server-owned dataset/source/API URL、OpenData grant operation/purpose、AFI服务凭证注入、独立默认false的selector flag及disabled/enabled失败行为。flag名称与共享config文件由root拥有。AFI浏览器或外部调用者不能任意指定server-owned dataset/source/URL/purpose/key；后端adapter只能使用明确注入的配置与凭证，unknown rights或grant必须fail closed。
5. **有界完整扫描预算。** 冻结页大小、最大页数/总行数/bytes、总时限、expiry处理和UI result cap。设计评审建议UI返回上限不大于80、单页使用低延迟小页；确切数字须根据catalog规模及UI延迟预算由root确认，不能直接采用通用SDK的200,000行/64 MiB/120秒上限。
6. **身份与时间语义。** 冻结stable ID到AFI query symbol的映射、alias日期字段名与端点包含规则、status/evidence更新时间的含义，以及显式业务生效日如何选择。publication `as_of`只表示平台发布可见时间，不能替代alias生效日、source availability或strategy PIT时间。

在冻结前，可以继续只读审查与设计，不得把候选字段或样例描述为最终合同。root负责profile/shared fixture、DTO/contracts、默认关闭config、route/router integration glue、quality census、合并顺序、测试allowlist与最终验收。

## 现有v2读取路径与约束

AFI启用时使用现有v2 dataset records page协议和其snapshot/cursor机制；本批不定义`/instrument-references`专用endpoint或remote `q`/`search`参数。root需要冻结dataset身份及正确路由配置。records首请求省略日期窗，创建并返回固定publication snapshot；继续页以同一snapshot ID与cursor读取，不得改变publication、page size或window。具体调用字段与错误映射随root的共享DTO一同冻结。

OpenData table/none分支的最低语义要求是：`record_kind=table`、`temporal_semantics=none`、`time_field=null`；无start/end date bounds；每条记录`business_date=null`；非空、可验证的stable business key；contract ordering与store的null-date/business-key分页顺序一致；profile的payload字段与business-key identity严格校验。具体business key、ordering与合同字段由root冻结。不得宣称支持PIT；其合同表达建议为不支持，仍待root冻结。不能静默推断time field，也不能降低既有time-series校验。

首次records读取必须同时通过匹配同一source的`data.read`与`snapshot.create`授权；continuation仍逐请求检查`data.read`并绑定到原snapshot/access scope。分页cursor不能替代授权。授权必须按exact dataset/source/domain/operation/purpose/subject/validity逐项匹配，API-key scope也须覆盖确切operation和domain；purpose由服务端明确选择，不能由调用方提供，也不能因helper默认值就假定生产grant允许`research`。现有DatasetGrant只授权OpenData内的具体访问范围，不证明第三方来源许可或再分发权；本批不新建grant，也不将离线fixture授权当生产授权。

## 完整快照读取、搜索和结果语义

AFI adapter必须读取并验证**整个有界snapshot**后才执行selector搜索和返回“完整”结果。每页应与首次返回的dataset/publication/sequence/schema与semantic version/contract hash/snapshot/content hash/publication `as_of`一致；验证cursor前进、stable ordering、business-key唯一性、snapshot expiry、总行数、响应bytes、页数及overall deadline。仅在所有页面通过验证后可计算exact total/has-more或写入可复用cache。

因为records API按原publication snapshot分页，而首版不新增filter endpoint，symbol/name/alias筛选应在AFI已完整验证的快照上进行。若预算耗尽、cursor/contract/provenance不一致、snapshot过期、响应过大或传输失败，必须返回unavailable/incomplete结果；不能把读到的前缀当成完整目录，不能返回看似正常的部分搜索命中或精确total。

只在经profile审查的候选字段上匹配并按固定规范化规则搜索。alias仅在调用者显式提供业务生效日期时按其有效期解析；不得默认使用今天、publication `as_of`、行情交易日或价格记录日期。alias日期和publication visibility是两个时钟，PIT保持unsupported。`known_start_date`仅能来自独立证据；不得用当前最早行情行推断上市日。lifecycle status须连同其证据日期/边界呈现，不能把旧的“active”值解释为当前状态。

若root最终批准adapter对完整快照做进程内memoization，该缓存也只能保存完整、校验通过的snapshot，绑定发布ID/序列、contract及content hash且不超过snapshot expiry；权限仍需逐请求检查，禁止跨principal或跨grant复用授权结果。它只是已验证REST响应的短期计算缓存，不得作为现有warehouse/cache/seed回退；发生REST denial、失效或不完整时不能用陈旧缓存冒充成功。缓存字段、寿命与使用条件仍待root冻结。未知/不可用与空目录、拒绝访问是不同状态，不能互相折叠。

## AFI身份与UI显示边界

`instrument_id`不等同于AFI各数据源所需的query symbol；只有root冻结并由reviewed profile明确绑定的映射才能填入AFI选股项。名称、交易所或market也只能展示有证据且进入冻结profile的值。目录命中只证明所发布snapshot包含这一身份映射，不证明股票历史、最新snapshot、coverage或可交易性。

AFI option DTO需把“经过目录验证的成员身份”和“行情数据可用性”分开表达。候选设计可采用verified-membership标记与`unknown/available/unavailable`可用性枚举，但字段名和类型在root冻结前不是承诺。未知availability不得写成`has_history=false`、`history_rows=0`或`has_snapshot=false`；只有另一条有权限的coverage/records证据才可将availability更新为已知。

现有`GET /market-instruments/options`仍由旧selector路径服务；flag关闭时不改变它的现有行为。`ensureCurrentInstrumentOption`为输入symbol创建的shell不是published membership。独立flag开启时，未解析的typed value必须保持unverified，不能作为目录命中或传入新backend作为canonical ID。UI不得在enabled-mode失败后显示旧warehouse/cache/seed结果；应清空旧搜索命中并明确呈现unknown或unavailable，不能伪造“无历史数据”。

## 五条独占工作流

五条流只在root冻结共享profile、fixture、DTO、访问和配置合同之后进入实现。每流在隔离分支内编辑自己的文件；root负责跨流共享文件、路由接线、测试selection和集成。

| 工作流 | 独占建议范围 | 交付与边界 |
| --- | --- | --- |
| 1. OpenData参考目录发布profile/projection | 新增`opendata/data/instrument_reference_publication.py`及对应独立测试；root-owned shared fixture/profile除外 | 按root冻结的profile生成published table rows，保留identity、alias/lifecycle与evidence；使用null business date与稳定key，不新增持久化schema。不得自行改变共享字段或声称来源权利已验证。 |
| 2. OpenData现有v2 records atemporal分支 | 独占修改`opendata/api/published_data.py`相关合同验证/记录验证分支及focused API tests（测试文件名由root冻结） | 为既有records endpoint增加严格table/none/no-window分支，校验scope、publication、snapshot和cursor；证明time-series行为未变。不新建专用search route、query-bound filter cursor或数据库迁移。 |
| 3. AFI async adapter与schema消费 | 新增独立`src/backend/app/services/market_data/opendata_instrument_reference.py`及MockTransport focused tests；共享DTO、config、API route wiring由root独占 | 固定server-side HTTPS origin，`trust_env=False`、redirects关闭、显式connect/read/overall timeout与streamed response byte cap。校验完整快照后搜索；不使用同步`SnapshotClient`、sibling repo imports或本地未发布wheel。 |
| 4. AFI selector UI | 独占`src/frontend/src/api/marketData.ts`、`src/frontend/src/views/data/useDataPage.ts`、`src/frontend/src/views/DataPage.vue`及相应targeted frontend tests | 展示verified membership、source/profile provenance和显式unknown availability；typed shell保持未验证。Disabled旧路径兼容；enabled模式不回退本地warehouse/cache/seed，也不把unknown呈现成false或0。 |
| 5. 12条财报脚本映射与可复用候选设计 | 使用既有只读映射receipt `/tmp/od204-receipts/wave8-securities-first-batch-mapping.json/.txt`，只更新root明确指定的设计receipt，不修改旧脚本/provider代码 | 把12个历史脚本映射作为有限设计批次，并评估首个Sina fetcher复用候选。不得运行脚本或source fetch、不得将历史task snapshot映射当当前运行/部署/源权利/迁移验收。 |

root独占现有`opendata/data/platform_contracts.py`共享模型的审查及任何必要调整、profile/shared fixture冻结、AFI配置/flag、route/router registration、跨流响应类型、quality census/OpenAPI pins、旧任务矩阵、shared test allowlist、合并及最终验收。任何流若发现必须触及root-owned文件或无法按冻结fixture实现，应先报告root调整契约与所有权，不自行扩大scope。此计划中的文件ownership是实现前的候选边界，具体文件清单仍由root在合同冻结时签定。

## 财报脚本首批候选映射

只读映射覆盖12个文件：3个balance sheet、4个cash-flow、4个income/profit及1个Sina三大报表。建议统一评估现有`FinancialStatement`领域，但不同source/endpoint的report period、公告日期、科目、单位、单季/累计、修订和退市覆盖不得因共用model就被视为同义。

| 类别 | 12脚本中的文件 | 首选设计方向 | 需先验证 |
| --- | --- | --- | --- |
| Balance sheet（3） | `stock_balance_sheet_by_report_delisted_em.py`、`stock_balance_sheet_by_report_em.py`、`stock_balance_sheet_by_yearly_em.py` | 3个Eastmoney endpoints均为扩展现有`FinancialStatement / balance`的候选 | Eastmoney provider、退市公司覆盖、年度/报告期语义、公告日、科目和修订 |
| Cash flow（4） | `stock_cash_flow_sheet_by_quarterly_em.py`、`stock_cash_flow_sheet_by_report_delisted_em.py`、`stock_cash_flow_sheet_by_report_em.py`、`stock_cash_flow_sheet_by_yearly_em.py` | 4个Eastmoney endpoints均为扩展现有`FinancialStatement / cashflow`的候选 | 单季/累计口径、退市覆盖、单位、报告期间、公告日、修订 |
| Sina consolidated statements（1） | `stock_financial_report_sina.py` | 首个潜在复用候选：现有`AkshareFinancialStatementFetcher`已注册同一Sina函数 | 当前能力仍`verified=false`/需人工复核；原始参数、字段、sink、来源与授权均未证实。Sina中文item键不能直接与THS英文键合并。 |
| Income/profit（4） | `stock_profit_sheet_by_quarterly_em.py`、`stock_profit_sheet_by_report_delisted_em.py`、`stock_profit_sheet_by_report_em.py`、`stock_profit_sheet_by_yearly_em.py` | 4个Eastmoney endpoints均为扩展现有`FinancialStatement / income`的候选 | 单季/累计、单位、公告日、修订、退市范围及不同endpoint重叠 |

现有`ThsFinancialStatementFetcher`的`verified=true`只属于其自身source/model的能力声明，不能单凭此标志证明真实来源、字段或权利已验收，也不为本表中Eastmoney或Sina候选背书。11个Eastmoney endpoint在映射收据中无provider；Sina fetcher虽是首个复用候选，仍不是已验收实现。历史脚本用共享writer写入MySQL表，唯一键`(symbol,data_date)`，缺日期时还可能填运行日期；这可能丢失report period、announcement date和revision区分，须先审计，不得直接把运行日当财报业务日期。

映射receipt依据AFI commit `85b27158b0b5686b38b2357ffb96217511d19554`复算脚本SHA，OpenData基线为`b4a1f630ad48781d21440724971562ec946374d3`。它引用的运行快照生成于2026-10-26T11:38:36Z，历史上将12个脚本映射到12个scheduled-task id，snapshot中active=1、schedule_type=cron；参数仅有空对象hash、时区未记录。该快照不是当前运行/安装/参数证据，不能把目录派生的`daily`、历史cron或这些12行解释为真实业务频率、SOURCE_VERIFIED或已迁移。12只是脚本数，不是数据集数或总分母。

## 依赖顺序与root验收

1. root冻结精确profile、共享fixture、DTO/page合同、授权purpose、独立关闭flag、超时与扫描预算，并书面确定每流独占文件；冻结前只做设计。
2. OpenData projection和existing-records API分支以同一fixture实现；两者不得各自增删字段。AFI adapter和UI依赖同一冻结DTO，可在fixture冻结后并行开发。财报映射只作静态review，不应阻塞selector合同实现，也不授权并行修改财报源代码。
3. root审核每流diff及权限/identity/provenance边界，再按精确allowlist执行隔离测试和兼容性检查；共享route wiring、OpenAPI/census更新和最终组合由root串行集成。

实施后建议覆盖：null-date table record合法而其他时间语义仍拒绝；time-series原date-window合同回归；stable key、alias日期边界和lifecycle unknown；首请求与continuation授权、grant source binding、snapshot pinning与cursor expiry；整包分页身份/哈希/顺序/unique-key验证；每类page/row/bytes/deadline cap失败都不产生partial success；disabled path不变、enabled失败不调用local warehouse/cache/seed；catalog membership不推导history/snapshot availability；typed shell不能变成verified member。AFI backend使用`httpx.MockTransport`和显式owned test resources；OpenData测试只使用固定fixture与测试owned SQLite；frontend用locked依赖下的定向Vitest。root冻结后的确切测试文件和命令未定，本计划未运行任何测试、coverage、build、应用导入或网络/数据库操作。

离线fixture最多验证合同、授权路径、分页和UI语义，不验证来源、许可证、真实catalog完整性、当前上市状态、自然周期或真实行情历史。若预算无法扫描完整目录，应将查询能力另列设计而不是返回部分前缀。不能降低已有coverage门槛或新加无关排除来声称通过。

## 生产启用与迁移范围仍开放

目前未发现reviewed production instrument dataset/profile、当前发布的完整标的snapshot、AFI symbol映射、source redistribution license或精确AFI DatasetGrant。数据库内的publication grant并不等于第三方权利证明。所有这些未知均保持UNKNOWN，缺任一项时selector新路径保持关闭并fail closed；不得通过本批代码或fixture创建授权、声称版权、切换任务或部署。

本批不改变控制矩阵：87项仍为8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；1,103个旧任务、1,066个脚本候选、所有AFI消费者、真实source rights、逐标的全历史head/interior/tail、natural cycles、backup/restore与单写者cutover继续OPEN。完整历史起点不能用首次行情行、snapshot `as_of`或目录成员推断。详细财报脚本和task的历史静态证据只见上述Wave 8 mapping receipt，不能改写全量清单或旧任务状态。
