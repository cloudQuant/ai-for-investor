# AFI 消费者边界与切换验收

## 已实现的消费边界

`MARKET_DATA_OPENDATA_ENABLED=True` 现在表示 **OpenData-only source policy**。selector 只注册 `opendata-stock-daily-v1`；此时不会注册或构造 THS、AkShare、OpenBB 候选路由。数据集、市场、字段语义或频率与该路由不匹配时，不会选另一个供应商。此路由当前只覆盖中国沪深股票日线，不代表其余资产类别和频率已迁完。

`MARKET_DATA_OPENDATA_ENABLED=False` 仍组装现有 legacy provider policy，是显式过渡模式。配置默认值在本次保持原值，因此部署还没有自动切换到 OpenData-only；此标志为 False 不能作为迁移验收证据。source-policy 仍需通过现有 capability ledger、provider registry 和来源授权检查后才允许联网。

OpenData-only 模式缺少 `OPENDATA_API_KEY` 时，selector 仍选择真实 `OpendataProvider`。适配器在发送 HTTP 请求前抛出稳定错误 `OPENDATA_CREDENTIAL_MISSING`，API 返回 HTTP 503 和同名错误码，不把凭据或其值放进响应。普通无 key 的 `OpendataProvider.from_environment()` 仍保留原有 `None` 行为，只有 OpenData-only selector 显式要求配置错误实例。客户端没有伪造 key。

已验证频率只有 `1d`。selector 的 OpenData policy 对 `1w` 返回空路由集合，policy 中不存在 AkShare/THS/OpenBB 后备；OpenData-only HTTP 查询在调用服务前对非日频返回 422 `OPENDATA_FREQUENCY_UNSUPPORTED`，适配器本身也在发 HTTP 前拒绝未支持频率。已有 AFI 本地持久化结果仍属于 AFI 研究读模型；source 授权按当前 policy 的 OpenData route 收窄可读来源。此改动没有将旧市场数据表或其历史来源声明批量重写。

API 统一请求的 singleflight 键由事件循环、query fingerprint、主体、租户和 entitlement revision 组成。它只合并当次 loop 内的并发请求，并在完成后删除，没有持久结果缓存；目前不存在跨 source policy 或 rollout epoch 复用缓存的问题。若后续引入持久/多层缓存，缓存身份必须包含已审查的 source policy/route epoch 和 publication/snapshot 版本。

## 可复算的静态盘点

扫描器 `src/backend/app/services/market_data/consumer_boundary.py` 只解析 Python AST，不导入、不运行待扫描项目代码。它覆盖 `src/backend/app/` 与 `src/backend/scripts/`，列出来源 SDK import/call、数据仓库连接/写入痕迹、本地数据文件 I/O、逐行位置和可静态解析的函数调用边。测试还用临时小仓库验证 `router handler → imported service → aliased AkShare call` 的静态调用链。运行时依赖注入、协议分派、装饰器注册、动态 SQL、拼接路径以及 Python 以外的配置不能由此扫描器证明。

扫描日期：2026-10-26。下面的计数是 **AST 命中次数**，不是唯一数据集、任务、实际运行次数或成功迁移数。

| 输入快照 | Python 文件 | 解析错误 | 命中 | 可解析调用边 | API 入口 | 静态连到 source/database/file sink 的入口 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 本迭代消费者 worktree（基于 `ae1ed034d`，含本项改动，分支 `codex/od204-wave2-consumers`） | 1,875 | 0 | 2,261 | 24,497 | 563 | 0 |
| 原始 AFI workspace（HEAD `c720a261c` 加当时未提交改动） | 1,949 | 0 | 2,360 | 28,733 | 563 | 0 |

原始 workspace 有 74 个额外 Python 文件，且包含迭代203未提交修改。本次只读扫描它，没有在该目录编辑文件。零条静态 API→sink 路径不代表没有消费者：当前主要分派经过 `Depends`、policy registry 和 `route.adapter.fetch()`，类型/实例关系是运行时注入。实际选择链由 selector 行为测试验证；动态路径仍需要逐个消费场景做 API 集成验收。

