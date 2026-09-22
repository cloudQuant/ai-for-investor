# 迭代 198：同花顺金融数据 API 接入

> 状态：设计交付（文档阶段）。所有实现、迁移、真实取数与运行验收初始状态均为 `NOT_RUN`。
> 编制日期：2026-09-18。
> 前置依赖：迭代 197 的 provider 抽象与 `md_*` 规范存储代码已合入 dev（`app/services/market_data/`）；197 整体尚未达到发布验收（G2/G3/G4 pending；2026-09-18 复核：`fund.nav`/`fund.liquidity` 已有真实来源完整闭环，`stock.liquidity`/`fx.range` 仍因上游连接拒绝 `FAIL`，E-197-07 双引擎核心已 `PASS`，详见 [迭代197-本地优先市场数据中台/ACCEPTANCE.md](../迭代197-本地优先市场数据中台/ACCEPTANCE.md)——197 状态以该目录为权威）。本迭代在其之上新增第三个 provider，不重建框架；197 未闭合项与本迭代的关系须在 S0/G0 逐项判定（见 T0），否则 S4 真实取数失败时无法区分 THS adapter 缺陷与中台闭环缺陷。

## 1. 目标与建议

在迭代 197 已落地的统一数据中台之上，新增「同花顺金融数据 API」（下文简称 THS API，`https://fuyao.aicubes.cn`）作为 **A 股主数据源**，补齐现有 AkShare / OpenBB 之外的结构化数据能力。THS API 提供经规范化的 REST 接口：行情快照、历史 K 线（日/周/月、前/后复权）、财务报表、除复权事件流、交易日历、标的检索/列表、指数成分股、涨跌停/热榜/龙虎榜等特色数据，以及基金、期货、期权、集合竞价、主力资金、全市场 Parquet 导出等能力。

核心目标：

1. **复用 197 的 provider 框架**：THS 作为第三个 `MarketDataProvider` 适配器接入，遵守 `MarketDataProviderRequest` / `ProviderFetchResult` / `ProviderContract` / `MarketDataProviderRoute` 现有契约，不另起炉灶。
2. **A 股主源**：在 `source_policy` 中，A 股（股票/指数）行情、财务、除复权、日历、标的检索等能力将 THS 排在 AkShare 之前作为主源；AkShare 降为后备。基金/期货/期权等资产按 DATA_SCOPE 逐项登记主/备关系。
3. **纯 HTTP 接入**：THS API 是标准 REST + `X-api-key` 鉴权，无需像 OpenBB 那样做隔离 SDK 子进程。作为进程内异步 HTTP adapter 实现，但 API Key 通过凭据引用（credential ref）管理，绝不明文入库或落日志。
4. **统一响应信封适配**：将 THS 的 `ApiResponse`（`code` / `message` / `request_id` / `data`，毫秒时间戳、`Asia/Shanghai`）归一化为中台的观察/来源证据模型，错误码 `2001/2003/4001` 等映射为结构化来源错误与限流语义。
5. **全市场 Parquet 导出**：将 `market-dumps` 作为受控的全市场回填路径（可选），而非页面即时查询路径。

## 2. 文档导航

| 文档 | 回答的问题 |
| --- | --- |
| [RESEARCH.md](RESEARCH.md) | THS API 的鉴权、信封、错误码、接口分组与字段契约；与现有 AkShare/OpenBB 的差异 |
| [DATA_SCOPE.md](DATA_SCOPE.md) | THS 各数据域如何映射到七类资产与 21 个页面主题；主/备源与语义等价边界 |
| [REQUIREMENTS.md](REQUIREMENTS.md) | 业务目标、功能需求、非功能需求、迁移与依赖要求 |
| [DESIGN.md](DESIGN.md) | THS adapter、HTTP 客户端、鉴权、限流、信封归一化、source policy 接线 |
| [ACCEPTANCE.md](ACCEPTANCE.md) | 如何证明首次取数、二次复用、A 股主源、错误码映射、全市场导出 |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 任务、文件边界、依赖、工期、发布与回滚顺序 |

阅读建议：README → RESEARCH → DATA_SCOPE → REQUIREMENTS → DESIGN → ACCEPTANCE → IMPLEMENTATION_PLAN。

## 3. 范围冻结

- **THS 作为 A 股主源**，覆盖：股票/指数行情快照、历史 K 线、财务报表（利润表/资产负债表/现金流量表/财务指标）、除复权事件流、交易日历、标的检索/列表、指数成分股、涨跌停/热榜/龙虎榜等特色数据。
- **其余资产按需登记**：基金、期货、期权的 THS 能力逐项登记主/备关系，不强行用 THS 替换已有可用功能；不能把 THS「有该模型」解释为「能为七类资产提供等价备用数据」。
- **不支持的功能如实阻断**：THS 历史 K 线当前仅 `1d`（文档声明 interval 仅支持 `1d`），不伪造分钟线；`adjust` 仅 `none/forward/backward`，需与中台的 `qfq/hfq/unadjusted` 显式映射，不得猜测。
- **历史窗口上限 10 年**：`historical` 与 `financials` 的时间区间跨度均不超过 10 年，缺口规划必须切块。
- **API Key 安全**：凭据引用管理，不落库明文、不进日志、不进浏览器响应。
- **限流与 429**：`code=4001` 与 HTTP 429 都视为限流；退避策略**不依赖 `Retry-After`**——THS 官方文档未承诺该头（2026-09-18 实查 `llms-full.txt` 无此表述，官方指引为"降低并发、稍后重试"），若响应携带则遵守之。

