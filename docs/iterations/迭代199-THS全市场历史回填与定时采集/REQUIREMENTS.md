# 迭代 199：需求文档

## 1. 问题与业务目标

迭代 198 打通了 THS 的 provider 与 collector 链路，但数据仍依赖人工触发的一次性 harness。
要让中台真正「本地优先」，必须把 THS 的历史数据**全量落库**并**每日自动更新**，使行情、
财务、除复权、日历、指数成分股在无人工干预下持续保持新鲜。

## 2. 功能需求

| ID | 需求 | 优先级 | 可验收行为 |
| --- | --- | --- | --- |
| FR-01 | 全市场标的主数据批量建立 | P0 | 从 `tickers/list` 拉取 A 股清单并落 identity，供回填解析 |
| FR-02 | `market-dumps` Parquet 下载与解析 | P0 | 取预签名链接、即时下载、解析 Parquet（日 K / 复权因子） |
| FR-03 | 全市场日线全量回填（10 年） | P0 | 日 K Parquet → `md_observation_revisions`，按标的分批 |
| FR-04 | 复权因子全量回填 | P0 | 复权因子 Parquet → `reference.stock_adjustment_factors` |
| FR-05 | 财务三表回填 | P1 | 逐标的 API → 三个财务数据集 |
| FR-06 | 交易日历回填 | P0 | API → `md_calendar_events`（复用 CalendarImporter） |
| FR-07 | 指数成分股回填（catalog） | P1 | 逐指数 API 取数并登记 |
| FR-08 | 每日增量采集（日线） | P0 | `daily-k-10d` Parquet 覆盖近 10 交易日，幂等 |
| FR-09 | 断点续跑 | P0 | 跳过已覆盖（series 已存在且窗口已满）的标的 |
| FR-10 | 限流与熔断 | P0 | 复用 `ThsRateLimiter`，批量在退避预算内完成 |
| FR-11 | 定时调度（每日收盘后） | P0 | APScheduler 注册每日任务，收盘后执行增量 |
| FR-12 | 可观测与审计 | P0 | 每次运行输出结构化结果（标的数/行数/错误码），不泄凭据 |

## 3. 非功能需求

| ID | 需求 | 指标 |
| --- | --- | --- |
| NFR-01 | 回填默认只读 | 未加 `--apply` 不写生产库（dry-run） |
| NFR-02 | 凭据安全 | API Key 不进日志/异常/工件 |
| NFR-03 | 数据库兼容 | MySQL/PostgreSQL/SQLite 不退化（复用 197 store） |
| NFR-04 | 幂等 | 重复运行不产生重复 revision（同 event_at 同 series） |
| NFR-05 | 零 schema 变更 | 复用 md_* 与 calendar 表 |
| NFR-06 | 可中断 | 单标的失败不阻断整批，登记失败码 |

## 4. 迁移与依赖

| ID | 要求 |
| --- | --- |
| MIG-01 | 只新增 importer/回填脚本/调度服务，不改 197 store 与 198 provider 契约 |
| MIG-02 | 复用 `market-dumps`、`ThsReferenceCollector`、`MarketDataCalendarImporter` |
| MIG-03 | 调度复用现有 APScheduler 基础设施，不新建并行调度平台 |

## 5. 完成判定

全量回填与每日增量在真实 THS API + 本地 MySQL 上跑通，调度任务注册且可解释；
不满足的部分登记为具体切片结果，不用 fixture 冒充真实闭环。
