# Wave 31 测量记录（2026-11-07）

本文件只记录本波**实测**到的数字与判定，不改写任何 AC 结论。凡"未测到"的地方写明未测，
不以相邻可证量代替。所有 as-of 时间均为 UTC。

## 1. 合并列车与类型平面

- `#314`（`fix(data-fetch): narrow the remaining 55 collection-plane errors per site`）
  已合入 `dev`，合并提交 `96741b8af8`。
- 在同一棵树上用 CI 镜像环境（Python 3.11 + `config/requirements-dev.lock`，mypy 1.20.2，
  `--cache-dir` 指向空目录）实测采集平面：
  `mypy_ratchet[collection]: advisory, no baseline yet - errors=7 checked=1108`。
  这是**本机对 CI 环境的复现读数**，不是基线；基线必须取 CI 作业自己打印的那一行
  （工具 `scripts/ci/freeze_collection_baseline_from_ci.py`，PR #318）。
- 复核这条链：dev `3325626f96` = 67 → `#314` 后 = 7；`#319` 预计 = 2；最后 2 条是
  `python-dateutil` 缺 stub（加 `types-python-dateutil` 到 lock 即 0，属主决定）。

## 2. AC11 分子：318/1048 @ 2026-11-07T19:02Z

同一仪器（`scripts/ops/ac11_runtime_evidence.py`）、同一 `--since 2026-11-05T14:00:00+00:00`、
同一定义；唯一变化是普查按**当前 armed 集**重跑（1048，而非停用前的 1098）。

- `AC11_RUNTIME_EVIDENCED = 318 / 1048`（上一次可比读数：168/1048 @ 11-06T15:36Z）。
- 四分类：`completed_and_grew 318 + completed_no_delta 109 + failed_only 20 + not_run 601 = 1048`。
- 静态族（`scripts/task_param_audit.py`，19:02:40Z）：`binds 155 / accepts_var_kwargs 886 /
  unexpected_param 7`；7 条全部是 `_ingest_mode`；`safe_default_injected_scripts=337`；
  `registered_script_rows_audited=1066`，其中 9 行无文件（已停用，属孤儿注册行）。
- 口径不变：这是**处置的输入**，不是处置。`assigned` 仍为 0，须属主对 6 条 REUSE_PROVIDER
  逐行填 `reviewer` / `reviewed_at_utc` 后用 `--registration-export` 重跑。

## 3. AC13 判定：停用本身没有止住幽灵任务

只读仪器 `evidence/2026-11-07-wave31/ac13_verdict.py`（`SET SESSION TRANSACTION READ ONLY`），
as-of 2026-11-07T18:59:57Z：

- 队列 A 的 50 个任务 50/50 仍是 `is_active=0`。
- **停用之后仍执行 48 次**，落在 46 个任务上，全部 `failed`：
  - 2026-11-06 22:30–22:45Z（41 行）
  - 2026-11-07 00:35–01:43Z（31 行，其中 1095/1096 各 2 次）
- 与停用前对照：2026-10-20..11-06 11:45Z 共 798 次（323 completed / 475 failed），
  说明该队列确实在触发。
- 01:43Z 之后没有新执行**不构成修复证据**：它们的 cron 是固定 CST 槽位，下一批是
  11-07 22:30Z 与 11-08 00:35Z。
- 时钟基准经复核：`ak_task_executions.created_at`/`start_time` 是 UTC（最新 scheduler 行
  19:03，同刻 `UTC_TIMESTAMP()`=19:04:27，而 `NOW()`=11-08 03:04 CST）。

**判定：AC13 仍是 NOT-PROVEN，但缺口从"是否仍触发"变成"#306 是否生效"。** #306 已合入并在
2026-11-07T17:22:14Z 部署（`ai-for-investor.service` 的 `ExecMainStartTimestamp`，
`NRestarts=9` 为累计值，`/docs` 200）。22:30Z / 00:35Z 两个槽位之后才能判。

## 4. `Backend - Unit Tests` 间歇红的根因（CI 门禁债务第 264 行）

症状：`[gwN] node down: Not properly terminated` + `worker 'gwN' crashed while running
...test_ai_strategy_research_task_api_runs_generated_goal_full_pipeline`，无 traceback。
今天已在 #308 / #313 等不同 PR、不同 worker（gw2/gw3）上重复出现。

