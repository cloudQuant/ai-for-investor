# 全 A 股官方名录来源核验

核验日期：2026-10-27。以下是官方网页本次实际可见的信息及明确的读取边界；网页当前展示状态不代表历史完整性。未能读取动态页面的字段、下载文件或接口不作推断。本次没有确认批量采集、保存或 API 再分发的授权。

## 官方页面与可证事实

| 来源 | 本次可证事实 | 未证实或限制 |
|---|---|---|
| 上交所 | [股票列表](https://www.sse.com.cn/assortment/stock/list/share/)可按主板 A 股、主板 B 股、科创板筛选；可见代码、简称、扩位简称、上市日期等列和下载控件。[暂停/终止上市列表](https://www.sse.com.cn/assortment/stock/list/delisting/)可见状态筛选及公司代码、简称、上市日期、暂停上市日期等列，也有下载控件。 | 暂停/终止列表没有本次可见的实际摘牌日期字段；页面快照显示“暂无数据”，不能据此认定没有退市公司。下载格式、底层接口、历史完整性及自动化采集方式未核验。[太和水摘牌公告](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20260629_10823832.shtml)记载退市整理期于 2026-06-29 届满、2026-07-03 摘牌，说明实际摘牌日需从事件公告核验。 |
| 深交所 | [股票列表页面](https://www.szse.cn/market/product/stock/list/index.html)被官方投资者规则页引用为股票列表入口；[月度统计](https://docs.static.szse.cn/www/market/periodical/month/W020261014351244013109.html)分别统计主板 A 股、主板 B 股和创业板 A 股；[退市公告实例](https://disc.static.szse.cn/download/disc/disk02/finalpage/2020-08-25/d6941c99-4243-4b10-8516-e8cca53fe113.PDF)载有证券类别、代码、终止上市决定日及终止上市/摘牌日。 | 本次股票列表页面读取超时，未核验其字段、筛选、下载格式或 API。月报是分类计数，不是证券级名录。[退市信息入口](https://www.szse.cn/marketServices/message/period/index.html)有退市整理期及已退市公司公告栏目；未找到可证明覆盖全部历史退市证券的批量主数据。 |
| 北交所 | [新旧代码对照表](https://www.bse.cn/service/code_mapping.html)可见证券简称、上市日期、旧代码、新代码；脚注明确，精选层平移公司的日期是原精选层挂牌日期。[原上市规则](https://www.bse.cn/cxjg_list/200010908.html)说明精选层平移上市时间连续计算。[现行上市规则](https://www.bse.cn/cxjg_list/200028220.html)要求终止上市公告列示股票终止上市日期，并规定退市后转入全国股转系统退市板块。 | [股票行情页面](https://www.bse.cn/nq/quotation.html)本次打开时发生重定向循环，未核验字段或批量接口。代码对照表是部分变更映射，不是全量现存及退市名录；不得把精选层/北交所上市日覆盖原始挂牌日。 |
| 全国股转系统（退市后 crosswalk 辅助来源） | [挂牌公司查询](https://www.neeq.com.cn/nq/listedcompany.html)可见查询入口；[退市公司公告](https://www.neeq.com.cn/disclosure/overview_information.html)有“两网及退市公司公告”；[2021 年挂牌业务指引](https://www.neeq.com.cn/class_d/200011099.html)说明退市后挂牌安排；[代码规则](https://www.neeq.com.cn/m/class_d/200011976.html)明确退市 A 股为 400 段、退市 B 股为 420 段。 | 查询页的 iframe 名录内容本次未展开。NEEQ 代码及退市板块挂牌日不能替代原交易所证券代码、原证券身份或实际摘牌日；需要逐项、有证据地建立映射。 |

深交所规则页还说明，股票/存托凭证特别简称与标识通过行情产品信息文件发布，可参见[相关规则](https://investor.szse.cn/lawrules/rule/allrules/bussiness/t20230217_598760.html)。这支持进一步调查官方产品文件渠道，但不等于已经验证存在可下载的全历史名录。

## 字段、身份与权利边界

来源原字段应与规范字段分开保存，并保留 `source_id`、源证券代码、名称、证券类别、交易所、原始状态、来源时点、公告/文件引用及文件哈希。生命周期事件至少要区分上市/挂牌日、转板日、暂停上市日、最后交易日、终止上市决定日和实际摘牌日；来源没有提供的日期保持 `unknown`，不能用行情首条记录补齐。

`instrument_id` 应是中台稳定身份；代码及名称作为带 `valid_from` / `valid_through` 和证据引用的来源别名/crosswalk 保存。代码复用、跨板转移或 NEEQ 退市代码不能仅凭字符串相似合并；精选层平移、北交所旧新代码与退市后 400 段代码都要保留各自有效期及关系类型。A 股是否包含特殊类别、历史证券类别变更如何处理，也需先冻结范围定义；B 股、基金、指数等不能混入 A 股分母。

交易所规则/服务页对**行情信息**载明权属、许可或授权要求：[上交所交易规则页面](https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml)、[上交所行情服务](https://www.sse.com.cn/transparency/services/index.shtml)、[深交所 2026 年交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf)、[深交所数据服务](https://investor.szse.cn/English/services/dataServices/index.html)、[北交所行情授权指南](https://www.bse.cn/application/guide.html)。上交所规则页面的 2026 年网页元数据与生效日期/状态信息存在冲突，适用状态需进一步核验；此处仅列为待核验来源，不称其为现行规则。这些行情条款不能自动推导静态证券名录的许可结论。静态名录的批量取得、自动化抓取、长期保存和通过 OpenData REST 再分发权限均待交易所/数据服务方或法务书面确认；公开页面或下载控件本身不视为授权。

## 下一步验收

1. 先书面确定 A 股范围、特殊类别、跨板转移及退市后证券的纳入规则，并完成静态名录抓取、保存、展示和 REST 再分发权利核验。
2. 为沪深北当前名录和退市公告/档案分别登记来源、有效时点、抓取时间、原始文件及哈希。对动态页面或接口，先由人工保存并审核真实响应样本；本次未读到的页面字段和导出格式不作为已实现契约。
3. 逐交易所对账现存证券；以公告证据补齐退市与跨代码事件，记录完整的来源代码有效区间。检查重复、遗漏、代码复用和日期顺序，未知项单列。
4. 只有在范围、来源证据、生命周期和 crosswalk 均通过审核后，才可将名录发布为“全 A 完整”。当前可读的在册快照可用于当前查询，但未知生命周期边界必须阻止“全历史覆盖/全 A 历史全集”验收，不能阻断其本身的有效快照读取。

## 2026-10-30 增量核验：深交所 XLSX 与北交所数据文件来源

本节追加 2026-10-30 新证据，不替换 2026-10-27 的网页核验和读取边界。官方来源页面可读或一次响应成功，只能证明该次观察到的来源与内容，不能证明名单完整、取得批量采集/保存/API 再分发授权，或具备历史覆盖。

### 深交所（SZSE）真实 XLSX 响应

2026-10-30 对深交所官方 `ShowReport` 导出地址进行受限单次捕获。两份响应均为 HTTP 200，响应体通过 XLSX ZIP/工作簿结构检查；捕获清单记录的时间和内容哈希如下。时间以 UTC 表示，括号内为 Asia/Shanghai 时间。文件与清单保存在 OpenData 本机私有归档 [`capture-manifest.json`](</home/yun/Documents/opendata/var/reports/afi204/szse-official-xlsx-capture-20261030-5809685a/capture-manifest.json>)，未提交到仓库。

| 官方文件 | 官方导出地址 | 捕获时间 | SHA-256 |
|---|---|---|---|
| 当前 A 股列表 | [`ShowReport` XLSX](https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1) | `2026-10-30T12:13:34Z`（20:13:34） | `c466df025f3d855ebb23b0a9c9a02da38d411a97936dea36775c1c01e74f0bc7` |
| 终止上市证券列表 | [`ShowReport` XLSX](https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1793_ssgs&TABKEY=tab2) | `2026-10-30T12:13:41Z`（20:13:41） | `5282994c879c1520ff8c4bc6ce4f3bb3aa7c4099267a955ece4ede0b2939606e` |

本地终止上市工作簿的表头只有证券代码、证券简称、上市日期和终止上市日期，没有显式证券类别列；对归档的工作表 XML 检视到 212 条数据行，其中 23 条证券代码字符串以 `200` 开头。这个代码前缀只能作为待分类线索；源表没有提供证券类型，证券类别仍为 UNKNOWN，须经独立身份/类别证据核验后再决定纳入范围，不能把该文件的所有行直接计入 A 股分母。该工作表的 XML dimension 声明为 `A1`，实际 XML 仍含后续行；解析时应核对实际行数据，不能仅信任 dimension 元数据。

### 已捕获工作簿的离线结构回放

后续对两份已捕获工作簿进行了独立静态审查和隔离离线回放：审查记录为 `PASS`，回放摘要状态为 `REPLAY_COMPLETE`。本次只检查固定 XLSX 的表头及非空计数；`current_a` 是调用方声明的 selector，不能当作已独立确认的来源分类。当前表读取到 22 列，E 列表头为“A股代码”、非空数 **2,905**；J 列表头为“B股代码”、非空数 **33**。终止列表读取到 4 列、**212** 条数据行，但证券类别仍未知。这里的 A/B 是工作簿列标题，不等于已证明交易所目录的市场归属或完整性。`suspended` 类别未纳入回放，状态保持 UNKNOWN；回放不输出行值。

独立审查、执行回执及回放摘要位于 OpenData 本机私有归档 [`static-review.json`](</home/yun/Documents/opendata/var/reports/afi204/szse-official-xlsx-capture-20261030-5809685a/replay-r1/review/static-review.json>)、[`RESULT.md`](</home/yun/Documents/opendata/var/reports/afi204/szse-official-xlsx-capture-20261030-5809685a/replay-r1/RESULT.md>) 和 [`replay-summary.json`](</home/yun/Documents/opendata/var/reports/afi204/szse-official-xlsx-capture-20261030-5809685a/replay-r1/output/replay-summary.json>)。回执记录隔离回放退出码为 0。归档中的 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/szse-official-xlsx-capture-20261030-5809685a/replay-r1/README.md>) 是运行前冻结的准备说明，其中“not executed”反映其写入时的状态，不是最终执行状态。回放限定于已保存输入与固定解析器，不访问网络或数据库，也不运行调度器/应用导入。这证明的是固定样本的结构解析和计数行为；来源身份、市场范围、证券类别语义、生命周期、分页、来源完整性及历史覆盖仍为 UNKNOWN。

这些 URL 与两份已捕获文件只证明本次单文件响应。没有证据证明 selector/分页已穷尽、当前在册与终止列表共同构成完整全集、源端历史保留边界，或早期退市和代码变更事件已完整归档。真实文件通过容器格式检查也不等于证券类别、日期、生命周期字段语义已经通过完整性验收。

### 北交所（BSE）证券目录与退市事件

北交所 2025 年[《北京证券交易所/全国中小企业股份转让系统数据文件接口规范》](https://www.bse.cn/uploads/6/file/public/202508/20250812182648_1tic2qew12.pdf)的官方搜索索引正文提及 `bj_securityinfo_YYYYMMDD.xml` 数据文件，并提示该目录涉及北交所与全国股转系统两个市场；同一索引提示 `SecurityIDSource=106` 对应北交所代码源。PDF 原文件未取得，直接访问会陷入重定向循环，因此这些是索引摘要而非对规范原文的核验。不得仅凭文件名或 `SecurityIDSource=106` 推断记录属于北交所市场成员或 A 股类别。需取得并核对规范原文、`SecurityIDSource` 与 `SecurityType` 的定义/枚举及实际样本，才能确认字段语义和市场归属；当前相关结论均为 UNKNOWN。

2023 年[《北京证券交易所 FDEP 数据文件网关用户手册》](https://www.bse.cn/uploads/6/file/public/202309/20230915184229_41ihuo1sgg.pdf)描述的是会员/市场参与者数据通道。当前未取得该文件原文或验证该通道的访问权限；检索索引可读，但直接访问记录为重定向循环。因此该网关不能据此视作公众 REST 目录接口，也不能推导采集、留存或内部 API 使用授权。

北交所[官方新旧代码对照表](https://www.bse.cn/service/code_mapping.html)提供代码变更映射，不是全部现存及历史证券全集。退市流程需将终止上市决定与最终终止上市公告/实际终止日期分别作为事件保留，不能把对照表中的代码关系当作完整退市名录或最终终止日期。

2026-10-29 两次不带凭证的旧目录 POST 探测均收到 HTTP 307，响应体各 164 字节；第二次 `Location` 指向原 URL。私有归档 [`bse-directory-probe-20261029/README.md`](</home/yun/Documents/opendata/var/reports/afi204/bse-directory-probe-20261029/README.md>)说明响应是通用 nginx 307 页面、不含目录记录。响应体有字节不等于返回了非空证券目录；这两次有限探测既不能证明目录可用或完整，也不能判断来源永久不可用。

以上新增资料为来源发现与单次文件/请求证据，仍不证明沪深北全 A 股全集、退市生命周期、任何历史区间的完整性，或来源授权。全 A 分母和历史覆盖验收继续要求按来源与业务键核对遗漏、重复、证券类别、代码有效区间及事件日期，并记录未知的来源保留边界。
