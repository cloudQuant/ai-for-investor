# 子任务合入实况重算（2026-11-05）

`SUBAGENT_TASKS.md` 的状态列是 2026-10-29 的计划快照，文档自己写明「尚未按之后合入的代码逐项重算」。本文件就是那次重算：98 个子任务按**当前两仓已合入代码**逐项读出证据面，并给出可直接派给并行代理的互斥文件清单。

平面词汇沿用清单 §验收边界与并行约定：`CODE/OFFLINE`、`REAL_SOURCE`、`DEPLOYMENT`、`NATURAL_CYCLE`。分类含义：

| 分类 | 含义 |
|---|---|
| `DONE_OFFLINE` | 该行声明的代码/离线交付已在树里，且带测试入口 |
| `ACTIONABLE_NOW` | 剩余部分可在纯 CODE/OFFLINE 面推进，不需要供应商请求、生产库或日历时间 |
| `BLOCKED_ENVIRONMENT` | 需要部署环境（活库、分区表、组合根、systemd 装配） |
| `BLOCKED_REAL_SOURCE_OR_CALENDAR` | 需要真实源返回或自然周期经过 |
| `BLOCKED_OWNER_DECISION` | 需要属主裁定后才能判定「算不算交付」 |

**方法与可信度**：三路只读盘点代理分别在 OpenData（A+D 域、B+C 域）与 AFI（E 域）按行为匹配读文件，不是按标签；下表证据列是其读回的 `文件:行` 或 commit。集成人另行复验了三条承重判断，命令与结果见 §5；其余行未逐条复验，引用时按「代理读数」对待。OpenData 本机**没有带依赖的解释器**，代理只复跑了部分测试文件；任何「N 项通过」若未在此处标注复验，都是台账读数而非本会话读数。

## 1 A 域（平台与数据契约）

| 子任务 | 分类 | 已覆盖面与证据 | 仍开放 |
|---|---|---|---|
| 204-A01-01 | DONE_OFFLINE | 基线 SHA 记录于 SUBAGENT_TASKS.md:23-27 | 需按现 HEAD 重取（本会话已重取，见 `RUNTIME_REPAIR_20261105.md` §0） |
| 204-A01-02 | ACTIONABLE_NOW | owner 表 :35-43、AFI `docs/adr/` | 204 专项共享文件 ADR 索引不完整 |
| 204-A02-01/02/03 | DONE_OFFLINE | `docs/afi204-v2-openapi.json`、`opendata/data/platform_contracts.py:227`（半开窗口/单位/币种）、`dataset_contract_registry.py`、`tests/fixtures/afi204/` | A02-02 的逐数据集非法单位拒绝样例待核 |
| 204-A02-04 | DONE_OFFLINE | `scripts/quality/check_published_openapi.py`（不自更新基线 :20）、`Makefile:46-47` | — |
| 204-A03-01 | ACTIONABLE_NOW | `alembic` 0007 job_definitions、`alembic_data` 0011/0021；registry 目前**文件式**（`published_data.py:687`） | DB 化 registry 提案未见 |
| 204-A03-02 | ACTIONABLE_NOW | `api/temporal_identity.py:231-269` 失败关闭、`data/temporal_identity_pins.py`、装配 `main.py:228-262`、`TEMPORAL_IDENTITY_ENABLED` 默认 False（`core/config.py:88`）、#152 universe | 退市/换码生命周期、分页终止、census attestation 仍 UNKNOWN（REAL_SOURCE+DEPLOYMENT） |
| 204-A04-01 | DONE_OFFLINE | `pipeline/raw_evidence.py`、`raw_evidence_reader.py` + 测试 | 「密钥不入 manifest」逐条单测未读回 |
| 204-A04-02 | ACTIONABLE_NOW | `services/provider_model_*`、`pipeline/financial_pit.py`、`alembic_financial_archive` 0001 | 修订链/snapshot 版本字段全量待核 |
| 204-A04-03 | ACTIONABLE_NOW | `publication_store.publish_in_connection:539-735`（事实+指针+outbox 同事务）、outbox 表 :213、`alembic_data` 0018 | 跨服务 relay 与独立 receipt 重放未实现 |
| **204-A04-04** | **ACTIONABLE_NOW（最大缺口）** | 全仓检索**无** visibility seal、无独立单调 sequence；`published_at_us` 仍是事务内字段（`publication_store.py:195`） | A05-04/06/07 的验收前置。Wave 27 已派实现代理 |
| 204-A05-01 | DONE_OFFLINE | `main.py:364-365` v1 挂载、`docs/afi204-v1-openapi.json` | — |
| 204-A05-02 | DONE_OFFLINE | `/api/v2` datasets/records/coverage/snapshots/capture-candidates（`published_data.py:746-1092`） | v2 日历端点未见 |
| 204-A05-03 | ACTIONABLE_NOW | `MAX_PAGE_SIZE`、410/422/429（:559-574）、`rate_limit.py` | 异步大导出入口未见 |
| 204-A05-04 | DONE_OFFLINE | `api/stock_daily_publication.py`（666 行，`include_in_schema=False:163`）、容量门 `stock_daily_capacity.py:185-187` 默认 404 | DEPLOYMENT 操作者证明、真实 seal 读取（依赖 A04-04） |
| 204-A05-05 | ACTIONABLE_NOW | `api/published_access.py:238-289` 逐 principal+purpose 失败关闭、source gate sg0001-0004 | 后台委托执行时的授权版本重验未读回；真实 grant 签发是 REAL/DEPLOYMENT |
| 204-A05-06 | ACTIONABLE_NOW | 财报观测归档 `api/financial_observation_archive.py:291`（挂载 `api/__init__.py:46`） | 修订/报告期/PIT 合同测试面待补 |
| 204-A05-07 | ACTIONABLE_NOW | snapshot POST/GET 在 `published_data.py` | cutoff+visibility sequence 双约束与 vector 保留期未实现 |
| 204-A06-01 | DONE_OFFLINE | `pipeline/history_coverage.py` 纯函数（不 import DB）+ `test_history_coverage.py` | — |
| 204-A06-02 | ACTIONABLE_NOW | `alembic_data` 0002 dq、`alert_matrix.py`/`diff_alerts` | 逐数据集规则配置未读回 |
| 204-A06-03 | BLOCKED_REAL_SOURCE_OR_CALENDAR | — | 需真实源请求与保留证据 |
| 204-A06-04 | ACTIONABLE_NOW | `query_window_coverage.py`、`coverage_evidence_registry.py:241`（缺证据→UNKNOWN） | 4/8/920 `NOT_SUPPORTED` 的覆盖测试未找到 |
| 204-A07-01 | ACTIONABLE_NOW | — | 跨仓 release manifest 无实现 |
| 204-A07-02 | BLOCKED_ENVIRONMENT | — | 阶段发布评审需部署与全量证据 |