根因已可复现：`src/backend/pytest.ini` 的 `timeout_method = thread`。pytest-timeout 2.4.0 的
线程法在超时后转储栈并 `os._exit(1)`（`pytest_timeout.py:542`），xdist 只能报"node down"，
栈本身丢失。用仓库自己的 `pytest.ini` 对一个睡眠测试做 A/B（`-n 1 -o timeout=2`）：

| method | 结果 |
|---|---|
| `thread` | `worker 'gw0' crashed while running 'test_hang.py::test_hang'` —— 与 CI 逐字相同 |
| `signal` | `FAILED ... Failed: Timeout (>2.0s) from pytest-timeout.` —— 带卡住帧的 traceback |

同一测试在本机 `-n 1`、无覆盖率、无四路争用下需 **19.73s**，而旧上限是 30s：CI 的覆盖率与
争用只要放大 1.5 倍就越线。修法（PR #321）为 `timeout_method = signal` 且上限 60s；
在新配置下该测试原样通过（`1 passed in 19.73s`）。

## 5. AC01 锚：重建流程已端到端验证，但暂不入账

在 `9209697211`（dev `96741b8a` + #313 工具）上跑完整流程（`evidence/` 里保留 check-before /
emit / check-after 三份 JSON）：

- 之前：`content_drift=891, ghost_registration=9, in_sync=166`，**0 unexplained**，
  derivation gate **166/166 PASS**；891 条漂移全部归因到"最后触碰该文件的提交"（839 条归 #270）。
- `--emit` 后：`in_sync=1057, ghost_registration=9`，**0 unexplained**，
  derivation gate **1057/1057 PASS**；改动 891 行（891+/891−）。
- **未提交**：#308 / #316 / #319 仍会改 `app/data_fetch/scripts`，现在冻结锚会再次腐烂。
  流程脚本已固定为 `evidence/` 中的 `ac01_reanchor.sh`，待最后一个采集面 PR 合并后执行。

## 6. OpenData 记账面

- OD `dev` = `c02b136ab5`，该 sha 的 CI run `42396841706` success。
- 按 CI 门禁债务第 262 行，已对 dev 发出 `sync_acceptance_ratchet=true` 的 dispatch
  （run `42404291048`，19:03:03Z 入队）。预期工件为 6 钉 + `AC-1|08`，且不再出现 `AC-5|07`。
  工件到手前不写任何入账结论。

## 7. AC01 运行资产面：8 个 unit、7 个不存在的脚本、0 个未入库源码

新仪器 `evidence/2026-11-07-wave31/unit_runtime_asset_audit.py`（只读）对 10 个
`ai-for-investor-*` user unit 的 `ExecStart` 目标逐条回答三个问题：在磁盘上？在 `origin/dev`？
在**任何** ref？结果：

- **8 个 unit 指向的脚本在磁盘上不存在**，合计 **7 个唯一路径**
  （`run_dce_browser_capture.sh`、`run_dce_option_recovery.sh`、`run_etf_nav_shard.sh`、
  `run_option_history_loop.sh`、`policy_expiry_watchdog.py`、`backfill_stock_amount_sina.py`、
  `run_stock_tail_slices.sh`）。
- **0 个 unit 实际执行"在磁盘但不在任何 ref"的源码**。这纠正了 wave 29 表述可能带来的
  误读：本机没有"未评审代码在跑"，真实缺陷是**可用性**——8 个 unit 永远起不来。
- 其中 `ai-for-investor-etf-nav-backfill@.service` 处于 `activating`，
  **`NRestarts=7895`**，`RestartSec=30`，即每 30 秒重试一次、已重试近 8 千次。
- `.venv/bin/python` 与 `node_modules/vite/bin/vite.js` 是解释器/打包产物路径，不计入
  "未入库源码"；把它们算进去会把结论夸大成 10 个 unit，是不成立的。

关闭方式只有两条：把 7 个脚本入库，或把 8 个 unit 改指向/停用。两者都是属主/运维决定；
这些文件无法从任何 ref 重建，凭空补写等于发明行为而不是恢复。

## 8. 本波明确不做的事

不替属主签 disposition；不把本机读数当基线；不在仍有采集面 PR 未合时冻结 AC01 锚；
不把"01:43Z 之后没有新执行"写成 AC13 已修复；不把 PR 合并或测试通过当作 AC 判定闭合。
