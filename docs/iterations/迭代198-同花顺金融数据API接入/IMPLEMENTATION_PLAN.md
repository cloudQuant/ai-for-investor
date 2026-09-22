# 迭代 198 同花顺接入 Implementation Plan

> **For Codex:** 后续明确启动实现后，使用 executing-plans 技能按任务推进；本文件当前仅为文档交付，不授权开始开发。

**Goal:** 在迭代 197 已落地的数据中台之上，新增 THS 作为 A 股主数据源，复用 provider 抽象，补齐财务/除复权/日历/检索/指数等能力。

**Architecture:** 进程内异步 HTTP adapter 实现 `MarketDataProvider`，复用 197 的 `ProviderContract`/`MarketDataProviderRoute`/`source_policy`/`store`/`publication` 全链路；THS 与 AkShare 为两个独立来源，各有限流/熔断。

**Tech Stack:** Python/FastAPI、httpx（或既有异步客户端）、SQLAlchemy/Alembic、MySQL/PostgreSQL/SQLite、pytest。

---

## 1. 实施前置与任务归属

当前只完成方案，不创建实现分支、不签发 API Key、不运行采集、不改生产库。实施必须在用户后续启动请求后开始；先读取 197 权威状态（[迭代197-本地优先市场数据中台/ACCEPTANCE.md](../迭代197-本地优先市场数据中台/ACCEPTANCE.md)，注意 197 有两个目录，状态以该目录为准）和当前 Git/Alembic 基线，确认 provider 抽象已合入。

**197 未闭合项处置（T0 硬性产出）**：197 整体尚未达发布验收（G2/G3/G4 pending；OpenBB 无 permit/route）。2026-09-18 复核后的分项状态（L-197-42/L-197-43 收据）：
- ✅ **中台闭环硬前置已满足**：`fund.nav`（akshare≥1.18.96 修复 `fund_etf_fund_info_em` 列名 bug 后）与 `fund.liquidity`（上游恢复）各完成一次真实来源 fetch→store→publication→`local_only` 重读完整闭环（一次性 SQLite）。此前建议的硬前置「至少一条真实来源闭环」已达成。
- ✅ E-197-07 双引擎核心 `PASS`（MySQL L-197-41 + PostgreSQL L-197-43，迁移链/UTC/租约/接管故障演练全绿；验收驱动修复 3 个迁移 PG 方言缺陷与 2 个 harness 缺陷）。
- ❌ `stock.liquidity`、`fx.range` 真实探测仍 `FAIL`：东财 push2his/外汇行情端点对本网络持续拒绝连接（上游/网络层，非适配器缺陷）。**THS 作为 A 股主源正是 stock 路线的结构性对策**；fx.range 无 THS 等价（RESEARCH：THS 无明确 FX 行情端点），需更换网络出口或另行评估来源——T0 判定其归属（本迭代内解决/登记递延）。
- ❌ 其余真实环境门保持 `NOT_RUN`：页面灰度三方证据（E-197-06）、真实多 worker 压测（E-197-08）、OpenBB 隔离栈（E-197-05/09，无 permit）、备份恢复演练、ratchet 38 项超限（E-197-15，发布签收 NO-GO，属 194 工程债域）。

T0 须逐项判定上述 ❌ 项哪些是本迭代硬前置、哪些登记递延；判定结论与证据写入 `baseline.json`。

| 责任 | 拥有范围 |
| --- | --- |
| 数据架构/后端 A | THS provider contract、信封归一化、错误码映射、source policy 接线 |
| 后端 B | THS HTTP 客户端、限流/熔断、凭据引用 |
| QA/运维 | 真实 THS API 探测、golden 对照、验收证据 |

## 2. 依赖图

```mermaid
flowchart LR
    T0[T0 基线冻结] --> T1[T1 THS 契约与信封]
    T1 --> T2[T2 HTTP 客户端与鉴权]
    T2 --> T3[T3 主源路由接线]
    T3 --> T4[T4 财务/除复权/日历/检索]
    T4 --> T5[T5 扩展域与全市场导出]
    T5 --> T6[T6 完整验收/灰度]
```

主干顺序：T0 → T1 → T2 → T3 → T4 → T5 → T6。

## 3. 任务包

路径相对仓库根目录；"新增"均为计划路径。

### T0：重新冻结现场与合同（2—3 人天）

