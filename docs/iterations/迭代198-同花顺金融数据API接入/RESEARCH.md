# 迭代 198：同花顺金融数据 API 调研

> 本文为 THS API 的调研结论，作为后续 DATA_SCOPE / DESIGN 的依据。
> 调研时间：2026-09-18；来源：`https://fuyao.aicubes.cn/docs/api-reference/overview/` 与 `https://fuyao.aicubes.cn/llms-full.txt`。

## 1. 概览

同花顺金融数据 API 是面向 AI Agent / 量化研究 / Fintech 应用的结构化金融数据服务，通过 REST 接口提供能力，其中已注册的公开能力同时通过 MCP Tools 暴露。核心特征：

- **Base URL**：`https://fuyao.aicubes.cn`
- **鉴权**：请求头 `X-api-key: <your-api-key>`，缺失/无效返回 `code=2001`，无权访问 capability 返回 `code=2003`
- **标的标识**：股票/指数/基金使用完整 `thscode`（如 `600519.SH`），不接受纯代码 `ticker`（如 `600519`）
- **时间戳**：毫秒级 Unix 时间戳（`long`），时区 `Asia/Shanghai`
- **字段风格**：snake_case，显式 `currency`，价格原始货币计价（A 股恒为 `CNY`）
- **设计原则**：LLM-friendly schema、统一响应信封、路径分层、原始数据为主

## 2. 统一响应信封

所有业务结果（含业务错误）通常返回 HTTP 200，业务结果经响应信封的 `code` 字段表达；触发限流时可能返回 HTTP 429。

