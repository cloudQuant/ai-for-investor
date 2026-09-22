# 迭代 198：需求文档

> 状态：设计基线。优先级 P0 为完整迭代必须实现并验收；P1 为后续增强。
> 已确认：THS 作为 A 股主源，覆盖全部 REST 能力；具体边界以 [DATA_SCOPE.md](DATA_SCOPE.md) 为准。
> 前置：迭代 197 已落地的 provider 框架（`provider_models` / `provider_contracts` / `source_policy` / `dataset_contracts`）。

## 1. 问题与业务目标

迭代 197 已建立统一数据中台，但 A 股数据仍主要依赖 AkShare 的 DataFrame 抓取，缺乏结构化、可审计、统一信封的数据源。同花顺金融数据 API 提供规范化 REST 接口（统一 `ApiResponse` 信封、snake_case 字段、毫秒时间戳），并在财务、除复权、交易日历、指数成分股、特色数据等 AkShare 相对薄弱的领域有显著增量。

迭代 198 的目标：在不重建中台框架的前提下，新增 THS 作为 A 股主数据源，复用 197 的 provider 抽象与本地优先/缺口补齐/持久化闭环，使 A 股行情、财务、除复权、日历、检索等能力走 THS 主源，AkShare 降为后备，同时保留分钟频等 THS 不覆盖的能力走原路径。

## 2. 用户与核心旅程

| 用户 | 旅程 | 可观察结果 |
| --- | --- | --- |
| 行情查看者 | 选择 A 股/指数/时间 → 查询 | THS 本地满足时直接返回，来源标识 THS，复权/窗口正确 |
| 行情查看者 | 查询财务/除复权/日历 | 结构化多期序列或事件流，字段可解析 |
| 策略研究者 | 准备 A 股日线数据 → 预检 → 运行 | THS 日线经 ensure/工件，与 197 相同冻结/重放契约 |
| 数据管理员 | 查看 THS 缺口/限流/权限失败 → 修复 | 错误码（2001/2003/4001）映射为可解释状态，可重试 |
| 运维人员 | THS 限流或 API Key 失效 | 429 遵守 Retry-After，本地数据仍可读，故障有原因码 |

## 3. 基本术语

- **THS provider**：实现 `MarketDataProvider` 协议的进程内异步 HTTP adapter，`provider="ths"`。
- **信封归一化**：将 THS `ApiResponse`（`code`/`message`/`request_id`/`data`）转为 `ProviderFetchResult` 与结构化错误。
- **A 股主源**：在 `MarketDataSourcePolicy.routes` 中 THS 路由排在 AkShare 之前，但仍受 `supports()` 精确匹配约束。
- **复权映射**：THS `none/forward/backward` 与中台 `unadjusted/qfq/hfq` 的显式、经 golden 对照验证的对应关系。
- **全市场导出**：THS `market-dumps` 预签名 Parquet 下载，作为受控批量回填路径。

## 4. 功能需求

| ID | 需求 | 优先级 | 可验收行为 |
| --- | --- | --- | --- |
| FR-01 | THS HTTP adapter 实现 `MarketDataProvider` | P0 | `fetch(MarketDataProviderRequest) -> ProviderFetchResult`，不写存储 |
| FR-02 | `X-api-key` 鉴权与凭据引用 | P0 | 凭据经 credential ref 注入，不落库明文/日志/响应 |
| FR-03 | 统一信封归一化 | P0 | `code==0` 取 `data.item`；`code!=0` 映射结构化错误；`request_id` 进来源证据 |
| FR-04 | 错误码映射 | P0 | 2001/2003/3001/3002/3004/4001/5001/5002/5003 → 稳定原因码，不重试不可重试错误 |
| FR-05 | 限流与 429 处理 | P0 | HTTP 429 与 `code=4001` 都按限流；退避不依赖 `Retry-After`（官方未承诺该头，携带则遵守）；熔断 |
| FR-06 | THS 作为 A 股主源 | P0 | stock/fund(ETF)/index 行情与财务/除复权/日历/检索路由 THS 在前，AkShare 后备 |
| FR-07 | 复权映射与 golden 对照 | P0 | `forward`≈`qfq`、`backward`≈`hfq` 经真实数据对照验证后才等价；否则独立 axis |
| FR-08 | 频率如实阻断 | P0 | `1d` 支持；分钟频 `UNSUPPORTED`，不伪造；`1w/1mo` 能力探测后登记 |
| FR-09 | 10 年窗口切块 | P0 | 历史/财务跨度 > 10 年自动切块；`code=1003` 不误判为数据缺失 |
| FR-10 | 财务多期序列接入 | P0 | 利润表/资产负债表/现金流量表/指标 → reference_series，`period`/`fiscal_period` 保留 |
| FR-11 | 除复权事件流接入 | P0 | `adjustment-factors` → reference_series，`ex_date_ms` 时间语义正确 |
| FR-12 | 交易日历接入 | P0 | `calendar` → reference_series，`date_ms`+`date` 双字段 |
| FR-13 | 标的检索/列表接入 | P0 | `tickers/search`/`list` 用于主数据补全与中文名解析 |
| FR-14 | 指数列表与成分股 | P0 | `a-share-index` → catalog_table，成分股清单 |
| FR-15 | 特色数据接入 | P1 | 涨跌停/热榜/龙虎榜 → catalog_table |
| FR-16 | 全市场 Parquet 受控回填 | P1 | `market-dumps` 下载后 importer 进规范层，遵守发布事务与授权 |
| FR-17 | 基金/期货/期权域探测 | P0 | 逐项探测并登记主/备关系，不强行替换已有功能 |
| FR-18 | 复用本地优先闭环 | P0 | THS 取数后落库、二次复用不联网；与 197 `store`/`publication` 一致 |
| FR-19 | 可观测性与审计 | P0 | THS 调用、`request_id`、限流、权限失败全链可追踪：审计事件含 `request_id`/错误码/路由 ID，可按 `request_id` 检索（AC-25） |
| FR-20 | 灰度与回滚 | P0 | THS 默认关闭：未获 capability ledger attestation、provider 未注册 active、source authorization 未授予时路由不生效（复用 197 门控链，见 DESIGN D7）；`MARKET_DATA_THS_ENABLED` 仅作叠加 kill-switch；回退 AkShare 不删 THS 数据，页面能表达「主备皆败」及原因码 |

