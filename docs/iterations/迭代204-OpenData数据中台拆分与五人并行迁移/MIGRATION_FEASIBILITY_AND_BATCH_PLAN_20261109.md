# 迭代204 — 迁移可行性与分批计划（2026-11-09）

**结论先行**：数据管理面**一项都没有迁移**。迭代204 至今交付的是契约、仪器、离线证据，以及把 AFI 自己的采集器修好；
OpenData 那套数据管理控制面是建库时的空壳（`4ee1bbca`，2026-09-22），里面只有 1 个参考脚本，
且那一个在迁移目录里也是 `REQUIRES_MANUAL` / `file_status: MISSING_PROVIDER`。
真正的切换机件（publication 生产者、research binding、能力台账读取器、fail-closed 判据）**代码都在**，
但**能力准入没有写入口**、OpenData 没有可用部署栈、消费者切换开关默认关闭且被空台账锁死。

本文只陈述实测事实并给出可执行批次；**未改动任何业务代码**。所有数字都给出可复跑坐标。

---

## 1. 现状事实（2026-11-09 实测）

### 1.1 AFI 侧：管理面与采集面都还在本机

| 事实 | 证据 |
|---|---|
| 管理 UI 在配置中心 | `src/frontend/src/router/index.ts:142-200`，路由前缀 `/config/data/*`；旧 `/data/*` 重定向进配置中心（`:335-390`）。页签：数据脚本/定时任务/执行记录/数据同步/接口管理/连接治理/Airflow |
| 后端是本地实现 | `src/backend/app/api/router.py:137` 挂 `app.api.akshare` 于 `/data`（36 条路由）；服务读写 AFI 自己的 `ak_data_scripts / ak_data_interfaces / ak_scheduled_tasks / ak_task_executions`；脚本在本地子进程 worker 里跑 |
| 采集仍在跑 | 1066 条 `ak_data_scripts`、**1048 个 armed 任务**；最近 2 小时 36 次执行（2026-11-09T03:28Z 读，最新 `03:24:00`） |
| 消费者未迁 | AST 普查 1935 文件 / 2296 命中，`legacy_data_fetch_to_migrate` **2162** 处 |
| 切换面全空 | 七张表均 **0 行**：`md_capability_ledger_entries`、`md_publications`、`md_publication_release_holds`、`md_research_data_bindings` + `_scopes`/`_consumers`/`_revocations` |

### 1.2 OpenData 侧：有控制面骨架，没有采集资产

- 路由面齐全：`/tasks /scripts /data/interfaces /tables /executions /settings /users /keys /providers /pipeline`（`opendata/api/__init__.py:53-67`），有 CRUD 与 trigger/cancel；admin 页面 coverage / backfill-planning / capacity-gate / reviewed-runs 均在。
- 但**资产为空**：`opendata/data_fetch/scripts/**` ＝ 十个 24–28 字节 `__init__.py` ＋ **1 个参考脚本** `stocks/daily/stock_zh_a_hist.py`（3303 B）；对照 AFI 1057 个真脚本。
- **scheduler 默认关闭**（`core/config.py:186-192` `enable_scheduler=None`；`pipeline/scheduling.py:62-77`）；`ReviewedRunsView.vue:296` 自陈「审核运行时未装配」；`deploy/afi204-reviewed/README.md:1-6,57-60` 需要部署方提供 composition root 并停 legacy sink writer。
- 迁移目录（`docs/afi204-migration-catalog.json`，冻结 `61afc776`，2026-10-26）：**files 1066 = MISSING_PROVIDER 877 + REQUIRES_MANUAL 189**；`runtime_verification` **NOT_RUN 1066/1066**；`provider_endpoint_catalog` 974（870 MISSING_PROVIDER / 1 READY_FOR_ADAPTER / 103 REQUIRES_MANUAL）；`opendata_provider_models` 319（全部 `registered_by_descriptor: true`）。目录自带的 notice 明确：READY_FOR_ADAPTER **不代表**任何脚本/任务/数据集已迁移或通过运行时验证。

### 1.3 AFI 里那条「OpenData 集成」是什么

