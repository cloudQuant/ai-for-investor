# 迭代 199：THS 全市场历史回填与定时采集

> 状态：设计 + 实施（本次开发）。
> 前置依赖：迭代 198 已落地的 THS provider / reference collector / market-dumps 契约。
> 编制日期：2026-09-19。

## 1. 目标

把同花顺（THS）金融数据 API 的**历史数据全量回填**到本地 MySQL（`backtrader_web` 库的
197/198 中台 `md_*` 规范存储），并建立**每日收盘后自动增量采集**，使中台具备
「一次全量 + 每日增量」的可持续数据供应，不依赖人工触发。

## 2. 现状与缺口

迭代 198 交付了 THS provider（A 股日线主源）、schedule-only reference collector
（财务/除复权）、日历转换、检索归一化，以及 `market-dumps` 预签名下载契约；
但**只有一次性验收 harness**，没有：

- 全市场历史数据的**批量回填**（`market-dumps` Parquet importer 未实现）。
- 全市场标的主数据（identity）的批量建立。
- **定时增量采集**与调度接入。

## 3. 数据域与回填路径

| 数据域 | 全量历史 | 每日增量 | 落库目标 |
| --- | --- | --- | --- |
| A 股日线（全市场 ~5561 只 × 10 年） | `market-dumps/daily-k` Parquet | `market-dumps/daily-k-10d` Parquet | `md_data_series` + `md_observation_revisions`（`market.bars`） |
| 复权因子（全量） | `market-dumps/adjustment-factors` Parquet | 逐标的 API（窗口内） | `reference.stock_adjustment_factors` |
| 财务三表（逐标的） | 逐标的 API（annual，10 年） | 按财报季低频（季度） | `market.stock_financials_{income,balance,cashflow}` |
| 交易日历（全局） | 逐次 API（近一年） | 每日 | `md_calendar_snapshots` + `md_calendar_events`（复用 `MarketDataCalendarImporter`） |
| 指数成分股（catalog） | 逐指数 API | 低频（周） | 取数验证（catalog 快照语义待评估） |

**选择 `market-dumps` Parquet 的理由**：全市场 10 年日线逐标的 API 需 ~5561 次请求，
受 THS 限流约束（退避+熔断）耗时很长；Parquet 一次下载即可覆盖全市场，是官方设计的
全市场回填路径（迭代198 RESEARCH 5.11）。

## 4. 关键约束（实测）

- Parquet 日 K schema：`thscode, currency, interval(1d), adjusted(none), date_ms,
  open_price, high_price, low_price, close_price, volume, turnover`。
- `date_ms` 语义与 API 一致：**交易日 T 的次日亚洲/上海零点**（`date_ms` 上海日期 - 1 天 = 交易日）。
- 预签名链接 **5 分钟有效**（`expires_in_seconds=300`），必须即时下载消费，不持久化链接。
- `daily-k-10d` 实测：5561 只 × 10 交易日 = 55501 行（约 1 MB / 2.6 秒下载）。
- store 单次 provider result 上限 `_MAX_PROVIDER_OBSERVATIONS = 50_000`（一个标的 10 年 ~2400 条，
  远低于上限，可按标的组织批次）。
- store 要求 `context.query.start <= event_at < context.query.end`（全量回填需按窗口分块，
  每块 ≤ 10 年，受 `_MAX_DIRECT_BAR_WINDOWS` 约束）。
- 全市场标的主数据（identity）必须先建立：Parquet 的 `thscode` 需解析为 canonical identity
  才能构造落库 context。

## 5. 阶段与交付物

| 阶段 | 交付物 | 验收 |
| --- | --- | --- |
| S0 前置 | 全市场 identity 批量建立（`ths_tickers` → master data） | 5561 只可解析 |
| S1 Parquet importer | `app/services/market_data/ths_dump_importer.py` | fixture 测试 + 真实 dump 解析 |
| S2 全量回填 | `scripts/backfill_ths_history.py`（日线/复权因子/财务/日历） | 真实回填 + 落库计数 |
| S3 每日增量 | `scripts/collect_ths_daily.py` | 幂等增量 + 复用不重复 |
| S4 调度接入 | `app/services/market_data/ths_scheduler.py` + 启动挂载 | 每日收盘后任务注册 |
| S5 验收 | `scripts/acceptance/iteration199_*.py` + 证据 | 真实闭环 |

## 6. 风险

| 风险 | 应对 |
| --- | --- |
| 全市场回填量大（1300 万条） | 按标的分批，断点续跑（跳过已覆盖） |
| dump 链接 5 分钟时效 | 即时下载，失败重取链接 |
| THS 限流 | 复用 `ThsRateLimiter`（退避+熔断），增量批次受预算约束 |
| identity 前置缺失 | S0 先建全市场主数据，缺失标的跳过并登记 |
| 生产库写入 | 回填脚本默认 `--dry-run`，显式 `--apply` 才写库；调度任务走同一审计链路 |

## 7. 阅读顺序

README → REQUIREMENTS → DESIGN → IMPLEMENTATION_PLAN → ACCEPTANCE
