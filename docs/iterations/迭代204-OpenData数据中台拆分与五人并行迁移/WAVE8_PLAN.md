# 第八批 股票标的参考目录 REST 接线与财报脚本映射计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED / NOT_PRODUCTION_ACCEPTED**。OpenData与AFI scoped offline gates、静态检查、bridge、指定reviews及独立归档审查均通过，最终A2/full-history secret和冻结归档已生成。本批未取得生产权利或切换批准，87项父矩阵不变。Full project extras、full CI/`make`及Python 3.10 runtime未运行；真实来源许可、grant与全历史验收仍开放。Wave 5至Wave 7的收据仅是历史记录，不作为Wave 8通过证据。

## 目标与边界

为AFI股票选择器设计一条可关闭的OpenData published-reference读取路径，使候选股票身份由已发布目录快照提供。启用后，该选择器的候选列表应来自OpenData REST；不得再从AFI本地warehouse、cache或seed拼接、补足或回退结果。独立的默认关闭配置必须控制此路径；关闭时现有选择器行为保持不变。

此切片只处理“目录中是否有一个经过审查的标的身份映射”。目录成员身份不表示行情快照或历史行情存在、可读或完整。`unknown`可用性必须继续表示未知，不能转换为`false`、`0`或“没有数据”。用户手工输入但尚未由目录确认的symbol也不能伪装成已验证成员。

本批不启用真实provider、production dataset、来源key、DatasetGrant或AFI OpenData selector flag；不写入行情表，不改变W5 K线接口或其`MARKET_DATA_OPENDATA_ENABLED`配置，不迁移财报脚本，不运行旧脚本，不改变87项控制任务或1,103任务/1,066脚本的既有分母，也不关闭逐标的全历史要求。

## 架构决策与设计依据

root最终决定是**扩展现有v2 records/snapshot路径，接纳窄化的`table + none + time_field=null`无时间窗分支**。首版不增加instrument专用搜索endpoint、不新增`reference` record kind、不制造时间字段，也不增加数据库迁移。根决策收据为`/tmp/od204-receipts/wave8-root-architecture-decision.json`，设计锚点为OpenData `f7aec5da6c30de03b48e88e7abbdcd748bde0934`和AFI `5225e947804bce32c51e2119dd25a40d651ac6f7`。

两份设计评审收据（`wave8-instrument-contract-proposal.txt`、`wave8-instrument-contract-independent-review.txt`）有一项建议为新建专用目录查询route；root的最终选择已否决该首版route方向，本计划以root决定为准。评审中关于完整快照读取、无部分结果、逐页授权、请求边界、alias日期语义和rights未证明等建议保留为设计约束。

现有OpenData `DatasetContract`已定义`record_kind="table"`和`temporal_semantics="none"`；`PublicationStore`的记录允许nullable `business_date`，也支持无日期边界的snapshot，并用null-date后接business-key的稳定排序分页。Wave8在OpenData `83c743095f3c132936c1ea640b281e0cf6fba813`加入冻结profile要求的窄table/none无时间窗分支，随后在`71fdf9cddeb0efebd120da77d80948dd6bdddb2d`补齐producer边界测试；其余record kind仍由原time-series/date-window校验处理。此处的OpenData scoped gate通过不等于Wave8整体验收或生产批准。

AFI不能直接复用同步的`opendata-client SnapshotClient`：它要求日期窗并按business date校验，在async请求中同步调用也会阻塞事件循环。设计方向是AFI专用的小型async HTTP adapter，读取现有records/snapshot页并在AFI内完成完整快照校验与有限搜索；不引入sibling-checkout导入或未发布的本地client依赖。

现有`InstrumentReferenceRegistry`只是对显式注入的记录做验证/解析，不是持久发布目录或listing API；目前也没有已审查的生产标的snapshot、AFI display/query-symbol mapping、name/market projection或授权。不能把这个validator的存在描述为目录已经可消费。

## 已冻结的共享契约（W8-01完成）