`src/backend/app/services/market_data/opendata_provider.py`（httpx REST）只接在归一化查询 API（`api/data/queries.py:120-131,171-209`），
受 `MARKET_DATA_OPENDATA_ENABLED`（`settings/market_data.py:98`，默认 **False**）＋ query v2 ＋ online-fetch ＋
能力台账 attestation ＋ provider registry ＋ source grant 六重门禁。台账 0 行 → `_lifecycle_for` 直接
`CAPABILITY_LEDGER_MISSING`（`capability_ledger.py:346-369`），**无论开关怎么设都 fail-closed**。
它覆盖 **CN stock daily / 1d / v1**，既不是采集面也不是管理面。代码自己写明：
「把 flag 设 false 是明确的过渡期 legacy 策略，**不是消费者迁移完成的证据**」（`queries.py:159-162`）。

---

## 2. 缺口分类（按可迁移性，不按字母序）

| 类 | 数量 | 含义 | 可迁移性 |
|---|---|---|---|
| `MISSING_PROVIDER` | **877** | OpenData 没有对应 provider | 主体工作；其中 **371 个当前正在增长** |
| `REQUIRES_MANUAL` | **189** | 有部分信号但需人工判定（含全部 22 个「无任务」项） | 需判断；其中 72 个正在增长 |
| 无任务目录项 | **22** | 目录有、AFI 无 armed 任务 | 需属主裁定是否保留 |
| 从未跑过 | **428** | armed 但窗口内无执行 | 无法做 parity 对照 |
| 只有失败执行 | **25–29** | `failed_only` | 先修再迁 |
| `unexpected_param:_ingest_mode` | **7** | 只失败、0 完成 | 先判定是否废弃 |
| 幽灵注册（无文件） | **9** | 台账有行、盘上无文件 | 只能删除或重建，不能迁 |
| 运行时幽灵（unit 指向） | **7** | systemd 指向、任何 ref 都没有 | 只能补造或改指向；已停用其中 4 个 shard |
| 源主机不可达 | 未知 | `push2.eastmoney.com` / `82.push2.eastmoney.com` 本机 3/3 ConnectionError | 本机不可验证，需 CI/其它网络 |

**catalog × 运行时交叉表**（AC11 口径，as_of `2026-11-09T03:01Z`，窗口自 `2026-11-05T14:00Z`）：

| bucket | 目录项 | 在用任务 |
|---|---|---|
| `completed_and_grew` | 443 | 443 |
| `completed_no_delta` | 148 | 148 |
| `failed_only` | 25 | 29 |
| `not_run` | 428 | 428 |
| 无任务 | 22 | — |

按目录状态拆：MISSING_PROVIDER → 371 grew / 375 not_run / 113 no_delta / 18 failed；
REQUIRES_MANUAL → 72 grew / 53 not_run / 35 no_delta / 7 failed / 22 无任务。
（5 个任务共用 `futures.weekly.daily_market_data`，故 1048 任务对 1066 目录项。）

近 7 天执行量 top：`crypto_hourly_market` **147**（task 1049）、`fx_spot_quote` **50**，其后各 17：
`bond_spot_deal`、`bond_spot_quote`、`bond_zh_hs_spot`、`crypto_js_spot`、`forex_spot_em`、
`fx_quote_baidu`、`movie_boxoffice_realtime`、`spot_hog_crossbred_soozhu`。

---

## 2.4 AC11 处置台账：迁移主体的真实规模（2026-11-09 新读数）

处置分派仪器 `src/backend/scripts/ops/assign_script_dispositions.py` 本机复跑（提议，不是指派）：

```
python3 src/backend/scripts/ops/assign_script_dispositions.py \
  --out-dir /tmp/it204/ac11-disp-1109 --limit 0 --as-of-utc 2026-11-09T04:50:00Z \
  --registration-export /tmp/it204/ac11-registration-export.json \
  --source-verification-export /tmp/it204/sv/source_verification_export.json
```

| 项 | 读数 |
|---|---|
| 受跟踪非 `__init__` 脚本 | **1057** |
| 台账行 | 1057（每脚本一行） |
| **已指派 `assigned`** | **0** |
| 提议（未评审） | 1057 |
| `EXTEND_PROVIDER` | **954** |
| `HELPER_ONLY` | 8 |
| `REUSE_PROVIDER` | **6** |
| `UNDECIDED_INSUFFICIENT_EVIDENCE` | **89** |
| 库存 sha 一致 | 1057/1057 |
| 对账问题 | none |
| 库存有行但盘上无文件 | 9 |

属主/族分布：`owner:B 604 / owner:C 445 / owner:review 8`；族 `stock 384 / other 317 / index 93 / fund 87 / futures 64 / option 46 / bond 41 / fx 20 / crypto 5`。

