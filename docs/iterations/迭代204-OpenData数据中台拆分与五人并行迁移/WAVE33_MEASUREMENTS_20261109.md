# 迭代 204 — Wave 33 实测与更正（2026-11-09）

本轮以实况证据推进，并**更正两条过期登记**。不改写任何 AC 判定；所有数字都给出可复跑命令或
CI 工件坐标。测量时刻见各节。

---

## 1. 更正：AC13 不是「无实现」

`ACCEPTANCE_AUDIT_20261106.md` 与 `SUBAGENT_TASKS.md` 里「AC13 单写者/协调器 无实现、NOT_IN_GIT、
NOT_RUN」的叙述**已过期**。实现早在 **#289 `c7ba5abb2`** 合入并在 `origin/dev` 上：

- `src/backend/app/services/akshare/run_coordinator.py`（601 行，`AkshareRunCoordinator`）
- `src/backend/app/services/akshare/write_fence.py`（178 行）
- `src/backend/app/models/akshare_scheduler.py`
- 迁移 `20261106_akshare_run_coordinator_claims.py`
- `src/backend/tests/test_akshare_run_coordinator.py`（19 个测试）

本机实测（部署树 `ce97f53f5`，backend venv）：

```
cd src/backend && .venv/bin/python -m pytest tests/test_akshare_run_coordinator.py -q -p no:cacheprovider
19 passed in 17.73s
```

**所以 AC13 的「离线判据面」现在有据可入：19/19 通过。** 但 AC13 仍未闭合，缺口是具体且可指名的：

1. `AkshareRunCoordinator` 在 `app/` 里**零引用**——只有 `write_fence` 被接线
   （`script.py:1690`、`script_worker.py:121`）。也就是说围栏在跑，**claim 写入者没接**，
   单写者语义在生产路径上尚未生效。
2. 29,126 条历史 claim 行的处置 + 开关 flag-on 属属主裁定。
3. 七连 live drills 未做。

登记口径改为：**实现已在 dev、离线 19 测试绿；生产接线 + 属主裁定 + 七连测仍 OPEN**。
不再写「无实现」。

## 2. 更正：OD AC-17|05 的复测作业是 cancelled，改用当前主干的成功 run 入账

旧行写「复测作业 `41936293992` 仍在跑」。实况：该 run `status=completed, conclusion=cancelled`
（头 `81bc5f9e145`）——**它永远不可能给出确认**。

改从当前 OD `origin/dev`（`c02b136ab5a2ce52be73e95a02387cd9b432fc23`）的成功 push run
**`42396841706`** 的 `gate-log` 工件 **`13585551963`** 读：

```
gate.log:5583  MEASURE AC-17|05 start
gate.log:5585  MEASURE AC-17|05 complete (54.2s)
gate.log:5776  VERDICT AC-17|05: proven
gate.log:5779  VERDICT AC-17|08: proven
```

同一份工件还佐证了 wave 32 §2.2 的结论：`AC-17|08` 探针读 **proven**，与台账一致，
所以它没有存量 finding 可钉，不出现在 `acceptance-gate-ratchet.json` 的 8 个键里——那是结论，不是缺账。

行数口径更正：该 `gate.log` 是 **78,672 行（`wc -l`）**；wave 32 写的 78,673 是按
`split('\n')` 计（含末尾空元素）。两者指同一文件，md5 `202f1fcb4c9b8f15ef22b3f15f2b9ae0`。

## 3. AC11 / AC14 的新读数（同一仪器、同一参数）

### AC11 运行时证据分子：417 → **443/1048**

```
python3 src/backend/scripts/task_param_audit.py --out-dir /tmp/it204/param-audit-1109 --env-file src/backend/.env
python3 src/backend/scripts/ops/ac11_runtime_evidence.py \
  --census /tmp/it204/param-audit-1109/task_param_bind_audit.json \
  --out-dir /tmp/it204/ac11-1109 --since 2026-11-05T14:00:00+00:00
```