```json
{
  "code": 0,
  "message": "success",
  "request_id": "a1b2c3d4e5f6789012345678abcdef01",
  "data": {
    "timestamp": 1716105600000,
    "item": []
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | integer | 业务结果码，`0` 成功，非 `0` 业务错误 |
| `message` | string | 结果描述 |
| `request_id` | string | 请求追踪 ID |
| `data` | object \| null | 业务数据容器，错误时可能为 `null` |
| `data.timestamp` | long | 数据时间戳（毫秒） |
| `data.item` | array | 业务数据列表 |

**关键**：客户端须同时检查 HTTP 状态码与信封 `code`；HTTP 429 无论信封如何都按限流处理。

## 3. 错误码

| code | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 | - |
| `1001` | 缺少必填参数 | `start`/`end`/`q`/`thscode` 漏传 |
| `1002` | 参数格式错误 | `thscode` 含逗号、日期格式错误 |
| `1003` | 参数取值越界 | 枚举非法、`limit <= 0`、历史查询窗口超 10 年 |
| `1004` | 参数冲突 | `financials` 同时传 `start`/`end` 与 `limit`；半开区间 |
| `2001` | 未认证 | `X-api-key` 缺失或无效 |
| `2003` | 权限不足 | API Key 无权调用该 capability |
| `3001` | 标的不存在 | 找不到目标标的 |
| `3002` | 数据未就绪 | 标的存在但暂无业务数据 |
| `3004` | 标的类型不支持该能力 | 标的类型不支持所请求能力 |
| `4001` | 频率超限 | 超过约定 QPS |
| `5001` | 服务内部错误 | 服务端未知错误 |
| `5002` | 上游服务超时 | 数据源响应超时 |
| `5003` | 数据源不可用 | 上游暂时不可用/返回失败/无法按契约解析 |

## 4. 接口分组

| 分组 | 路径前缀 | 说明 |
| --- | --- | --- |
| 价格数据 | `/api/a-share/prices` | A 股行情快照与历史 K 线 |
| 估值数据 | `/api/a-share/valuations` | A 股多股票最新估值快照（PE TTM/MRQ、PB MRQ、PS TTM、PCF TTM，含 `name`，批量上限 100） |
| 指数行情 | `/api/a-share-index/prices` | 指数行情快照与历史 K 线（仅 `1d`，无 `adjust`——指数无复权语义，`start`/`end` 必填，窗口 ≤ 10 年） |
| 主力资金 | `/api/a-share/capital-flow` | 主力资金实时快照与历史（后续接入 AI 客户端） |
| 高频动向 | `/api/a-share/high-frequency` | 个股/指数高频历史与单日分时（后续接入 AI 客户端） |
| 全市场导出 | `/api/dump/market-dumps`（API Key） | 全 A 股 10 年日 K、近 10 交易日日 K、复权因子 Parquet |
| 标的检索 | `/api/meta/tickers/search` | 按 thscode/ticker/名称跨市场检索 |
| 标的列表 | `/api/meta/tickers/list` | 按资产类型分页获取代码表 |
| 基金 | `/api/fund` | 基金资料/持仓/业绩/经理/财务/诊断/募集/资讯/行情 |
| 基金在线回测 | `/api/fund/backtest` | 执行基金在线回测并查询指标 |
| 基金通用指标 | `/api/fund/indicators` | 画线式与表格式指标 |
| QDII 额度 | `/api/fund/quota` | QDII 分类额度汇总与基金列表 |
| 期货总览 | `/api/futures` | 期货基础资料/持仓/仓单/基差/交易日程/行情 |
| 期货扩展资料 | `/api/futures` | 品种板块/主连/主力/次主力/商品指数合约（后续接入） |
| 期货 F10 宏观 | `/api/futures/fundamentals` | 期货 F10 宏观指标历史（后续接入） |
| 期货交易时间轴 | `/api/futures/calendar/session-timeline` | 合约最近交易日交易时间轴（后续接入） |
| 期权总览 | `/api/options` | 期权基础资料/分时行情/日 K |
| 期权交易时间轴 | `/api/options/calendar/session-timeline` | 期权合约最近交易日交易时间轴（后续接入） |
| 除复权 | `/api/a-share/corporate-actions` | A 股复权因子事件流（分红/送股/配股） |
| 财务报表 | `/api/a-share/financials` | 利润表/资产负债表/现金流量表多期序列 |
| 财务指标 | `/api/a-share/financials/indicators` | 成长/盈利/偿债/营运/现金流五类指标 |
| 交易日历 | `/api/a-share/calendar/trading-days` | A 股近一年交易日序列 |
| 集合竞价 | `/api/a-share/auction` | 集合竞价快照与竞价基准 |
| 特色数据 | `/api/a-share/special-data` | 涨跌停/热榜/异动原因/龙虎榜 |
| 指数列表与成分股 | `/api/a-share-index/catalog/ths-index-list`、`/api/a-share-index/constituents/ths-stock-list` | 同花顺指数列表与成分股（含沪深 300 等标准指数） |

## 5. 核心接口契约（本迭代重点）

### 5.1 行情快照 `GET /api/a-share/prices/snapshot`

- 参数：`thscodes`（逗号分隔，给定时按序批量取数、不分页）、`limit`（默认 100）、`offset`（默认 0）
- **批量上限**：`thscodes` 单次请求最多 **100 个原始 token**（去重前校验，服务端配置不可覆盖）；超过返回 `code=1003`。批量补齐须按 100 切批
- 响应 `data.item[]` 字段：`thscode`、`ticker`、`last_price`、`price_change`、`price_change_ratio_pct`、`open_price`、`high_price`、`low_price`、`prev_price`、`volume`、`turnover`
- 注意：快照不返回中文名 `name`，需配合 `tickers/search` 或 `tickers/list` 解析（估值快照接口返回 `name`，见 5.12）

### 5.2 历史 K 线 `GET /api/a-share/prices/historical`

- 参数：`thscode`（必填，每次仅一个，不接受逗号）、`interval`（当前仅 `1d`）、`start`/`end`（**均为必填**毫秒戳，闭区间 `[start,end]`，`end-start` 超 10 年返回 `code=1003`）、`adjust`（`none`/`forward`/`backward`，默认 `forward`）
- 响应 `data.item[]`：`date_ms`、`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`turnover`

**关键约束**：历史 K 线仅支持日线 `1d`；窗口跨度 ≤ 10 年；单请求单标的；**仅支持时间区间模式（`start`/`end` 必填），无「最近 N 根」模式**——中台开放式窗口请求须在请求变换层先解析为具体窗口再切块。

### 5.3 除复权 `GET /api/a-share/corporate-actions/adjustment-factors`

- 参数：`thscode`（单标的）、`from`/`to`（`YYYY-MM-DD`，可选）
- 响应 `data`：`thscode`、`ticker`、`item[]`（`ticker`、`ex_date_ms`、`dividend_per_share`、`per_share_bonus`，按 `ex_date_ms` 降序）
- 注意：不返回 `event_type`/`record_date`/`adjust_factor`，事件类型由 `dividend_per_share` 与 `per_share_bonus` 隐式区分；复权因子需调用方自行推导

### 5.4 财务报表 `GET /api/a-share/financials/*`

三个接口（`income-statements` / `balance-sheets` / `cash-flow-statements`）入参契约一致：