本迭代 worktree 的命中分类如下：

| 命中类别 | 次数 | 迁移含义 |
| --- | ---: | --- |
| `source_sdk_import` / `source_sdk_call` | 86 / 96 | 182 处直接来源 SDK 语法命中，主要是 AkShare；不等同于182个任务 |
| `source_adapter_import` | 12 | 统一 query/API 或兼容导入器仍有 provider adapter 边界 |
| `warehouse_import` / `warehouse_call` / `warehouse_connection` | 1,066 / 977 / 15 | 旧脚本/数据服务仍直接引用写库入口或连接实现 |
| `shared_file_io` / `shared_file_path` | 9 / 0 | 发现9处显式文件读写；静态字面量规则没发现额外的路径常量 |

最需单独拆迁、不能把它们算入 1,066 个历史采集脚本的业务 service 候选如下：

| 文件 | 命中 | 后续工作 |
| --- | --- | --- |
| `src/backend/app/services/market_instrument_asset_adapter.py` | 21 | 直接 AkShare 调用；改为读取 OpenData master-data/records API |
| `src/backend/app/services/market_instrument_dynamic_data.py` | 2 | 运行时 instrument 数据直连来源；需要先冻结查询字段与 freshness 语义 |
| `src/backend/app/services/realtime_data_service.py` | 2 | 直接 source SDK；评估它是REST查询还是需独立低延迟 ADR |
| `src/backend/app/services/scanner_universe.py` | 9 | universe/标的列表直连；迁到主数据与成分版本 API |
| `src/backend/app/services/stock_analysis/data_collector.py` | 9 | 研究采集器直连；迁到 OpenData 数据准备/读取接口，保留业务衍生逻辑 |
| `src/backend/app/services/stock_signal/batch.py` | 2 | 信号批处理的基础行情依赖切换至 REST |
| `src/backend/app/services/stock_signal/calendar.py` | 2 | 日历消费改为版本化交易日历接口 |
| `src/backend/app/services/stock_signal/universe.py` | 2 | universe 消费改为版本化主数据接口 |
| `src/backend/app/services/asset_research/providers/akshare.py` | 1 | 检查是否为可迁移来源适配器，避免研究服务在 selector 外直抓 |
| `src/backend/app/services/akshare/interface_loader.py` | 1 | 迁移数据管理/接口目录职责；执行权限留在 OpenData worker |

此外，`src/backend/app/api/data/queries.py` 有3处 AkShare/THS/OpenData adapter 导入，是本次唯一实现的在线 market-data source selector。它的默认 legacy mode 仍能选旧 source；OpenData-only 开关已用 selector 实际行为隔离。

旧 `app/data_fetch` 家族在本 worktree 命中 2,163 次（2163次语法命中，不是唯一脚本数）。仓库已有逐脚本/哈希底账 `script_migration_inventory.csv`：1,066 个 Python 文件，其中1,056个候选 entrypoint、10个 helper 待复核。候选需要映射到 OpenData 自研 provider、domain contract、业务键与调度定义，不能将“脚本可导入/搬到新目录”记作迁移完成。

对比这两个扫描快照，原始 workspace operational-script 角色有43个命中文件、127次语法命中；本 worktree 有9个命中文件、29次命中。原始快照中这些脚本需先分清采集任务、审计、schema 管理，再分别迁移或退役：