## 2 B 域（证券数据适配）

| 子任务 | 分类 | 证据与缺口 |
|---|---|---|
| 204-B01-01 | ACTIONABLE_NOW | `opendata/migration_catalog.py`、`docs/afi204-migration-catalog.json`（`61afc776`，2026-10-26 口径：legacy 1066 / entrypoint 1056 / provider endpoint 974 / MISSING_PROVIDER 870 / REQUIRES_MANUAL 103）、`scripts/ops/build_migration_catalog.py`；基线 CSV **无处置列**，1056 行「待盘点/待映射」+10 review_only |
| 204-B01-02 | BLOCKED_REAL_SOURCE_OR_CALENDAR | `tests/fixtures/upstream/*/meta.json` 为 recorded（upstream commit `c4f6a631`）；2026-10-28 活采尝试留档于 `var/reports/**/2026-10-28-akshare-live-pilot-attempt/ARCHIVE_NOTES.txt`（网络失败，无 HTTP 状态） |
| 204-B02-01 | DONE_OFFLINE | `providers/akshare/models/stock_daily.py:22`（`_BSE_ROUTE_UNVERIFIED`）、`stock_daily_native.py`、`stock_daily_wire.py`、`cf561b8e` |
| 204-B02-02 | BLOCKED_REAL_SOURCE_OR_CALENDAR | `docs/akshare-stock-daily-pilot.md:13` 自陈「真实试采尚未运行」；`scripts/ops/akshare_stock_daily_pilot.py:424-425` |
| 204-B02-03 | ACTIONABLE_NOW | `corporate_events.py`（`360c61dd`）、`models/adjustment.py`、`scripts/ops/rebuild_adjustment_factors.py`、SSE/SZSE/BSE 生命周期捕获脚本 |
| 204-B02-04 | ACTIONABLE_NOW | `providers/akshare/provider.py`（10 个 lazy fetcher）、`api/stock_daily_publication.py:160-167` |
| 204-B02-05 | BLOCKED_ENVIRONMENT | `fuyao_financial_bundle/process/run_job.py`（`e39f64b7`）、六 scope 回放测试；`docs/operations-fuyao-financial-job.md:7` = `enabled=False, reviewed=False`，无组合根入口 |
| 204-B03-01 / B03-02 | ACTIONABLE_NOW | `models/fund_etf_daily.py` + `fund_etf_daily_em/sina` 夹具；`models/bond_daily.py`、`_vendor/bond/*`。缺：NAV/万份收益/七日年化、债券曲线模型 |
| 204-B04-01 / B04-02 | ACTIONABLE_NOW | `models/index_constituent.py:29,100-108`（as_of）、`providers/ths/index_daily_publication.py`；`pipeline/provider_model_schema.py`、`diff_governance.json`（known_differences 空） |
| 204-B05-01 | ACTIONABLE_NOW | `pipeline/dwd_backfill.py`、`partitions.py`、`scripts/ops/{backfill_dwd,plan_legacy_migration}.py` |
| 204-B05-02 | BLOCKED_ENVIRONMENT | `scripts/ops/window_partition_explain.py` 需活库（AC-11\|04 同源障碍） |
| 204-B05-03 | BLOCKED_REAL_SOURCE_OR_CALENDAR | 控制面已在树：`stock_daily_backfill_plan.py`(1444 行, `a76b4858`)、`stock_daily_backfill_executor.py`(806 行)、`scripts/ops/execute_stock_daily_backfill.py`（digest-pinned、默认 dry-run、SQLite 台账）、`stock_daily_reconcile.py`(1509 行, `34f6e146`)。缺：权威全市场/退市分母、逐 `instrument×dataset` 真实回补、生产库发布 |
| 204-B06-01/02/03 | ACTIONABLE_NOW / BLOCKED_ENVIRONMENT | `pipeline/templates.py`、`job_definition_store.py:111`、`schedules.yaml:12-18`、`migration_worklist.py:39,495,532`（只有 BLOCKED/NON_SCHEDULED_HELPER 两种态）；B06-03 的 `runtime_task_mapping.status = NOT_CHECKED_DATABASE_OR_INSTALLED_HOST` |
| 204-B07-01/02/03 | BLOCKED_REAL_SOURCE_OR_CALENDAR / BLOCKED_ENVIRONMENT | 仅 `docs/operations-provider-patrol.md`，无源受限 runbook |