- 取数模式二选一（互斥）：
  - 最近 N 期：不传 `start`/`end`，返回最近 `limit` 期（默认 4，范围 `[1,20]`），按 `period_end` 降序
  - 时间区间：同时传 `start`+`end`（毫秒戳），返回闭区间全部报告期，跨度 ≤ 10 年
  - 同时传 `start`/`end` 与 `limit` 或半开区间 → `code=1004`
- 共有参数：`thscode`（单标的）、`period`（`annual`/`quarterly`，默认 `annual`）、`limit`、`start`、`end`
- 共有响应元数据：`thscode`、`ticker`、`period`、`fiscal_year`、`fiscal_period`、`report_date_ms`、`period_end_ms`、`currency`
- 金额单位原币元，`basic_eps` 元/股；`null` 表示「该期未披露」，透传不补零

### 5.5 财务指标 `GET /api/a-share/financials/indicators`

- A 股成长、盈利、偿债、营运、现金流五类财务指标

### 5.6 交易日历 `GET /api/a-share/calendar/trading-days`

- A 股近一年交易日序列（固定窗口 `[今日-1 年, 今日]`，无请求参数），返回 `date_ms`（毫秒戳）与 `date`（`yyyyMMdd`）

### 5.7 标的检索 `GET /api/meta/tickers/search`

- 参数：`q`（必填，支持子串）、`exchange`（可选）、`asset_type`（可选，单值或逗号多值）、`limit`（默认 10，最大 50）
- `asset_type` 枚举：`a-share`、`a-share-index`、`fund-otc`、`fund-etf`、`fund-lof`、`fund-reits`、`forex`、`futures`、`options`
- 响应 `item[]`：`thscode`、`ticker`、`name`、`exchange`、`asset_type`、`currency`、`list_date`、`end_date`、`last_trade_date`、`last_delivery_date`

### 5.8 标的列表 `GET /api/meta/tickers/list`

- 参数：`asset_type`（可选，逗号多值，省略返回全部）、`limit`（默认 1000，最大 10000）、`offset`（默认 0）
- 分页取尽判定：`item.length < limit`

### 5.9 指数列表与成分股

- 指数列表 `GET /api/a-share-index/catalog/ths-index-list`：参数 `tag`（白名单 `cn_concept`/`region`/`tszs`/`industry`，默认 `cn_concept`），单 `tag` 全量返回，无分页。
- 指数成分股 `GET /api/a-share-index/constituents/ths-stock-list`：参数 `thscode`（单指数，不接受逗号，`trim().toUpperCase()` 标准化），返回当前成分股清单；支持同花顺板块指数（`886042.TI`）与标准指数（`000300.SH`/`399300.SZ`）。
- 指数行情快照 `GET /api/a-share-index/prices/snapshot`：参数 `thscodes`（**必填**，逗号分隔），不支持空入参枚举全指数。
- 指数历史 K 线 `GET /api/a-share-index/prices/historical`：仅 `1d`，`start`/`end` 必填毫秒戳，窗口 ≤ 10 年，**无 `adjust`**（指数无复权语义）。

### 5.10 特色数据 `GET /api/a-share/special-data`

- 涨跌停数据、同花顺热榜、个股异动原因与龙虎榜

### 5.11 全市场导出 `/api/dump/market-dumps`（API Key 路径 `/api/dump/market-dumps`）

| dump | dump_id | 下载端点 |
| --- | --- | --- |
| 10 年全量日 K | `a_share_daily_k_1d_none_10y` | `GET /api/dump/market-dumps/daily-k/download-url` |
| 最近 10 交易日日 K | `a_share_daily_k_1d_none_10d` | `GET /api/dump/market-dumps/daily-k-10d/download-url` |
| 复权因子全量 | `a_share_adjustment_factors_event_none_all` | `GET /api/dump/market-dumps/adjustment-factors/download-url` |

- 下载端点返回 `data.presigned_url`（短时有效，通常 `expires_in_seconds=300` 即 5 分钟）与 `presigned_url_expires_at`，不可持久化缓存；需在每次下载前重新获取链接
- Parquet 日期时间为毫秒戳，交易日期按 `Asia/Shanghai`；A 股价格 `CNY`
- 日 K 列：`thscode`、`currency`、`interval`（`1d`）、`adjusted`（`none`）、`date_ms`、`open_price`/`high_price`/`low_price`/`close_price`、`volume`、`turnover`
- 复权因子列：`thscode`、`ticker`、`ex_date_ms`、`dividend_per_share`、`per_share_bonus`、`allotment_ratio`、`allotment_price`、`currency`

### 5.12 估值快照 `GET /api/a-share/valuations/snapshot`（2026-09-18 补充核实）