root在`/tmp/od204-receipts/wave8-frozen-contract.json`冻结v1离线实现契约。规范化contract SHA-256为`8dc2e5912f5a8c9e371beed3c36c772fe32914f59065d7655310a4e6e3be5c96`；OpenData、AFI backend与AFI frontend三份共享fixture的SHA-256均为`bc891b8abaa1f332bf6f1c08ee4737bdada68e10a848f30866dd43dbbe215f72`。冻结记录状态是`FROZEN_FOR_OFFLINE_IMPLEMENTATION; NOT_PRODUCTION_APPROVED`，fixture内的行、source、publication、可用性和日期均为合成协议样例，不是现实标的或权利证据。

冻结profile为`od.instrument-reference.v1`，fixture dataset为`fixture.instrument-reference.stock`，schema/semantic版本为`1`/`1.0.0`，来源身份为`fixture.reference`/`synthetic-fixture`。字段、类型、nullable、business key与顺序以fixture为准；关键约束为`record_kind=table`、`temporal_semantics=none`、`time_field=null`、`pit_policy=unsupported`，business key和ordering均为`instrument_id`。记录使用`business_date=null`，API不接收日期窗；null business date不代表历史业务日期。完整字段表及分页wire样例只以三处hash相同的共享fixture为准，流不得另造schema或样例。

载荷只表达中国股票的显式身份映射：symbol必须是6位ASCII数字，market为`CN`，exchange显式为`XSHG`、`XSHE`或`XBSE`，不得从symbol推断交易所；name非空、不含控制字符且最长128字符。公开evidence reference仅接受`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`，普通registry ID/version/alias仍遵循registry自身格式。每标的最多16个alias。必须保留显式未知上市起点和lifecycle证据；模糊symbol、重复key或不完整projection拒绝整个catalog，不能丢行后继续服务。

AFI adapter使用注入配置，不自行读环境或设置；协议限制为每页100行、最多200页/20,000行、单响应2 MiB、累计16 MiB、请求超时2秒、overall deadline 5秒，selector上限80项。固定server-owned origin，禁止代理环境继承与重定向；仅HTTPS或数字loopback的HTTP。完整snapshot校验成功后才搜索和返回，不重试、不提供不完整前缀。合同错误码及固定安全消息由冻结协议约束；enabled-stock参数校验可使用`OPENDATA_REFERENCE_REQUEST_INVALID`并返回422安全错误封套。

读取仍复用既有v2 records/snapshot路径，不新增reference搜索route或迁移。OpenData首请求要求同一source的`data.read`与`snapshot.create`及现有research purpose，continuation逐请求检查`data.read`；root/operator必须另行核实grant purpose确实覆盖AFI标的选择。本批不创建grant。AFI selector flag `MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED`默认关闭；dataset/source/contract pin默认空，凭证使用既有服务端配置。fixture的`options_response`固定`catalog_verified`、`data_availability`与`has_history`等字段语义：标的成员身份不能推导行情可用性，unknown必须保持unknown/null。alias匹配必须由用户显式提供`effective_on`，不得用今天或publication `as_of`代替。

## 现有v2读取路径与约束

AFI启用时使用既有v2 dataset records page协议和snapshot/cursor机制；冻结合同明确不定义`/instrument-references`专用endpoint或remote `q`/`search`参数。首请求不带日期窗并固定publication snapshot；后续页绑定同一snapshot与cursor，page size及contract/provenance pins不得变化。OpenData仅放行冻结的窄`table + none + time_field=null`分支，其他record kind仍走既有time-series/date-window校验；每条table记录必须`business_date=null`，business key与ordering为`instrument_id`，ordering与null-date/business-key存储排序一致。

首次读取须匹配同一source的`data.read`与`snapshot.create`，continuation逐请求检查`data.read`并绑定原snapshot/access scope。cursor不能替代授权；授权需按exact dataset/source/domain/operation/purpose/subject/validity匹配，purpose由服务端固定选择。数据库DatasetGrant只证明OpenData内访问范围，不证明第三方来源许可或再分发权；fixture及offline tests都不证明production grant可用。不得降低既有time-series校验或把完整snapshot的`content_sha256`描述成搜索子集hash。

## 完整快照读取、搜索和结果语义

