# 迭代204 子任务台账对账（SUBTASK LEDGER RECONCILIATION, 2026-11-06）

> **本文是开发范围的可追溯性台账，不是验收。** 它只回答一个问题：计划在 `SUBAGENT_TASKS.md` 里声明的 99 个子任务 id，截至今天有多少能落到我亲自验证的产物上。> **它不改变任何 AC 结论**（AC01–AC18 的判定仍由 [ACCEPTANCE_AND_CUTOVER.md](ACCEPTANCE_AND_CUTOVER.md)、`ACCEPTANCE_AUDIT_20261106.md`（尚未合入：它只存在于开 PR AFI #288，因此本文不对其做链接）与 `DEVELOPMENT_STATUS.md` 持有）。> **日历与 owner 绑定项不能靠改台账关闭**：AC05（全历史/逐标的终点）与 AC14（自然发布周期）这类项，要么等真实源发布周期到达后被观察到，要么等 owner 完成逐域切换授权；本文把它们记为 `PARTIAL` / `NOT_STARTED` / `BLOCKED_ON_OWNER` 并给出缺失证明，绝不把它们写成完成。

## 0. 基线与验证方法（全部本人执行，先验后引）

| 项 | 值 | 取得方式 |
| --- | --- | --- |
| AFI `dev` tip | `3e9f4a76e5a33a9493597d0e0fc4f77da87c6db0` | `git rev-parse HEAD`（工作树 `.wt-afi-ledger`）与 `git ls-remote --heads origin refs/heads/dev` 双读一致 |
| OpenData `dev` tip | `1815e2a2a66ea28afb27b4d2d88e81a832a261c0` | `git ls-remote https://github.com/cloudQuant/opendata.git refs/heads/dev`；同时是已合入 PR #195 的落地提交 |
| OpenData 合入树分母 | 11,137 个 blob 路径，`truncated=false` | GitHub API `GET /repos/cloudQuant/opendata/git/trees/1815e2a2a…?recursive=1` |
| AFI 合入树分母 | 7,768 个跟踪文件 | `git ls-files`（在 `3e9f4a76e`） |
| 本波 AFI PR | #273、#274、#278、#280–#295 全部 `state=open`、base=`dev`、未合并；#275 `merged=true`，merge commit = `3e9f4a76e5a33a9493597d0e0fc4f77da87c6db0` | GitHub API `GET /repos/cloudQuant/ai-for-investor/pulls/N` 逐个读取，写文件清单取自 `GET …/pulls/N/files` |
| 被取代的同标题关闭 PR | #272→#281、#276→#282、#277→#283、#279→#284（均 `closed` 且 `merged=false`） | 同上 |
| OpenData 本波 PR | #195 merged；#196（head `7c4c43f89a`，8 个文件）、#197（head `5a41a3284e`，12 个文件）、#198、#199 open | GitHub API `pulls`/`pulls/N/files` |

本文所有“缺失证明”都是同一个可复现动作的结果，下称 **路径扫描**（口径是文件路径字符串，不是文件内容）：

```bash
# OpenData：对 11,137 个 blob 路径做子串命中统计（排除 docs/ 后的代码/测试/迁移面）
GET /repos/cloudQuant/opendata/git/trees/1815e2a2a66ea28afb27b4d2d88e81a832a261c0?recursive=1
  → [p for p in paths if not p.startswith('docs/') and '<子串>' in p.lower()]

# AFI：对 7,768 个跟踪文件做同样的路径扫描
git ls-files | grep -i '<子串>'
```

两个易造成误读的假阳性已单独标注：子串 `rpo` 在 OpenData 的 4 个命中全部来自 `corporate_events*` 文件名；子串 `nav` 的唯一命中是 `frontend/src/__tests__/layout-navigation.test.ts`。它们都不构成声明产物。

## 1. 状态语义与硬规则（本文执行的判定标准）

- **DEV_DONE**：必须同时满足 ① 表内验收面恰为 `CODE/OFFLINE`（不含 `REAL_SOURCE`/`DEPLOYMENT`/`NATURAL_CYCLE`）；② 声明的“具体交付”对应的产物已在合入 tip 上存在，我逐个给出路径；③ 至少一个对应测试文件/门禁脚本同样在合入 tip 上存在。三条缺一则降为 `PARTIAL`。
- **PARTIAL**：声明交付的一部分有合入产物，或实现只存在于**开 PR**（此时必须点名 PR 编号与头 SHA，并写 `delivered, unmerged`）。`REAL_SOURCE`/`DEPLOYMENT`/`NATURAL_CYCLE` 面未闭合的混合面子任务按计划第 14 行约定只能停在这里。
- **NOT_STARTED**：路径扫描/文件检索找不到声明产物，或唯一相关产物既不属本迭代也不做声明的事（例如 vendored akshare 函数库、旧采集面补数脚本）；我在证据栏给出查询与零结果。
- **BLOCKED_ON_OWNER**：声明本身要求 owner 决策/切换授权/自然周期到达，在此之前无任何可开发的产物。
- **未对任何 id 使用“大概在某个 PR 里做过”作为升级理由**；凡引用 PR/提交/路径/行号均由本文第 0 节的方法重新读回。

## 2. 状态分布（99 个 id 全量，无遗漏）

| 状态 | 数量 | 占比 |
| --- | --- | --- |
| `DEV_DONE` | 10 | 10.1% |
| `PARTIAL` | 61 | 61.6% |
| `NOT_STARTED` | 23 | 23.2% |
| `BLOCKED_ON_OWNER` | 5 | 5.1% |
| 合计 | 99 | 100% |

对比计划自身的快照：五张泳道表的状态列（as of 2026-10-29）本人重测为 **PLANNED 80 / IN_PROGRESS 11 / DEV_DONE 8**（合计 99），与 `SUBAGENT_TASKS.md:3` 自述的“8个DEV_DONE、11个IN_PROGRESS、79个PLANNED”一致（差的 1 项是 2026-10-30 新增的 `204-B05-03`，它不属于原 98 项快照）。因此“零项完成”的说法不可复现：表内确实写了 8 项 `DEV_DONE`。

本文给予 `DEV_DONE` 的共 **10** 项：`204-A02-04`、`204-A06-01`、`204-B02-01`、`204-D02-01`、`204-D02-02`、`204-D02-03`、`204-D05-01`、`204-E01-01`、`204-E02-01`、`204-E02-02`。其中 8 项是计划表内已自标 `DEV_DONE` 且我独立验到产物；另外 2 项（`204-B02-01`、`204-E01-01`）是表内 IN_PROGRESS/PLANNED 但声明的具体交付已在合入树里逐项可见，我把它们升级并在下文逐条写明依据。

## 3. 重复行如何处理（台账脏乱的定量化说明）

- `SUBAGENT_TASKS.md` 全文共 **130** 个含 id 的表格行，对应 **99** 个不同 id。拆解：
  - **99 行是定义行**：五张泳道表（A 25 / B 20 / C 14 / D 19 / E 21）恰好每个 id 一行，无重复、无遗漏。本文的“声明内容/owner/验收面/表内状态”全部只取这 99 行。
  - **24 行是跨引用**：同一 id 出现在别的行的《前置依赖》列里（例如 `204-A02-02` 在 11 行里出现，其中只有一行是定义）。
  - **6 行是《首批子任务精确范围》表**（209–214），只给“当前代理/本轮不包含”，不重定义范围。
  - **20 行是两张增量证据表**（51–60、68–77，`2026-10-31` 两节），给部分 id 补了部分证据与剩余面。
- **缩写展开**：矩阵表用 `204-A03-01/02`、`204-B02-01/02/03/04/05` 这类缩写，共 23 处；展开后《当前基线与近期执行矩阵》覆盖 60 个 id，剩 39 个 id 不在该矩阵里。展开后未发现一个 id 被划到两个泳道，也未发现矩阵泳道与泳道表 owner 前缀相矛盾的 id。
- 另有 1 处真正的“一行挂两个 id”：`SUBAGENT_TASKS.md:76` 的证据行把 `204-B01-01` 与 `204-B01-02` 合并为一行，而泳道表给它们两套不同的验收面（CODE/OFFLINE vs REAL_SOURCE）。本文按行内句号拆开处理。

## 4. 逐条台账（99 项）

每项给出：计划原文（直接引用，不意译）、出处 `file:line`、父 WP、owner、验收面、表内声明状态、本文状态与我亲自验证的产物。

### 泳道 A — A：平台与数据契约

#### `204-A01-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:85`（父WP `A01`，owner `A / root`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `—`）
- 声明的具体交付：

  > 记录两仓基线提交、脏文件路径与哈希、运行时/依赖版本、数据库迁移head、工具版本；秘密只记录存在性，不读出或复制。

- 状态：`PARTIAL`
- 证据：SUBAGENT_TASKS.md:23 记录 AFI `b825f921476b6e698881e1be68993c8a4ac610e1` 与 OpenData `373211d246ab3099ac8c551681c0f1703fcbd964`；:27 记录 2026-10-30 快照 `73c7b2f75…`/`cc7965417…`。两仓当前 dev tip 已用 `git ls-remote` 复核：AFI=3e9f4a76e5、OpenData=1815e2a2a6。
- 剩余/原因：脏文件哈希、运行时/依赖版本、数据库迁移 head、工具版本没有作为可重现清单落在任何合并文件里，因此不升级为 DEV_DONE。

#### `204-A01-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:86`（父WP `A01`，owner `A / root`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 建立所有权与ADR索引，标记共享契约、总路由、公共依赖、迁移序列、provider域、客户端和UI文件owner。

- 状态：`PARTIAL`
- 证据：SUBAGENT_TASKS.md:37–41 的五泳道独占文件/owner 表已在 AFI@3e9f4a76e 合入；`docs/adr/` 有 15 个 ADR（000–013 + README），但 grep `docs/adr/` 无 `迭代204`/`opendata`/`ownership` 命中，即没有为共享契约/总路由/依赖锁/Alembic 序列建立的 ADR 索引条目。
- 剩余/原因：所有权记录只存在于本清单散文表，不在 ADR 索引里。

#### `204-A02-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:87`（父WP `A02`，owner `A / 契约代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 冻结v1兼容约束和v2 OpenAPI骨架：端点、认证、闭/半开区间、分页、错误信封、版本字段。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 有 `docs/afi204-v1-openapi.json`（实测 `paths` = 140）与 `docs/afi204-v2-openapi.json`（实测 `paths` = 9），两者均含 `info.version` = `0.1.0`、`components`、分页与错误信封字段。
- 剩余/原因：声明要求的“每项拟议能力标明现存或待实现”没有可核对的逐项标注产物；认证/闭区间/半开区间语义只在契约文本层面可见，未逐项核验。

#### `204-A02-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:88`（父WP `A02`，owner `A / 契约代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-01`）
- 声明的具体交付：

  > 逐数据集身份、instrument、业务时间/事件时间/可得时间、单位/币种、Decimal、空值、质量和许可schema。

- 状态：`PARTIAL`
- 证据：`docs/afi204-v2-openapi.json` 中出现 `adjustment_basis`、`annual`、`quarterly`（脚本内字符串判定为 True）；`opendata/data/temporal_instrument_identity.py`、`opendata/pipeline/history_coverage.py` 在 tip 存在。
- 剩余/原因：声明要求 schema 示例同时覆盖股票日线、基金NAV、曲线或财务修订四类语义；blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 中子串 `nav` 命中 0、`decimal` 命中 0，基金NAV 与 Decimal 单位语义没有可核对 schema 条目，故不能升级为 DEV_DONE。

#### `204-A02-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:89`（父WP `A02`，owner `A / 契约代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-01, 204-A02-02`）
- 声明的具体交付：

  > 提供黄金fixture、错误fixture和可本地运行的mock服务，供opendata API及AFI client并行开发。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `tests/fixtures/upstream/stock_daily_raw/meta.json`、`tests/fixtures/upstream/stock_daily_sina_qfq/{meta.json,reference.csv.gz,responses.json.gz}`；AFI tip 存在 `src/backend/tests/test_opendata_stock_daily_real_sample_replay_wire.py`、`test_opendata_v2_cross_repository_wire.py`。
- 剩余/原因：“同一 fixture 驱动服务端与客户端合同测试”只在我看到文件名、未逐行证明两端读同一 fixture 的范围内成立；声明里的“可本地运行的mock服务”没有对应产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `mock_server` 命中 0。

#### `204-A02-04` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:90`（父WP `A02`，owner `A / wave3_contract_gate`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（代码/离线门禁）`，前置依赖 `204-A02-03`）
- 声明的具体交付：

  > 加入OpenAPI兼容性门禁、schema版本规则和破坏性变更检查。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `scripts/quality/check_published_openapi.py`（首行 docstring：`Fail closed when the published HTTP API drifts from its reviewed contract.`）与 `tests/test_published_openapi_gate.py`（`def test_` 计数 = 29）。冻结面为 `docs/afi204-v1-openapi.json`（140 paths）与 `docs/afi204-v2-openapi.json`（9 paths）。