- A 股多股票**最新**估值快照；不提供历史估值、分页、指标选择或高低估结论
- 参数：`thscodes`（逗号分隔，**批量上限 100 个原始 token**，服务端 trim/转大写/去重/保序）
- 响应 `data.item[]`：`thscode`、`ticker`、`name`（本地代码表中文名，可为 `null`）、`pe_ttm`、`pe_mrq`、`pb_mrq`、`ps_ttm`、`pcf_ttm`
- 上游空值返回 `null` 不补零；负值原样返回；无匹配记录返回 `code=0`、`total=0`、`item=[]`
- **边界**：该接口**不含市值字段**（`market_cap`/`float_market_cap` 均无；流通市值仅在集合竞价接口出现），且 PE 口径为 TTM/MRQ 双口径而非单一 `pe`——与中台 `stock.valuation` family 的必需字段（`market_cap`、`float_market_cap`、`pe`、`pb`、`as_of`）不满足，按 4.1 路由原则不得路由；接入需先变更 197 对该 family 的 captured-snapshot-only 设计决定

### 5.13 指数行情 `GET /api/a-share-index/prices/*`（2026-09-18 补充核实）

- 指数快照 `snapshot`：字段结构与 A 股行情快照一致
- 指数历史 K 线 `historical`：`thscode`（单标的，不接受逗号）、`interval`（仅 `1d`）、`start`/`end`（**必填**毫秒戳，窗口 ≤ 10 年，超限 `code=1003`）；**无 `adjust` 参数**（指数无复权语义）、无 `offset`
- 支持标准指数（如 `000001.SH` 上证综指）与同花顺概念指数（如 `886042.TI` 白酒概念）

## 6. 与现有来源的差异分析

| 维度 | AkShare | OpenBB | THS API |
| --- | --- | --- | --- |
| 接入形态 | 同步 SDK，隔离子进程 runner | SDK + 隔离子进程 runner | 纯 HTTP REST，进程内异步 |
| 鉴权 | 无（公开源） | provider 各自 | `X-api-key` 单一凭据 |
| 响应格式 | DataFrame，中文字段 | OBBject / DataFrame | 统一信封 + snake_case JSON |
| 时间戳 | 各接口不一 | 各 provider | 统一毫秒戳 + Asia/Shanghai |
| 复权 | `adjust`（qfq/hfq/空） | provider 相关 | `adjust`（none/forward/backward） |
| 历史频率 | 日/周/月为主 | provider 相关 | 当前仅 `1d` |
| 财务/除复权 | 部分能力 | 弱 | 结构化多期序列 + 事件流 |
| 全市场批量 | 需逐脚本 | - | Parquet 预签名导出 |

**核心结论**：
1. THS 在「结构化财务数据」「除复权事件流」「统一信封」「毫秒时间戳」上优于 AkShare 的 DataFrame 抓取，适合作为 A 股主源。
2. THS 历史 K 线仅 `1d`，是明确的频率短板，分钟频必须保留 AkShare/OpenBB 路径。
3. THS 的 `adjust`（`forward`/`backward`/`none`）与中台语义 `qfq`/`hfq`/`unadjusted` 存在映射关系：**官方文档已明确 `forward`=前复权、`backward`=后复权**（2026-09-18 核实），映射方向不再待定；仍需 golden 对照核实的仅剩**复权基准锚定方式**（THS 前复权是否以最新价为动态基准），验证前不得与 AkShare `qfq`/`hfq` 混拼。

## 7. 鉴权与许可要点

- API Key 在文档站「API Key 管理」页签发，与同花顺账号绑定；完整 Key 仅签发时可见一次。
- `code=2001` 缺失/无效 Key，`code=2003` 权限不足 —— 需在 capability 探测阶段区分。
- 当前不限制累计调用次数，但需控制并发与频率；HTTP 429 与 `code=4001` 均表示限流，需降低并发、避免立即连续重试。**官方文档未承诺 `Retry-After` 响应头**（2026-09-18 实查 `llms-full.txt` 全文无此表述），退避策略不得依赖该头存在；若响应实际携带则遵守之。
- MCP 接入复用同一 API Key（`API_KEY` 环境变量）；本迭代仅用 REST，不引入 MCP。

**许可核对（G0 必做）**：THS 数据的保留、再分发、研究与导出权限须依据同花顺实际条款核对，登记进 `AssetDataSourceRegistry` 的 `allowed_uses` / `retention_policy` / `redistribution_policy`，不能因「进程内 HTTP」而推定许可结论。