AFI adapter必须读取并验证**整个有界snapshot**后才执行selector搜索和返回“完整”结果。每页应与首次返回的dataset/publication/sequence/schema与semantic version/contract hash/snapshot/content hash/publication `as_of`一致；验证cursor前进、stable ordering、business-key唯一性、snapshot expiry、总行数、响应bytes、页数及overall deadline。仅在所有页面通过验证后才可计算exact total/has-more；v1不写cache。

因为records API按原publication snapshot分页，而首版不新增filter endpoint，symbol/name/alias筛选应在AFI已完整验证的快照上进行。若预算耗尽、cursor/contract/provenance不一致、snapshot过期、响应过大或传输失败，必须返回unavailable/incomplete结果；不能把读到的前缀当成完整目录，不能返回看似正常的部分搜索命中或精确total。

只在经profile审查的候选字段上匹配并按固定规范化规则搜索。alias仅在调用者显式提供业务生效日期时按其有效期解析；不得默认使用今天、publication `as_of`、行情交易日或价格记录日期。alias日期和publication visibility是两个时钟，PIT保持unsupported。`known_start_date`仅能来自独立证据；不得用当前最早行情行推断上市日。lifecycle status须连同其证据日期/边界呈现，不能把旧的“active”值解释为当前状态。

v1冻结为不缓存、不重试。不得将AFI现有warehouse/cache/seed当REST失败回退，也不得在权限拒绝、snapshot失效或扫描不完整时用陈旧结果伪装成功。未知/不可用、空目录和拒绝访问是不同状态，不能互相折叠。

## AFI身份与UI显示边界

`instrument_id`不等同于AFI各数据源所需的query symbol；冻结profile明确绑定后才能作为AFI selector option。options DTO字段和安全错误码以共享fixture为准；fixture要求成员验证与行情数据可用性分开，synthetic `catalog_verified=true`并不证明真实目录审核完成。unknown availability须保持`unknown`及相应`null`，不得转换为`has_history=false`、`history_rows=0`或`has_snapshot=false`。只有另一条获准的coverage/records证据才能使availability变为已知。

现有`GET /data/market-instruments/options`继续承载selector；flag关闭或非stock请求维持旧行为，enabled stock请求才走新目录路径。无效search/limit或非canonical `effective_on`可返回`OPENDATA_REFERENCE_REQUEST_INVALID`及422安全封套；未显式提供alias生效日时返回effective-date-required。`ensureCurrentInstrumentOption`为输入symbol创建的shell不是published membership。独立flag开启时，未解析typed value必须保持unverified，不能作为目录命中或传入新backend作为canonical ID。UI不得在enabled-mode失败后显示旧warehouse/cache/seed结果；应清空旧搜索命中并明确呈现unknown或unavailable，不能伪造“无历史数据”。

### Stock options请求的重试与错误提示

root已决定并在`d337`/`d626`实现、review浏览器stock-options请求的`skipRetry: true`和`suppressErrorToast: true`，包括初始catalog-mode discovery调用。一次自动重试会再触发最多三次完整snapshot扫描，因此stock请求改由view控制手动重试并显示固定安全错误。stock旧路径成功结果和默认DTO保持不变；transient stock失败不再自动重试或弹通用toast，由view显示安全信息。非stock请求的retry/toast默认行为保持不变。相关UI定向测试、类型检查、构建和静态检查通过，此项已纳入Wave8 scoped offline validation。

## 实施工作流、分支与当前任务状态

四个独立代码工作树分别处理OpenData producer、OpenData v2 table API、AFI async adapter和AFI selector UI。以下路径、branch和HEAD是工作流快照；scoped offline status以本表与后续精确收据为准，HEAD快照不代表单一revision上的combined suite或生产验收。