本迭代不改写 AkShare 脚本，不删除现有数据功能，不预设 189/196/197 之外的新存储或调度平台。

## 4. 关键架构决定

| 决定 | 原因与结果 |
| --- | --- |
| 复用 197 provider 框架 | THS 是 `MarketDataProvider` 协议的新实现，不新增平行查询/采集路径 |
| THS 为 A 股主源，AkShare 后备 | 在 `MarketDataSourcePolicy.routes` 顺序中体现，路由仍受 `supports()` 精确匹配约束 |
| 进程内异步 HTTP adapter | THS 无重 SDK 依赖，不需隔离 runner；但仍需超时、限流、熔断、可取消 |
| 统一信封归一化 | `code != 0` 映射为结构化错误；`data.item` 归一化为观察；`request_id` 进入来源证据 |
| 凭据引用鉴权 | `X-api-key` 通过 credential ref 注入，worker/adapter 持凭据，业务库不存明文 |
| 全市场 Parquet 走受控回填 | `market-dumps` 预签名链接仅 5 分钟有效，作为后台批量回填，不作页面即时路径 |

## 5. 交付阶段与结束条件

| 阶段 | 核心产出 | 门禁 |
| --- | --- | --- |
| S0 基线与合同 | THS API Key、接口契约冻结、能力矩阵、与 197 provider 契约对齐 | G0 |
| S1 THS 基础接入 | HTTP 客户端、鉴权、信封归一化、错误码映射、限流/熔断 | G1 |
| S2 A 股主源闭环 | 行情/财务/除复权/日历/检索接入 source policy，主备路由 | G1/G2 |
| S3 扩展数据域 | 基金/期货/期权/特色数据/全市场导出逐项登记与实现 | G2 |
| S4 真实验收与灰度 | 真实 API 取数、二次复用、错误码、全市场导出、灰度 | G3/G4 |

阶段可分批开发评审；**完整迭代验收必须覆盖 S0—S4 全部必需项**。本次结束条件仅为设计文档完整、需求到验收可追踪、引用有效；所有实现与运行验收初始状态均为 `NOT_RUN`。

## 6. 主要风险与落实点

| 风险 | 应对与门禁 |
| --- | --- |
| THS 历史仅 `1d`，无法覆盖策略页分钟频 | 能力登记如实阻断，不伪造分钟；分钟仍走现有 AkShare/OpenBB 路径 |
| API Key 权限不足（`code=2003`） | capability 探测前置，未获权能力保持 `BLOCKED` |
| 10 年窗口上限导致长区间缺口 | 缺口规划按 10 年切块，`code=1003` 视为窗口超限而非数据缺失 |
| 全市场 Parquet 预签名链接短时效 | 下载即时消费，不持久化链接；批量回填在链接有效期内完成 |
| THS 与 AkShare 同上游/同语义限流 | 共享限流/熔断需按「真实供应商」区分，THS 是独立来源，不与 AkShare 合并额度 |
| 197 中台闭环真实来源验证不完整 | 2026-09-18 复核：`fund.nav`/`fund.liquidity` 已各有一次真实来源 fetch→store→publication→`local_only` 完整闭环（L-197-42）；但 `stock.liquidity`/`fx.range` 仍因东财行情端点连接拒绝 `FAIL`（上游/网络层），且 G2/G3/G4 整体 pending——THS 主源正是 stock 路线的结构性对策，fx.range 需在 T0 判定归属 |
| THS 路由激活与 197 门控架构不一致的风险 | 197 的路由激活链是 capability ledger durable attestation + provider active 注册 + source authorization grant（环境变量/浏览器不可铸造），非单一 settings flag；本迭代 flag 只能作叠加 kill-switch，见 DESIGN D7 |
| AkShare 后备可靠性有限 | 197 证据显示 AkShare 真实探测存在间歇空返回/字段漂移/端点连接拒绝（2026-09-18 复核：fund 系恢复、stock/fx 系仍拒绝）；「THS 失败回退 AkShare」是尽力而为，页面最终态须能表达「主备皆败」并给出原因码 |

> 注：THS API 由同花顺提供（文档站点 `fuyao.aicubes.cn`）。其使用许可、数据保留与再分发权限须在 G0 依据 THS 实际条款核对，不能因「进程内 HTTP」而推定许可结论。
