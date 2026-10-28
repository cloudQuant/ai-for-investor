# AFI 财报归档 raw-only consumer

本文记录股票分析流程读取 OpenData 财报归档的当前行为和验收边界。它提供来源原生证据，尚不提供可供评分或历史回测使用的标准化财务指标。

## 配置

该读取器仅服务 `market_type="A股"` 的股票分析，开关默认为关闭：

| 环境变量 | 当前行为 |
| --- | --- |
| `STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED` | 默认 `false`。开启后，财报选择 OpenData 读取路径。 |
| `OPENDATA_API_KEY` | OpenData API 凭证；通过 `X-API-Key` 请求头发送，不放入 URL、报告或稳定错误消息。 |
| `OPENDATA_BASE_URL` | 可选 OpenData 服务根 URL；默认 `http://127.0.0.1:8000`。支持配置端口，例如 `https://opendata.example:8443`。只允许根路径，不接受 URL 用户信息、查询参数或片段。 |
| `STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS` | 逗号分隔的精确远端主机白名单。裸主机名对应 HTTPS 443；非标准端口必须写成精确的 `host:port`。回环地址可用于本机开发；非回环 HTTP 会被拒绝。 |

缺少凭证、非法 URL 或远端主机未列入白名单时，归档证据以稳定错误码降级返回。远端 API Key 不会进入 URL；客户端关闭环境代理和自动重定向。

## 请求和报告行为

对每只 A 股，consumer 将代码解析成 `NNNNNN.SH`、`.SZ` 或 `.BJ` 格式；无法明确判定或交易所后缀冲突时拒绝请求。它固定读取 `source_id=ths_fuyao`，分别请求利润表、资产负债表、现金流量表的年报和季报，共六个查询。每次查询的报告期范围从分析日期年份前两年的 1 月 1 日开始，截止分析日；这是分析窗口，不代表完整历史范围。

响应中的 `report_period`、`source_disclosure_date` 和 `observed_at_utc` 保持分开的原始字段；金额以原始十进制文本和来源原生单位保留。分析日筛选仅依据 `report_period`。披露日期晚于分析日的记录仍保留在原始证据中，并标注其与分析日的关系及数量，因此这些记录不能被解释成历史时点可见数据。

成功、部分成功、空结果和不可用分别以 `observed`、`partial`、`empty`、`unavailable` 表示。股票分析快照的 `financials.annual` 与 `financials.quarterly` 在 OpenData 路径下保持为空，原始内容放在 `financials.raw_archive`。生成的分析报告在 `data_sources` 中标记 `opendata:financial_archive`，并在 `source_snapshot` 中保留完整快照，供审阅其来源证据和失败状态。

Pipeline 不把 `raw_archive` 映射为财务特征或送入 AI source context。当前回归用例验证它不会产生基本面分数：基本面分数为 0，信号为 `WATCH`，资格状态为 `degraded`，并记录 `financials_unavailable`。因此，已验证的股票分析 Pipeline 评分和信号不使用这些原始行；回测接入尚未验收，本文不对回测行为作结论。

## 预算和失败处理

- 每个归档查询最多请求一页，`page_size=199`；当前 consumer 不翻页，也不重试。
- 每个响应最多保留 256 KiB JSON，六个查询累计最多保留 1 MiB 响应体；单次请求超时为 8 秒，整个读取最多 30 秒。
- HTTP 413 映射为 `archive_scope_page_limit_exceeded`，该查询失败且不读取错误响应体。没有通过降低结果范围、翻页或改用其他来源进行补偿。
- 超过单响应限制时返回 `response_too_large`；超过累计预算时返回 `archive_response_too_large`，后续查询不再发起。已经成功的查询可以保留，因此结果可能为 `partial`；完整性仍未知。
- 401/403 后停止剩余查询。其他失败使用不包含凭证或响应正文的稳定错误码。
- OpenData 已被显式选中后，任何凭证、权限、网络、服务器、响应或预算错误都不会回退到 AkShare。归档失败会进入报告的数据质量降级原因。

## 语义和验收边界

consumer 要求服务端明确返回 `completeness="unknown"`、`point_in_time_reconstruction="unavailable"` 和 `period_amount_semantics="unknown"`，并将本地证据标记为 `provenance_status="incomplete"`、`normalization_status="unreviewed"`、`eligible_for_decision_or_backtest=false`。观察时间表示去重后的观察时间，不等于采集时间。条目代码、单位、季度累计/单季口径和来源完整性尚未完成统一语义审核。

现有 consumer 测试使用 HTTP mock transport，验证配置默认关闭、请求构造、来源字段保留、报告快照、降级及无 AkShare 回退等行为。这些测试没有访问真实 OpenData API 或生产数据库，也不证明端到端生产凭证、真实 API 授权和网络连通性已经验收。当前窗口不覆盖股票上市以来的全部历史；全 A 股（含退市证券）的来源覆盖、头部/内部/尾部缺口、来源留存限制和完整历史恢复均未验收。未经单独的数据治理和历史完整性验收，不得将这些快照视为完整财报序列或 PIT 数据。

实现位置：`src/backend/app/config.py`、`src/backend/app/services/market_data/opendata_credentials.py`、`src/backend/app/services/stock_analysis/data_collector.py`、`src/backend/app/services/stock_analysis/opendata_financial_archive.py`、`src/backend/app/services/stock_analysis/report_builder.py`。对应回归用例位于 `src/backend/tests/test_stock_analysis_opendata_financial_archive.py`。