| 代码流 | 工作树 / branch / 当前HEAD | 当前范围与状态 |
| --- | --- | --- |
| OpenData producer | `/tmp/od204-wave8-reference-publication` / `codex/od204-wave8-reference-publication` / `109f58d763e2e27670a17a406df9e2e6aa8ecdfe`（在`6ac9becd83051f4d4923cb02b2c06ba0c0ef56f7`、`2fbb4a11645c11487c2532753e73ac9014fba1bf`之后） | projection及边界测试已实现并静态审查；接受的OpenData门禁source为`71fdf9cddeb0efebd120da77d80948dd6bdddb2d`。 |
| OpenData v2 table API | `/tmp/od204-wave8-table-api` / `codex/od204-wave8-table-api` / `9593660c1c3f445600c974696969a73b1e55fa47` | 既有records endpoint的atemporal分支及API tests已实现并静态审查；API源码hash在复测中与review pin一致。 |
| AFI async adapter | `/tmp/od204-wave8-afi-reference` / `codex/od204-wave8-afi-reference` / base `d069d829d04486c85a8159b8db3631e8d234a305`；root精确门禁source `6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c` | boundary timeout测试修正`11825`与增量发布适配`11f516`/`7082`已集成；Python 3.11.15锁定依赖子集环境中的三文件运行203 passed、11.33秒，adapter coverage 92.55319%达到90%门槛，route helper 94.68085%达到85%门槛。adapter增量发布复审GREEN。 |
| AFI selector UI | `/tmp/od204-wave8-afi-selector` / `codex/od204-wave8-afi-selector` / `a2f3431fde5bdfa3f545d44a2bb06bc818335d29`，后续UI提交`1926c8c4d8f220d07d7ac1ef440673ab3dafd311`、`730acf1f5b4bebe41578a8460d4a5b88a2248516` | 目录模式、针对性测试及stock options retry/toast请求策略已有实现和review；root另有legacy测试断言`d441574e49e4885b524e57795b38c1e579edffd7`及crypto fixture更新`6df61696640fa3cd1653b24f014fa2309002026d`。 |

root在managed AFI集成工作树`/home/yun/.codex/worktrees/od204-integration/ai-for-investor`独占共享fixture/schema消费、`app/config.py`、API route glue、OpenAPI/quality census、集成和测试选择。route/glue `98c3e1e93978d7e8c42ae9a6f95861b7a376fc08`与adapter `d069d829d04486c85a8159b8db3631e8d234a305`先合入`7950a4cfd3fe54202f4417306af28766ac73fa65`；当前managed AFI source为`6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`。Wave8的focused receipts来自多个精确source revision，public validation manifest逐run记录source SHA；manifest中的production-byte pins均与当前production文件匹配。因此本批结论是分run、分scope的offline验证，不代表一套在单一HEAD执行的combined suite。各编码流继续使用独立工作树；root独占共享文件并串行合并，避免多个author改同一source。