**Owner：** 架构 A；协作：QA。

**产出：** 本迭代 `evidence/<run-id>/baseline.json`、`ths-capability-matrix.json`、197 未闭合项处置记录（入 baseline.json）；核对 197 `app/services/market_data/` provider 抽象已合入。

1. 读取 Git/migration head，确认 `provider_models`/`provider_contracts`/`source_policy`/`dataset_contracts` 落地状态。
2. 读取 197 权威 ACCEPTANCE，逐项登记未闭合项（stock.liquidity/fx.range 上游连接拒绝、G2/G3/G4 pending、OpenBB permit、ratchet 超限）并判定是否为本迭代硬前置；确认 2026-09-18 已闭合项（fund.nav/fund.liquidity 真实闭环、E-197-07 双引擎核心）。
3. 签发 THS API Key，登记 credential ref，核对许可/保留/再分发条款（含「服务方代客户环境取数/客户自有 Key」的条款边界，关联 B2B 部署路线）。
4. 真实探测各数据域，填 `ths-capability-matrix.json`；缺权限登记 `BLOCKED`。核对 RESEARCH 补充项：估值接口（5.12）、指数历史（5.13）、100 token 上限、`start/end` 必填。
5. 对 `600519.SH` 做 `forward` vs AkShare `qfq` golden 对照，确认复权基准锚定等价性（映射方向官方已明确 forward=前复权，见 RESEARCH 第 6 节）。
6. 完成 G0。

**退出条件：** THS 各数据域无未归属项；复权等价性有明确结论；许可条款已登记；197 未闭合项处置有明确结论。

### T1：THS 契约与信封归一化（4—6 人天）

**Owner：** A。

**新增：** `app/services/market_data/ths_contracts.py`、`ths_envelope.py`、`ths_errors.py`；`tests/market_data_platform/test_ths_contracts.py`、`test_ths_envelope.py`。

1. 定义 `THS_PROVIDER_CONTRACTS`，新增 `request_transform_id`（`ths.historical-kline-request-v1`、`ths.financials-request-v1`、`ths.symbol-only-request-v1`）、`timestamp_normalizer_id`（`ths.millis-timestamp-normalizer-v1`）、`window_semantics`（闭区间）。
2. 实现 `ApiResponse` 解析与错误码映射（D3.3 表）。
3. 复权映射（D2.3）、时间窗口切块（D2.4，含开放式窗口解析与 100 token 切批）。
4. fixture 测试覆盖 AC-01—AC-08、AC-10—AC-14（AC-09 golden 对照属 T0/G0 真实数据，不在本任务）。

**验收：** AC-01—AC-08、AC-10—AC-14（G1）。

### T2：HTTP 客户端、鉴权与限流（3—5 人天）

**Owner：** B。

**新增：** `app/services/market_data/ths_http.py`、`ths_credentials.py`、`ths_rate_limiter.py`；`tests/market_data_platform/test_ths_http.py`。

1. 实现有界异步 HTTP 客户端（超时、取消、响应体上限）。
2. 凭据引用解析 `X-api-key`，脱敏。
3. 429/4001 退避 + 熔断（分「携带/不携带 `Retry-After`」两分支测试，不依赖该头存在）。
4. 测试 AC-04—AC-08、AC-23。

**验收：** AC-04—AC-08、AC-23（G1）。

### T3：THS adapter 与主源路由（4—6 人天）

**Owner：** A；B 评审。

**新增：** `app/services/market_data/ths_provider.py`；`tests/market_data_platform/test_ths_provider.py`。

**修改：** `app/api/data/queries.py`（`market-default-v1` policy 的 routes 组装点，插入 THS 路由）；`app/services/market_data/capability_ledger.py` 或既有机制（THS route 的 capability definitions 对接）；provider 注册数据路径（`ensure_provider_active` 所需的 `ths` provider 行，含 activation/attestation 的部署步骤说明）。

1. 实现 `ThsProvider`，`fetch(MarketDataProviderRequest) -> ProviderFetchResult`。
2. 在 source policy 中接线 A 股主源（THS 在前，AkShare 后备），受 `supports()` 约束；接线点为 `app/api/data/queries.py`。
3. 按 DESIGN D7 实现完整激活链：provider 注册行 → source authorization grant → capability ledger attestation → `MARKET_DATA_THS_ENABLED` kill-switch；验证缺任一层时路由 fail-closed。
4. 复用 197 `store`/`publication` 完成落库闭环。
5. 测试 AC-15—AC-17。