### 4.1 THS 主源路由原则

THS 仅在语义等价时前置 AkShare。判定顺序：

1. 身份（`thscode`）、市场、资产类型一致；
2. 复权口径经 golden 对照验证等价；
3. 频率 THS 原生支持（`1d`）；
4. 字段满足 family 的 `required_fields`。

任一不满足则回退 AkShare 或保持原路径；不能因「THS 排在前」而用不等价数据冒充。

### 4.2 错误与限流语义

- `code=2001`（未认证）、`code=2003`（权限不足）为**不可重试**错误，立即失败，不浪费重试预算。
- `code=1001/1002/1003/1004`（参数问题）为**请求构造错误**，应在 adapter 请求变换阶段前置校验，不应发送到上游。
- `code=3001/3002/3004`（标的问题）为领域结果，映射为 `EMPTY_CONFIRMED`/`DATA_NOT_READY`/`UNSUPPORTED_IDENTITY`。
- `code=4001`（限流）与 HTTP 429 等效，指数退避，触发熔断；**退避不依赖 `Retry-After`**——THS 官方文档未承诺该头（2026-09-18 实查），若响应实际携带则遵守之。
- `code=5001/5002/5003`（服务端/上游）为暂时性错误，可限次重试。
- THS `historical`/`financials` 之外须注意：`historical` 的 `start`/`end` 必填（无「最近 N 根」模式），`thscodes` 批量接口单次上限 100 token——请求构造层负责窗口解析与切批，越界参数（`1003`）应在本地前置拦截。

### 4.3 数据质量与时间

- 毫秒时间戳统一转 UTC，保留 exchange timezone（`Asia/Shanghai`）与 `trading_date`。
- 财务 `null` 字段透传不补零；`basic_eps` 元/股不与金额字段单位换算。
- 除复权事件按 `ex_date_ms` 降序，事件类型由 `dividend_per_share`/`per_share_bonus` 隐式区分，保留该语义。
- 快照不返回 `name`，中文名经 `tickers/search` 补全，不冒充快照自有字段。

## 5. 非功能需求

| ID | 需求 | 指标 |
| --- | --- | --- |
| NFR-01 | HTTP 客户端有界 | 单请求超时默认 20s；可取消；响应体大小上限（AC-23） |
| NFR-02 | 限流与熔断 | 429/4001 退避不依赖 `Retry-After`（携带则遵守）；连续 5 次暂时失败触发 60s 熔断；多标的批量补齐在限流预算内完成（AC-26） |
| NFR-03 | 复用不联网 | 首次成功后重复查询及重启后外部调用 = 0（复用 197 闭环） |
| NFR-04 | 凭据安全 | API Key 不出现在日志/异常/浏览器/工件 |
| NFR-05 | 运行环境兼容 | 主应用 MySQL/PostgreSQL/SQLite 支持不退化（复用 197；本迭代目标零 schema 变更） |
| NFR-06 | 前端可用性 | 来源标识（THS）、限流/权限失败状态、主备皆败终态有中英文标签（AC-24） |

## 6. 迁移与依赖要求

| ID | 要求 |
| --- | --- |
| MIG-01 | 只新增 THS adapter、provider contract、source policy route、source registry 行；不改写 AkShare 脚本与 legacy 表 |
| MIG-02 | 复用 197 的 `md_*` 规范存储、发布事务、覆盖、快照，不另建平行存储 |
| MIG-03 | THS source registry 行登记许可/保留/再分发，G0 按 THS 实际条款核对 |
| MIG-04 | feature flag 默认关闭，灰度后逐项启用；回退不删 THS 已落库数据 |

## 7. 明确的后续增强（P1）

- 估值快照接入（THS `/api/a-share/valuations/snapshot` 契约已核实，但无市值字段且 197 将 `stock.valuation` 定为私有 captured-snapshot 数据集；接入须先变更 197 设计决定并补市值来源，见 DATA_SCOPE 第 3 节）
- 基金在线回测/指标/QDII 额度接入
- 期货 F10 宏观、交易时间轴接入
- 期权交易时间轴接入
- 全市场 Parquet 定时回填调度
- MCP 工具接入（当前仅 REST）

本次不实现：高频逐 tick、分钟频历史、MCP 客户端集成、THS AI 客户端能力。

## 8. 完成判定

需求全部映射到设计与具名验收，见 ACCEPTANCE 追踪矩阵。文档通过只代表具备进入实施评审基础；实施条件仍由 G0 现场核验，运行验收分别计算 G1—G4，不能用编译通过、HTTP 200、fixture 数据替代真实 THS API 数据闭环。