**这组数字决定了迁移的形状**：迁移主体是 **954 个「扩展现有 provider 家族」**，不是 954 个从零写起；
真正能「复用已有 provider」的只有 **6 个**；89 个连证据都不足（在已提供 source-verification export 的情况下仍是 89——说明该出口本身还没覆盖它们，不是靠再审一遍就能降）。
这与目录口径的 `MISSING_PROVIDER 877` **不是同一把尺子**：目录问「有没有 provider」，处置问「要不要扩/复/只当 helper」，
两者不应被强行对平。**assigned 仍为 0：提议不是指派，签字仍属属主。**

**因此 B1/B2/B3 的分批不能只看目录状态**：954 个 EXTEND 里有多少是同一 provider 家族的多变体，决定了脚手架的复用率；
这需要在动工前先做一次「族归并」统计（同一 `target_models` 下的脚本数），否则会把同一家族的重复工作量乘 954 次。

## 2.5 真正的第一道缺口：provider model ↔ source function 的绑定几乎为空

对 `docs/afi204-migration-catalog.json`（origin/dev 版本）逐条统计：

| 事实 | 读数 |
|---|---|
| `provider_endpoint_catalog` 端点 | 974 |
| 带非空 `target_models` 的端点 | **10**（9 REQUIRES_MANUAL + 1 READY_FOR_ADAPTER） |
| `target_models` 为空的端点 | **964**（870 MISSING_PROVIDER + 94 REQUIRES_MANUAL） |
| 这 964 个的 `runtime_verification` | **NOT_RUN 964/964** |
| `opendata_provider_models` | 319 |
| 其中带非空 `source_functions` 的 | **12**（**307 个为空**） |
| 全库不同 `source_functions` 函数名 | **13** |
| 964 个未绑定端点中，按函数名能匹配到现有 model 的 | **0** |

**这条改变了对工作量的理解。** 不是「有 877/954 个 provider 要写」，而是**先要建立 model↔source 的绑定元数据**：
现有 319 个 model 里 307 个连「我负责哪些源函数」都没声明，所以「按家族归并、复用脚手架」这件事**现在做不了**，
任何按家族分批的计划都缺少输入。

**可自动化的前置（建议作为 B0.0，先于 B1）**：catalog 的 `files` 条目自带每个脚本的 `calls` 与 `source_imports`，
端点条目自带 `function`、`observed_argument_names`、`compatible_query_fields`；三者合起来足以**机械生成
「端点 → 源函数 → 候选 model」的绑定候选表**。这一步不需要 877 次人工判断，只需要一次数据工程 + 人工复核抽样。

**B0.0 的验收**：产出候选绑定表，每个端点必须落到两类之一并计数——
(a) 绑定到一个已声明 model（并给出该 model 的 `module_path`）；
(b) 明确标为「无匹配 model，需新建」。
两类都可复查；**只有到这一步之后，「954 EXTEND」才能被换算成真实的人月**，在那之前任何工期估计都不可信。

## 2.6 B0.0 的实测答案：661 可挂到 8 个已有 akshare 家族，299 必须新建

先纠正一个容易误读的前提：OpenData 的 319 个 `opendata_provider_models` **绝大多数不是 akshare**——
按 `source` 统计：fmp 69、fred 40、sec 24、federal_reserve 20、intrinio 18、yfinance 16、imf 11、oecd 11、
ths 11、**akshare 10**、finviz 9、nasdaq 9、cboe 8、congress_gov 8、econdb 7 …。
也就是说：**这个 provider 库是为别的数据商建的，不是为 AFI 的 akshare 资产建的**。
akshare 家族只有 10 个 model、11 个源函数。

对 964 个未绑定端点，用 catalog 的 `files[].calls` 反查「哪个 AFI 脚本调用了这个端点函数」，
再用处置台账的 `asset_family` 归类：

| 归到哪个家族 | 端点数 | 该家族是否已有 akshare model |
|---|---|---|
| stock | **368** | 有（`stock_daily` / `stock_action` 两个 model） |
| index | **77** | 有（`index_daily` / `index_constituent`） |
| fund | **74** | 有（`fund_etf_daily`） |
| futures | **56** | 有（`futures_daily`） |
| option | **46** | 有（`option_daily`） |
| bond | **40** | 有（`bond_daily`） |
| other | **278** | **无** |
| fx | **18** | **无** |
| crypto | **3** | **无** |
| 多族 | 4 | — |
| 无调用者 | 0 | — |

**合计 661 个可挂到 8 个已有 akshare 家族模板，299 个落在没有 model 的族（other/fx/crypto），4 个多族。**