## 3 C 域（衍生品与其他资产）

| 子任务 | 分类 | 证据与缺口 |
|---|---|---|
| 204-C01-01 | ACTIONABLE_NOW | 同一清点工具；按今天的族分布 other=317（快照口径 449/607 均已过期） |
| 204-C01-02 / C02-02 / C03-02 / C04-02 / C07-01 | BLOCKED_REAL_SOURCE_OR_CALENDAR | 树内无跨域活捕获证据 |
| 204-C02-01 | ACTIONABLE_NOW | `akshare/models/{futures_daily,option_daily}.py`、`providers/ths/models/*_daily.py`、`_vendor/{futures,option}/*`。缺：连续合约/主力合约/TAS 身份（全仓未找到） |
| 204-C03-01 | ACTIONABLE_NOW | `models/currency.py`、`providers/deribit/`、`tests/test_currency_reference_contract.py`、`test_deribit_provider.py` |
| 204-C04-01 | ACTIONABLE_NOW | `scripts/ops/import_minute_archive.py`、`pipeline/sina_fzb_fanout.py`（`a7ccb02a`）；仓内无浏览器捕获模块 |
| 204-C05-01 | ACTIONABLE_NOW | `models/{economic_series,financial,fred_macro_iter2}.py` 的 vintage/revision 字段、`pipeline/financial_pit.py` |
| 204-C05-02 | BLOCKED_OWNER_DECISION | 清点 319 模型 / 289 已登记 / 30 未登记（`scripts/quality/{upstream_model_specs,iter2_model_evidence,model_capability_census}.py`）——是否入册属属主 |
| 204-C06-01 | ACTIONABLE_NOW | `migration_catalog.py`、`migration_worklist.py`（`2b3bc7e6`）、`pipeline_step.py:26-28` checkpoint |
| 204-C06-02 | BLOCKED_ENVIRONMENT | `replay_warehouse_pipeline.py` 需已迁移库 |
| 204-C07-02 | BLOCKED_ENVIRONMENT | 只有 `Makefile:200 gate`，无部署回执 |

## 4 D 域与 E 域