- 剩余/原因：计划行 90 写的是“24项行为测试”“v2共6路径”，实测为 29 个测试、9 条 v2 路径；差异见冲突章节，OpenData #159 之后基线被刷新过。

#### `204-A03-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:91`（父WP `A03`，owner `A / 元数据代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-02`）
- 声明的具体交付：

  > 定义dataset/schema版本、来源、负责人、许可和域注册表的元数据模型及首个迁移提案。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `alembic/versions/2026_10_26-0007_job_definitions.py`、`alembic/versions/2026_10_28-0008_metadata_publication_receipt.py`、`docs/migrations/metadata-publication-receipt-0008.md`、`opendata/job_definition_store.py`、`tests/test_job_definition_migration.py`。
- 剩余/原因：这些是 job/publication-receipt 元数据，不是声明要求的 dataset/schema版本/来源/负责人/许可/域注册表模型：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `license` 命中 3（全部是 LICENSE 文件本身）、`dataset_metadata` 命中 0。

#### `204-A03-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:92`（父WP `A03`，owner `A / wave4_reference`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-A03-01`）
- 声明的具体交付：

  > 定义instrument稳定ID、别名生效区间、上市/退市/到期生命周期和交易日历版本接口。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/data/temporal_instrument_identity.py`、`opendata/data/temporal_instrument_identity_snapshot.py`、`tests/test_temporal_instrument_identity.py`、`tests/test_temporal_instrument_identity_snapshot.py`；交易日历在 `opendata/pipeline/trading_calendar.py`。
- 剩余/原因：计划 SUBAGENT_TASKS.md:75 自己记录 OpenData #152 的 universe 仍 `分页终止 UNKNOWN`、`无退市生命周期`、`universe_census_attested=false`；声明要求的基金份额类别/到期合约/换码 fixture 覆盖未在 tip 产物中体现。

#### `204-A04-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:93`（父WP `A04`，owner `A / 存储代理`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-A03-01`）
- 声明的具体交付：

  > 增加raw响应证据引用与受控artifact manifest合同，包含请求摘要、内容hash、采集时刻、状态和保留策略。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/stock_daily_gap_evidence_bundle.py`、`tests/test_stock_daily_gap_evidence_bundle.py`、`tests/test_stock_daily_gap_evidence_content_edges.py`、`opendata/data/raw_response_cache.py`、`tests/test_ths_raw_response_capture.py`。
- 剩余/原因：声明要求的“受控 artifact manifest 合同”没有产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `artifact_manifest` 命中 0、`evidence_ref` 命中 0（AFI 侧唯一命中是无关的 `openbb_yfinance_runtime_artifact_manifest.json`）。

#### `204-A04-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:94`（父WP `A04`，owner `A / 存储代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-01, 204-A03-02`）
- 声明的具体交付：

  > 建立ODS到DWD的来源血缘、转换版本、修订链、可得时点和固定publication/snapshot版本字段。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `lineage` 命中 0；`revision_chain` 命中 0。AFI 侧 `git ls-files | grep -i lineage` 只命中迭代202的一个 TLS 指纹台账文件名，与本声明无关。
- 剩余/原因：ODS→DWD 来源血缘/转换版本/修订链/snapshot 版本字段在任何一仓 tip 都没有实现。

#### `204-A04-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:95`（父WP `A04`，owner `A / 存储代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-02, 204-D02-01`）
- 声明的具体交付：

  > 定义候选分区验证、原子publication指针和跨metadata/warehouse receipt/outbox的可重放提交。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `alembic_data/versions/20261026-0011_publication_snapshots.py`、`alembic_data/versions/20261028-0018_publication_outbox.py`、`tests/test_publication_coverage_integrity_edges.py`、`tests/test_deferred_publication*.py`（AFI tip 亦有 `src/backend/alembic/versions/20260911_market_data_deferred_publications.py`）。
- 剩余/原因：声明的验收面是故障注入证明“提交状态不领先事实数据”，我没有找到对应的故障注入用例名落在合并代码里；`visibility` 在 tip 命中 0（见 A04-04）。

#### `204-A04-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:96`（父WP `A04`，owner `A / visibility-ledger代理`，验收面 `CODE/OFFLINE+DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-A04-03, 204-D02-01`）
- 声明的具体交付：

  > 新增post-commit publication visibility seal及持久单调visibility sequence。只有publication涉及的warehouse事实分区、publication指针和跨库receipt均提交，且read-after-commit确认可读后才封存；保留现有事务内`published_at`为非证明性字段，使用可信UTC时钟并检测回拨/不可信时钟，失败时不封存。

- 状态：`PARTIAL`
- 证据：仅在开 PR：OpenData #196（`state=open`，head `7c4c43f89a`，文件清单实测 8 个）新增 `opendata/pipeline/visibility_seal.py`、`alembic_data/versions/20261031-0022_publication_visibility_seal.py`、`tests/test_visibility_seal.py`、`tests/test_visibility_seal_migration.py`。tip 1815e2a2a6 上 `visibility` 命中 0。
- 剩余/原因：按硬规则 2，未合入最高只记 PARTIAL (delivered, unmerged)，且本行验收面含 DEPLOYMENT。

#### `204-A05-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:97`（父WP `A05`，owner `A / API代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-03, 204-A03-01`）
- 声明的具体交付：

  > 实现兼容v1只读端点及固定latest-view行为，沿用既有闭区间和count语义。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 的 `docs/afi204-v1-openapi.json` 冻结 140 条 v1 路径（含 `/api/data/catalog`、`/api/data/domains/{domain}/freshness`、`/api/data/download`），由 `scripts/quality/check_published_openapi.py` + `tests/test_published_openapi_gate.py`（29 项）作为兼容门禁。
- 剩余/原因：声明的“普通读身份不能触发 provider 抓取或写入”我没有找到对应的合并用例；`opendata/api/data.py`、`data_query.py` 是既有实现，不能当成本子任务的交付证明。

#### `204-A05-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:98`（父WP `A05`，owner `A / API代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-03, 204-A03-02`）
- 声明的具体交付：

  > 实现v2目录、标的、日历、records、coverage和snapshot只读服务的首批端点。

- 状态：`PARTIAL`
- 证据：`docs/afi204-v2-openapi.json` 实测 9 条路径：`/api/v2/datasets`、`/api/v2/datasets/{dataset_id}`、`/api/v2/datasets/{dataset_id}/records`、`/api/v2/datasets/{dataset_id}/coverage`、`/api/v2/datasets/{dataset_id}/capture-candidates`、`/api/v2/identity/resolve`、`/api/v2/snapshots`、`/api/v2/snapshots/{snapshot_id}`、`/api/v2/data/financial-statements/archive`。
- 剩余/原因：声明列出“目录、标的、日历、records、coverage、snapshot”六类，其中“日历”端点在 v2 面缺失（9 条里没有 calendar 路径），因此是 PARTIAL 而非 DEV_DONE。

#### `204-A05-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:99`（父WP `A05`，owner `A / API代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A05-01, 204-A05-02`）
- 声明的具体交付：

  > 实现分页/行数/响应体/超时边界、异步大导出入口、scope/许可门禁及稳定错误码。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/api/rate_limit.py`、`opendata/core/api_key_rate_limit.py`、`opendata/api/provider_model_export.py`、`opendata/services/provider_model_export_request.py`；`opendata/pipeline/request_budget` 相关见 `opendata/data/request_budget.py`。
- 剩余/原因：“异步大导出入口 + 429/503 稳定错误码 + scope/许可门禁”只逐项存在文件，未证明三者构成声明的同一入口；许可维度 blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `license` 命中 0（非 LICENSE 文件）。