这条把工作量从「877 个 provider」改写成一个可执行的形状：
**8 个家族 fetcher × 每个内部多个源函数/参数组合（661）+ 约 299 个新 model（other/fx/crypto）**。
8 个模板已经存在于 `opendata/data/providers/akshare/models/*.py`，所以 B1 的试点应当**优先落在有模板的家族**
（`bond_zh_hs_spot`、`fx_spot_quote` 中的 fx 属无模板族，需要另选一个 futures/index 的样本做对照）。

**必须说明的局限**：这 661 是**按家族做的启发式归类**，不是已完成的绑定——`asset_family` 来自处置台账，
domain 归属需要人工复核；但复核的对象是 **8 个桶**，不是 964 个逐条判断。这正是 B0.0 要产出的东西：
一张「端点 → 家族 → 候选 model」的候选表，加每个桶的抽样复核记录。

---

## 3. 已存在的切换机件（可直接用，不必重造）

| 机件 | 位置 | 状态 |
|---|---|---|
| Publication 生产者 | `services/market_data/publication.py:196-419`：`stage` / `hold_staged_source_snapshot` / `publish_staged` / `publication_for_entity` / `recover_pending` | **存在且有写路径** |
| 可见性锚 | 同文件 `MarketDataVisibilityAnchor.permits(visible_at, visibility_sequence)`（`:142-183`） | 存在 |
| Research binding | `services/market_data/research_binding.py:179-747`：`bind_request` / `resolve_runtime_binding` / `attach_runtime_binding_consumer` / `revoke_runtime_binding` | **存在且有写路径** |
| 能力台账读取 + fail-closed | `services/market_data/capability_ledger.py:103-235` + `:346-369` | 存在 |
| 台账模型 | `models/market_data_platform.py:368+`（append-only 部署证明，带 `descriptor_sha256` / `evidence_sha256` 约束） | schema 存在，0 行 |
| OpenData 控制面 | `opendata/api/**` CRUD + scheduler + worker + admin UI | 骨架存在，资产为空 |
| 单一写入围栏 | `services/akshare/write_fence.py`（已接线 `script.py:1690`、`script_worker.py:121`） | 已接线 |
| 运行协调器 | `services/akshare/run_coordinator.py`（601 行，#289）+ 19 个测试 | **代码在、测试绿、但 `app/` 里零引用** |

## 4. 缺失的机件（这是真正的「迁移」缺口）

1. **能力准入写入器**：`MarketDataCapabilityLedger` 明确「intentionally exposes no request-facing mutation method」（`:86`），
   `scripts/` 里也没有任何写 `md_capability_ledger_entries` 的工具 → **没有任何受支持的途径把一条能力写进台账**。
   没有它，所有 OpenData 路由永久 `CAPABILITY_LEDGER_MISSING`。
2. **OpenData 可运行部署栈**：scheduler 默认关、reviewed runtime 未装配、没有可读的 OpenData 实例（`ACCEPTANCE_AUDIT_20261106.md:60,178`；`CREATE DATABASE` 被拒、docker 不可用）。
3. **Provider 实现**：877 个；**没有脚手架生成器**，model/fetcher 必须手写（见 §5 工序）。
4. **消费者切换**：没有把某个消费者从 AFI 表切到 OpenData publication 的开关/路径；`MARKET_DATA_OPENDATA_ENABLED` 是读取侧且被台账锁死。
5. **管理面接线**：配置中心 → OpenData 控制面的跳转/兼容只到 `204-E05-01 PLANNED`（`SUBAGENT_TASKS.md:197`）；OpenData 侧没有 AFI 那套脚本/任务数据。
6. **单写者切换**：coordinator 未接线（零引用）、29,126 条历史 claim 行未裁定、flag 未定。

---

## 5. 实现一个 provider 的标准工序（从唯一参考脚本反推）

OpenData 里 **`.py` 脚本是惰性参考物**，不被任何 loader 发现；真正生效的是 **provider descriptor**：
`data/providers/catalog.py:182 register_provider()` + 显式 import（`:13-33`），解析入口
`registry.resolve(asset_class, domain, period=, market=, source=)`（`api/data_query.py:283`）。