`as_of_utc = 2026-11-09T03:01:29+00:00`，普查 `2026-11-09T03:01:25Z`：
`completed_and_grew 443 + completed_no_delta 148 + failed_only 29 + not_run 428 = 1048`。
逐族：`accepts_var_kwargs 380/85/13/408`、`binds 63/63/9/20`、`unexpected_param 0/0/7/0`
（那 7 行仍只有失败执行）。普查元数据：`tasks_audited 1048`、`script_rows 1066`
（active 1051、without_file 9）、`safe_default_injected 337`、`ghost_script_ids 9`。

**签字面已就绪但仍属属主**：`/home/yun/afi204-evidence/2026-11-07-ac11-review/review-file.reuse-6.unsigned.json`
的 6 行 `REUSE_PROVIDER`，其 6 个 `file_sha256` 与当前文件**逐一仍匹配**，只有
`reviewer` 与 `reviewed_at_utc` 为空。仪器自己拒绝替人签字（`assigned.value = "not computed here"`）。
本轮**没有**填这两个字段。另注：已提交的 `script_disposition_ledger.{csv,json}` 里
`REUSE_PROVIDER` 计数为 0（983 空 / 63 EXTEND / 8 HELPER / 3 UNDECIDED），那 6 行只在
`--limit 0` 的运行里出现——这个差异本身要属主看见，不能由我抹平。

### AC14 小时链：19 → **31/48**，无断点

`evidence/2026-11-08-wave32/ac14_hourly_chain.py`，读数 `2026-11-09T03:01:15Z`
（db utc `2026-11-09 03:01:15` / local `11:01:15`）：task 1049 `armed=1`、cron `3 * * * *`，
部署锚 `2026-11-07T19:26:47Z` 之后 **31** 条执行，11-07 20Z … 11-09 02Z 每小时恰好一个
`['completed']`，连续 completed 槽位 **31**，窗口内 0 失败 0 缺行。
`first non-completed slot: 2026-11-09 03:00, None` **不是断点**：cron 在 :03 触发，测量在 :01:15，
该小时还没到点。

**AC14 仍未达标**：还差 17 个自然小时，按 1/小时观测节奏第 48 槽是 2026-11-09 19Z（19:03Z 触发），
即约 `2026-11-09T19:05Z` 才可能到齐。本轮不预告、不提前判定。

## 4. AC01：锚无漂移，但运行资产面的缺陷在恶化

- 锚清单（部署树 `ce97f53f5`，`refresh_script_migration_inventory.py --check --snapshot-commit 29afaeb47`）：
  **matched 1057 / mismatched 0 / missing 9 of 1066**，`in_sync=1057, ghost_registration=9`，
  unexplained 0，派生门禁 **1057/1057 PASS**。与上一读数逐字节相同，**无漂移**。
  `origin/dev` 只比部署树多 1 个提交（`7c8f6f2f1`），且只动 CI/测试/文档，不碰任何被锚路径。
- 运行资产面（`evidence/2026-11-07-wave31/unit_runtime_asset_audit.py`）：
  **10 units / 8 missing-on-disk / 7 unique missing paths / 0 unversioned-running-source**。
  7 个路径仍全部 `in_head=False, in_dev=False, in_any_ref=False`：
  `run_etf_nav_shard.sh`、`run_dce_option_recovery.sh`、`run_dce_browser_capture.sh`、
  `run_option_history_loop.sh`、`policy_expiry_watchdog.py`、`backfill_stock_amount_sina.py`、
  `run_stock_tail_slices.sh`（均在 `src/backend/scripts/ops/`）。
- **「0 个未入库源码」是空真**：那 7 个源文件既不在任何 ref、也不在盘上，所以根本没有东西在执行。
  不能把这条读成「运行代码都已入库」。
- **缺陷在恶化**：`etf-nav-backfill@0–3` 四个 unit 仍 `activating/auto-restart`，
  `NRestarts` 从 7895 涨到 **11695（+3800）**。停/禁用 unit 属服务状态变更，**需属主批准**，
  本轮未动。`full-history-recovery` unit 为 `failed`，但它的两个目标
  （`run_with_core_environment.py`、`run_full_history_recovery_worker.py`）在盘上且在 dev——
  这条与上面 7 条不同类，值得单独查。
