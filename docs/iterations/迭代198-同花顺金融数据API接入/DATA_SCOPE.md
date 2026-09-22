# 迭代 198：同花顺数据域与能力映射

> 本表定义 THS API 各数据域如何映射到迭代 197 已落地的七类资产与 21 个页面主题（family）。
> `THS-*` 为 THS 数据域覆盖项。所有项进入验收清单；S0 逐项登记 `SUPPORTED/LOCAL_ONLY/UNSUPPORTED/PENDING_PROBE/BLOCKED`。
> 现有 family 定义见 `app/services/market_data/dataset_contracts.py`；本迭代不新增 family，只新增 provider 路由（route）。

## 1. 范围规则

1. THS 作为 A 股主源，仅对语义等价的数据域替换或前置 AkShare；不等价或 THS 缺失的域保持 AkShare/OpenBB。
2. THS 历史 K 线当前仅 `1d`，分钟频（`5min/30min/1h`）明确 `UNSUPPORTED`，不能伪造。
3. THS `adjust` 值 `none/forward/backward` 与中台 `unadjusted/qfq/hfq` 需显式映射并核实复权基准，登记进 provider contract 的 `supported_adjustments`。
4. THS 时间窗口（历史 K 线、财务）跨度 ≤ 10 年，缺口规划切块；`code=1003` 是窗口超限而非数据缺失。
5. 输入精确标的不存在是单次请求的 `EMPTY_CONFIRMED/UNSUPPORTED_IDENTITY`，不是整类资产验收失败。
6. 全市场 Parquet 导出（`market-dumps`）是受控批量回填路径，不是页面即时查询路径。

## 2. THS 数据域 → 七类资产主链

| 资产 | THS 可用能力 | 主/备关系 | 语义边界 |
| --- | --- | --- | --- |
| M-STOCK 股票 | 行情快照、历史 K 线（1d/1w/1mo 需核实）、财务、除复权、日历、检索 | THS 主源，AkShare 后备 | `thscode` 完整代码；`adjust` 显式映射；`name` 需检索接口补（估值快照接口亦返回 `name`，见 RESEARCH 5.12） |
| M-INDEX 指数 | 指数行情快照、历史 K 线（`/api/a-share-index/prices/historical`，仅 `1d`、`start`/`end` 必填、**无 `adjust`**——指数无复权语义、窗口 ≤ 10 年，见 RESEARCH 5.13）、同花顺指数列表与成分股 | THS 主源（指数成分股 AkShare 无等价） | `a-share-index` asset_type；成分股清单；指数历史无复权轴 |
| M-FUTURES 期货 | 期货基础资料、持仓、仓单、基差、交易日程、行情 | 需探测，主/备待定 | THS 中国期货合约与 AkShare CFFEX 语义核对 |
| M-BOND 债券 | 无直接可转债价格接口（THS 债券域未在 A 股主干明确） | 保持 AkShare | 不可用 THS 利率数据冒充可转债价格 |
| M-FUND 基金 | 基金资料/持仓/业绩/经理/财务/诊断/募集/资讯/行情；基金在线回测/指标/QDII | 需探测，主/备待定 | ETF 行情与场外 NAV 分开；`manager_id`/`company_id` |
| M-OPTION 期权 | 期权基础资料、分时行情、日 K；期权交易时间轴 | 需探测，主/备待定 | 具体合约与链分开；执行价/到期/方向/乘数 |
| M-FX 外汇 | `forex` asset_type 在检索/列表枚举中，但无明确 FX 行情端点 | 保持 AkShare | 不可用 USDCNH 冒充 USDCNY |
| M-CRYPTO 数字货币 | 无 | 保持 OpenBB | THS 不覆盖数字货币 |

## 3. THS 数据域 → 页面 family（21 主题）

下表仅列 THS 能实质贡献的 family；未列出的 family（如 bond 系列、crypto 系列、option.risk_surface）保持现有来源。

| Family | THS 数据语义 | 映射 provider route | 频率 | 必验内容 |
| --- | --- | --- | --- | --- |
| stock.realtime | 历史 K 线 + 行情快照 | `ths-stock-primary-v1` | `1d`（`1w/1mo` 待核实） | OHLCV/turnover；`adjust` 映射；窗口切块 |
| stock.valuation | THS 有独立估值快照接口（RESEARCH 5.12：`pe_ttm`/`pe_mrq`/`pb_mrq`/`ps_ttm`/`pcf_ttm`，批量上限 100），但**无市值字段**，不满足 family 必需字段（`market_cap`/`float_market_cap`/`pe`/`pb`/`as_of`）；且 197 已将该 family 定为私有 captured-snapshot 数据集（不发起 fetch、不注册 request-time route） | **不新增 route，保持 197 现状**；接入须先变更 197 设计决定并补市值来源，登记为后续增强（P1） | - | 估值接口契约已核实；4.1 路由原则第 4 条（字段不满足）即不路由 |
| stock.liquidity | 快照/历史量额换手 | `ths-stock-liquidity-v1` | `1d` | volume/turnover/turnover_rate |
| futures.realtime | 期货行情 | `ths-futures-primary-v1`（待探测） | `1d` | 中国期货合约语义 |
| futures.settlement | 结算/持仓 | `ths-futures-settlement-v1`（待探测） | `1d` | settle/OI |
| fund.realtime | ETF 行情 | `ths-fund-primary-v1`（待探测） | `1d` | ETF 价格与 NAV 区分 |
| fund.nav | 基金净值 | `ths-fund-nav-v1`（待探测） | `1d` | nav/cumulative_nav |
| option.realtime | 期权行情/日 K | `ths-option-primary-v1`（待探测） | `1d` | 合约 bars |
| fx.realtime / fx.range | THS 无明确 FX 行情 | 不新增 | - | 保持 AkShare |