1. 选定目录条目，确认 `status` 与 `target_models` 绑定；
2. 写/扩 `providers/<source>/models/<dataset>.py`：`QueryParams` + Fetcher，输出归一化行；
3. 用 provider descriptor 的 `fetchers` 注册（并走 facade `register()`）；
4. 声明 `data/domains.yaml`、`data/mappings/<source>.yaml`；
5. 仅为了 parity 才维护 `data_fetch/scripts/**` 参考 shim；
6. 加 golden/parity fixture（捕获源行与归一化结果）；
7. 加 acceptance-probe 条目（measure/judge/repair/breaks）并跑 `--self-test`；
8. 重建目录，确认 `status` 翻转且 `runtime_verification` 有值；
9. 产出 reviewed-run 收据 + `pipeline/visibility_seal.py` 的 `seal_after_commit` 证据，过 `make gate`。

**可自动化**：目录重建（`scripts/ops/build_migration_catalog.py`）、范围清单（`port_scope.py` / `port_scope_inventory.py`）、
源审查证据（`provider_source_review_evidence_build.py`）、probe 自检。
**必须人工**：provider model/fetcher 代码、descriptor import 行、reviewed-run 证据叙述、golden fixture。
**没有**类脚手架生成器 → 这是 877 个 provider 的最大成本项。

也正因如此，**「按目录状态分批」没有意义，必须按运行时重要性 + 可验证性分批**。

---

## 6. 分批计划

### B0 — 前置：把「准入」这条路打通（不做完，任何 provider 都无效）

- B0.1 写**能力准入工具**（受 review 的 CLI/服务，而不是请求面 API）：输入 capability_id、评审过的 descriptor、证据 sha256、有效期；输出 append-only 台账行。验收：台账从 0 行到 1 行，且 `evaluate()` 对该能力返回 effective；负例：descriptor 漂移/过期/证据不符时必须仍 fail-closed。
- B0.2 部署一个**可读的 OpenData 栈**（scheduler 显式关闭也可以；先要能 `resolve()` 到 provider、能出 reviewed-run 收据）。
- B0.3 决定消费者开关的默认值与回滚方式（见 §7 D3）。

### B1 — 试点：3 个数据集端到端（1 高频 + 1 债券 + 1 汇率）

选 `crypto_hourly_market`（147 次/7d）、`bond_zh_hs_spot`、`fx_spot_quote`（50 次/7d）。
理由：都在「正在增长」桶，parity 有基线；三种不同 asset class，能一次暴露 domain/mapping/单位/业务键的通用问题。
每支验收：同窗口同业务键的行级 parity（源 vs OpenData 归一化）、acceptance-probe 条目、reviewed-run 收据、visibility seal、以及 AFI 侧一次真实读取（开关打开后）与回滚演练。

### B2 — 放量：top-20 执行量数据集

按 7 天执行量取前 20（已含 B1 三项）。验收同 B1，另加：每支的 `runtime_verification` 由 NOT_RUN 变为有值，目录 `status` 翻转，且 `make gate` 全绿。

### B3 — 443 个「正在增长」的剩余项

按 asset class 分成 6–8 个子批（stocks / funds / bonds / futures / options / forex+macro / index / 其它），每批 40–70 支。
这批可以做**行级 parity**，是迁移的主体。每批验收：parity 报告 + probe + seal；批次之间不共享开关，逐批可回滚。

### B4 — 148 个「无增量」项

先判「为什么无增量」：是真无新数据（如低频/停更），还是写入路径坏了。**未判清前不迁**——否则迁过去也证明不了 parity。

### B5 — 428 个「从未跑过」项

只能先让它们在 AFI 跑起来产生基线，再迁。**不能把「从未运行」当成迁移完成**。

### B6 — 硬案例（不进入常规批次）

22 个无任务项（属主裁定去留）、9 个幽灵注册、7 个运行时幽灵、7 个 `unexpected_param` 全失败项、快照型端点（无法重建历史）、退市/生命周期缺口、源主机不可达项。
每一项单独登记结论：**删除 / 重建 / 改指向 / 保持 OPEN**，不允许用「迁移完成」掩盖。

### 规模判断（诚实估计）

877 个 provider × 手写 model/fetcher + fixture + probe + 收据。若一人一天 1–2 个，**这是一项 12–24 人月的工作**，
且前提是 B0 先完成、并先做一个脚手架生成器把「注册 + mapping + fixture 骨架」自动化。
**因此必须由属主决定：是「全量迁移」，还是「先迁 top-N + 正在增长的 443，其余长期留在 AFI 并明确登记」。**
本计划建议后者，并把「长尾留在 AFI」写成显式验收结论而不是遗漏。

---

## 7. 属主必须做的决定