- 主服务健康：`ai-for-investor.service` active/running，MainPID 2925396，
  `ExecMainStartTimestamp Sun 2026-11-08 16:22:49 CST`，`NRestarts=0`，`/docs` HTTP 200。

**AC01 仍 NOT_PROVEN**：判据要求两仓重新冻结 + 未提交 diff 哈希、七面全部带环境身份与采集时间、
显式分母 + 双向 anti-join 且零未解释项。本轮只刷新了源文件面与 systemd 面；
9 个 CSV ghost 与 7 个运行 ghost 是**未解释残差**，不是已 reconciled 的处置。
判据还明确禁止把 1,066 scripts / 1,103 tasks 当当前总数，故 `1057/1066` 只是历史快照分母。

## 5. #303 无法合并的真实原因，与本轮处置

#303（`da0f1c2d7`）**39/39 绿但 `mergeable_state=dirty`**：dev #295（`67b42f9c8`，复权基过滤）
与 #280（`4eeeae8c4`）在它分支之后重写了同一路由与同一 `get_table_rows()`。
`git merge-tree --write-tree origin/dev da0f1c2d7` exit 1，**2 文件 / 7 hunk 冲突**；
测试与 types 文件虽能文本自动合并，但**语义会坏**（dev 的测试仍断言 #303 删掉的 4-tuple）。

它**不是冗余**：dev 上没有 `table_pagination.py`，`data.py:562-568` 仍是每页一次
`SELECT COUNT(*)` + 无 `ORDER BY` 的 `LIMIT/OFFSET`。

本轮处置（**普通推送，无 force-push，无历史重写**）：把本地已整合两侧的内容超集
`a59dca628ecd3a5440f94685afdf3f5ee6c1144b` 推到新 ref
`fix/afi-table-pagination-determinism` 并开 **#332**。本机复核：

```
git merge-tree --write-tree origin/dev a59dca628  -> exit 0, tree 1b34518116a9…
git rev-list --count origin/dev..a59dca628        -> 2  (161763cff + dev merge)
git diff --stat origin/dev...a59dca628            -> 5 files, +1195 / -65
```

该提交此前**仅存在于本地**：远端分支已删、无任何 PR 引用它，在 GitHub 上属未引用对象、有被 GC 风险；
推送即保全。它自身 0 check-runs，所以旧的「已验证」只是本机口径，#332 的 CI 才是它第一次远程度量。
风险分类用仓库自己的分类器复跑为 **R1**（这些 akshare 路径不在 risk-map rules 内，走 default）。

**#303 保持 open**：关闭它或往它 force-push 都是属主的决定，本轮不替属主做。

## 6. #331（门禁修法）本轮状态

`Backend - Unit Tests (py3.12)` 在 head `003760474` 上 1 failed / 10752 passed：
`tests/test_ai_strategy_research_service.py:3799 assert len(improver.calls) == 1` 得到 2，
且两条记录都是 `code_validation_failed: True, repair_attempt: 1`、
`Strategy code validation failed before backtest: strategy code sandbox validation…`——
走的是**沙箱校验拒绝→repair** 路径，不是该测试意图的样本外失败路径。
同一测试在 dev `7c8f6f2f12f` 的 py3.11/py3.12 都绿，而 #331 的 diff 不含任何 backend 代码。
本轮已 `rerun-failed-jobs`（run `42491915088` attempt 2，作业 `128956438468`）并另派根因调查；
**在根因清楚之前不把它写成「偶发、重跑即可」**。

## 7. 仍 OPEN 且本机不可闭合（诚实登记）

属主裁定/签字：AC11 的 6 行 `REUSE_PROVIDER`（`reviewer` + `reviewed_at_utc`，包已就绪、哈希仍匹配）、
AC13 的 29,126 历史 claim 行处置与 flag-on、`types-python-dateutil` 是否进 lock（采集平面 2→0）、
ruff 版本分裂改哪一侧（`ci.yml:397` 装 `0.16.2` vs `config/requirements-dev.lock:431` 钉 `0.15.13`，
本轮在 `origin/dev 7c8f6f2f12f` 上复核仍真）、OD 重复触发修法（R3 且 digest 钉需人工 `reviewer`）、
#257 合并集成税形状、#262 dependabot 主版本升级、#303 的关闭/force-push 决定、
以及停/禁用 `etf-nav-backfill@0–3` 等崩溃循环 unit（服务状态变更）。