| W8任务 | 状态 | 范围/依据 |
| --- | --- | --- |
| W8-01 共享合同与fixture | DONE — CONTRACT_FROZEN | frozen receipt与三份fixture hash如上；任何wire变化须由root重新冻结。 |
| W8-02 OpenData producer | OFFLINE_VALIDATED | producer projection及boundary tests；第二次OpenData四文件gate覆盖率98.9071%（门槛90%）。 |
| W8-03 OpenData table API | OFFLINE_VALIDATED | v2现有records atemporal分支；第二次gate覆盖率89.8862%（门槛85%）。 |
| W8-04 AFI adapter | OFFLINE_VALIDATED | source `6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`的锁定依赖Python 3.11.15三文件运行203 passed、11.33秒；adapter coverage 92.55319%及route helper 94.68085%均达到各自阈值。锁定subset metadata/pip check通过；timeout与增量发布修正已集成，增量协议复审GREEN。receipt `wave8-afi-backend-lock-root-command.json`。 |
| W8-05 AFI route/config接线 | OFFLINE_VALIDATED | route/glue提交`98c3e1e93978d7e8c42ae9a6f95861b7a376fc08`；auth/revocation用例通过，最终route/UI独立review为GREEN。 |
| W8-06 UI DTO | OFFLINE_VALIDATED | 前端fixture DTO与API定向测试通过；stock请求`skipRetry`/`suppressErrorToast`已在`d337`/`d626`实现并review。 |
| W8-07 UI membership/availability | OFFLINE_VALIDATED | verified membership、unknown availability、enabled失败安全消息与manual retry已有定向测试并通过。 |
| W8-08 protocol/root integration tests | OFFLINE_VALIDATED | OpenData四文件gate PASS；AFI锁定依赖三文件gate 203 passed，两个coverage target达标；producer→API→AFI隔离bridge两测试PASS。 |
| W8-09 auth/revocation race tests | OFFLINE_VALIDATED | 锁定依赖Python 3.11.15环境中的AFI三文件精确run通过，授权/撤权路由用例通过。 |
| W8-10 UI tests/build/typecheck/static | OFFLINE_VALIDATED | 新UI 18 tests、legacy两文件91 tests、vue-tsc、source-stable build通过；锁定静态复跑中Ruff/format 7 files、mypy/Bandit 4 files、ESLint 7 files均PASS。 |
| W8-11 independent reviews | OFFLINE_VALIDATED — SCOPED REVIEWS GREEN | OpenData producer/API、最终AFI route/UI（`wave8-afi-final-route-ui-review.txt`）、incremental-publication（`wave8-afi-incremental-publication-review.txt`）、locked environment（`wave8-afi-lock-environment-review.txt`）及bridge harness `9ef70ba6`（`wave8-reference-wire-bridge-review-v2.txt`）均GREEN。 |
| W8-12 12条财报脚本映射 | STATIC_ONLY — COMPLETE | 只读历史snapshot映射已完成；不是provider迁移、真实运行或权利验收。 |
| W8-13 文档与批次验收 | OFFLINE_VALIDATED | frozen archive、public JSON hashes、corrected public-doc secret scan及独立162-file archive audit均PASS；此状态仅关闭Wave8离线批次文档/归档子项，不表示生产验收。 |
| W8-14 adapter protocol-boundary tests | OFFLINE_VALIDATED | Timeout修正`11825`随`d538`集成，增量publication修正`11f516`/`7082`随`a57ae`/`6b8`集成；最终三文件run 203 passed，coverage targets达标。首轮199 passed、1 failed保留为历史记录。 |
| W8-15 producer→API→AFI wire bridge | OFFLINE_VALIDATED | 独立审查GREEN的harness `9ef70ba6dd1dd00c2489b28b7d6210a956c12d9a8066706f5728d7fe9abb8297`由root隔离runner运行两个实际ASGI节点：2 tests passed、1.25秒。覆盖第一次及增量publication路径。收据：`wave8-reference-wire-bridge-root-command.json`。 |

三类独立审查职责为：OpenData producer/table API；AFI adapter协议与安全边界；AFI route/UI consumer及隔离runner。OpenData producer/API、AFI incremental-publication adapter、最终route/UI、locked environment及wire-bridge harness静态reviews均GREEN，bridge scoped run和Wave8独立归档审查也PASS。任何review都不能证明来源许可、生产grant、真实目录完整性或部署安全。

## OpenData精确离线门禁结果

两次运行使用同一root allowlist：`tests/test_instrument_reference_publication.py`、`tests/test_instrument_reference.py`、`tests/test_published_table_api.py`、`tests/test_published_data_api.py`，均通过隔离runner执行；coverage阈值分别是producer 90%及`published_data.py` 85%。

- 首次运行在OpenData `83c743095f3c132936c1ea640b281e0cf6fba813`：107 passed，14.91秒。测试本身退出码为0，但coverage gate **FAIL**：producer 87.97814207650273%低于90%；API 89.88621997471554%达到85%门槛。收据：`/tmp/od204-receipts/wave8-od-first-root-command.json`、`wave8-od-first-root.txt`及对应coverage文件。
- 加入producer边界测试提交`109f58d763e2e27670a17a406df9e2e6aa8ecdfe`后，在OpenData `71fdf9cddeb0efebd120da77d80948dd6bdddb2d`重跑同一allowlist：112 passed，12.42秒，scoped gate **PASS**。producer coverage 98.90710382513662%，API coverage 89.88621997471554%；API源码hash仍与`9593660c1c3f445600c974696969a73b1e55fa47` review pin一致。收据：`/tmp/od204-receipts/wave8-od-second-root-command.json`、`wave8-od-second-root.txt`、`wave8-od-second-root-coverage.json/.xml`及`wave8-od-second-root-htmlcov/`。

第二次结果只关闭OpenData这四个文件的离线子门禁。OpenData静态/census收口另在commit `ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`报告PASS。两者都不关闭AFI adapter、route、UI、reviews或组合验收，也不构成生产数据、source rights、真实目录完整性或切换批准。