| # | 决定 | 影响 |
|---|---|---|
| D1 | 迁移范围：全量 877 / 先 443 正在增长 / 先 top-N | 决定整个计划的规模与工期 |
| D2 | 能力准入由谁签：工具只能生成行，谁做 reviewer 与有效期 | B0.1 的输入 |
| D3 | 消费者开关默认值与回滚窗口（`MARKET_DATA_OPENDATA_ENABLED` 等） | B1 的切换与回滚 |
| D4 | OpenData 部署栈放哪、谁运维、是否允许建库 | B0.2 |
| D5 | 单写者切换：coordinator 接线 + 29,126 条历史 claim 行处置 + flag | AC13 |
| D6 | 配置中心处置：跳转、并存、还是下线（`204-E05-01`） | 管理面迁移的用户可见部分 |
| D7 | 22 个无任务目录项、9 幽灵注册、7 运行时幽灵的去留 | B6 |
| D8 | 长尾（not_run 428 + no_delta 148）是否接受「暂不迁移」并登记 | 验收口径 |

### 7.1 D5（单写者接线）的可执行方案：一处调用点，一个开关

AC13 的实现已在 dev（`run_coordinator.py` 601 行 + `write_fence.py` + 迁移 + 19 个测试），
缺的是生产路径上的接线。接线点是一处，不是一处架构改造：

现在 `services/akshare/script.py:1690` 这样开围栏：

```python
fence_token = set_write_fence(
    claim_key=f"akshare_script:{script.script_id}",
    owner_id=str(execution.execution_id),
    fencing_token=int(execution.id),      # <-- 每次执行的局部序号
    execution_id=str(execution.execution_id),
)
```

`fencing_token` 取的是**执行行 id**，不是 claim 的单调令牌——所以晚到的旧 worker 不会被令牌挡住，
这正是「单写者」缺的那一跳。接上 coordinator 之后形状是：

```python
if settings.akshare_run_coordinator_enabled:
    outcome = await coordinator.try_claim(
        claim_key=f"akshare_script:{script.script_id}",
        owner_id=str(execution.execution_id),
        task_id=task_id, script_id=script.script_id, source=source,
        period_key=period_key, parameter_hash=parameter_hash,
        parameters=parameters, max_attempts=...,
    )
    if outcome.state != "claimed":
        # 不跑，按冲突/未到期结算这次执行行，并写清 reason
        ...
    await coordinator.set_execution_id(outcome.lease, str(execution.execution_id))
    fence_token = set_write_fence(..., fencing_token=outcome.lease.fencing_token, ...)
else:
    ...现有路径...
```

并在同一函数的收尾处按结果调用 `complete` / `fail` / `cancel`，外加一个用
`recoverable_claims()` 的回收循环。`RunLease.fencing_token` 才是随 claim 单调递增的令牌
（`run_coordinator.py:59-68, 93-138`）。

**为什么这需要属主裁定而不是直接写**：开关的默认值决定生产行为；29,126 条历史 claim 行
（迁移已建表）在开关打开时会被 `try_claim` 视作已有占用还是历史噪声，取决于滚动策略；
以及 `period_key` / `parameter_hash` 的取值口径（`cron:<UTC ISO>` vs `day:<Shanghai date>`，
见 `try_claim` docstring）会直接改变哪些手动运行被允许。这三件都不是代码能替属主定的。
**代码量可估**：1 个调用点 + 3 个收尾调用 + 1 个回收循环 + 1 个设置项 + 测试，属于 S 级改动。

---

## 8. 本计划不声称的事

- 不声称任何 AC 已通过：AC16 PARTIAL、AC13/AC18 NOT_RUN、AC17 BLOCKED_ON_OWNER，18 行无一 PASSED（`ACCEPTANCE_AUDIT_20261106.md:38-42`）。
- 不把「目录里 READY_FOR_ADAPTER 1 条」当成已迁移（目录 notice 自己否定了这一点）。
- 不把「provider 测试通过」当成 parity 通过；parity 必须是同窗口、同业务键、行级对照。
- 不把本机读数当 CI 基线：本机环境身份仪器自判 `allowed=false`（py3.13.5、system-site-packages、14 个依赖在 venv 外）。

**可复跑**：`evidence/2026-11-09-migration-binding/provider_binding_candidates.py`
（默认只输出汇总；`--include-rows` 输出 964 行逐条分类），其输出
`evidence/2026-11-09-migration-binding/provider_binding_candidates.json` 记录了本节 661/299/4
与 10/319 的全部来源。任何复核者都可以用同一条命令重算，不需要相信这段文字。