| 子任务 | 分类 | 证据与缺口 |
|---|---|---|
| 204-D01-01 | ACTIONABLE_NOW | `host_inventory.py`、`runtime_inventory.py` + 测试；本会话已对本机运行态做了现行刷新（见 `RUNTIME_REPAIR_20261105.md`） |
| 204-D01-02 / D02-01 / D02-02 / D02-03 / D03-01 / D05-01 / D05-02 | DONE_OFFLINE | `migration_apply.py:121-351` 指纹+allowlist、`run_identity.py`(523 行)、`run_ledger.py:183`（#162 已并入 dev，`test_run_ledger_atomic.py:104` 拒过期 token）、`alembic_data` 0010→0011/0020 + `test_afi204_owned_mysql.py:112`、`process_executor.py`、`migration_inventory.py`、`migration_plan.py:138` + `migration_apply.py:444,323` |
| 204-D02-04 | DONE_OFFLINE + BLOCKED_ENVIRONMENT | `run_service.py:228,467,540` execution_only + `reviewed_worker.PersistentRunWorker:249,318`（含伪造时钟拒绝 :261）；生产多进程/租约恢复未测 |
| 204-D03-02 | ACTIONABLE_NOW | `data/request_budget.py:122-277` 进程内密封、`source_attempt_gate.py` + sg0004 one-shot、THS transport 有 Retry-After。缺：跨进程/跨运行持久预算与 WAF 停试 |
| 204-D03-03 | DONE_OFFLINE + BLOCKED_ENVIRONMENT | `run_dispatch.py:282,484` APSchedulerSubmissionCallback、`reviewed_cli.py`、`reviewed_runs` POST /runs、角色门 `reviewed_runtime.py:148`。**但** legacy `services/scheduler.py` 不引用 RunService（0 命中），`deploy/README:58` 明示组合根缺失 |
| 204-D04-01 | DONE_OFFLINE | `api/reviewed_runs.py`（CurrentAdmin、cancel:443、脱敏状态），仅挂 reviewed_app |
| 204-D04-02 | ACTIONABLE_NOW | `frontend/src/views/admin/ReviewedRunsView.vue`(544 行) + `router/index.ts:89`；缺覆盖/补数/容量页 |
| 204-D05-03 / D06-02 / D07-01..03 | BLOCKED_ENVIRONMENT | 恢复演练、告警实触发、切换均无实证 |
| 204-D06-01 | ACTIONABLE_NOW | `middleware/request_logging.py:5` 已有 trace_id；run/publication 串联未见 |
| 204-E01-01 | DONE_OFFLINE | `app/services/market_data/consumer_boundary.py`（AST 扫描器 + CLI）+ `CONSUMER_MIGRATION.md` 逐文件命中表 |
| 204-E01-02 | ACTIONABLE_NOW | 场景调用矩阵已在 `CONSUMER_MIGRATION.md`；缺带通过/受限结论的回归矩阵 |
| 204-E02-02/03/04 | DONE_OFFLINE | `opendata_provider.py:177-186,368-438`（symbol/日期/页/字节上限）、整体 httpx 异步、`:62-66,206-234,351-363` deadline/重试/Retry-After→稳定错误码；活调用点 `api/data/queries.py:120,185,204`、`base.py:286`、`realtime.py:269`（全在默认关 flag 后） |
| 204-E03-01/02/03 | ACTIONABLE_NOW | flag-on 仅 `opendata-stock-daily-v1`；SSE50/HS300-500-800 benchmark 选择器默认关；前端 `useDataPage.ts` 的 `opendata_direct` 显示态（Wave 27 #272 正在补覆盖状态区分与大文件整改） |
| 204-E03-04 | BLOCKED_OWNER_DECISION | 生产者接缝在（`stock_analysis/report_evidence_producer.py`，由 `tasks.py:29` 调）；reader 仅 Protocol，**无生产调用点**：`api/stock_analysis.py:168,225,…` 全部 `StockAnalysisTaskService(db)` 传 reader=None → `stock_daily_report_evidence_reader_unavailable`（producer:121-123）。选择器无业务窗口（`schemas/stock_analysis.py:43-52`），`read_authorized` 只返回行不暴露 receipt（`opendata_stock_daily_snapshot.py:186-194`） |
| 204-E03-05 | BLOCKED_OWNER_DECISION | 冻结 vector + 保存前 revalidate（`tasks.py:575`）+ 迁移 `20261101_…` 已在树；真实重放依赖 E03-04 |
| 204-E04-01/02/03 | ACTIONABLE_NOW | 见 §5 复验：绑定层无 publication 引用 |
| 204-E05-01 | ACTIONABLE_NOW（受设计约束） | `views/data/*` 无 OpenData 管理入口；OpenData #182 的先例是「审核运行时未装配」而非发必然 404 的请求，入口须先陈述状态 |
| 204-E06-01/02 | BLOCKED_ENVIRONMENT | AFI `app/` 内无影子读实现；离线 503/422 映射已有 |
| 204-E06-03 | BLOCKED_REAL_SOURCE_OR_CALENDAR | `tests/test_opendata_stock_daily_publication_cross_repository_wire.py`、`…_real_sample_replay_wire.py`（需 `AFI_OPENDATA_STOCK_DAILY_WIRE_TEST`/`…_REPLAY_TEST` + `OPENDATA_REPO/_PYTHON`） |
| 204-E07-01/02 | BLOCKED_ENVIRONMENT | 未移除任何旧入口，切换归 D07 |