**验收：** AC-15—AC-17（G2 部分；G3 真实源部分留待 T6）。

### T4：财务/除复权/日历/检索接入（4—6 人天）

**Owner：** A。

**新增：** `app/services/market_data/ths_financials.py`、`ths_reference.py`；`tests/market_data_platform/test_ths_reference.py`。

**修改：** `app/services/market_data/bootstrap.py`（`dg_datasets` 数据集目录登记：`market.stock_financials_*`、`reference.stock_adjustment_factors`、`reference.cn_trading_calendar`、`catalog.*` 等，DATA_SCOPE 第 3 节新增数据集）。

1. 财务多期序列 → reference_series（`period`/`fiscal_period` 维度）。
2. 除复权事件流 → reference_series。
3. 交易日历 → reference_series。
4. 标的检索/列表 → 主数据补全与中文名解析。
5. 测试 AC-11—AC-13、AC-18。

**验收：** AC-11—AC-13、AC-18。

### T5：扩展域与全市场导出（3—5 人天）

**Owner：** B；QA 协作。

**新增：** `app/services/market_data/ths_dump.py`；`tests/market_data_platform/test_ths_dump.py`。

1. 基金/期货/期权域探测登记主/备关系。
2. 特色数据（涨跌停/热榜/龙虎榜）→ catalog_table（P1）。
3. 全市场 Parquet 受控回填 importer。
4. 测试 AC-19—AC-20。

**验收：** AC-19—AC-20。

### T6：完整验收与灰度（3—5 人天，加观察期）

**Owner：** QA/运维。

**新增：** `scripts/acceptance/iteration198_ths.py`、本迭代 evidence。

**修改：** 前端来源标签与失败状态（AC-24：来源标识 THS、限流/权限失败、主备皆败终态的中英文标签；涉及 `src/frontend` 相关页面组件，T0 时核对具体文件）。

1. 跑完 G1/G2 契约与真实 API 流程。
2. 逐项 G3（THS-STOCK-DAILY、FINANCIALS、ADJUSTMENT、CALENDAR、TICKER、INDEX）；AC-24 前端标签、AC-25 审计链路检索。
3. 灰度：先 THS 后备、AkShare 主，验证后调换。
4. 回滚与限流恢复测试（AC-21—AC-22，含激活链各层独立关闭）。
5. 批量补齐容量场景（AC-26：≥300 只 A 股日线缺口，100 token 切批 + 限流预算内完成 + 中断恢复）。
6. 输出逐案例结果与全需求矩阵。

**退出条件：** G0—G4 全部必需门闭合；否则只声明具体切片结果。

## 4. 初始工作量

合计 **20—30 人天**，另预留 30% 风险缓冲，约 **26—39 人天**。这是按单一 provider 接入范围作的规划估计，不是承诺工期。

## 5. PR 与回滚单元

| PR 单元 | 内容 | 回滚粒度 |
| --- | --- | --- |
| P1 | THS 契约/信封/错误码 | 默认关闭，无外部调用 |
| P2 | HTTP 客户端/鉴权/限流 | 关闭 THS，无网络 |
| P3 | adapter + 主源路由 | feature flag 关闭回退 AkShare |
| P4 | 财务/除复权/日历/检索 | 关闭对应 route，保留数据 |
| P5 | 全市场导出/扩展域 | 停回填，保留断点 |

每个 PR 附变更行为、精确文件 diff、G1/G2 证据及未闭合门。

## 6. 当前交接状态

- 已交付：需求、数据域、调研、设计、验收规范和本实施计划（2026-09-18 修订：197 依赖表述校准、估值/指数/批量契约补实、D7 激活链重写、AC-09 门归属修正、新增 AC-23—AC-26）。
- 尚未开始：T0—T6 实施、真实 API 探测、golden 对照、代码测试、采集和部署。
- 必须重新核验：197 权威状态与未闭合项处置（`迭代197-本地优先市场数据中台/`）、THS 许可条款、复权基准锚定等价性、激活链各层与 197 门控的对接、各数据库兼容（本迭代目标零 schema 变更）。
- 本轮源码、依赖、数据库、运行服务不属于修改目标。