#### `204-A05-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:100`（父WP `A05`，owner `A / OpenData records合同代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-02, 204-A04-04, 204-A05-02`）
- 声明的具体交付：

  > 为股票日线新增reviewed v2 records合同；当前v2 publication sequence本身不足以构成股票日线接口。固定publication_id/sequence和可验证visibility seal，返回instrument、`business_date`、`observed_at`、`visibility_sealed_at`、来源、原生字段/单位及schema既有枚举`adjustment_basis=raw`；不提供虚构的逐行`available_at`，v1保持不变。`business_date`按交易所日历`Asia/Shanghai`解释，instant按带时区RFC3339归一为UTC。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/api/stock_daily_publication.py`（`git log --path` 最新提交 `a76b48580 feat(stock-daily): gate reads and run pinned backfills (#150)`，前一提交 `2b616245d feat(api): prepare gated stock daily publication reads (#146)`）；v2 契约含 `adjustment_basis`。
- 剩余/原因：声明把 `visibility_sealed_at` 作为必返字段，而 visibility seal 只在未合入的 OpenData #196 里；tip 上 `visibility` 命中 0，故最多 PARTIAL。

#### `204-A05-05` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:101`（父WP `A05`，owner `A / OpenData auth代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-01, 204-A03-01, 204-A05-03`）
- 声明的具体交付：

  > 给研究读取增加双重授权：实际用户对目标dataset/标的/研究用途具有精确`READ_DATA`，且用户的source research grant覆盖实际来源、dataset、市场和用途；后台调用须携带委托用户身份并在执行、读取和结果发布前重新校验授权版本。

- 状态：`PARTIAL`
- 证据：AFI 已合并：`1af1366cc feat(data): add exact snapshot grant storage (#201)`、`b825f9214 feat(stock-analysis): authorize pinned stock daily publication reads (#204)`（两者都在 `git log --oneline dev` 输出中，且 tip=3e9f4a76e5）。OpenData 已合并 #146 路由含读 grant 依赖。
- 剩余/原因：计划 SUBAGENT_TASKS.md:29 明确：grant 存储默认为空、无签发/撤销认证、无 registry revision 比对；`DEPLOYMENT`/真实 grant 验收面未闭合。

#### `204-A05-06` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:102`（父WP `A05`，owner `A / financial records合同代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-02, 204-A03-02, 204-A04-04, 204-A05-02`）
- 声明的具体交付：

  > 定义并实现股票财务v2 dataset/records合同：annual/quarterly report_type，statement_type，instrument、报告期起止业务日期与稳定metric/business key；修订作为可追溯观察版本，不静默覆盖历史。保留来源原始字段、单位/币种，source timestamp缺失时为UNKNOWN；固定publication查询并分页，返回post-commit `visibility_sealed_at`。所有instant按RFC3339时区规则保存原值及版本化转换规则，`business_date`按对应市场日历定义。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/api/financial_observation_archive.py`、`docs/afi204-v2-openapi.json` 的 `/api/v2/data/financial-statements/archive` 与 `annual`/`quarterly` 字面；`opendata/data/providers/sina/financial_statement_publication.py`、`opendata/fuyao_financial_evidence_coverage.py`、`tests/test_fuyao_capture_gate_trace_integration.py` 亦在 tip。
- 剩余/原因：声明要求返回 post-commit `visibility_sealed_at` 与“同一期多次修订”合同测试；seal 只在未合入的 #196，故不升级。

#### `204-A05-07` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:103`（父WP `A05`，owner `A / snapshot与visibility查询代理`，验收面 `CODE/OFFLINE+DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-A04-04, 204-A05-04, 204-A05-06`）
- 声明的具体交付：

  > 为研究查询提供cutoff与visibility sequence双约束及固定多dataset snapshot vector；vector固定每个dataset的publication_id/sequence、visibility seal、content/contract hash和过滤条件。snapshot临时ID不承担报告保留；定义publication/vector长期保留期并提供稳定可解析引用。

- 状态：`PARTIAL`
- 证据：tip 有 `opendata_client/opendata_client/snapshots.py` 与 v2 `/api/v2/snapshots` 两条路径；cutoff/sequence 双约束与多 dataset snapshot vector 的实现只在未合入的 OpenData #196（seal 列）与 #197（容量/覆盖运维页）里。
- 剩余/原因：声明要求“现有最多7天 snapshot TTL 不够时必须拒绝长期重放承诺”，我没有在合并产物中找到该拒绝路径的用例名。

#### `204-A06-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:104`（父WP `A06`，owner `A / dev_coverage`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅代码/离线）`，前置依赖 `204-A02-02`）
- 声明的具体交付：

  > 实现逐标的日粒度head/interior/tail缺口纯函数；输入预期交易日/生命周期边界和观测业务日期，输出缺口段及状态，不接数据库、不抓源、不判定上市边界真伪。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `opendata/pipeline/history_coverage.py` + `tests/test_history_coverage.py`；并且 `opendata/pipeline/stock_daily_reconcile.py:21` 实际 `from opendata.pipeline.history_coverage import (… evaluate_history_coverage …)`，第 849 行使用 `coverage.head_gaps + coverage.interior_gaps + coverage.tail_gaps`——head/interior/tail 三段语义在合入代码里可执行。
- 剩余/原因：计划行 104 自标 DEV_DONE（仅代码/离线），我的独立核验与之一致；父 WP A06 仍开放。

#### `204-A06-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:105`（父WP `A06`，owner `A / 质量代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-A06-01`）
- 声明的具体交付：

  > 为首批dataset配置主键、重复、单位、时间、跨表和发布质量规则及严重级别。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `alembic_data/versions/20260923-0002_dq_diff_report.py`、`opendata/pipeline/coverage_service.py`、`tests/test_coverage_service.py`；AFI tip 存在 `src/backend/app/services/market_data/field_quality.py`、`src/backend/tests/market_data_platform/test_field_quality.py`。
- 剩余/原因：声明要求“为首批 dataset 配置主键、重复、单位、时间、跨表和发布质量规则及严重级别”这一逐项规则集；我没有找到带严重级别的分 dataset 规则清单产物，故 PARTIAL。

#### `204-A06-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:106`（父WP `A06`，owner `A / 质量代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-B01-02, 204-C01-02`）
- 声明的具体交付：

  > 为源受限/缺历史记录真实请求参数、最早可回溯点、许可/保留证据、责任人及复查触发条件。

- 状态：`PARTIAL`
- 证据：已合并的相邻产物：本目录 `SOURCE_RIGHTS_REVIEW.md`、`INVENTORY_AUDIT_20261105.md`（两者都在 AFI@3e9f4a76e 的文件清单里，`git ls-files` 可见）。
- 剩余/原因：声明验收面是 REAL_SOURCE（真实请求参数、最早可回溯点、许可/保留证据、责任人、复查触发条件）。这些文档是权利/清单审查，不是逐 dataset 的真实请求证据台账；按硬规则，REAL_SOURCE 面未闭合，不能升级。

#### `204-A06-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:107`（父WP `A06`，owner `A / coverage与主数据代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-A05-06, 204-A06-01, 204-A06-02`）
- 声明的具体交付：

  > 建立股票分析按`instrument_id × dataset_id × publication × 窗口`的分数据族coverage合同。日线预期键由每个目标交易所经验证的`Asia/Shanghai`交易日历及上市/退市边界决定；财报预期键由annual/quarterly类型、报告期集合和经review的数据源/数据集披露周期决定，不能套用交易日历。无法独立证明证券目录分母、分页完整性、日历、生命周期、报告期或周期时为UNKNOWN。当前API尚不支持BSE是实现现状，不得将北交所从全A股目标范围中排除。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/coverage_service.py`、`opendata/pipeline/financial_period_coverage.py`、`opendata/pipeline/query_window_coverage.py`、`opendata/data/coverage_evidence_registry.py` + `tests/test_coverage_evidence_registry.py`；AFI tip 有 `src/backend/app/services/market_data_coverage_service.py`。
- 剩余/原因：声明要求 venue 分母缺失时返回 `NOT_SUPPORTED` 且总体保持 UNKNOWN，并逐项覆盖 4/8/920 拒绝；我没有在合并代码里定位到该显式 NOT_SUPPORTED 分支的用例名，且 BSE 支持本身未闭合。

#### `204-A07-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:108`（父WP `A07`，owner `A / root`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-04, 204-A05-03, 204-E06-02`）
- 声明的具体交付：

  > 形成跨仓发布manifest和合同/依赖兼容门禁，绑定opendata commit、AFI commit、client版本、schema及数据publication。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `release_manifest` 命中 0；git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 子串 `release_manifest` 命中 0；`cross-repo release` 在 docs 中只出现在计划自述里。
- 剩余/原因：跨仓发布 manifest（绑定 opendata commit + AFI commit + client 版本 + schema + publication）没有任何可核对产物。

#### `204-A07-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:109`（父WP `A07`，owner `A / root`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-A07-01, 204-B07-03, 204-C07-02, 204-D07-03, 204-E07-02`）
- 声明的具体交付：

  > 汇总最终范围、未迁项、源限制、回滚条件、运营owner与阶段发布说明，提交关闭/阶段发布评审。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #288（`state=open`，head `c928b28e61c4baefbe7038557b63ceb39d4f5f19`）新增 `docs/iterations/…/ACCEPTANCE_AUDIT_20261106.md`（1 个文件）。
- 剩余/原因：声明验收面是 DEPLOYMENT 且要求“提交关闭/阶段发布评审”；这是一份审计文档，不是阶段发布评审，也未合入。

### 泳道 B — B：证券数据适配

#### `204-B01-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:115`（父WP `B01`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 刷新证券候选资产清单并分批逐项处置；607是2026-10-26静态CSV历史候选数，不是当前总数。记录旧脚本hash、输入参数、数据集、provider、落库、消费者、许可和REUSE/EXTEND/CONSOLIDATE等决策。

- 状态：`PARTIAL`
- 证据：已合并：本目录 `INVENTORY.md`、`INVENTORY_AUDIT_20261105.md`、`script_migration_inventory.csv`（均在 AFI@3e9f4a76e）。仅在开 PR：AFI #286（head `75e5acf3ad07894c1b775b413656266faa5a10ae`）新增 `script_disposition_ledger.csv/.json` + `src/backend/scripts/ops/assign_script_dispositions.py` + `tests/test_assign_script_dispositions.py`；AFI #274（head `835c43653137e9ef374fb92f28f102377707a1b4`）刷新 `INVENTORY.md`。
- 剩余/原因：逐候选的 REUSE/EXTEND/CONSOLIDATE 处置台账仍未合入 dev，因此不升级。

#### `204-B01-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:116`（父WP `B01`，owner `B / 证券代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 选10个证券代表案例，实测简单、复权、财报报告期/修订/来源时间语义、多表、源限流/失效等源能力与字段语义。

- 状态：`NOT_STARTED`
- 证据：缺失证据：我在计划目录 39 个 markdown 文件里检索“10个证券代表案例/代表案例”的逐项记录，只有 SUBAGENT_TASKS.md:116 的声明本身；两仓 tip 都没有逐案例的真实源记录产物（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 中 `representative_case` 命中 0）。
- 剩余/原因：声明验收面是 REAL_SOURCE。OpenData #150/#151 回放的是既往捕获字节，计划 SUBAGENT_TASKS.md:73/74 自己写明“不能作为 REAL_SOURCE 验收”。

#### `204-B02-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:117`（父WP `B02`，owner `B / wave4_stock_job`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-A02-02`）
- 声明的具体交付：

  > 完成股票日线M1样板Provider、标准映射和fixture，采用schema枚举`adjustment_basis=raw`，分离价格、成交量/额单位与源字段。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 上 `opendata/data/providers/akshare/stock_daily_native.py`、`opendata/data/providers/akshare/stock_daily_mapper.py`、`opendata/data/providers/akshare/stock_daily_wire.py`、`opendata/pipeline/stock_daily_native_mapping.py`，配套测试 `tests/test_stock_daily_native.py`、`tests/test_stock_daily_native_mapping.py`，fixture `tests/fixtures/upstream/stock_daily_raw/meta.json`；schema 枚举 `adjustment_basis` 出现在 `docs/afi204-v2-openapi.json`。
- 剩余/原因：计划行 117 自标 IN_PROGRESS；我按声明的具体交付（样板 Provider + 标准映射 + fixture + `adjustment_basis=raw` + 价格/量额单位分离）逐项核到合并文件与测试，故记 DEV_DONE；真实源验收另属 204-B02-02/04，父 WP B02 仍开放。

#### `204-B02-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:118`（父WP `B02`，owner `B / 证券代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-B02-01`）
- 声明的具体交付：

  > 对选定股票真实抓取日线，核对源参数、交易日、原始响应、字段及许可/历史保留边界。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #283（head `a8dca0486e0bc37ca23aa9a10a575cc7ebc7735b`）新增 `src/backend/scripts/stock_full_history_controller.py` + 对应测试。已合并的相邻产物：opendata@1815e2a2a 的 `opendata/pipeline/stock_daily_reconcile.py`（`git log --path` 首现 `34f6e1465 feat(pipeline): reconcile stock daily history gaps (#71)`）。
- 剩余/原因：声明验收面 REAL_SOURCE（真实抓取 + 逐字段比对 + 上市起点与源最早返回日分开）未闭合。

#### `204-B02-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:119`（父WP `B02`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-B02-01`）
- 声明的具体交付：

  > 形成股票universe/上市退市、公司行动和独立复权数据集方案。

- 状态：`PARTIAL`
- 证据：已合并：本目录 `STOCK_DAILY_V2_DELIVERY_PLAN.md`、`IDENTITY_BOUND_STOCK_DAILY_V2.md`、`OFFICIAL_A_SHARE_UNIVERSE_SOURCES.md`（AFI@3e9f4a76e）；opendata@1815e2a2a 的 `alembic_data/versions/20260923-0005_dwd_stock_adjust.py`、`20260930-0007_affine_stock_adjust.py`。
- 剩余/原因：公司行动维度没有产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `corporate_action` 命中 0；复权/换码/退市 as-of 重建 fixture 未逐项核验，故不升级。

#### `204-B02-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:120`（父WP `B02`，owner `B / 股票日线源代理`，验收面 `CODE/OFFLINE+REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-02, 204-A05-05, 204-B02-01`）
- 声明的具体交付：

  > 将AkShare适配到OpenData股票日线Provider，首版只输出经源字段核对的raw价格和源端原生量/额单位；按AkShare函数→实际来源产品→字段登记映射证据，保留source、参数、`business_date`、`observed_at`、空值语义与raw evidence引用。用户已允许本迭代使用AkShare，无需再次索取授权。

- 状态：`PARTIAL`
- 证据：已合并：opendata@1815e2a2a 的 akshare 股票日线 provider 四件（见 B02-01）+ OpenData #150 `a76b48580c2f71ac3dc6a045a05edafba1f896e5`（真实 Eastmoney 捕获 body 经 job→publication→v2→AFI reader 回放）。
- 剩余/原因：验收面是 CODE/OFFLINE+REAL_SOURCE 混合；SUBAGENT_TASKS.md:73 自己写明“未重新请求来源……不能作为 `REAL_SOURCE` 验收”，按约定混合面必须逐面闭合，故最高 PARTIAL。

#### `204-B02-05` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:121`（父WP `B02`，owner `B / 财报源代理`，验收面 `CODE/OFFLINE+REAL_SOURCE`，表内声明状态 `IN_PROGRESS（仅预检和合成门禁切片；真实源/发布未验收）`，前置依赖 `204-A02-02, 204-A05-05, 204-A05-06, 204-B01-02`）
- 声明的具体交付：

  > 将Fuyao已提供的财报数据接入OpenData reviewed v2 annual/quarterly dataset；按原样保留报告期业务日期、源字段、source、原生金额单位/币种、可核验的原始时间及平台visibility seal和raw evidence引用。没有可核验证据的公告时间保持UNKNOWN，不把本任务描述为PIT财报。用户已允许本迭代使用Fuyao，无需再次索取授权。

- 状态：`PARTIAL`
- 证据：已合并：OpenData #151 `56d4cb38869c0fb8114c917be78e720506f659de`（opt-in Fuyao 六 scope 离线回放）；tip 上 `opendata/pipeline/fuyao_stock_daily_observations.py`、`opendata/fuyao_financial_evidence_coverage.py`、`tests/test_fuyao_capture_gate_trace_integration.py`。
- 剩余/原因：SUBAGENT_TASKS.md:74：回放的仍是既往捕获字节，六查询实时闭环/单位/修订/报告期/PIT 未验收；混合面未逐面闭合。

#### `204-B03-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:122`（父WP `B03`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02`）
- 声明的具体交付：

  > 建立基金/ETF交易价格、单位净值、累计净值、万份收益和七日年化的独立数据集及映射。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `nav` 命中 1 且唯一命中是 `frontend/src/__tests__/layout-navigation.test.ts`（导航测试，与净值无关），即净值数据集命中 0；`万份收益`/`七日年化` 在两仓 tip 均无产物。AFI tip 只有既有的 `src/backend/scripts/backfill_fund_nav_history.py`（旧采集面的补数脚本）。
- 剩余/原因：`opendata/data/providers/akshare/_vendor/fund/*` 是 vendored akshare 原函数库，不是声明要求的“独立数据集及映射 + 合同测试”，不能当成交付。

#### `204-B03-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:123`（父WP `B03`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02`）
- 声明的具体交付：

  > 建立可转债个券与国债/信用收益率曲线的分离模型及证券字段映射。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `convertible` 命中 0、`chinese_bond` 命中 0、`treasury` 命中的 3 个文件全部是美联储/FRED 美债模型（`providers/federal_reserve/models/treasury_rates.py` 等），与本声明的中国国债/信用收益率曲线无关。
- 剩余/原因：`_vendor/bond/bond_cb_sina.py` 等仍是 vendored 函数库；声明要求的个券与曲线分离模型及证券字段映射没有产物。

#### `204-B04-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:124`（父WP `B04`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02`）
- 声明的具体交付：

  > 接入指数定义、历史成分有效期和估值分母，支持退市证券与历史universe回测。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/data/providers/akshare/models/index_constituent.py`、`opendata/data/providers/ths/models/index_constituent.py`、`opendata/data/providers/cboe/models/index_constituents.py`、`opendata/data/models/cboe_index_historical.py`。
- 剩余/原因：声明核心是“历史成分有效期 + as_of 重建、当前成分不得反向套用到历史”；blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `as_of` 命中 0（路径名口径），我没有找到 as-of 有效期重建的合同测试产物，估值分母也无独立实现，故 PARTIAL。

#### `204-B04-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:125`（父WP `B04`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02`）
- 声明的具体交付：

  > 建立证券事件及长尾Provider字段漂移隔离、映射版本和错误工单模板。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `drift` 命中 0、`runbook` 命中 0、`work_order` 命中 0；git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 子串 `drift` 只命中 `scripts/ci/check_orm_schema_drift.py`（ORM 漂移，与源字段漂移隔离无关）。
- 剩余/原因：字段漂移隔离带、映射版本与错误工单模板三项声明交付都没有产物。

#### `204-B05-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:126`（父WP `B05`，owner `B / 迁移协作代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED（as of 2026-10-29）`，前置依赖 `204-A04-02, 204-B02-01`）
- 声明的具体交付：

  > 制定证券历史ODS/DWD、成交额sidecar和旧复权数据的迁移映射/分区dry-run。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `scripts/ops/migrate_legacy_stock_daily.py`、`opendata/migration_host_reconcile.py` + `tests/test_migration_host_reconcile.py`、`scripts/ops/legacy_stock_daily_inventory.py`、`opendata/pipeline/stock_daily_reconcile.py`。
- 剩余/原因：声明还包含“成交额 sidecar 和旧复权数据的迁移映射”；sidecar 没有产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `sidecar` 命中 0。

#### `204-B05-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:127`（父WP `B05`，owner `B / 迁移协作代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED（as of 2026-10-29）`，前置依赖 `204-B05-01, 204-A06-02`）
- 声明的具体交付：

  > 对批准的证券分区执行迁移后逐标的/逐分区head、interior、tail与行级抽样对账；该迁移对账不替代 `204-B05-03` 的全历史回补。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/stock_daily_reconcile.py`（601 行 `def reconcile_stock_daily_gaps(...)`，849 行合并 head/interior/tail 缺口）与 `scripts/ops/reconcile_stock_daily_history.py` + `tests/test_stock_daily_gap_cli.py`。
- 剩余/原因：验收面 REAL_SOURCE 未闭合（逐分区行级抽样对账 + 预期分母证据），且 SUBAGENT_TASKS.md:55 记录全历史仍 OPEN。

#### `204-B05-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:128`（父WP `B05`，owner `B / 全A历史回补owner；D提供预算/Run支持`，验收面 `CODE/OFFLINE+REAL_SOURCE+DEPLOYMENT`，表内声明状态 `PLANNED（2026-10-30新增控制任务；未实现/未验收）`，前置依赖 `204-A03-02, 204-A06-04, 204-B02-04, 204-B02-05, 204-D02-04, 204-D03-02`）
- 声明的具体交付：

  > 对冻结的全部必需股票数据集，按 `instrument_id × dataset_id` 分批从独立有证起点回补至每个标的/数据集的独立目标终点；范围包含沪深北在册及退市证券、跨板/换码生命周期。按来源/交易所/数据集/窗口设请求、行数、并发和时间预算；用持久checkpoint、幂等业务键和可审计重入收据续跑，禁止无限重试或以一个大请求绕过额度。

- 状态：`PARTIAL`
- 证据：已合并：opendata@1815e2a2a 的 `opendata/pipeline/stock_daily_backfill_executor.py` + `scripts/ops/execute_stock_daily_backfill.py`（`git log --path` 首现 OpenData #150 `a76b48580`）。仅在开 PR：AFI #283（五个全历史恢复控制器，body 引用 `204-B05-03`）、AFI #273（head `0dbb3f25f5da86b94c449bb29625f227fce5561c`，`src/backend/scripts/ops/run_full_history_recovery_worker.py` + 测试）、AFI #287（head `d7b80f6f3379dc7a91d57c1f15b000ad745fea60`）。
- 剩余/原因：验收面 CODE/OFFLINE+REAL_SOURCE+DEPLOYMENT；SUBAGENT_TASKS.md:55/69 记录权威全市场/退市分母、逐 `instrument_id × dataset_id` 全历史、生产 MySQL、自然周期都未闭合。

#### `204-B06-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:129`（父WP `B06`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-B02-01`）
- 声明的具体交付：

  > 把首批股票/基金共源脚本按业务模型合并为可版本化Provider模板和TaskDefinition映射。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `task_definition` 命中 0（只有 `job_definition`，是运行定义不是声明的“Provider 模板 + TaskDefinition 映射”）；`provider_template` 命中 0。
- 剩余/原因：按业务模型合并共源脚本并版本化的映射产物不存在。

#### `204-B06-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:130`（父WP `B06`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-B01-01`）
- 声明的具体交付：

  > 按批完成剩余证券候选文件处置，保存资产清单总分母及未决项。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #286（head `75e5acf3ad…`，`src/backend/scripts/ops/assign_script_dispositions.py` + `tests/test_assign_script_dispositions.py` + `script_disposition_ledger.csv/.json`）；已合并的输入面是本目录 `script_migration_inventory.csv`。
- 剩余/原因：处置台账未合入 dev，因此不升级；“所有候选逐项有处置/负责人/依赖/阻塞证据”也未证明。

#### `204-B06-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:131`（父WP `B06`，owner `B / 证券代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-B01-01, 204-D01-01, 204-D05-01`）
- 声明的具体交付：

  > 建立旧证券task_id/参数hash到脚本hash、dataset、provider/model、job/version、sink和验收收据的映射。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #284（head `8971f3098822245ed7d83c7fe1e67c67ba5f7099`，`src/backend/app/services/akshare/param_bind_audit.py`、`src/backend/scripts/task_param_audit.py`、`tests/test_akshare_task_param_bind_audit.py`），其 PR body 显式引用 `204-B06-03`；AFI #279（同标题，head `8b24d5606a…`）状态为 closed 且未合并，是 #284 的前身。
- 剩余/原因：声明的“旧 task_id/参数hash ↔ 脚本hash/dataset/job/version/sink/验收收据 双向 anti-join”只覆盖参数绑定一侧，且未合入。

#### `204-B07-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:132`（父WP `B07`，owner `B / 证券代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-B02-02, 204-B03-02, 204-B04-02`）
- 声明的具体交付：

  > 对证券域样板及分批Provider做真实源/仓/API比对、质量核验与数据权利审查。

- 状态：`NOT_STARTED`
- 证据：缺失证据：逐数据集的“源响应 + 落库 + API”三对齐证据产物不存在——blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 中 `rights`/`license` 只命中许可 LICENSE 文件与质量 allowlist；本目录 `SOURCE_RIGHTS_REVIEW.md` 是权利审查，不是逐数据集的实测比对收据。
- 剩余/原因：声明验收面 REAL_SOURCE；没有可核对的分数据集实测记录，故按硬规则 1 记 NOT_STARTED。

#### `204-B07-02` — **BLOCKED_ON_OWNER**

- 出处：`SUBAGENT_TASKS.md:133`（父WP `B07`，owner `B / 运维协作代理`，验收面 `DEPLOYMENT+NATURAL_CYCLE`，表内声明状态 `PLANNED`，前置依赖 `204-B07-01, 204-D06-02`）
- 声明的具体交付：

  > 在目标环境运行证券代表日更/补数任务，观察至少一个源定义的自然发布周期。

- 状态：`BLOCKED_ON_OWNER`
- 证据：已合并的相关度量产物在开 PR 阶段：AFI #282（head `4cf6b9399eec848f53f6873d73c8f15a97486f31`，`src/backend/scripts/ops/report_iteration204_acceptance_window.py` + `tests/test_report_iteration204_acceptance_window.py`）只是**度量** AC14 自然周期已累积多少证据；本目录 `ACCEPTANCE_AND_CUTOVER.md`（AFI@3e9f4a76e）把单写者切换与逐域授权列为尚未执行的门禁。
- 剩余/原因：声明面是 DEPLOYMENT+NATURAL_CYCLE：目标环境日更任务与“至少一个源定义的自然发布周期”观察必须由 owner 完成切换后才有周期可观察；按硬规则 3，ledger 编辑不能闭合 owner/日历绑定项。

#### `204-B07-03` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:134`（父WP `B07`，owner `B / C交叉评审`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-B07-02, 204-C07-01`）
- 声明的具体交付：

  > 完成证券源语义交叉审查和运维/源受限runbook。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `runbook` 命中 0；本目录没有证券源语义交叉评审记录文件（`git ls-files` 的 204 目录里 39 个文件中无 cross-review 产物）。
- 剩余/原因：“C 审阅并记录异议关闭 + 限流/授权/漂移/恢复 runbook”两半都没有产物。

### 泳道 C — C：衍生品与其他数据适配

#### `204-C01-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:140`（父WP `C01`，owner `C / 衍生品代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 刷新其他域候选资产清单并分批逐项处置；449是2026-10-26静态CSV历史候选数，不是当前总数。记录source/provider/模型、参数、sink、消费者、许可及文件关系。

- 状态：`PARTIAL`
- 证据：已合并：本目录 `INVENTORY.md`、`INVENTORY_AUDIT_20261105.md`、`script_migration_inventory.csv`。仅在开 PR：AFI #286（处置台账）、AFI #274（刷新 `INVENTORY.md`）。
- 剩余/原因：449 候选的逐项处置未合入；声明要求“刷新总分母与历史快照 anti-join 有解释”，我只在开 PR 里看到台账文件。

#### `204-C01-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:141`（父WP `C01`，owner `C / 衍生品代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 实测10个跨期货、期权、FX/crypto、宏观/归档代表源案例及访问/保留边界。

- 状态：`NOT_STARTED`
- 证据：缺失证据：跨期货/期权/FX/crypto/宏观/归档的 10 个代表源案例逐项实测记录在两仓 tip 与计划目录里都不存在（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `representative_case` 命中 0；计划目录 grep “实测10个”只命中 SUBAGENT_TASKS.md:141 的声明本身）。
- 剩余/原因：验收面 REAL_SOURCE，按硬规则 1 记 NOT_STARTED。

#### `204-C02-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:142`（父WP `C02`，owner `C / 衍生品代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-02, 204-C01-02`）
- 声明的具体交付：

  > 定义期货/期权精确合约、连续/主力/TAS、结算/收盘、持仓与乘数的独立schema和转换。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/data/models/futures.py`、`opendata/data/models/cboe_futures_curve.py`、`opendata/data/providers/deribit/client.py`、`opendata/data/models/intrinio_options_snapshots.py`、`opendata/data/providers/akshare/_vendor/futures/*`、`…/option/*`。
- 剩余/原因：这些是既有 provider/model 面，不是本声明的验收面：夜盘业务日、连续拼接边界、TAS、乘数与负价合法性四项在 tip 都没有产物（子串 `continuous` 命中 0、`multiplier` 命中 0、`night` 仅命中美联储 `overnight_bank_funding_rate.py`）。

#### `204-C02-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:143`（父WP `C02`，owner `C / 衍生品代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-C02-01`）
- 声明的具体交付：

  > 对指定期货/期权源进行真实参数和交易所日历/合约字段核对，含年度归档边界。

- 状态：`NOT_STARTED`
- 证据：缺失证据：指定期货/期权源的真实参数与交易所日历/合约字段逐项核对档案不存在；blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `cffe` 命中 0，AFI tip 只有 `src/backend/app/services/market_data/cffex_settlement_collector.py`（既有结算采集，非本声明的交易所日历/合约字段核对档案）。
- 剩余/原因：验收面 REAL_SOURCE；年度归档边界证据亦无产物。

#### `204-C03-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:144`（父WP `C03`，owner `C / 衍生品代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-C01-02`）
- 声明的具体交付：

  > 建立FX base/quote、crypto venue/base/quote、小时/日桶、UTC边界及来源时区映射。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/data/providers/tiingo/models/crypto_historical.py` + `tests/test_tiingo_crypto_historical_spec.py`；AFI tip 存在 `src/backend/scripts/backfill_fx_history.py`（旧采集面补数脚本）。
- 剩余/原因：声明的 FX base/quote 方向、crypto venue/base/quote、小时/日桶与 UTC 边界映射没有契约产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `venue` 命中 0、`forex` 仅命中 `opendata/data_fetch/scripts/forexs/__init__.py`（空包）。

#### `204-C03-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:145`（父WP `C03`，owner `C / 衍生品代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-C03-01`）
- 声明的具体交付：

  > 对选定FX与crypto真实端点核对历史保留、时间戳、限速和日内/日线语义。

- 状态：`NOT_STARTED`
- 证据：缺失证据：选定 FX 与 crypto 真实端点的历史保留/时间戳/限速对照可复现产物不存在（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `binance` 命中 0、`forex` 命中 1 且是空 `__init__.py`）。
- 剩余/原因：验收面 REAL_SOURCE；按硬规则 1 记 NOT_STARTED。

#### `204-C04-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:146`（父WP `C04`，owner `C / 采集代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-C02-01, 204-D03-01`）
- 声明的具体交付：

  > 把浏览器capture、年度归档下载和商品期权文件解析封装成有界Provider/Run输入输出。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/process_executor.py`、`opendata/pipeline/process_executor_worker.py`、`opendata/utils/cooperative_checkpoint.py` + `tests/test_cooperative_checkpoint.py`、`opendata/data/capture_selection.py`、`alembic_data/versions/20261028-0017_sina_capture_discovery_index.py`，v2 契约里有 `/api/v2/datasets/{dataset_id}/capture-candidates`。
- 剩余/原因：这三项是新浪 capture + 进程执行器，不是声明的“浏览器 capture / 年度归档下载 / 商品期权文件解析”三项封装：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `browser` 命中 0、`annual_archive` 命中 0、`option_file` 命中 0；“web worker 无阻塞浏览器进程”没有对应产物。

#### `204-C04-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:147`（父WP `C04`，owner `C / 采集代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-C04-01`）
- 声明的具体交付：

  > 对获准的浏览器/年度归档入口执行真实拉取并确认许可、来源hash和可恢复点。

- 状态：`NOT_STARTED`
- 证据：缺失证据：获准浏览器/年度归档入口的真实拉取 manifest 与失败证据档案不存在（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `archive_manifest` 命中 0、`waf` 命中 0）。
- 剩余/原因：验收面 REAL_SOURCE；登录/验证码/WAF 阻断的人工处置规则亦无产物。

#### `204-C05-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:148`（父WP `C05`，owner `C / 衍生品代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A03-02, 204-C01-02`）
- 声明的具体交付：

  > 建立宏观/财务外部主题数据vintage、修订、公布时刻与可得时刻合同。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `vintage` 命中 0；宏观模型虽多（`opendata/data/models/fred_macro_iter2.py`、`federal_reserve_macro.py`、`macro.py`），但声明要求的 vintage/修订/公布时刻/可得时刻合同没有实现：`revision` 只命中 1 个与新浪分栏宽度有关的测试文件名。
- 剩余/原因：既有宏观 provider 不含“旧版/修订版可重放”与 `PIT_UNKNOWN` 标注语义，故记 NOT_STARTED 而不是 PARTIAL。

#### `204-C05-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:149`（父WP `C05`，owner `C / 衍生品代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-C05-01`）
- 声明的具体交付：

  > 将宏观/财务主题与opendata迭代2模型清单交叉映射，裁定复用、扩展或保持独立。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 144 个含 `iter2` 的路径（如 `opendata/data/models/fred_iter2.py`、`opendata/data/providers/intrinio/models/iter2_snapshots_clean.py`），对应本目录 `ARCHITECTURE.md`/`INVENTORY.md`（AFI@3e9f4a76e）对迭代2模型面的自述。
- 剩余/原因：声明验收面是“每个重叠项只有一个实现 owner 与 schema”的逐项裁定；我没有找到逐重叠项的裁定表，故 PARTIAL。

#### `204-C06-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:150`（父WP `C06`，owner `C / 迁移协作代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-01, 204-C02-01`）
- 声明的具体交付：

  > 生成原始文件、进度/cooldown/checkpoint和旧数据库映射，定义可回放迁移manifest。

- 状态：`NOT_STARTED`
- 证据：缺失证据：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `cooldown` 命中 0、`migration_manifest` 命中 0；`checkpoint` 仅命中 `opendata/utils/cooperative_checkpoint.py`（协作式检查点，非声明的旧数据库映射 manifest）。
- 剩余/原因：声明的“原始文件 + 进度/cooldown/checkpoint + 旧数据库映射 → 可回放迁移 manifest”没有产物。

#### `204-C06-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:151`（父WP `C06`，owner `C / 迁移协作代理`，验收面 `CODE/OFFLINE+REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-C06-01, 204-A06-02`）
- 声明的具体交付：

  > 对批准的衍生品/其他域分区dry-run并按业务键、日历、单位、覆盖做前后对账。

- 状态：`NOT_STARTED`
- 证据：缺失证据：衍生品/其他域分区的 dry-run 与前后对账报告没有产物（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `dry_run` 命中 0、`reconcil` 命中的文件全部只覆盖股票日线与 CSI500/新浪分栏，没有期货/期权/FX/crypto/宏观任一分区的对账项）。
- 剩余/原因：声明要求把离线结构差异与真实源可得性分栏报告；两栏都不存在。

#### `204-C07-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:152`（父WP `C07`，owner `C / 衍生品代理`，验收面 `REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-C02-02, 204-C03-02, 204-C04-02, 204-C05-02`）
- 声明的具体交付：

  > 汇总期货、期权、FX/crypto、宏观/长尾各域的source/warehouse/API实测及许可证据。

- 状态：`NOT_STARTED`
- 证据：缺失证据：期货/期权/FX/crypto/宏观/长尾各域的 source/warehouse/API 实测与许可证据汇总不存在（git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 与 blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 均无逐域实测收据文件；计划目录里 `SOURCE_RIGHTS_REVIEW.md` 未给出逐 dataset 的通过/受限/未知状态）。
- 剩余/原因：验收面 REAL_SOURCE。

#### `204-C07-02` — **BLOCKED_ON_OWNER**

- 出处：`SUBAGENT_TASKS.md:153`（父WP `C07`，owner `C / 运维协作代理`，验收面 `DEPLOYMENT+NATURAL_CYCLE`，表内声明状态 `PLANNED`，前置依赖 `204-C07-01, 204-D06-02`）
- 声明的具体交付：

  > 对选择的衍生品/其他域任务完成目标环境运行、自然周期观察、恢复演练和runbook。

- 状态：`BLOCKED_ON_OWNER`
- 证据：已合并的门禁文档是本目录 `ACCEPTANCE_AND_CUTOVER.md`（AFI@3e9f4a76e），它把逐域切换授权列为未执行门禁；度量自然周期累积情况的 AFI #282（head `4cf6b9399e…`）仍是开 PR。
- 剩余/原因：DEPLOYMENT+NATURAL_CYCLE：没有域被切换，就没有该域的自然周期观察与恢复演练可执行；由 owner 决定，不由 ledger 关闭。

### 泳道 D — D：调度、迁移与运维

#### `204-D01-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:159`（父WP `D01`，owner `D / 运维代理`，验收面 `DEPLOYMENT/READ_ONLY`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 只读导出实际task/run/claim、crontab/systemd/进程、checkpoint、脚本参数、目标库/表及版本。

- 状态：`PARTIAL`
- 证据：已合并：本目录 `INVENTORY_AUDIT_20261105.md`。仅在开 PR：AFI #284（`src/backend/scripts/task_param_audit.py`：armed task 参数能否绑定到脚本）、AFI #285（head `d992d3d37b2f1803c0b5c3312be925158819b249`，`src/backend/scripts/ops/check_service_runtime_assets.py` + `tests/test_service_runtime_assets.py`：systemd ExecStart 目标是否被 git 跟踪）。
- 剩余/原因：声明要求一次性只读导出实际 task/run/claim、crontab/systemd/进程、checkpoint、目标库/表及版本；我没有找到覆盖全部分项的合并导出产物。

#### `204-D01-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:160`（父WP `D01`，owner `D / 运维代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01, 204-D01-01`）
- 声明的具体交付：

  > 记录目标环境/数据库指纹、允许目标白名单、账号权限分离和恢复基线。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #291（head `253180420b4051057f085fa05587630580195602`，`src/backend/scripts/ops/warehouse_identity.py` + `tests/test_warehouse_identity.py`；PR 标题即“preflight warehouse database identity before recovery writes (AC12)”）。
- 剩余/原因：账号权限分离与恢复基线（备份恢复演练 owner）没有合并产物，且声明面是 DEPLOYMENT。

#### `204-D02-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:161`（父WP `D02`，owner `D / dev_runs`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅合同/纯函数）`，前置依赖 `204-A02-02, 204-D01-01`）
- 声明的具体交付：

  > 定义声明式Job/Run UTC canonical身份合同及规范化/幂等身份纯函数：job版本、UTC计划时刻、分片、运行类型；补数含明确范围和request id。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `opendata/pipeline/run_identity.py` + `tests/test_run_identity.py`（另有 `tests/test_run_identity_credentials_ledger.py`、`tests/test_run_identity_ledger_integration.py`）。模块 docstring 原文：`This module defines and validates job and run inputs only. It does not schedule, persist, claim, or execute runs, and its digest is not a distributed single-writer or exactly-once guarantee.`——与声明的“不含 durable repository/lease/worker 接线”范围逐字吻合。
- 剩余/原因：计划行 161 自标 DEV_DONE（仅合同/纯函数），我的核验一致；父 WP D02 未关闭。

#### `204-D02-02` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:162`（父WP `D02`，owner `D / dev_ledger`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅ledger离线）`，前置依赖 `204-D02-01`）
- 声明的具体交付：

  > 在独立opendata-od204-ledger分支实现显式Engine注入的SQL持久Run ledger、幂等入队、CAS状态/租约/token、heartbeat、终态和取消；提供owned SQLite双实例行为测试。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `opendata/pipeline/run_ledger.py` 与 `tests/test_run_ledger.py`、`tests/test_run_ledger_atomic.py`、`tests/test_run_ledger_boundaries.py`、`tests/test_run_ledger_additional_offline.py`、`tests/test_run_ledger_database_clock.py`。声明中“独立 opendata-od204-ledger 分支”的 ledger 现已在 dev tip 上（`git log --path` 最新提交 `9f71cf9ae fix(quality): clear the A2 mypy and bandit planes (#158)`）。
- 剩余/原因：计划行 162 自标 DEV_DONE（仅 ledger 离线），核验一致；Alembic 接线见 D02-03，运行接线见 D02-04。

#### `204-D02-03` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:163`（父WP `D02`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（MySQL/SQLite迁移）`，前置依赖 `204-D02-02`）
- 声明的具体交付：

  > 为Run ledger分配唯一Alembic迁移序列并集成到目标数据库迁移体系，保持双库版本治理。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `alembic_data/versions/20261026-0010_run_ledger.py`、`alembic_data/versions/20261029-0020_run_ledger_claim_policy.py`，配套 `tests/test_run_ledger_claim_policy_migration.py`、`tests/test_alembic_migrations.py`；`alembic_data/versions/` 在 tip 共 21 个 revision 文件。
- 剩余/原因：计划行 163 自标 DEV_DONE（MySQL/SQLite 迁移），并明确 PostgreSQL 行为未验证；我未重复执行迁移测试，只核验 revision 文件与其测试在合并树中存在。

#### `204-D02-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:164`（父WP `D02`，owner `D / wave4_worker`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-D02-02, 204-D02-03, 204-D03-01`）
- 声明的具体交付：

  > 把持久ledger接入统一Run service与worker入口，加入持久环境下多进程竞争/崩溃恢复测试。

- 状态：`PARTIAL`
- 证据：已合并：opendata@1815e2a2a 的 `opendata/pipeline/stock_daily_backfill_executor.py` 复用既有 RunLedger/RunService/RunDispatcher（OpenData #150 `a76b48580`）。仅在开 PR：AFI #289（head `6a3b53a25016220b58ec95249788bc17f4622c34`，`src/backend/app/services/akshare/run_coordinator.py`、`src/backend/app/models/akshare_scheduler.py`、`alembic/versions/20261106_akshare_run_coordinator_claims.py`、`tests/test_akshare_run_coordinator.py`）。
- 剩余/原因：tip 上 `run_coordinator` 命中 0；声明要求的“多进程竞争/崩溃恢复 + 旧 token 不能写终态或事实数据”仍未在合并树中闭合（AFI #280 的 write fence 也是开 PR）。

#### `204-D03-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:165`（父WP `D03`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-D02-01`）
- 声明的具体交付：

  > 实现Provider task executor协议、统一日志/退出码和可终止的有界子进程执行器。

- 状态：`PARTIAL`
- 证据：已合并：opendata@1815e2a2a 的 `opendata/pipeline/process_executor.py` + `opendata/pipeline/process_executor_worker.py`（OpenData #179/#172 等把 deadline 改为事件驱动）。仅在开 PR：AFI #280（head `ccddb2687af207a685d161ea32ef16b8b6a763ef`，`src/backend/app/services/akshare/script_worker.py`、`script_worker_runtime.py`、`write_fence.py`、`tests/test_akshare_killable_script_worker.py`、`tests/akshare_killable_worker_cases.py`、`tests/test_akshare_crypto_hourly_timeout_floor.py`）。
- 剩余/原因：tip 上 `src/backend/app/services/akshare/` 只有 7 个模块且 `subprocess.Popen`/`create_subprocess` 命中 0，即可终止执行器在 AFI 侧尚未合入；声明面是 AFI 的 worker。

#### `204-D03-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:166`（父WP `D03`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS（仅补数规划预算；重试、并发等未完成）`，前置依赖 `204-D03-01`）
- 声明的具体交付：

  > 实现重试/预算/并发/供应商限速/退避、自然槽与显式补数分流及分片规则。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/retry.py`、`opendata/data/request_budget.py` + `tests/test_fetcher_request_budget.py`、`opendata/data/providers/ths/transport/rate_limiter.py`、`opendata/api/rate_limit.py`；已合并 OpenData #147 `ab8591f875 feat(pipeline): pass request budgets to THS stock jobs (#147)`。
- 剩余/原因：SUBAGENT_TASKS.md:57 自己记录：Retry-After 尊重、WAF 不无限重试、历史恢复独立预算仍未完成；`retry_after` 在 tip 的逐项行为用例未定位到。

#### `204-D03-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:167`（父WP `D03`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-D02-01`）
- 声明的具体交付：

  > 让APScheduler、手工API、CLI、systemd外壳统一提交同一Run入口。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #293（head `ad5578341c5905b5aea18d8ea9f57524f190375b`，`src/backend/app/startup/orchestration.py`、`src/backend/app/config.py`、`tests/test_startup_scheduler_handoff.py`：让 AkShare 调度器的 API 交接显式且可观察）。已合并的相邻面是 OpenData #144 隔离 CLI。
- 剩余/原因：SUBAGENT_TASKS.md:58 明确：该 CLI “不是统一 Run 提交入口，不接 APScheduler/手工 API/CLI/systemd”，因此声明的统一入口未闭合。

#### `204-D04-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:168`（父WP `D04`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A02-03, 204-D02-04, 204-A06-02`）
- 声明的具体交付：

  > 提供管理员JobDefinition/Run/DQ/coverage后端接口、授权scope、操作者审计和安全取消。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/api/executions.py`、`opendata/api/pipeline.py`、`opendata/api/keys.py`、`opendata/api/auth.py`、`opendata/job_definition_store.py` + `alembic/versions/2026_10_26-0007_job_definitions.py` + `tests/test_job_definition_migration.py`。
- 剩余/原因：声明要求 DQ/coverage 管理接口 + 授权 scope + 操作者审计 + 安全取消四件同体；coverage 管理端点在 v2 契约里只有数据集侧 `/coverage`，审计链与取消语义未逐项核验，故 PARTIAL。

#### `204-D04-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:169`（父WP `D04`，owner `D / 运维代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-D04-01`）
- 声明的具体交付：

  > 实现opendata运维控制台的任务、执行、下次运行、覆盖、隔离、补数/取消/重放和容量页面。

- 状态：`PARTIAL`
- 证据：仅在开 PR：OpenData #197（head `5a41a3284e`，12 个文件：`frontend/src/views/admin/CoverageView.vue`、`BackfillPlanningView.vue`、`CapacityGateView.vue`、`frontend/src/api/coverage.ts`、`frontend/src/router/index.ts` 及 6 个 `frontend/src/__tests__/admin-ops/*.test.ts`）。tip 上 `frontend/src/views/admin/` 只有 `InterfaceManagement.vue`、`ReviewedRunsView.vue` 两个既有页面。
- 剩余/原因：按硬规则 2，未合入只记 PARTIAL (delivered, unmerged)。

#### `204-D05-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:170`（父WP `D01,D05,B01,C01`，owner `D / dev_inventory`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅静态盘点工具）`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 实现opendata/migration_inventory.py、CLI与tests，把AST源文件和可选JSON任务映射整理成可重跑JSON/CSV及双向差异报告，拒绝输出覆盖源/输入；不查生产库、不执行脚本或抓源。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `opendata/migration_inventory.py` + `tests/test_migration_inventory.py`；`git log --path` 给出 `40184f5e3 feat(inventory): add legacy script inventory scanner` 与 `9bae4e977 fix(inventory): protect scanner inputs from report output`（后者正是声明“拒绝输出覆盖源/输入”的实现提交）。
- 剩余/原因：计划行 170 自标 DEV_DONE（仅静态盘点工具），核验一致。

#### `204-D05-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:171`（父WP `D05`，owner `D / 迁移代理`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-D01-02, 204-D02-03, 204-A04-03`）
- 声明的具体交付：

  > 实现存量Job/执行/checkpoint迁移的只读dry-run、显式apply闸门、备份和目标指纹校验。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/migration_host_reconcile.py` + `tests/test_migration_host_reconcile.py`；仅在开 PR：AFI #291（仓库数据库身份 preflight，`warehouse_identity.py`）。
- 剩余/原因：声明的“显式 apply 闸门 + 备份 + 目标指纹校验”中，apply 闸门与备份可恢复性检查未定位到合并用例（tip `warehouse_identity` 命中 0）。

#### `204-D05-03` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:172`（父WP `D05`，owner `D / 运维代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-D05-02`）
- 声明的具体交付：

  > 在隔离恢复环境验证元数据/warehouse备份、artifact manifest和迁移后状态的恢复流程。

- 状态：`NOT_STARTED`
- 证据：缺失证据：隔离恢复环境的备份/artifact manifest 恢复流程验证不存在（blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `restore` 命中 0；`rpo` 的 4 个命中全部是 `corporate_events*` 文件名里的假阳性，不是 RPO 度量；本目录 39 个文件中也没有恢复演练收据）。
- 剩余/原因：声明面 DEPLOYMENT，需要 RPO/RTO 实测与偏差记录。

#### `204-D06-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:173`（父WP `D06`，owner `D / 可观测性代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-D03-03, 204-A05-03`）
- 声明的具体交付：

  > 连接request/run/source/publication的trace_id，建设低基数日志、trace和指标埋点。

- 状态：`PARTIAL`
- 证据：AFI tip 存在 `src/backend/app/telemetry.py` 与 `docs/adr/005-opentelemetry-core-dependency.md`；opendata@1815e2a2a 存在 `opendata/api/metrics.py`。
- 剩余/原因：声明要求的 request/run/source/publication 四段 `trace_id` 贯通在 OpenData 侧无产物：blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `trace_id` 命中 0；AFI 的 trace_id 命中全在 research 候选注册表，不在采集链。

#### `204-D06-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:174`（父WP `D06`，owner `D / 可观测性代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-D06-01, 204-D05-03`）
- 声明的具体交付：

  > 配置按源周期的数据freshness告警、API/worker/磁盘/备份SLO仪表盘和故障演练。

- 状态：`PARTIAL`
- 证据：opendata@1815e2a2a 存在 `opendata/pipeline/alerts.py`、`opendata/pipeline/alert_matrix.py`、`opendata/pipeline/diff_alerts.py`、`opendata/pipeline/freshness.py` + `tests/test_alert_matrix.py`、`tests/test_freshness.py`、`tests/test_domain_freshness_semantics.py`。
- 剩余/原因：声明面是 DEPLOYMENT（目标环境触发、SLO 经实测校准、故障演练）；仪表盘与演练没有目标环境收据，故不升级。

#### `204-D07-01` — **BLOCKED_ON_OWNER**

- 出处：`SUBAGENT_TASKS.md:175`（父WP `D07`，owner `D / root+运维代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-D05-02, 204-D06-02, 204-E06-01`）
- 声明的具体交付：

  > 以dataset/sink为单位制订新旧单写者fence、影子读、切换清单和分波授权。

- 状态：`BLOCKED_ON_OWNER`
- 证据：已合并的门禁文档：本目录 `ACCEPTANCE_AND_CUTOVER.md`（AFI@3e9f4a76e）。逐 dataset 的 B07/C07 真实源+部署+自然周期收据尚不存在（见 B07-01/02、C07-01/02 行的缺失证据）。
- 剩余/原因：声明要求“逐波授权”与每波唯一 writer/回滚 owner；这是 owner 决策前置，ledger 不能代为闭合。

#### `204-D07-02` — **BLOCKED_ON_OWNER**

- 出处：`SUBAGENT_TASKS.md:176`（父WP `D07`，owner `D / 运维代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-D07-01`）
- 声明的具体交付：

  > 对单波执行重复投递、worker崩溃/租约过期、源失败和回滚演练。

- 状态：`BLOCKED_ON_OWNER`
- 证据：依赖项未启动即无从演练：D07-01 的 fence/切换清单尚无产物；blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `single_writer` 命中 0、`shadow` 命中 0、`fence` 在路径名中命中 0。
- 剩余/原因：重复投递/租约过期/源失败/回滚四类故障注入用例必须按 `ACCEPTANCE_AND_CUTOVER.md` §5/§6 落在对应 PR 里，目前没有任何这样的用例名可引用。

#### `204-D07-03` — **BLOCKED_ON_OWNER**

- 出处：`SUBAGENT_TASKS.md:177`（父WP `D07`，owner `D / 运维代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-D07-02`）
- 声明的具体交付：

  > 在逐域切换验收后停用旧systemd/worker/凭据并保留可审计退役记录。

- 状态：`BLOCKED_ON_OWNER`
- 证据：退役清单未定义；现役 systemd 单元仍在运行（`deploy/systemd/…example` 只出现在未合入的 AFI #273），git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 中 `decommission` 命中 0。
- 剩余/原因：声明要求每项旧入口有 owner、最后运行与禁用证据；前置的 D07-02 演练未完成。

### 泳道 E — E：ai-for-investor消费端与业务回归

#### `204-E01-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:183`（父WP `E01`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A01-01`）
- 声明的具体交付：

  > 清点AFI所有行情、数据库DSN、文件、直接源SDK、页面与任务读路径，记录调用点和旧功能。

- 状态：`DEV_DONE`
- 证据：合并产物：AFI@3e9f4a76e 的 `src/backend/app/services/market_data/consumer_boundary.py` + `src/backend/tests/services/market_data/test_consumer_boundary.py`。模块 docstring 原文：`Read-only AST inventory of AFI market-data consumers and bypass paths. … It reports literal source SDK imports/calls, direct warehouse access patterns, local shared-data file paths, and the statically resolvable Python call edges that connect those findings to application entry points.`——与声明“清点行情/DSN/文件/直接源SDK/页面与任务读路径，记录调用点”逐项对应。
- 剩余/原因：docstring 同时自述动态注入与字符串拼路径是报告的显式限制；“每个读路径归属具体业务场景和责任人”未闭合，属验收面，不影响开发面 DEV_DONE 判定。

#### `204-E01-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:184`（父WP `E01`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E01-01`）
- 声明的具体交付：

  > 建立功能场景、频率、单位、日期边界、错误和权限回归矩阵。

- 状态：`PARTIAL`
- 证据：AFI tip 存在 `src/backend/tests/market_data_platform/` 共 90+ 个测试模块（含 `test_legacy_kline_api.py`、`test_coverage.py`、`test_field_quality.py`），以及本目录 `CONSUMER_MIGRATION.md`（AFI@3e9f4a76e）。
- 剩余/原因：声明要求一张“功能场景 × 频率 × 单位 × 日期边界 × 错误 × 权限”的回归矩阵产物；我没有找到这样一个矩阵文件/表，现有测试不构成矩阵。

#### `204-E02-01` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:185`（父WP `E02`，owner `E / dev_client`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅同步SDK v1分页）`，前置依赖 `204-A02-03`）
- 声明的具体交付：

  > 实现opendata同步SDK现有v1 GET的分页请求/响应校验、行/页预算和流式响应字节上限；保持latest-view，不提供固定版本或跨页快照保证。

- 状态：`DEV_DONE`
- 证据：合并产物：opendata@1815e2a2a 的 `opendata_client/opendata_client/client.py` + `opendata_client/opendata_client/snapshots.py` + `tests/test_opendata_client.py`（contents API 取回 blob `a5a10164f5…`，56,081 字节）。实测测试名覆盖声明的每一条：`test_iter_rows_follows_a_short_page`、`test_iter_rows_stops_on_an_empty_page`、`test_iter_rows_rejects_a_repeated_page_echo`、`test_query_rejects_untrusted_page_metadata`、`test_query_rejects_invalid_pagination_before_request`、`test_iter_rows_raises_before_yielding_rows_over_the_row_budget`、`test_iter_rows_raises_when_page_budget_cannot_confirm_completion`、`test_oversized_stream_stops_reading_and_closes_response`、`test_failure_envelope_raises_safely_even_with_200`、`test_status_codes_map_to_errors`。
- 剩余/原因：声明的排除项同样成立：这些是 v1 GET 分页 + 行/页预算 + 流式字节上限，未见 cursor/snapshot 语义参与。

#### `204-E02-02` — **DEV_DONE**

- 出处：`SUBAGENT_TASKS.md:186`（父WP `E02,E03`，owner `E / dev_consumer`，验收面 `CODE/OFFLINE`，表内声明状态 `DEV_DONE（仅AFI输入校验）`，前置依赖 `204-A02-03, 204-E02-01`）
- 声明的具体交付：

  > 在现有AFI股票日线v1适配器核对响应symbol、严格业务日期和分页元数据，拒绝重复页；流式读取并限制单响应/累计字节，保留原窗口转换与过滤。

- 状态：`DEV_DONE`
- 证据：合并产物：AFI@3e9f4a76e 的 `src/backend/app/services/market_data/opendata_provider.py`（第 175–178 行逐行核对 `symbol != request.provider_symbol` 即拒绝；第 281–282 行 `max_response_bytes` / `max_total_response_bytes` 双字节上限；第 278 行 `total_deadline_seconds`）与 `src/backend/tests/market_data_platform/test_opendata_provider.py`：`test_each_row_symbol_must_exactly_match_request`（287 行）、`test_non_date_only_timestamp_is_refused`（265 行）、`test_duplicate_event_dates_are_refused`（245 行）、`test_repeated_page_number_is_refused`（384 行）、`test_repeated_page_rows_are_refused_even_when_page_number_advances`（406 行）、`test_total_response_limit_stops_before_requesting_another_page`（450 行）、`test_provenance_limit_stops_before_requesting_another_page`（476 行）、`test_total_deadline_covers_all_pages`（500 行）。
- 剩余/原因：计划行 186 自标 DEV_DONE（仅 AFI 输入校验），核验一致。

#### `204-E02-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:187`（父WP `E02`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E02-01, 204-E02-02`）
- 声明的具体交付：

  > 为async FastAPI读路径加独立Async HTTP适配器或薄REST层，确保不在事件循环调用同步SDK。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e 上 `grep -rl httpx.AsyncClient src/backend/app/services/` 命中 `services/opendata_stock_daily_freshness.py`、`services/stock_analysis/opendata_sina_lrb_snapshot.py` 等，说明异步 REST 读取层在部分路径已存在。
- 剩余/原因：声明要求的“独立 Async HTTP 适配器或薄 REST 层 + async 并发测试确认无同步阻塞”没有整体产物：`async_http`/`rest_client` 命名面在 git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 命中 0，且 `market_data/opendata_provider.py` 自身是同步实现被异步路径复用，未见“事件循环不被阻塞”的行为用例名。

#### `204-E02-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:188`（父WP `E02`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E02-03, 204-A02-04`）
- 声明的具体交付：

  > 统一认证、单位/时区、deadline、有限重试、request_id、429/503/空结果错误映射。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e：`opendata_provider.py` 内 `retry` 出现 29 次、`total_deadline_seconds` 存在；`market_data/opendata_credentials.py` 存在（认证）。
- 剩余/原因：声明要求“可区分合法空、未覆盖、无权和中台不可用”四类语义映射与“scope/许可错误不重试”；我没有定位到覆盖这四类的合并用例名，故不升级。

#### `204-E03-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:189`（父WP `E03`，owner `E / afi_inventory`，验收面 `CODE/OFFLINE`，表内声明状态 `IN_PROGRESS`，前置依赖 `204-E02-04, 204-A05-01`）
- 声明的具体交付：

  > 将行情列表、搜索、覆盖/主题卡等首批业务读路径改到REST client。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e：`src/frontend/src/views/DataPage.vue` 第 101/132/218–232 行已含 `instrumentOptionsCatalogMode === 'opendata'` 与 `opendata-stock-daily-freshness` 数据测试钩子；`src/backend/tests/test_opendata_stock_daily_freshness.py` 亦在 tip。
- 剩余/原因：计划行 189 自标 IN_PROGRESS；“业务路径无数据库直读/源 SDK 调用”的 API 级证明未闭合（`consumer_boundary.py` 报告仍有 bypass 面），故 PARTIAL。

#### `204-E03-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:190`（父WP `E03`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E02-04, 204-A05-02`）
- 声明的具体交付：

  > 迁移单标的分析、扫描器、信号所需行情读路径并明确频率不可用时的业务响应。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e：`src/backend/app/services/market_data/query_service.py`、`multi_record_query_service.py`、`query_window_coverage.py` 等价物与 `market_data_coverage_service.py` 均已合入。
- 剩余/原因：声明要求扫描器/信号所需行情读路径迁移与频率不可用时的显式业务响应；我没有找到“不静默降频/换源”的行为用例名，故不升级。

#### `204-E03-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:191`（父WP `E03`，owner `E / 消费端代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E03-01, 204-E03-02`）
- 声明的具体交付：

  > 补齐迁移业务页面和关键API回归，保持已有分析功能并标记暂不可用能力。

- 状态：`PARTIAL`
- 证据：仅在开 PR：AFI #281（head `c59e5f25b3866683083f644f594a426781d99704`，其 PR body 引用 `204-E03-03` 与 `204-E05-02`；文件含 `src/frontend/src/views/data/components/OpenDataStockDailyFreshnessStates.vue`、`src/frontend/src/api/openDataCoverage.ts`、`src/frontend/src/__tests__/views/DataPage.opendata-kline.test.ts`）。AFI #272 是同标题的 closed 未合并前身（head `3d26406271`）。
- 剩余/原因：按硬规则 2，未合入只记 PARTIAL (delivered, unmerged)。

#### `204-E03-04` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:192`（父WP `E03`，owner `E / 股票分析REST消费代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-B02-04, 204-B02-05, 204-E02-04`）
- 声明的具体交付：

  > 把股票分析市场/财务事实读取改为OpenData REST固定publication vector；后台执行以实际请求用户身份重新取权并复核`READ_DATA`及source research grant。AFI只在单次请求内持有数据，不新建/写入可复用事实缓存，不保留直连SDK、仓库读或其他来源fallback。

- 状态：`PARTIAL`
- 证据：已合并：AFI #202 `076caa979 feat(market-data): read pinned stock daily publications`、#204 `b825f9214 feat(stock-analysis): authorize pinned stock daily publication reads`（均在 `git log --oneline dev` 输出中）。仅在开 PR：AFI #278（head `c5b9e134652750d03baf6eb321086a0e31b2407f`，`research_binding.py`、`research_binding_contract.py`、`stock_analysis/exporter.py`、`tests/market_data_platform/test_research_binding.py`）。
- 剩余/原因：SUBAGENT_TASKS.md:59/70 自己记录 reader/adapter 未接任何股票分析业务路径、默认关闭；BSE 与 coverage UNKNOWN 时的停止语义未验证。

#### `204-E03-05` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:193`（父WP `E03`，owner `E / 股票报告契约代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-E03-04`）
- 声明的具体交付：

  > 定义首版股票分析报告的必需数据、字段/单位/质量/coverage门槛和可见限制；输出持久保存每个dataset的publication_id/sequence、可信cutoff/visibility vector、content hash、contract/schema hash、source/grant revision及业务窗口。临时snapshot ID可作调试引用，但不作为durable replay依据；确认publication/vector保留期覆盖报告复现期。只保存用户请求的分析工件，不把REST事实行或可复用衍生事实写回AFI。

- 状态：`PARTIAL`
- 证据：已合并：AFI `cbd4ca930 feat(stock-analysis): persist revalidated OpenData report evidence (#229)` 与 `c3877b6b5 feat(stock-analysis): produce the stock-daily report evidence vector at task start (#250)`；tip 上 `src/backend/alembic/versions/20261101_stock_analysis_report_evidence_vector.py`、`src/backend/app/services/stock_analysis/report_evidence_producer.py`、`stock_daily_report_evidence.py`、`tests/test_stock_analysis_report_evidence_producer.py`。
- 剩余/原因：冲突登记：SUBAGENT_TASKS.md:60（2026-10-31）称 E03-05“无直接证据”，但 #229/#250 晚于该条目合入并落在开发树上；声明要求的 publication/vector 保留期与“缺 visibility 证据即不保存报告”门禁仍未闭合，故记 PARTIAL。

#### `204-E04-01` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:194`（父WP `E04`，owner `E / 研究工件代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-03, 204-E02-04`）
- 声明的具体交付：

  > 为研究快照/导出增加publication、schema、过滤条件、内容hash与来源manifest引用。

- 状态：`PARTIAL`
- 证据：已合并：`cbd4ca930 (#229)`（tip 有 `20261101_stock_analysis_report_evidence_vector.py` 等 4 个文件）。仅在开 PR：AFI #278，其 PR body 引用 `204-E04-01`，新增 `src/backend/app/services/market_data/research_binding_contract.py` 与 `src/backend/tests/test_stock_analysis_export_publication_binding.py`。
- 剩余/原因：声明要求“哈希/契约不匹配时拒绝加载”与 publication/schema/filter/content hash + 来源 manifest 引用五件齐备；来源 manifest 引用无产物（A04-01 的 `artifact_manifest` 命中 0）。

#### `204-E04-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:195`（父WP `E04`，owner `E / 研究工件代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E04-01, 204-A05-02`）
- 声明的具体交付：

  > 将回测/优化输入绑定固定snapshot、PIT要求、数据版本与明确的时间窗口。

- 状态：`NOT_STARTED`
- 证据：缺失证据：git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 中 `grep -rl snapshot src/backend/app/services/backtest/` 返回空（0 个文件），即回测/优化输入没有绑定固定 snapshot 的实现面。
- 剩余/原因：声明要求“对冻结 fixture 重跑结果可核验”“不满足严格 PIT/缺口阈值时明确失败或降级为标注研究”；两半都无产物。

#### `204-E04-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:196`（父WP `E04`，owner `E / 研究工件代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E04-02, 204-A05-03`）
- 声明的具体交付：

  > 实现sealed数据集、用户/租户研究权限和导出/工件访问控制。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e 存在 `src/backend/app/services/market_data/access.py`、`opendata_credentials.py`、`scope_manifest.py`、`src/backend/tests/market_data_platform/test_access_authorization.py`、`tests/test_stock_daily_snapshot_authorization_adapter.py`。
- 剩余/原因：声明要求“越权和跨租户测试拒绝读取/导出 + 授权缓存随权限变化失效”；我没有找到跨租户导出拒绝的用例名，且导出访问控制随 #278 一起在开 PR 中。

#### `204-E05-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:197`（父WP `E05`，owner `E / UI协作代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-D04-02, 204-E03-03`）
- 声明的具体交付：

  > 将旧数据管理入口加兼容提示/跳转到opendata控制面，保留必要只读摘要入口。

- 状态：`NOT_STARTED`
- 证据：缺失证据：AFI 前端没有把旧数据管理入口跳转/指向 OpenData 控制面的产物——`grep -rn opendata src/frontend/src/views/DataPage.vue` 只命中 instrument 目录模式与 freshness 钩子，没有外部控制面链接；git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 中 `cutover_redirect` 命中 0。
- 剩余/原因：声明面依赖 OpenData 受权限保护的管理 API（D04-01/D04-02 未合入），因此跳转本身还没有可指向的合法目标。

#### `204-E05-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:198`（父WP `E05`，owner `E / UI协作代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-E05-01, 204-A05-02`）
- 声明的具体交付：

  > 为保留的AFI行情/可用性页面接入真实coverage/freshness状态。

- 状态：`PARTIAL`
- 证据：已合并：`DataPage.vue` 第 218–232 行的 `opendata-stock-daily-freshness` 组件与 `src/backend/tests/test_opendata_stock_daily_freshness.py`；仅在开 PR：AFI #281（head `c59e5f25b3…`，PR body 引用 `204-E05-02`；新增 `OpenDataStockDailyFreshnessStates.vue`、`useOpenDataStockDailyFreshness.ts`、`api/openDataCoverage.ts` 与两个 `__tests__` 文件）。
- 剩余/原因：声明要求状态显式区分 PARTIAL/UNKNOWN/SOURCE_LIMITED/NOT_APPLICABLE；tip 上的 freshness 组件没有这四态，四态在未合入的 #281 里。

#### `204-E06-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:199`（父WP `E06`，owner `E / 集成代理`，验收面 `DEPLOYMENT+REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-E03-01, 204-E04-02, 204-D06-01`）
- 声明的具体交付：

  > 对授权样本执行新旧影子读比对，记录行、字段、单位、来源、时间边界和差异。

- 状态：`NOT_STARTED`
- 证据：缺失证据：git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 与 blob-path scan of all 11,137 tracked files at opendata@1815e2a2a 子串 `shadow` 在代码路径中均命中 0（AFI 唯一命中是迭代192的一个 markdown 台账文件名）；没有逐标的同窗口的行/字段/单位/来源差异记录产物。
- 剩余/原因：声明面 DEPLOYMENT+REAL_SOURCE；新旧影子读比对从未开始。

#### `204-E06-02` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:200`（父WP `E06`，owner `E / 集成代理`，验收面 `DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-E06-01, 204-E02-04`）
- 声明的具体交付：

  > 验证AFI在opendata超时、限流、源受限、权限失败和部分覆盖时的降级/恢复体验。

- 状态：`NOT_STARTED`
- 证据：缺失证据：针对 opendata 超时/限流/源受限/权限失败/部分覆盖五类的降级恢复体验故障注入没有产物：git-ls-files scan of all 7,768 tracked files at AFI@3e9f4a76e 子串 `fault_injection` 命中 0；开 PR 中最接近的 AFI #294（head `93e2571770e850ec9ff5abedd1130ca1ef76376c`，`verify_api_only_consumption.py` + `tests/test_api_only_consumption_verify.py`）验证的是 API-only 消费来源，不是故障注入降级。
- 剩余/原因：按 `ACCEPTANCE_AND_CUTOVER.md` §5/§6，故障注入用例名与命令应落在对应 PR；目前没有任何 PR 引用这些用例名。

#### `204-E06-03` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:201`（父WP `E06`，owner `E / 跨仓股票研究验收代理`，验收面 `CODE/OFFLINE+REAL_SOURCE`，表内声明状态 `PLANNED`，前置依赖 `204-A04-04, 204-A05-04, 204-A05-05, 204-A05-06, 204-A05-07, 204-A06-04, 204-B02-04, 204-B02-05, 204-E03-05`）
- 声明的具体交付：

  > 在受控集成环境用一个或少量已授权沪深标的验证AkShare日线与Fuyao财报从真实返回、OpenData post-commit visibility seal、固定cutoff/sequence snapshot vector REST到AFI研究请求的端到端证据链；限制请求范围，不运行全A全历史下载。

- 状态：`PARTIAL`
- 证据：已合并：AFI tip 的 `src/backend/tests/test_opendata_v2_cross_repository_wire.py`、`test_opendata_stock_daily_publication_cross_repository_wire.py`、`test_opendata_temporal_identity_cross_repository_wire.py`、`test_opendata_stock_daily_real_sample_replay_wire.py`；OpenData #150 `a76b48580`（跨仓合成 wire + 真实捕获字节回放）。
- 剩余/原因：声明面 CODE/OFFLINE+REAL_SOURCE：真实用户 grant、实时来源、生产部署、影子对账与自然周期未闭合（SUBAGENT_TASKS.md:72 自述）。

#### `204-E07-01` — **NOT_STARTED**

- 出处：`SUBAGENT_TASKS.md:202`（父WP `E07`，owner `E / 集成代理`，验收面 `CODE/OFFLINE`，表内声明状态 `PLANNED`，前置依赖 `204-D07-01, 204-E06-02`）
- 声明的具体交付：

  > 在对应业务路径切换并具备回滚条件后，移除AFI采集SDK、仓库DSN和采集启动hook。

- 状态：`NOT_STARTED`
- 证据：缺失证据（移除未发生，旧面仍在）：`find src/backend -name '*.py' -path '*data_fetch*'` 在 tip 返回 1,125 个文件；`src/backend/app/services/data_fetch/` 目录仍在；`src/backend/scripts/` 下 44 个脚本仍在。AFI tip 也未出现任何采集 SDK/DSN 移除提交。
- 剩余/原因：声明要求“在对应业务路径切换并具备回滚条件后”才移除，前置的 D07/E06 未完成，因此这是真实未开始而非漏记。

#### `204-E07-02` — **PARTIAL**

- 出处：`SUBAGENT_TASKS.md:203`（父WP `E07`，owner `E / 集成代理`，验收面 `CODE/OFFLINE+DEPLOYMENT`，表内声明状态 `PLANNED`，前置依赖 `204-E07-01, 204-D07-02`）
- 声明的具体交付：

  > 检查安装包、容器、CI secret、环境变量和启动配置边界，确认只保留必要opendata client与身份。

- 状态：`PARTIAL`
- 证据：AFI@3e9f4a76e 存在 `src/backend/app/services/market_data/consumer_boundary.py`（静态扫描旁路面）与 `scripts/ci/check_sensitive_tracked_files.py`、`scripts/bandit_gate.sh`；仅在开 PR：AFI #285（ExecStart 目标是否被 git 跟踪的服务资产守卫）。
- 剩余/原因：声明面是 CODE/OFFLINE+DEPLOYMENT（构建产物不含 opendata 内部包/DSN/源密钥，目标环境只持最小读 scope）；目标环境证据没有，故 PARTIAL。

## 5. 无法验证任何产物的 id

`NOT_STARTED`（23 项，均附缺失证明，见第 4 节各自的证据栏）：

`204-A04-02`, `204-A07-01`, `204-B01-02`, `204-B03-01`, `204-B03-02`, `204-B04-02`, `204-B06-01`, `204-B07-01`, `204-B07-03`, `204-C01-02`, `204-C02-02`, `204-C03-02`, `204-C04-02`, `204-C05-01`, `204-C06-01`, `204-C06-02`, `204-C07-01`, `204-D05-03`, `204-E04-02`, `204-E05-01`, `204-E06-01`, `204-E06-02`, `204-E07-01`

`BLOCKED_ON_OWNER`（5 项，需 owner 决策或自然周期到达，不是可以靠代码关闭的项）：

`204-B07-02`, `204-C07-02`, `204-D07-01`, `204-D07-02`, `204-D07-03`

按泳道的诚实比例（`DEV_DONE`/`PARTIAL`/`NOT_STARTED`+`BLOCKED_ON_OWNER`）：

| 泳道 | 总数 | DEV_DONE | PARTIAL | NOT_STARTED | BLOCKED_ON_OWNER |
| --- | --- | --- | --- | --- | --- |
| A | 25 | 2 | 21 | 2 | 0 |
| B | 20 | 1 | 11 | 7 | 1 |
| C | 14 | 0 | 5 | 8 | 1 |
| D | 19 | 4 | 11 | 1 | 3 |
| E | 21 | 3 | 13 | 5 | 0 |

B/C 泳道（逐 provider / 逐资产迁移）集中了多数 `NOT_STARTED`：B 泳道 20 项里 7 项、C 泳道 14 项里 8 项，各再有 1 项为 owner 绑定（`204-B07-02`、`204-C07-02`）；全部 23 项 `NOT_STARTED` 里有 15 项落在 B/C。我没有把它们往完成上靠：唯一能归到它们名下的合入代码是既有 provider 面（`_vendor` 下的 akshare 函数库、美联储/FRED/CBOE/Tiingo 模型），它们既不是本迭代产物，也不做声明的事。

## 6. 计划自身的内部不一致（不选边，只登记）

1. **“98 vs 99”叙事**：`SUBAGENT_TASKS.md:3` 与 `IMPLEMENTATION_PLAN.md:3` 都称“98 个子任务”并给出 8/11/79 的快照；五张泳道表实际含 **99** 个唯一 id（多出的是 2026-10-30 新增的 `204-B05-03`），重测得 8 DEV_DONE / 11 IN_PROGRESS / 80 PLANNED。两句话可以共存，但只有在明确排除 `204-B05-03` 时才成立；引用“98”作分母的一切完成率都应重新标注。
2. **`204-A02-04` 的自述数字与合入树不一致**：行 90 写“v1共140路径、v2共6路径冻结，24项行为测试”。我在 1815e2a2a6 实测：`docs/afi204-v1-openapi.json` = 140 条路径（一致），`docs/afi204-v2-openapi.json` = **9** 条（不一致），`tests/test_published_openapi_gate.py` 的 `def test_` = **29** 个（不一致）。原因可定位：OpenData #159（已合入，`9f0d97e4f7` 后的 `f33bfc9a9 fix(quality): refresh the v1 OpenAPI contract baseline to the shipped surface`）在该行写定之后刷新了基线。
3. **同一文件内对 `204-B02-05` 给出相互矛盾的证据判定**：`SUBAGENT_TASKS.md:54`（2026-10-31 增量证据节）写“Fuyao 财报数据集本身没有新实现或证据”；同一天的 `:74`（Wave 13/14/15 合入证据节）写 OpenData #151 已合入且提供六 scope 离线回放（**1 passed、52 项观察**）。两行不能同时为真；本文采用后者（因为 #151 head `ed7ec84fb9` 确已 merged，且回放产物在 tip 上可见），但保留本条登记。
4. **`204-E03-05` 同样被两行矛盾化**：`:60` 写“无直接证据”，`:71` 写 AFI #204 合入后有固定 publication/content SHA 与离线回放证据。而且两行都早于已合入的 AFI #229 `cbd4ca930 feat(stock-analysis): persist revalidated OpenData report evidence` 与 #250 `c3877b6b5`；tip 上现存在 `alembic/versions/20261101_stock_analysis_report_evidence_vector.py` 等 4 个文件。即证据行已过时。
5. **`204-D02-02` 的分支叙事已过时**：行 162 与行 214 均称 ledger 位于独立分支 `opendata-od204-ledger`、“必须由 root 与 dev_runs 契约集成后再并入主线”；实际上 `opendata/pipeline/run_ledger.py` 与 5 个 `tests/test_run_ledger*.py` 已在 1815e2a2a6 的主线上（回溯提交 `9f71cf9ae (#158)`）。两处叙述已不成立。
6. **泳道归属跨文件不同**：`IMPLEMENTATION_PLAN.md:20` 的 B 泳道 id 清单从 `204-B01-02` 开始，漏掉 `204-B01-01`；而 `SUBAGENT_TASKS.md:38` 写的是 `204-B01-01/02`。两处对同一 id 的泳道包含关系不一致（本文按泳道表取 B）。
7. **多父 WP 行**：`204-D05-01` 的父 WP 列写 `D01,D05,B01,C01`（唯一四父），而 `204-E02-02` 写 `E02,E03`；这两行按 `IMPLEMENTATION_PLAN.md` 的父包统计时会被重复计数，引用它们的完成率必须声明去重口径。
8. **状态列格式不统一**：同一列里出现 `PLANNED`、`PLANNED（as of 2026-10-29）`、`PLANNED（2026-10-30新增控制任务；未实现/未验收）`、`DEV_DONE（代码/离线门禁）`、`DEV_DONE（仅预检和合成门禁切片…）` 等 8 种写法；机器解析必须先剔除括号后缀。本文的“表内声明状态”保留原文，不做归一化。
9. **计划对 PR 的 id 引用几乎为零，但不是绝对零**：我逐个读了本波 21 个 AFI PR（#273、#274、#275、#278–#295）的标题与正文，只有 **5** 个 PR 引用了 **5** 个不同 id：#278 引用 `204-E04-01`、#279（closed，未合并）与 #284 引用 `204-B06-03`、#281 引用 `204-E03-03` 与 `204-E05-02`、#283 引用 `204-B05-03`。其余 16 个 PR 零引用；因此“本波 PR 从不引用子任务 id”需修正为“5/21 引用，其中 1 个已 closed”。反过来说，99 个 id 里有 51 个除了本清单自身外不在计划目录任何文件里出现，这才是真正的断链。

## 7. 本文不能证明的事

- 它不证明任何 `REAL_SOURCE`、`DEPLOYMENT`、`NATURAL_CYCLE` 面已通过；它也不是部署或数据完整性声明。
- 它不把子任务状态推导为父工作包状态（计划第 17 行约定）。
- 它不修改也不重算 AC 判定；AC05/AC14 类日历与 owner 绑定项仍开放。
- 它不声称“所有合入测试都被本人重新运行”：本文是 docs-only 产物，我验证的是产物存在性与合入性（文件/测试名/提交 SHA/PR 状态），并非重新执行测试套件。