**新增数据域（超出 21 主题，作为 reference 数据集登记）**：

| 数据集（拟登记） | THS 端点 | data_kind | 说明 |
| --- | --- | --- | --- |
| `market.stock_financials_income` | `/financials/income-statements` | reference_series | 利润表多期序列 |
| `market.stock_financials_balance` | `/financials/balance-sheets` | reference_series | 资产负债表多期 |
| `market.stock_financials_cashflow` | `/financials/cash-flows` | reference_series | 现金流量表多期 |
| `market.stock_financial_indicators` | `/financials/indicators` | reference_series | 五类财务指标 |
| `reference.stock_adjustment_factors` | `/corporate-actions/adjustment-factors` | reference_series | 复权因子事件流 |
| `reference.cn_trading_calendar` | `/a-share/calendar` | reference_series | 交易日历 |
| `catalog.cn_index_constituents` | `/a-share-index` | catalog_table | 指数成分股 |
| `catalog.special_limit_up` | `/special-data` | catalog_table | 涨跌停/热榜/龙虎榜 |

> 注：财务、除复权、日历、指数成分股、特色数据是 THS 相对 AkShare 的核心增量，作为 `reference_series` / `catalog_table` 登记，不强行塞进 OHLCV bars。

## 4. 语义等价与复权映射

| 中台语义 | THS `adjust` | 映射关系 | 核实项 |
| --- | --- | --- | --- |
| `unadjusted` | `none` | 直接对应 | 原始价格口径 |
| `qfq`（前复权） | `forward` | 官方文档已明确 forward=前复权（2026-09-18 核实） | 仅剩复权基准锚定方式（是否以最新价为动态基准）待 golden 对照 |
| `hfq`（后复权） | `backward` | 官方文档已明确 backward=后复权（2026-09-18 核实） | 与 AkShare `hfq` 的数值一致性待 golden 对照 |

**关键**：不能隐式等同。G0 用同一标的（如 `600519.SH`）对 `forward` 与 AkShare `qfq` 做 golden 对照，确认复权基准一致后才登记为等价；否则 THS 复权值作为独立 adjustment 轴，不与 AkShare 混拼。

## 5. 标的身份映射

| THS 概念 | 中台概念 | 映射 |
| --- | --- | --- |
| `thscode`（`600519.SH`） | `provider_symbol` | 直接透传 |
| `ticker`（`600519`） | 展示代码 | 不能单独作主键 |
| `exchange`（`SH`/`SZ`/`BJ`） | venue | 用于 market 归一 |
| `asset_type`（`a-share` 等） | asset_type | 显式映射，不靠正则猜 |
| `name` | 中文名 | 需 `tickers/search` 补，快照不返回 |

## 6. 频率与窗口

| 消费入口 | THS 支持 | 处理 |
| --- | --- | --- |
| 行情页 daily | `1d` 支持 | 主源 |
| 行情页 weekly/monthly | `interval` 仅 `1d`（文档），需核实 `1w/1mo` | 若 THS 不支持则由 `1d` 聚合或回退 AkShare |
| 策略页 1d | `1d` 支持 | 主源 |
| 策略页 1h/30m/5m | 不支持 | `UNSUPPORTED`，保持 AkShare/OpenBB |
| 历史长区间 | 跨度 ≤ 10 年 | 缺口规划切块，`code=1003` 处理 |
| 财务区间 | 跨度 ≤ 10 年 | 同上 |
| 开放式窗口请求（无显式起止） | `historical` 的 `start`/`end` **必填**（无「最近 N 根」模式，RESEARCH 5.2） | 请求变换层先解析为具体窗口（结合日历/本地最新数据）再切块 |
| 多标的批量快照/估值 | `thscodes` 批量上限 **100 token**（RESEARCH 5.1/5.12） | 按 100 切批；历史 K 线单标的单请求，批量补齐须评估限流预算（AC-26） |

## 7. 全市场导出（受控回填）

| dump | 用途 | 触发 | 约束 |
| --- | --- | --- | --- |
| 10 年全量日 K | 全市场历史回填 | 管理员显式回填，预算控制 | 预签名链接 5 分钟有效，即时下载 |
| 近 10 交易日日 K | 增量刷新 | 调度或管理员 | 同上 |
| 复权因子全量 | 复权因子回填 | 管理员 | 独立事件流 schema |

全市场导出不作页面即时路径；下载后经 importer 进入规范层，遵守现有 `md_*` 发布事务与授权。

## 8. S0 能力登记状态

初始状态均为 `PENDING_PROBE`，S0 用真实 API Key 探测后逐项确认；缺权限（`code=2003`）登记 `BLOCKED`，缺真实环境登记 `NOT_RUN`。

| THS 域 | 初始状态 |
| --- | --- |
| 行情快照 | PENDING_PROBE |
| 历史 K 线（1d） | PENDING_PROBE |
| 财务报表 | PENDING_PROBE |
| 财务指标 | PENDING_PROBE |
| 除复权事件流 | PENDING_PROBE |
| 交易日历 | PENDING_PROBE |
| 标的检索/列表 | PENDING_PROBE |
| 指数列表与成分股 | PENDING_PROBE |
| 特色数据（涨跌停/热榜/龙虎榜） | PENDING_PROBE |
| 全市场 Parquet 导出 | PENDING_PROBE |
| 基金/期货/期权域 | PENDING_PROBE |
| 分钟频历史 | UNSUPPORTED（明确不支持） |