- 回补、控制器与审计（目录 `src/backend/scripts/`）：`audit_full_history_contracts.py`、`backfill_etf_nav_controller.py`、`backfill_fund_nav_history.py`、`backfill_fx_history.py`、`backfill_market_history.py`、`bond_convertible_history_controller.py`、`bond_full_history_audit.py`、`cffex_option_history_controller.py`、`cffex_option_range_controller.py`、`commodity_option_history_controller.py`、`crypto_full_history_recovery.py`、`crypto_history_backfill.py`、`futures_daily_history_backfill.py`、`futures_data_audit_common.py`、`futures_full_history_audit.py`、`stock_full_history_controller.py`、`verify_reviewed_unit_nav_full_source.py`。
- `src/backend/scripts/ops/`：`audit_dce_option_history.py`、`backfill_bond_issuance_universe.py`、`backfill_etf_option_history.py`、`backfill_shfe_archive_holes.py`、`backfill_stock_amount_sina.py`、`backfill_stock_tail.py`、`backfill_stock_tencent_volume.py`、`cfets_daytime_managed_acceptance.py`、`dce_option_browser_capture.py`、`dce_option_history_ingest.py`。
- DDL/schema 与兼容管理（目录 `src/backend/scripts/`）：`deploy_cffex_option_history_schema.py`、`deploy_commodity_option_history_schema.py`、`deploy_etf_option_history_schema.py`、`deploy_forex_eastmoney_daily_history_schema.py`、`deploy_forex_sina_daily_history_schema.py`、`deploy_fund_monetary_income_schema.py`、`deploy_fund_reviewed_unit_nav_schema.py`、`deploy_fx_spot_schema.py`、`deploy_index_eastmoney_daily_history_schema.py`、`deploy_iteration203_warehouse_schema.py`、`deploy_sina_index_daily_history_schema.py`、`migrate_source_files.py`。
- runner 与验收入口（目录 `src/backend/scripts/`）：`accept_iteration197_akshare_stock_liquidity.py`、`acceptance/iteration198_ths.py`、`openbb_market_data_runner.py`、`sina_index_daily_managed_acceptance.py`。

这些是两个不同源快照之间的差异，不应仅凭扫描次数推断每个额外文件的状态或运行频率。非应用 Python 的 DB 定时任务、cron/systemd service/timer、进程分片和外部部署配置不在此 AST 扫描范围；须与迭代203执行台账及实际主机调度清单逐一对账后再停旧写入者。

复算方式（输出包含所有逐行 `hits`、`edges` 和文件计数，可将 JSON 保存到临时目录比较）：

```bash
PYTHONPATH=src/backend python -m app.services.market_data.consumer_boundary \
  --root "$PWD" --format json

PYTHONPATH=src/backend python \
  -m app.services.market_data.consumer_boundary \
  --root /home/yun/Documents/ai-for-investor --label '原始 AFI workspace' --format json
```

扫描器只标记代码中看得见的路径/SDK/数据库模式。报告数字应与底账行数、活跃任务实例、真实容器/主机 schedule 和 source 权限逐项对照；本报告不代表所有消费者已迁移，也不构成 OpenData 生产数据覆盖证明。

## 业务场景调用矩阵

补充只读审查以集成分支 `d1384ccba` 为基线，原目录仍为 `c720a261c` 加203未提交变更；两个源快照不混用。下表沿实际service调用核对AST无法解析的注入路径，没有请求源站或生产API。OpenData domains.yaml中的声明不等于已部署/授权/填充的数据能力。