环境不可达：`push2.eastmoney.com` 3/3 ConnectionError → AC10 与若干 `*_em` 行的真实源对照本机产不出；
AC01 那 7 个脚本的字节在任何 ref 里都不存在，不能凭空补造。

自然周期：AC14 小时链 31/48（约 2026-11-09T19:05Z 到齐），daily 7 / weekly 2 / monthly 1 同样只能按自然周期 accrual。

## 8. AC01 七面本轮全部刷新（带采集时间与仪器坐标）

判据原文（`ACCEPTANCE_AND_CUTOVER.md` §1 矩阵 AC01 行）：重新冻结两仓与未提交差异 hash；
**源文件、实际 DB 任务（含 inactive）、systemd/cron/worker、进程、表、消费者、OpenData 重叠能力**
七面都要有带环境身份/采集时间的清单，各自分母明确且**双向 anti-join 无未解释项**；
旧盘点的 1,066 脚本候选与 1,103 任务只能当历史快照。

本轮产出在 `/tmp/it204/ac01-1109/`，采集时间 `2026-11-09T03:08:51Z`：

| 面 | 仪器 | 本轮读数 |
|---|---|---|
| 冻结 + 环境身份 | `evidence/2026-11-06-wave29/ac01_freeze_and_overlap.py`；`scripts/ops/check_runtime_environment_identity.py` | AFI `ce97f53f5813…`、OD 本地 `051824bd38`（**落后 origin/dev `c02b136ab5` 9 个提交**，故 OD 侧一律读 `git show origin/dev:`）；两仓 `tracked_diff_sha256` 与 `status_porcelain_sha256` 均为空树哈希 `e3b0c442…`；AFI 未跟踪 **1** 项（`var/backups/iteration204/…sql.gz`，列表哈希 `35439087…`）；84 个 worktree、5 个 dirty |
| 源文件 | `scripts/ops/refresh_script_migration_inventory.py --check` | CSV 1066 / 盘上 1057 / git 跟踪 1057；锚 **1057 matched、0 mismatched、9 missing** |
| DB 任务（含 inactive） | `/tmp/it204/ac01-1109/measure_faces.py`（只读 + rollback） | 任务 **1103** 总 / **1048** active / **55** inactive / **1048** armed，全为 cron；50 个 inactive 仍带 next；执行 33030 条，近 7 天 **completed 1058 / failed 1761**；`md_capability_ledger_entries` **0**；MySQL 8.0.46 |
| systemd/cron/worker | `scripts/ops/check_service_runtime_assets.py`；`wave29/unit_execstart_existence.py` | 无用户 crontab、`/etc/cron.*` 无 AFI 条目；**6** 个 AFI timer、18 个 unit、4 个 shard auto-restart、6 个 failed |
| 进程 | `ps -eo pid=,args=`（`verify_api_only_consumption.py --ps-file` 的输入） | 453 行；uvicorn PID 2925396、vite PID 1829 |
| 表 | `ac01_freeze_and_overlap.py::schemas()` | information_schema **171 / 1047 / 75 = 1293** |
| 消费者 | `app/services/market_data/consumer_boundary.py --format json`（纯 AST） | **1935** 文件、**0** 解析错误、**2296** 命中、**1093** 文件有发现；角色 legacy_data_fetch 2162 / service_candidate 49 / ops_script 63 / boundary 11 / app_support 8 / api_consumer 3 |
| OpenData 重叠 | `ac01_freeze_and_overlap.py::od_catalog_overlap()`（指向 `origin/dev:docs/afi204-migration-catalog.json`） | catalog 文件 **1066**，∩AFI **1057**，catalog_only **9**，afi_only **0**；MISSING_PROVIDER 877 / REQUIRES_MANUAL 189；`runtime_verification` **NOT_RUN 1066**；models 319（akshare 10）、endpoints 974 |

