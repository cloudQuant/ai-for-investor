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