## 5 集成人复验（命令与读数）

```
git grep -c -E "publication_id|publication_sequence" dev -- src/backend/app/services/market_data/research_binding.py
  → 0（无该引用）                                   ⇒ E04 三行的「绑定层不引用 publication」成立
git grep -l -i akshare dev -- 'src/backend/app/**' | grep -vcE 'app/data_fetch/|app/scripts/'
  → 77                                             ⇒ AC18 的运行时旧源耦合面（不含采集树）
git grep -l "DB_CONFIG|akshare_data" dev -- 'src/backend/app/**'（排除 data_fetch）
  → app/db/__init__.py, app/db/akshare_data_database.py, app/models/data_governance.py,
    app/schemas/sync.py, app/services/akshare/data.py, app/services/asset_info/gateway_specs.py
git log --all --diff-filter=A -- "*/{5 个恢复控制器}.py" → added-in-any-ref = 0（逐个）
```

AC18 判定口径提醒：77 个文件里既包含 `app/api/akshare/*` 这类**管理旧采集面的路由**（迁移后本就该退役），也包含文档字符串命中；不能把 77 直接当作「还需迁移 77 处」。真正阻塞 AC18 的是运行时导入与直连库，上表第二组已具名。

## 6 可直接派发的互斥文件清单（ACTIONABLE_NOW 排序）

| 序 | 任务 | 独占文件 | 必须排队的共享文件 |
|---|---|---|---|
| 1 | A04-04 visibility seal | 新 `opendata/pipeline/visibility_seal.py`、`tests/test_visibility_seal*` | `publication_store.py`、`alembic_data/versions`（单 head）、`core/config.py`、`api/__init__.py`、v2 OpenAPI 基线 |
| 2 | A05-07 snapshot vector | 新 `opendata/data/snapshot_vector.py` + 测试 | `published_data.py`、OpenAPI 基线 |
| 3 | D04-02 运维页 | `frontend/src/views/admin/*`、`frontend/src/api/*` | 路由 index |
| 4 | A06-04 + BSE 覆盖键 | `pipeline/coverage_service.py`、`query_window_coverage.py` + 测试 | registry |
| 5 | D03-02 跨进程预算 | `data/request_budget.py`、`pipeline/retry.py` | `run_service.py`（与 D02 同 owner 排队） |
| 6 | E04 研究绑定 publication 引用 | `app/services/market_data/research_binding.py`、`stock_analysis/exporter.py` + 测试 | **禁**新建 Alembic revision（本会话由集成人处理链） |
| 7 | B01-01 + C01-01 清点重算 | `opendata/migration_catalog.py`、`migration_worklist.py`、`scripts/ops/build_migration_*` | `docs/afi204-migration-catalog.json` |
| 8 | C02-01 衍生品身份合同 | `opendata/data/models/futures.py`、新连续性模块 + 测试 | provider registry、A2 allowlist、ratchet |

## 7 本文件不声称的事

- 不把任何行写成验收通过：`DONE_OFFLINE` 只表示该行声明的离线交付在树里。
- AC01–AC18 的判定未因本文件改变；真实源、部署、自然周期三类不因重算而闭合。
- 代理盘点的「N 项测试通过」凡未复验者仍属台账读数；OpenData 本机不可复跑整套。
- 族/频率分母与 1057 脚本的处置词表仍未确认（`INVENTORY_AUDIT_20261105.md` 记录 AC11 处置为 0/1057），本文件不替代它。