**双向 anti-join**：registered→disk = **9 ghosts**（`yield_release_policy`、`forex_hist_sina`、
`etf_realtime_quote_sina`、`fund_monetary_income_history`、`fund_reviewed_unit_nav_history`、
`futures/release_policy`、`cffex/commodity/etf_option_daily_history`）；disk→registered **0**；
tracked→registered **0**；disk△tracked **0**。`ak_data_scripts` **1066** 行（1051 active）→ 同样那 9 个，
反向 **0**。任务↔脚本业务键 dangling **0**；无任务的脚本 **10**（2 ghost + 8 helper）。
运行侧 ghost **恰好 7**，`git log --all` 全 0 命中。**没有新增残差**——但这 9+7 仍是未解释残差，
不是已处置项，所以 AC01 依旧 NOT_PROVEN。

### 8.1 本机环境身份被仓库自己的仪器拒绝（量化了第 266/267 行的测量危害）

`scripts/ops/check_runtime_environment_identity.py` → **exit 2，`allowed=false`**，5 条理由：
解释器 **3.13.5** 而 CI 矩阵是 3.11/3.12；venv 带 `--system-site-packages`；
**14** 个依赖解析到 venv 之外、**11** 个与 lock 钉版不同、**4** 个越出约束。时区 +8h 与 `Asia/Shanghai` 一致。
也就是说：**本机读数不能冒充 CI 读数**这条旧登记，现在有了仪器给出的拒绝理由与计数。
要拿到 `allowed=true` 需要 CI 矩阵那种隔离的 3.11/3.12 venv（属主/运维动作）。

## 9. 本轮新开/推进的 PR

- **#332**（`fix/afi-table-pagination-determinism`，head `a59dca628`）：见 §5。受影响测试
  `tests/test_akshare_management_api.py` 在 a59 代码上本机 **96 passed, 79 skipped in 105.51s**
  （用 `PYTHONPATH` 指向该 worktree，已核对 `app.__file__` 与 `table_pagination.__file__` 确实解析到 a59 树）。
- **#333**（`fix/afi-bond-sql-percent-literal`，head `97facd998`）：修 §4 里 `full-history-recovery`
  的**真实产品缺陷**。`MySQLConvertibleReader._execute` 原来传 `tuple(parameters)`，而 pymysql 只要
  `args is not None` 就做 `%` 插值——空 tuple 也算 args，于是 overview 的
  `DATE_FORMAT(data_date, '%Y-%m-%d')`（`:1179`）里的 `%d` 被当整数转换符，报
  `not enough arguments for format string`（无库实测：`"SELECT DATE_FORMAT(d, '%Y-%m-%d')" % ()`
  → 同一个 TypeError）。worker 分类器据此拒绝债券报告，整轮 exit 2；同一分钟加密腿 exit 0。
  修法是在执行边界传 `None`（不是只给这一条 query 转义 `%%`），并加 2 条回归：一条钉
  `executed == [(sql, None)]` 且反证 `sql % ()` 会抛，一条走**真实 overview 路径**断言每个
  `DATE_FORMAT(data_date` 探针都以 `args is None` 到达驱动且字面量完好。
  本机 **38 passed in 15.64s**（36 既有 + 2 新），ruff check/format 干净。
  **未重启任何 unit**：服务状态变更需属主批准，故该 unit 仍 failed，直到有人去跑它。
- **#331**：见 §6，py3.12 那条红仍在查根因，未写成「偶发」。

## 10. 本轮明确不做的事

不替属主填 AC11 那 6 行的 `reviewer`/`reviewed_at_utc`（包已就绪、6 个哈希我自己复核仍匹配）；
不 force-push、不关闭 #303；不停/禁用任何崩溃循环 unit；不为那 7 个在任何 ref 都不存在的脚本编造字节；
不把本机读数当 CI 基线；不因 AC13 的 19 个离线测试绿就宣称 AC13 闭合（生产接线仍缺）。