## AFI定向验证与未关闭门禁

以下为不同AFI source snapshot上的root窄范围结果；后端最新精确运行source pin为`6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`。单项通过不表示AFI整体或Wave8通过。

- **前端定向验证。** 两个新增instrument-reference Vitest文件18 passed，2.37秒；原有`marketData.test.ts`与`DataPage.test.ts`两文件91 passed，4.13秒。全局`vue-tsc --noEmit`在Vite生成忽略的component/auto-import declaration后通过；早期缺少生成声明时的50个TS2558错误已审计为setup问题。第一次build退出码为0、36.40秒，但因并发测试fixture-only提交`6df61696640fa3cd1653b24f014fa2309002026d`导致source-fence不匹配，收据判FAIL；在稳定HEAD `dee1849`上重跑的build通过，39.65秒，仍报告既有大于500 kB的chunk warning。前端收据分别为`wave8-afi-frontend-new-fixed-root`、`wave8-afi-frontend-compat-fixed-root`、`wave8-afi-frontend-typecheck-generated-root`、`wave8-afi-frontend-build-stable-root`。stock request retry/toast策略已在`d337`/`d626`实现并review；前端及本批静态检查结果见相应收据。
- **静态检查。** Python 3.11.15锁定依赖subset下的复跑在AFI backend 7个Python文件上Ruff/format通过，4个生产文件mypy/Bandit通过；frontend 7个文件ESLint通过。收据`/tmp/od204-receipts/wave8-afi-static-lock-command.json`，source pin为`6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`；先前静态PASS收据仍保留。
- **后端第一次运行。** 在`8406641b0cffa3eaf4ac526f530a81e85a9b9450`上31 failed、72 passed、9.92秒；记录的问题包括adapter raw fixture不匹配和预算测试期望错误。该项不是通过。
- **后端第二次运行。** 在`a3ecf761e25ab8db8f7426d604bacc588fdeb865`上104 passed、1 failed、7.45秒；剩余失败是测试错误假设HIST alias在2020年仍属于旧标的。该项不是通过。
- **后端第三次运行（历史失败）。** 在当时的candidate `dee1849fa960758505f1816ba70acaeacc543b48`上105 passed、10.68秒，功能用例全通过，但coverage gate **FAIL**：adapter service `77.27771679473106%`低于90%门槛，route helper `94.68085106382979%`达到85%门槛，整体报告约79%也低于既有85% fail-under。试验配置新增`concurrency=greenlet,thread`；coverage阈值、branch测量和exclusions均未降低或增加。后续精确运行已达到两个目标文件的coverage阈值，见下一条。收据：`wave8-afi-backend-greenlet-root-command.json/.txt`及对应coverage报告。
- **边界测试集成后的首次精确运行（历史失败保留）。** 在source pin `2404c19aecc054c7aaa096ba2f231a3100d84f78`上，对`test_opendata_instrument_reference.py`、`test_opendata_instrument_reference_boundaries.py`和`test_market_instrument_reference_options.py`运行：199 passed、1 failed，11.33秒。adapter coverage `92.75521405049396%`达到90%门槛，API helper `94.68085106382979%`达到85%门槛；命令因立即抛出`asyncio.TimeoutError`的MockTransport测试错误期待budget-limit错误码而FAIL。timeout测试修正`11825`已在`d538`集成；失败历史保留。收据：`wave8-afi-backend-boundaries-root-command.json/.txt`及coverage报告。
- **增量修正后的首次精确运行（环境不匹配历史结果）。** 在root source `6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`上，对同一三文件allowlist运行：203 passed，12.19秒，exit 0。adapter coverage `92.55319148936171%`达到90%门槛，API helper `94.68085106382979%`达到85%门槛。后续发现该质量环境SQLAlchemy版本低于项目声明，因此此项保留为历史结果；同一选择在锁定依赖环境的最终结果见下一条。收据：`wave8-afi-backend-incremental-root-command.json/.txt`及coverage报告。
- **锁定依赖环境的最终AFI精确运行。** 在source `6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`及相同三文件allowlist上，以Python 3.11.15运行：203 passed，11.33秒，exit 0。adapter coverage `92.55319148936171%`达到90%门槛，API helper `94.68085106382979%`达到85%门槛。收据：`wave8-afi-backend-lock-root-command.json/.txt`及coverage报告。
- **增量publication/latest-view语义修正。** OpenData delta/latest-view中，未变化行可以保留原有row-level `publication_id`和`publication_sequence`；snapshot-level sequence/ID仍必须精确pin到当前snapshot。root决策`wave8-incremental-publication-decision.json`要求校验row sequence在`[1, pinned snapshot sequence]`范围、publication ID有效，且完整snapshot内sequence↔ID一一对应；只有达到当前sequence的row才必须匹配当前snapshot ID。空目录时无法从行证实`profile_version`和`registry_version`，所以保留provenance键并给null是准确表达，不得编造版本。adapter修正`11f516`/`7082`已集成至`a57ae`/`6b8`，独立复审GREEN。
- **Producer→API→AFI bridge。** 最终隔离harness `9ef70ba6dd1dd00c2489b28b7d6210a956c12d9a8066706f5728d7fe9abb8297`经独立review v2评为GREEN；root runner在两个实际ASGI节点上2 tests passed、1.25秒。结果收据：`wave8-reference-wire-bridge-root-command.json`；review收据：`wave8-reference-wire-bridge-review-v2.txt`。
- **锁定focused环境与兼容性边界。** 早期质量环境实际SQLAlchemy 2.0.39，低于项目声明的`sqlalchemy[asyncio]>=2.0.50,<2.1`；该历史版本差异已由独立Python 3.11.15锁定dev-lock subset验证解决：52 packages、metadata mismatches 0、`pip check` exit 0，SQLAlchemy 2.0.54、pydantic-settings 2.14.2、mypy 1.20.2及Ruff 0.15.13。环境收据`wave8-afi-lock-environment-verification.json`；独立review `wave8-afi-lock-environment-review.txt`为GREEN。此结论限于focused subset；full project extras、full CI/`make` gate和Python 3.10 runtime均NOT_RUN。
- **Final A2/static。** PASS：complete resolver 1,203；787 mypy roots全部exit 0。333项docs/evidence排除仍按原有政策；149,323项历史Ruff findings仍NOT GREEN，支持项及16项active evidence gaps仍OPEN。Wave8 scoped验证不改变这些存量问题。
- **Full-history secret scan。** 固定Gitleaks 8.30.1扫描872 commits，0 leaks，PASS。
- **公开证据与secret复扫。** Public validation JSON SHA-256 `926255ab9c82ef7f7a63842efe25b3cdba75a528edd1f7c14ded266f31c3a058`；archive JSON SHA-256 `1b6062101f29676db9c7beb39f8de70210de781f398b08de6bdd6640e53b46ca`。首次public-doc scan的1个`generic-api-key`命中经独立核实是Git commit metadata false positive。修正仅改变receipt mapping→list-objects处理，保留内容值且不加scanner allowlist；corrected scan 0 findings，PASS，收据`wave8-public-docs-secret-scan-corrected-command.json`。修正及复核收据位于归档外，immutable archive未改动。
- **Wave8冻结归档与独立审查。** 原始归档位于`/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave8`，162 files、14,408,256 bytes，目录0700/文件0600；Wave7归档保持不变。独立归档审计25项检查、0 findings，PASS；receipt `/tmp/od204-receipts/wave8-archive-independent-audit.json`，SHA-256 `21f1a0cba555f786b567358fa32ed67b323be3d643c2041b9e4d258db634273d`。审计核验162个Wave8文件/8个ZIP、Wave7归档106个文件保持不变、13份已接受收据、10个当前production byte pins、失败运行留档及corrected public scan链。审计和post-scan收据位于冻结归档之外，原归档未改动。此项仅关闭Wave8离线文档/归档子验收，不改变87项父矩阵，也不构成生产批准。
- **未执行的较大范围检查。** Full project extras、full CI/`make` gate、未指定目录测试及Python 3.10 runtime均NOT_RUN；这些范围不属于本批scoped offline validation。