| 业务场景 | 当前调用及数据边界 | 后续迁移和回归条件 |
| --- | --- | --- |
| `/data/queries`、`/data/kline` | `api/data/queries.py:152` → `market_data/query_service.py:818` → OpenData adapter；仍先写AFI本地数据store再读 | 共用REST读门面直接返回中台数据；隔离研究sealed副本，移除通用行情复制维护；保留权限/来源/单位/日期校验 |
| 标的lookup/options | `market_instrument.py:280` → 旧行情warehouse DSN/本地历史缓存，线上refresh被拒绝 | 中台instrument/alias/交易所/生命周期合同；离线缓存须带版本，不能只换DSN |
| 普通回测 | `backtest/service.py:448,891` → AFI coverage预检、`BACKTRADER_DATA_DIR` CSV | 从固定中台snapshot取数并校验覆盖/调整口径/PIT，运行中不可读取变化的latest；AFI保留策略和结果 |
| Workspace研究绑定 | `market_data/research_binding.py:231,257` 的local_only → CSV/hash/manifest；runtime仅用已验证绑定文件 | 将输入来源改成REST固定snapshot，保留AFI签名、hash、封存和复现边界 |
| 扫描器 | `scanner_universe.py:266,314,418` 直接成分/行情源，池/指标快照本地JSON；`:362`可生成seed_fallback值 | 成分/行情读中台；用户自定义池和规则留AFI；移除或明确标注模拟值，不将其当真实行情；缺域合同显式不可用 |
| 股票分析后台任务 | `stock_analysis/data_collector.py:113,152,322` → 旧行情仓库、新闻库、直接财务/公司/行业/新闻源 | 行情、财报、公司画像、同行、新闻逐项合同；缺数据呈现质量限制，研究报告和结论留AFI |
| 夜间信号 | `stock_signal/universe.py:16`、`calendar.py:20`、`batch.py:189,225,307` → 成分/日历/基准源及AFI行情库 | 统一REST消费版本化成分、日历、基准和outcome行情；信号模型、预测/评分及业务调度保留 |
| 多资产研究 | `asset_research/orchestrator.py:193` → `providers/akshare.py:385,1261` 与本地仓库适配器 | 按期货/期权/债券/基金/FX/crypto独立合同迁移；保留AFI来源授权、cutoff校验、任务和研究快照审计 |
| 历史/实时行情路由 | `realtime_data_service.py:175,237` 直接日/周/月线来源 | 支持的历史日线走中台；实时tick/执行报价单独定义产品/时延边界，不套日线或静默降频 |
| 旧采集与调度 | `akshare/scheduler_service.py:65,101`、`startup/orchestration.py:49` 管理任务，失败fallback可启动旧scheduler | 采集计划/执行日志迁中台；先导入默认disabled定义、隔离目标影子补数/影子读，再逐dataset/sink单写者切换；AFI业务调度保留 |

以上为首批场景矩阵，动态分派与额外203恢复工具仍须单独核对。下一波优先做共用async REST门面、直接行情读、固定研究snapshot与单一股票调用链回归，再按资产模型族补其余合同；多人不同时修改 `MarketDataQueryService` / `MarketInstrumentService`。实际库分母为1,103调度任务（1,098active、5inactive）、10条无调度helper，不能把5个停用任务当辅助脚本。

## 未迁移与切换限制

- 当前 OpenData consumer route 仅股票日线、仅 v1 stock-daily endpoint。基金、债券、期货、期权、外汇、crypto、指数、财务、宏观及分钟频率没有 OpenData consumer route；OpenData-only 模式下不会转去旧 provider。
- `app/data_fetch` 旧入口及其 worker/task CRUD、管理界面和脚本运行器尚未迁到 OpenData。直接 API 与历史脚本需要按任务 ID / 路径 / schedule / writer 组逐项对账，保持 broker account/order/gateway control API 原样。
- 本次没有在生产环境下载数据、重跑定时任务、改数据库或关闭旧 timer。没有证据证明全历史覆盖、source 授权、生产调度单写者或自然周期验收。
- `.joyincode/rules/backend.md` 与 `.joyincode/rules/frontend.md` 在该 worktree 不存在；本项只改后端 consumer selector/adapter 和无前端影响的文档，按仓库 `AGENTS.md` 的 Python/API 规范实现。

## 验收结果

通过的离线验证：

- `tests/services/market_data/test_consumer_boundary.py` 与 `tests/market_data_platform/test_opendata_provider.py`：58 passed。包含临时仓库调用链、扫描真实当前源树、OpenData-only selector 实际只选 OpenData、无 key 时真实 adapter 零 HTTP 调用并返回配置错误、selector 对 `1w` 没有其他来源候选、API 对无 key 返回503，以及 API 对非日频返回422。
- `tests/market_data_platform/test_source_policy.py` 与 `tests/market_data_platform/test_query_api.py`：76 passed。

尚需单独验收的事项：实际迭代203脏 workspace 的逐脚本复扫需在其提交整合后重跑；selector false→true 的部署开关变更须等 OpenData route 覆盖、权限证据和回滚检查通过；全量 API 消费替换、任务迁移、生产源数据/全历史、调度器和跨数据库写入均未由上述测试覆盖。