静态coverage tracing audit对比第二、三次后端收据：helper生产源码及route测试pin一致，greenlet-aware tracing使await后的授权检查和异常处理行被计入；adapter测试文件pin在两次运行间变化，因此不能把它描述为全局严格A/B因果证明。该历史审计支持helper覆盖率受greenlet tracing影响的判断；后续锁定依赖精确运行中adapter与helper coverage均已达到各自门槛。未降低coverage阈值，也未添加coverage exclusions。静态结果见`wave8-afi-coverage-tracing-audit.txt`与`wave8-afi-coverage-tracing-result-audit.txt`。

adapter protocol-boundary测试与timeout修正已合入并在锁定依赖的203-test精确运行中通过；保留先前199 passed/1 failed的运行历史。producer→OpenData records API→AFI adapter的wire-bridge harness独立review v2及2-test actual-ASGI bridge execution均PASS。两项分别对应W8-14和W8-15，不能由OpenData、UI或单侧AFI用例通过替代。

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

1. W8-01合同与共享fixture已冻结；四个实现流只按同一hash接线。发现字段或wire含义需变更时先停下并由root版本化/重新冻结，避免各流出现不同DTO。
2. OpenData producer与table API已在`71fdf9cddeb0efebd120da77d80948dd6bdddb2d`通过精确四文件离线子门禁，静态/census另在`ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`通过；首次coverage失败保留在上文。AFI route/config/adapter在`6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`锁定依赖精确三文件门禁PASS，stock request policy已实现并review；incremental-publication修正及producer→API→AFI bridge也已集成、review和scoped PASS。locked environment review、root A2/static、full-history secret、public-doc scan及独立Wave8 archive audit均PASS。财报映射只作静态分析，不阻塞selector实现，也不授权修改财报脚本或provider代码。
3. root继续串行整合各branch、复查shared contract和auth/provenance边界。OpenData、AFI及bridge scoped gates、指定reviews、A2/static、full-history secret、corrected public-doc scan及162-file archive audit均通过；Wave8状态为`SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED / NOT_PRODUCTION_ACCEPTED`。Full project extras、full CI/`make` gate和Python 3.10 runtime NOT_RUN，真实来源许可、grant、全历史及production cutover保持OPEN。不改变87项父矩阵或生产权限结论。

实施后建议覆盖：null-date table record合法而其他时间语义仍拒绝；time-series原date-window合同回归；stable key、alias日期边界和lifecycle unknown；首请求与continuation授权、grant source binding、snapshot pinning与cursor expiry；整包分页身份/哈希/顺序/unique-key验证；每类page/row/bytes/deadline cap失败都不产生partial success；disabled path不变、enabled失败不调用local warehouse/cache/seed；catalog membership不推导history/snapshot availability；typed shell不能变成verified member。AFI backend使用`httpx.MockTransport`和显式owned test resources；OpenData使用固定fixture与测试owned SQLite；frontend使用locked依赖下的定向Vitest。OpenData精确allowlist和AFI实际选择的三文件见上文。

离线fixture最多验证合同、授权路径、分页和UI语义，不验证来源、许可证、真实catalog完整性、当前上市状态、自然周期或真实行情历史。若预算无法扫描完整目录，应将查询能力另列设计而不是返回部分前缀。不能降低已有coverage门槛或新加无关排除来声称通过。本计划作者只对Markdown和现有收据作只读检查，未运行测试、coverage、build、应用导入或网络/数据库操作。

## 生产启用与迁移范围仍开放

目前未发现reviewed production instrument dataset/profile、当前发布的完整标的snapshot、AFI symbol映射、source redistribution license或精确AFI DatasetGrant。数据库内的publication grant并不等于第三方权利证明。所有这些未知均保持UNKNOWN，缺任一项时selector新路径保持关闭并fail closed；不得通过本批代码或fixture创建授权、声称版权、切换任务或部署。

本批不改变控制矩阵：87项仍为8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；1,103个旧任务、1,066个脚本候选、所有AFI消费者、真实source rights、逐标的全历史head/interior/tail、natural cycles、backup/restore与单写者cutover继续OPEN。完整历史起点不能用首次行情行、snapshot `as_of`或目录成员推断。详细财报脚本和task的历史静态证据只见上述Wave 8 mapping receipt，不能改写全量清单或旧任务状态。
