# 迭代 204 · 集成波次 28（2026-11-06，UTC 2026-11-05 日间至 18:30）

本文件记录 Wave 28 的实测读数、被纠正的既有说法与仍被挡住的面。除另行标注外，所有
`file:line`、SQL 计数与 API 读数都由记录人在本波当场打开/执行并读回；集成属主原始工作稿在
`/tmp/afi204_wave28_evidence.md`，凡本文引用其结论处均已复核，复核不一致的已就地改正并列入 §6。
取证脚本：`/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/`（`MANIFEST.tsv`、
`CONTRACT_DUMP.txt`、`afi204_ac13_precheck.py`）。

### Wave 28（2026-11-06）：运行时活过来了，仪器先被拆出两处缺陷，代码平面又被证实缺了一层

## 1. 本波结论摘要

1. **采集确实回来了。** 修复后第一个 12 小时窗内直接 SQL 读到 76 条执行、
   `completed 72 / failed 4`（本文 §2，`failed` 全部可归因）；对照 Wave 27 的九天全量失败。
   这只是 DEPLOYMENT 面的存活读数，不是覆盖率。
2. **AC14 仪器本身有两处缺陷，都已修并进 #282**：cron 按 `Asia/Shanghai` 求值而
   `created_at` 存 UTC（`src/backend/app/config.py:275-276`、
   `src/backend/app/services/akshare/scheduler.py:49/71/78/82`），以及手触发行可以顶替自然槽位。
   修后同库同窗复测：daily 0→5、weekday_daily 0→3、weekly 0→1、sub-daily 6→28、
   `unknown` 17→0、hourly 仍 103（§3）。**结论：达标为 0 的一部分历来是仪器假阴性。**
3. **`Check diff coverage` 的红不是覆盖率。** 日志原文是
   `diff_cover.command_runner.CommandError: fatal: origin/dev...HEAD: no merge base`
   （job 127337387339，2026-11-05T16:26:58.5457450Z，前一行是
   `9001 passed, 234 skipped`）；`.github/workflows/ci.yml:689-699` 用 `--depth=1` 取 base，
   所以 head 必须已含 base tip。合入纪律：先 update-branch、等全部跑完、再连续合（§4）。
4. **幽灵代码平面被证实且规模可数**：本机扫描 5,629 个 `.pyc`，72 个无源码孤儿、共 2,274,034 B；
   领取/围栏（claim/fence）平面与 `ak_task_run_claims` 的模型、迁移都不在任何 ref 里。
   **因此 AC13 是「未实现」而不是「未测」**：git 里没有 claim 写入者（§5）。
5. **恢复闭环仍被同一个原因挡住**：`ai-for-investor-full-history-recovery.service`
   每分钟触发、每次 `status=2/INVALIDARGUMENT` 具名失败关闭（当场读回
   `required runtime inputs missing: …/bond_convertible_history_controller.py`、
   `backfill_etf_nav_controller.py`，`run_id 20261105T182607Z-d2208b7286fb`）。
   要它变绿需要 #273+#283 合并并且本机工作树快进。
6. **本波的诚实要求**：多处先前读数被当场推翻（§6），包括我自己的 746/1,098（真值 50）、
   「4,781 条 failed claim 带未来 `next_retry_at`」（实测 0）、OpenData #196 的阻塞归因，
   以及上一位 agent 报的两条基线失败（不可复现）。

## 2. 运行时修复之后的第一个自然周期读数

**平面声明：本节全部是本机 DEPLOYMENT 观测。** 它只证明「修复后的进程在按 cron 写入执行行」，
不证明覆盖率、不证明字段级源一致（AC10）、不证明源侧范围（AC11）、也不构成 REAL_SOURCE 证据。

12 小时窗（属主工作稿：`report_iteration204_acceptance_window.py --hours 12`，
2026-11-05T16:52Z 运行，窗 2026-11-05T04:52Z→16:52Z UTC，armed 任务 1098）。
下表为工作稿读数；**状态分布由我用直接 SQL 复测**：

| 口径 | 属主工作稿 | 本文当场复测 |
|---|---|---|
| armed 任务 | 1098 | 1098（`SELECT COUNT(*) … WHERE is_active=1`） |
| 同窗执行状态 | completed 73 / failed 4 | **completed 72 / failed 4**（见 §6 第 6 条：73 是散文算术滑点，报告表本身相加即 72/4） |
| 14:44 UTC 重启以来 | 57 条 | 75 条（`created_at>='2026-11-05 14:44'`，最早 14:46:09） |

按 `--hours 12` 表的分族读数：weekday_sub_daily 42 completed / 1 failed、weekly 30 completed、
hourly 3 failed、daily/monthly/weekday_daily/unknown 全 0——与 72/4 一致。

四条失败逐条归因（SQL 复测，全部 `triggered_by='scheduler'`）：

| task | 时间（UTC） | 错误文本 | 归因 |
|---|---|---|---|
| 1049 `crypto_hourly_market`（cron `3 * * * *`） | 14:03 / 15:03 / 16:03 | `Script call timed out after 600 seconds` | 600 s 超时地板；#280 的 1800 s + 可杀子进程尚未部署。实测到 18:03 仍在逐小时重复同一失败（13:00 以后 5 条） |
| 389 `etf_fund_hist_em`（cron `20 8,22 * * mon-fri`） | 14:20 | `EtfFundHistEm.run() got an unexpected keyword argument 'source'` | #284 只做静态度量的参数绑定缺陷的活体实例 |

14 天窗（2026-10-22T17:27Z → 2026-11-05T17:27Z）**由本文自行复算**：载入 #282 修正后的
`classify_cadence`/`expected_slots`/`consecutive_completed_slots`，直接读库、按族聚合，
窗内执行行 10,760 条：

| 族 | 任务数（修前/修后） | 最长连续槽位：UTC 枚举（修前） | 最长连续槽位：Asia/Shanghai（修后） | 完成：自然/手触 |
|---|---|---|---|---|
| daily | 32 / 32 | 0 | **5** | 135 / 1 |
| hourly | 1 / 1 | 103 | 103（无回归） | 103 / 1 |
| monthly | 21 / 21 | 0 | 0 | **0 / 20** |
| unknown（槽位不可判） | **17 / 0** | — | — | — |
| weekday_daily | 17 / 32 | 0 | **3** | 77 / 2 |
| weekday_sub_daily | 83 / 85 | 6 | **28** | **220** / 47 |
| weekly | 927 / 927 | 0 | **1** | **113 / 685** |

任务数合计 32+1+21+32+85+927 = 1098，与 armed 计数闭合。达标列全为 0，这是诚实读数：
AC14 目标是连续 7（daily/weekday_daily）/2（weekly）/1（monthly）/48（hourly），
而九天停机吃掉了 14 天里的绝大部分自然周期。**本节不改变任何 AC 判定。**

## 3. AC14 仪器本身的两处缺陷与修正

### 3.1 时钟面：cron 在 Asia/Shanghai 求值，`created_at` 存 UTC

打开的原文：`src/backend/app/config.py:275-276`
（`AKSHARE_SCHEDULER_TIMEZONE` 默认 `"Asia/Shanghai"`）；
`src/backend/app/services/akshare/scheduler.py:49`（`AsyncIOScheduler(timezone=settings…)`）、
`:70-71`、`:75-78`、`:81-82`（每一支 `CronTrigger.from_crontab(..., timezone=settings.AKSHARE_SCHEDULER_TIMEZONE)`）。
`ak_task_executions.created_at` 为 UTC（Wave 27 §5 已同连接钉死）。
报告器原先在窗口自身时区（UTC）里枚举槽位，8 小时偏移使 daily/weekly/monthly 的连续判定
结构上不可能成立——平台再健康也永远读 0。

修正前后（同库、同 14 天窗，本文复算，见 §2 表）：daily 0→5、weekday_daily 0→3、weekly 0→1、
sub-daily 6→28、unknown 17→0、hourly 103 不变。测试 15→18 条，含反事实（同一 cron 用
`cron_tz="UTC"` 对三次真实运行判 0，用 `Asia/Shanghai` 判 3）。
**未核实**：属主工作稿记录的容差校验（scheduler 行 649 条、偏移 p50 0.0 min / p90 0.1 min、
99.8% 落在 ±900 s 内；manual 5,354 条仅 0.9% 落在槽内）本文未复算，复核方法是按
`triggered_by` 分组计算到最近期望槽位的偏移分位数。

顺带定性的仪器疑点（本文当场读回，记为开放问题，不作证据使用）：`next_execution_at` 不是可靠的钟。
task 1049（`3 * * * *`）14:03–18:03 UTC 连续执行，列值仍是 **2026-11-05 23:03**；
task 389 实际 14:20 UTC（=22:20 CST）跑过，列值 **2026-11-06 08:20**；
task 139（`1 17 6 * *`）列值 2026-11-06 17:01，而按 CST 算出的自然槽是 2026-11-06 09:01 UTC。
`scheduler.py:109/120/155` 只是把 `job.next_run_time` 原样写入，没有回退写入路径。
**结论：AC14 连续度只从 `ak_task_executions.created_at`（UTC）算，`next_execution_at` 记为仪器未决项。**

### 3.2 触发面：手触发行能顶替自然槽位

全表 `triggered_by` 实测：`manual 26,437 / scheduler 5,437`（属主读数 5,422，本文读数已随之后的自然周期增长）。
修复前 `summarize()` 把任意 `completed` 行的时间戳都喂给 `consecutive_completed_slots`，
一次手点只要落在槽位 ±900 s 内就能续上 streak——而 AC14 明确是自然周期判据，
本项目的既有不变量是手触发不得消耗 cron occurrence（B29）。修复：只取 `scheduler` 行计分，
手触发完成另列报告，并加反事实测试（手触发行不续 streak、scheduler 行续）。

**撤回的预测（必须留档）**：属主先前预测「排除手触发行后 daily/weekly 的连续数会下降」。
实测**没有下降**——14 天窗内落在槽位 ±900 s 内的手触发行只有约 7 条，
上面 §2 表的 streak 列就是用「仅 scheduler 行」算出来的，与修后数值逐一相同。
**膨胀发生在总数列，不在 streak 列**；修复仍然必须做，理由不是今日数字，
而是 AC14 不能可以被手点满足，而注水的 streak 在报告里与真实 streak 无法区分。

## 4. 门禁机理：`Check diff coverage` 的红不是覆盖率

失败原文（本文自行从 Actions 日志取回，非转录）：

```
2026-11-05T16:26:55.7053750Z ========= 9001 passed, 234 skipped, 71 warnings in 3711.99s (1:01:51) ==========
2026-11-05T16:26:57.8384361Z diff-cover coverage.xml --compare-branch="origin/dev" --fail-under=60
2026-11-05T16:26:58.5457450Z diff_cover.command_runner.CommandError: fatal: origin/dev...HEAD: no merge base
```

（run 42049570205 / job 127337387339，`Backend - Unit Tests (py3.12)`，PR #273 的旧 head `5e6b513c7`。）

机理三条，全部打开过原文：

1. `.github/workflows/ci.yml:689` 是 `Check diff coverage` 步骤，`:698`
   `git fetch --no-tags --depth=1 origin "${{ github.base_ref }}"`，`:699` 即上面的 diff-cover 命令。
   浅取 base 后，若 head 不含 base tip，三点语法找不到 merge base，直接 `CommandError`。
2. `src/backend/.coveragerc:2` 是 `source = app`，且 `:4-6` 还 omit 了 `app/data_fetch/**`。
   于是 **`scripts/`、`tests/`、`deploy/` 根本不被测量**，diff-cover 对它们无话可说——
   #273 的红不是「新增脚本没测试」，是「取不到 diff」。
3. 后果即合入策略：**先对每个 PR 做 update-branch（服务端把 dev 合进 head），等所有 run 跑完，
   再背靠背连续合并**；因为 squash 合并会移动 dev tip，只要还有一个兄弟 PR 在跑，
   它跑完时 base tip 已变，diff-cover 会再次 `no merge base`。
   本机可验的分支：#274/#280/#285/#287/#289 的 head 在本地对象库里，
   `git merge-base --is-ancestor 3e9f4a76e… <head>` 全部为真；#273/#281/#282/#283/#284 的 head
   是服务端 update-branch 产生的合并提交，本机没有该对象，无法本地复算，
   但当场 API 读回 `mergeable=True`、`mergeable_state=unstable`、`failed=[]`。

同一步骤里**真正**的内容型失败只有一条，且不是覆盖率：
`Backend - Lint & Type Check` → `src/backend/app/services/akshare/script.py: 2157 lines exceeds baseline 1823`
（job 127405373101；基线见 `scripts/ci/large_file_baseline.json:16`；同一 job 里 mypy 行
`errors=0 baseline=0 delta=+0 checked=742`，ruff 两步无输出）。
处置是把 PR 自己新增的 worker 监督符号抽到 `app/services/akshare/script_worker_runtime.py`，
**不是**抬基线。（本文在 `.wt-afi-killable` 里看到该抽取正在进行、工作树为脏，
故本地行数不可引用：dev 副本 1823 行。）

## 5. 幽灵代码平面：运行时的另一半代码不在版本控制里

**盘点由本文自行重跑**（`src/backend` 下 `app/ scripts/ alembic/` 的 `__pycache__`，
判据是同名 `.py` 源文件不存在）：

```
scanned 5629 pyc / orphans 72 / bytes 2274034
```

与留档清单 `/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/MANIFEST.tsv`（72 行、第 2 列求和 2,274,034 B）
逐项一致。构成（按清单实测，替代工作稿的约数，差异见 §6）：

| 族 | 数量 |
|---|---|
| `scripts/` 控制器/审计/验证（含五个恢复控制器、`audit_*`、`*_managed_acceptance`） | 21 |
| `scripts/deploy_*_schema` | 11 |
| `scripts/ops/*`（`backfill_stock_amount_sina`、`dce_option_*`、`policy_expiry_watchdog`、`cfets_daytime_managed_acceptance` 等） | 11 |
| `app/data_fetch/providers/*`（cffex、forex eastmoney/sina、fund nav、reviewed-unit NAV、futures snapshot、sina index schema、stock snapshot…） | **9** |
| `app/data_fetch/scripts/*` | **9** |
| `app/services/`（`fund_metric_semantics`、`fund_nav_semantics`、`market_instrument_option_history`、`stock_analysis/…`(py311)） | 4 |
| `app/services/akshare/{run_coordinator,write_fence,script_worker}.py` | 3 |
| `app/data_fetch/utils/stock_universe` | 1 |
| `app/models/akshare_scheduler.py`（claim 表的模型） | 1 |
| `alembic/versions/20261019_akshare_*`（幽灵迁移两条） | 2 |

为什么必须在合并之前抢救：#280/#283 会把真实 `.py` 放到 `write_fence.py`、`script_worker.py`
和五个控制器路径上，下一次 import 就**静默覆盖** 10-20/10-25 的更丰富字节码。

不在 git 的证据（当场执行）：`git cat-file -e origin/dev:src/backend/app/services/akshare/run_coordinator.py`
→ 不存在；`write_fence.py`、`script_worker.py`、`app/models/akshare_scheduler.py` 同样不在 origin/dev；
Wave 27 另已实测五个控制器在任何 ref 的 added-in 计数为 0。
本文另测：`git log --all` 现在能找到 `run_coordinator.py`，唯一命中是本波新开的
`bfcacd7e8`（PR #289，`feat(akshare): re-implement durable run coordinator and claim models`）——
**那是重新实现，不是找回**；五个控制器同样只有本波 PR 分支这一份新增。
`git fsck --dangling` 本文读回 25 个悬空提交（工作稿记 176，见 §6）。

恢复度：10 个可用 ≥0.95 符号一致度从 `var/reports/` 留档里认回（含 `write_fence` 0.97），
**65 个在磁盘上任何地方都没有副本**，其中两个最承重的 `run_coordinator.py`、
`app/models/akshare_scheduler.py` 不在可恢复集合里。
符号一致度表本文**未复算**（需按留档逐份编译再取 top-level 符号集比对，
留档 dump 在 `CONTRACT_DUMP.txt`，1,520 行，可据此复算）。

**领取/围栏平面（claim plane）实测读数**（本文只读 SELECT）：

```
ak_task_run_claims 总计 29126 = completed 24345 + failed 4781
COUNT(next_retry_at)=0  COUNT(lease_expires_at)=0
4781 条 failed 全部 completed_at IS NULL
MAX(created_at)/MAX(updated_at) = 2026-11-05 00:45(:02)   MAX(completed_at) = 2026-10-27 00:55:35
MAX(ak_task_executions.created_at) = 2026-11-05 18:2x（本文读数；工作稿 18:04）
```

即：执行面在修复后一直写，**领取面在 00:45 UTC 之后一个字都没写**，而重启在 14:44 UTC。
唯一与之一致的机制是工作树里的 `.py` 随分支移动而消失——这正是 §5 的幽灵平面。
AC13 因此是 **unimplemented，而不是 unmeasured**：git 里从来没有 claim 写入者。
反向硬证来自本波 #289 的门禁：`Check - Alembic Migrations` 失败于
`scripts/ci/check_orm_schema_drift.py` → `FAIL: 2 drift(s) detected`，
两行分别是 `ak_scheduler_control`、`ak_task_run_claims` = 「expected in ORM, not migrated」
（job 127427109672）。**模型进了 git，迁移仍然没有**，属主不为这两条幽灵 revision 伪造迁移。

预警脚本：`/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/afi204_ac13_precheck.py`
（`/tmp` 同名副本）。**要重跑它，不要相信本文转录的数字。**

配套事实（本文复算，构成 AC13 之外的运行约束）：
`AKSHARE_SCHEDULER_MAX_CONCURRENT_TASKS` 默认 1（`src/backend/app/config.py:278-281`），
`scheduler.py:29/32-34` 建 `asyncio.Semaphore(self._run_semaphore_limit)`、
`:95-96` 每次调度触发的 `_run_task_job` 都要过这个闸；作业默认
`coalesce=True, max_instances=1, misfire_grace_time=3600`（`scheduler.py:48`）。
**1,098 个 armed 任务排在 1 个并发槽后面 → 运行是排队而不是丢弃**，
AC13 的跨进程源额度与 AC08 的性能界都以此为前提。

## 6. 被纠正的既有说法

| # | 原说法 | 实测 | 结论 |
|---|---|---|---|
| 1 | 「746/1,098 个 armed 任务骑在幽灵模块上」 | 本文按 `is_active=1` 逐 script_id 计数：1,066 条 `ak_data_scripts` 中 9 条无导入得到源码文件，其 armed 任务 26+16+4+1+1+1+1 = **50**，与审计独立给出的 `script_file_absent: 50` 闭合 | **错**。746 来自 `ak_scheduled_tasks LEFT JOIN ak_task_executions … GROUP BY script_id` 的连接扇出，COUNT(*) 数的是 task×execution 对 |
| 2 | 「4,781 条 failed claim 带着未来的 `next_retry_at`，可能反过来挡住采集」 | `COUNT(next_retry_at)=0`、`COUNT(lease_expires_at)=0`，4,781 条全部 `completed_at IS NULL` | **错**，该风险不存在。把协调器放在默认关闭开关后面的理由改变但成立：该平面自 00:45 UTC 起没写过，打开它是未观测的行为变更 |
| 3 | OpenData #196 被 `quality gate` 挡在打印的 `VERDICT AC-1|05: gap` | 本文取回该门失败 job 日志：`FAIL: acceptance-probe gate` 下列出的**唯一**棘轮新增是 `棘轮新增（AC-5|07 / stale-proof）`；`AC-1|05` 确实打印 gap（`runtime=failed/valid=no`，486 条证据问题，前三类 build-source-file-missing=340、build-source-file-hash-mismatch=138、build-log-stale=1）但不是拦下这轮的那一格；同一遍里 `VERDICT AC-17|08: proven` | **归因错误一半**：`AC-5|07` 成立，`AC-17|08` 在本文读到的这次运行（2026-11-05T18:13:45Z，head 7c4c43f89）不是新增未钉格 |
| 4 | 矩阵名未展开的 `skipped` 检查被当成失败 | 处置逻辑已写进工具：`/tmp/afi204_merge_sweep.py:63-71` 明确把 `skipped/neutral` 视为满足必需检查，并注释了 `Backend - Unit Tests (py${{ matrix.python-version }})` 这种未展开名会被误判 | 教训成立；但本文在本波 13 个 head 的 check-runs 里**没有再读到**未展开的矩阵名，故「当前仍在发生」未核实 |
| 5 | 上一位 agent 报的两条基线失败：18 条既有 `DefaultRow` 错误、一条 `executions-view` 基线失败 | 用 `opendata/.venv-quality`（numpy 2.5.0 / pandas 3.0.3，非 conda 栈）在 051824bd 上全量：`758 passed, 35 deselected, 0 errors`（85.7 s），`DefaultRow` 为 0 | **不复现**。`executions-view` 那条本文只见到一个可解释的版本：`tests/publication/test_views.py::TestListExecutions::test_returns_paged_rows` 在 051824bd 失败，是 tmpdb 夹具没有种入执行行；种一行后整包 152 passed——即夹具完备性缺口，不是神秘基线红 |
| 6 | 「同窗 completed 73」 | 直接 SQL：`completed 72 / failed 4`；报告表自身相加也是 72/4（sub-daily 42+weekly 30=72；hourly 3+sub-daily 1=4） | 散文算术滑点，非读数错误 |
| 7 | 幽灵构成「11 providers、11 data_fetch scripts、~20 deploy-schema」 | 清单实测：**9** providers、**9** `app/data_fetch/scripts`、**11** 个 `deploy_*_schema`，另有 21 个 `scripts/` 控制器/审计（工作稿把它们混计成「~20 deploy-schema」） | 总数 72 / 2,274,034 B 不变，族内划分按上表改正 |
| 8 | monthly 族「20 条手触发行全部在 2026-10-26 08:52–09:31」 | 21 个 armed monthly 任务（day-of-month 字段非 `*` 且 month 字段为 `*`）在 `created_at >= 2026-10-01` 共 25 行：`completed/manual` 20、`failed/scheduler` 4、`failed/manual` 1。20 条手触完成行**全部**落在 2026-10-26 08:52:06 → 12:37:22 UTC，其中 12 条（12 个不同任务）在 08:52–09:31:59；那条 `failed/manual` 在 10-26 07:00:09。原说法把 `scheduler` 失败行的最大时间（11-03 19:55）误当成了手触行的跨度端点 | 「0 条自然完成」成立；跨度端点归属错，按上表改正 |
| 9 | sub-daily 自然/手触 222/47 | 220/47（同一 14 天窗、同一分类器） | 2 行差，疑为窗边界；按 220 记 |
| 10 | 悬空提交 176 个 | `git fsck --dangling` → 25 | 未核实：计数随 GC 衰减，需要当时原始输才能定；不影响结论（任何 ref 与悬空提交都不含那 72 份源码） |
| 11 | 被 #287 污染的 `Security - Secret Scan` 只在 #281/#283/#284/#285 | 当场 API：#280/#281/#283/#284/#285/#286 六个 head 的该检查为 failure，文本一致 | 污染面按 6 个 PR 记 |
| 12 | 「17 个 monthly 任务整月无行 → monthly 武装本身坏」 | 按天统计 `triggered_by='scheduler'` 的行：10-01→10-18 **一条都没有**（10 月首行在 10-19），10-19..10-25 每天 11–109 行且几乎全 completed，10-26 起 445→555 行/天且转为大面积 failed，11-05 自 14:44 UTC 重启后 80 行 / 76 completed（重启前 50 行 / 24 completed，当日最大 `created_at` 就是读数时刻，写仍在继续）。用 `CronTrigger.from_crontab(expr, Asia/Shanghai)` 逐条枚举这 17 个任务的窗口内槽位：**15 个**的唯一（或 outage 前的全部）槽位落在 10-01→10-18 这段无行区间内 | **本文 §7 的原归因错**：主因是 10 月上旬调度器整段无行，不是 monthly 武装坏。剩 2 个（248 槽位 2026-10-19 17:47 UTC、284 槽位 2026-10-24 13:16 UTC）落在当天有调度器行的时段仍无行——但 `is_active` 无变更历史（这 21 行的 `updated_at` 全被 11-05 14:45 的整表重载覆盖），**当时是否 armed 无法从这一面判定**，故不记为缺陷，只在 §7 留作下一次自然槽位的观测项 |

## 7. 未解释现象与取证计划

**monthly 族（本节原归因已由 §6 #12 推翻，以下为重写后的读数）。**
21 个 armed 任务（day-of-month 非 `*`、month 为 `*`）在 `ak_task_executions` **全表历史**里
只留下 4 条 `scheduler` 行，全部 `failed`、来自 4 个不同任务，时间是
2026-10-28 00:41 → 2026-11-03 19:55 UTC（300 `41 8 28 * *`、345 `39 23 2 * *`、
252 `55 10 3 * *`、567 `55 3 4 * *`，逐条按 CST 墙钟对齐后与 cron 表达式一致）；
自然完成 **0**，AC14 monthly 目标（连续 1）仍 **未达**。
其余 17 个任务无 scheduler 行。

成因按实测重排：`triggered_by='scheduler'` 的行按天分布显示 **2026-10-01→10-18 整段为空**
（10 月首行 10-19），而 17 个无行任务里 **15 个**的唯一窗口内月度槽位正好落在这段调度器不写行的区间；
只有 248（10-19 17:47 UTC）与 284（10-24 13:16 UTC）在当天确有调度器行的时段错过槽位。
所以「monthly 武装本身坏」**不是本轮成立的结论**：monthly 在调度器活着时确实会自然触发
（10-28→11-03 那 4 条就是），真正未解释的是 10 月上旬那 18 天为何整段无行。

已排除的假设（本文当场执行）：

- 表达式解析：1,098 条 armed 表达式经 `CronTrigger.from_crontab(expr, timezone=Asia/Shanghai)`
  全量试解析，**失败 0**；`next_execution_at IS NULL` 的 armed 任务 **0**。
  （`scheduler.py:135-136` 的 `reload_active_tasks` 确实逐条裸调用 `add_or_update_task`，
  一条抛异常就会中断后续武装——这是**潜在**健壮性缺口，不是本次成因。）
- 排队而非丢弃：`AKSHARE_SCHEDULER_MAX_CONCURRENT_TASKS` 默认 1（`app/config.py:278-281`），
  作业 `coalesce=True, max_instances=1, misfire_grace_time=3600`（`scheduler.py:48`）。
- 日志侧：`ai-for-investor.service` 的重启时间戳当场读回 2026-11-05 22:44:45 CST（=14:44 UTC）；
  journald 用户作用域自该时刻起只留 4 行，因此「misfire 行为 0」**无法从这一面复验**，
  要定它需换取证面（应用日志落盘或 `journalctl` 全量 + `--all`）。

决定性观察（下一次可测）：task 139 `macro_canada_retail_rate_monthly` cron `1 17 6 * *`，
自然槽 **2026-11-06 17:01 CST = 2026-11-06 09:01 UTC**（本文用修正后的枚举器算得，
列值 `next_execution_at=2026-11-06 17:01` 是 CST 墙钟）。11 月 6—8 日窗口内共有
5 个 monthly 任务到槽（139 11-06 17:01 CST、516 11-06 21:57、617 11-07 19:18、
303 11-08 13:00，另 278 11-11 紧随），这是**自 10-19 恢复写行以来第一次**能在
「已知 armed + 采集链路成功」两个条件同时成立时观测 monthly 自然触发。
有行且 completed → AC14 monthly 目标在下一个读数窗口可判达；
无行 → 才是 monthly 武装缺陷，须单开一条仪器缺陷。

**幽灵后端的 50 个 armed 任务。** 代码层面的答案已打开：
`app/services/akshare/script.py:395-425`（`_resolve_callable`，定义在 `:395`）对注册 `module_path` 的
`ModuleNotFoundError` **被吞掉**（`:401-402`、`:415-416` 置 `module = None`），
解算一路落到通用 akshare 接口装载器（`:408/422`），只有它也失败才在 `:425` 抛
`No callable entrypoint found`。因此这 50 个任务到点**不会静默跳过**，很可能照常跑、
甚至记 `completed`——但走的是缺了逐基金水位、业务键 upsert 与快照来源逻辑的那条路，
绿色执行行不是 AC10/AC11 要的语义证据。
本文复测：14:44 UTC 重启以来这些任务 **0 行**（它们的槽位在 2026-11-06 CST 06:30–19:45，尚未到点）。
检查项因此是「到点后有没有行、什么状态、`rows_delta` 多少、走的是哪条 interface」，
其中「有行但走 fallback」比「无行」更可能也更严重。

## 8. 合入清单

dev tip（本文 API 读回）：`3e9f4a76e5a33a9493597d0e0fc4f77da87c6db0`。
下表 head 全部由 GitHub API 当场读回；merge SHA 留空由属主在合入后填写。

| PR | 范围 | 平面 | head SHA（API 读回） | 当场门禁 | merge SHA |
|---|---|---|---|---|---|
| #273 `fix/afi-recovery-runtime-assets` | 恢复 worker 运行时资产 | DEPLOYMENT/CODE | `0dbb3f25f5da86b94c449bb29625f227fce5561c` | 36 检查、2 未跑完、0 失败 |  |
| #274 `docs/iteration-204-wave27-runtime` | Wave 27 台账 | 文档 | `835c43653137e9ef374fb92f28f102377707a1b4` | 28 检查、12 未跑完、0 失败 |  |
| #278 `fix/afi-research-publication-binding` | 研究工件绑定 | CODE/OFFLINE | `391398764bbd1b977e2fc605b14c47b27567619a` | base 仍是 `9f573d34d`（旧 dev），`Lint & Type Check`、`Mypy Ratchet (services)` 失败 → 需 update-branch |  |
| #280 `fix/afi-killable-script-worker` | 可杀子进程 + 1800 s 地板 | DEPLOYMENT | `cd25683c9401cb8354cd1c799319798546c5a950` | `Secret Scan`（被 #287 污染）、`Lint & Type Check`（`2157 lines exceeds baseline 1823`）失败 |  |
| #281 `feature/afi-frontend-coverage-states` | 前端覆盖状态 | OFFLINE | `c59e5f25b3866683083f644f594a426781d99704` | 仅 `Secret Scan` 失败 |  |
| #282 `feature/afi-acceptance-window-reporter` | AC14 时钟（两处仪器修复） | 仪器 | `4cf6b9399eec848f53f6873d73c8f15a97486f31` | 0 失败、8 未跑完 |  |
| #283 `feature/afi-recovery-controllers` | 五个恢复控制器（**重实现，非找回**） | CODE/OFFLINE | `a8dca0486e0bc37ca23aa9a10a575cc7ebc7735b` | 仅 `Secret Scan` 失败 |  |
| #284 `feature/afi-task-param-audit` | 任务参数绑定审计（静态） | CODE/OFFLINE | `8971f3098822245ed7d83c7fe1e67c67ba5f7099` | 仅 `Secret Scan` 失败 |  |
| #285 `feature/afi-service-asset-guard` | systemd 单元 ExecStart 目标审计 | DEPLOYMENT | `d992d3d37b2f1803c0b5c3312be925158819b249` | 仅 `Secret Scan` 失败 |  |
| #286 `feature/afi-ac11-dispositions` | AC11 处置台账（74 proposed） | OFFLINE | `75e5acf3ad07894c1b775b413656266faa5a10ae` | 仅 `Secret Scan` 失败 |  |
| #287 `feature/afi-ghost-script-recovery` | 七个幽灵脚本按符号一致度找回 + `.gitleaks.toml` 逐值放行 | CODE/OFFLINE | `d7b80f6f3379dc7a91d57c1f15b000ad745fea60` | 0 失败、8 未跑完 |  |
| #288 `docs/iteration-204-acceptance-audit-20261106` | 验收审计文档 | 文档 | `04e02311fe20a4b160c82e8daf03518d971a987f` | 0 失败、10 未跑完 |  |
| #289 `feature/afi-run-coordinator` | AC13 协调器与 claim 模型重实现（默认不接线） | CODE/OFFLINE | `bfcacd7e885ffe16101dc66bed357bbd18c4c4ac` | `Check - Alembic Migrations` 失败：`ak_scheduler_control`/`ak_task_run_claims` = expected in ORM, not migrated |  |

**顺序约束：**

1. **#287 必须先落**（它携带 `.gitleaks.toml:47` 的逐值 allowlist
   `b533a93f…`（本文在该分支 blob 上读回该行，对应
   `scripts/ops/cfets_daytime_managed_acceptance.py:53` 的 `PROTECTED_NATURAL_CLAIM_KEY`，
   是确定性 claim 标识不是凭据）），否则 #280/#281/#283/#284/#285/#286 的
   `Security - Secret Scan (177 §D)` 无法重跑转绿——各 PR 的检出读自己的配置文件。
2. 之后对每个仍红的 PR 做 **update-branch + 自审重绑到新 40 位 head + `/runs/{id}/rerun`**，
   等全部 run 跑完，再背靠背 squash 合并（§4 的 `no merge base` 机理）。
3. 合并后把 live 工作树快进到 dev tip：29 个新增路径里只有
   `src/backend/scripts/ops/run_full_history_recovery_worker.py`
   （`sha256 8715a285f2c38ef7d78b44de120ce23b7d3b2dab3d9ed9c4ded678b74b404f83`，与 #273 blob 逐字节相同）
   与本机未跟踪文件相撞，先移到取证目录再让 git 重建。
4. OpenData 侧本轮不入此批：#196 publication seal 被 `acceptance-probe gate` 的
   **新增未钉格 AC-5|07 / stale-proof** 挡住（§6 第 3 条），属主裁定或修复后进账；
   管理运维控制台视图（覆盖/回填/容量）为 OFFLINE 面另开 PR。

### 8.1 Wave 28 续记（2026-11-06 本地闭口复核；未推送项已就地标注，勿当已落库）

下表 head、merge SHA 与 file:line 均由本文当场从 GitHub API / Actions / 工作树读回；
开口窗计数（随时间增长）不在此列。

| PR / 流 | 范围 | 平面 | head SHA（API 读回） | 门禁/复核 | merge SHA（API 读回） |
|---|---|---|---|---|---|
| **#273 `fix/afi-recovery-runtime-assets`** | 恢复 worker 运行时资产（§8 上表首行） | DEPLOYMENT/CODE | 旧 head `0dbb3f25f…` | 已合入，把 dev tip 前移到其 squash | `c16f00515cb4b7437bd89ebad3d7b3e33a14efca`（message `fix(ops): restore the recovery worker the systemd unit runs (AC01/AC12 runtime asset gap) (#273)`，merged 2026-11-05T20:41:15Z） |
| **#289 `feature/afi-run-coordinator`** | 协调器/claim 模型重实现 + **alembic 单头常量重钉** | CODE/OFFLINE | `aeaa071c21ca3f5e7e4dac28b746eb4865217ff1`（较 §8 上表 `bfcacd7e8…` 为再钉后的新 head） | 重钉 **11** 个单头测试常量为 revision `20261106_akshare_run_coordinator_claims`（11 个测试文件各 1 行 + 迁移文件 2 行，本文按 #289 diff 读回）。**注：11 个测试硬编码迁移头，是仓库用来侦测误加第二头的既有约定。** | |
| **#297 `refactor/afi-settings-module-split`** | `Settings` 拆成 11 个分节 mixin | CODE/OFFLINE | `20b33e17b062cd82509bdb75f4ea1186aa0e8155` | 字段面未变的证明见 #297 证据评论（issue comment id `6669416050`），本文不重述其方法 | |
| **#299 `fix/ci-diff-cover-base-rev`** | `Check diff coverage` 改用 base 提交（§C 仪器修正） | CI/仪器 | `ac52ff42c6f074cabebdb6b176efc5b4d7b8c71d` | 断言 `HEAD^1==head.sha` 后取 `BASE_REV=git rev-parse HEAD^2`；`--fail-under=60` 不变 | |

**仅本地、未推送的两条流（勿当作已落库；待 #299 先落、队列排空后按 §4/§8 顺序并入）：**

- **本地流 #37 — AC06 发布一致性测试**：`.wt-afi-ac06` 提交 `4a671067de63069c91e2b9e1b369bb653edeba2e`
  （`test_publication_resubmission.py` 6 例 + `test_publication_reader_isolation.py` 3 例，本地 `9 passed`）。
  平面 CODE/OFFLINE；**未推送**、**不入本批**。
- **本地流 #4 — `mark_failed` 相关增量**：属主工作树内的本地改动，**未推送**、无对应 GitHub PR，
  待队列排空后另议。此两条仅为占位记录，SHA/PR 号在推送前不存在，不得臆造。

**状态更正（相对 §8 与属主工作稿）：** ① §8 记 #287 的 diff-cover 失败 job 为 `127337387339`（旧 head `5e6b513c7`），
本文在当前 head `d7b80f6f…` 读回的是 py3.12 腿 job `127491841431`，另 #291 双腿 `127499745868`/`127499746065`；
属主另引的 `127500114307` 本文未能在该步骤对应上，弃用。② §8 表内 #289 的 head `bfcacd7e8…` 已被重钉后的
`aeaa071c21…` 取代；本文按 §6 惯例保留原行不删，仅在此登记新 head。③ OpenData 侧 §8 第 4 条口径下的
#199（原「开着且红」）现**已合入**（`cloudQuant/opendata` merge commit `28607e186c9c31ed34389acab27a7397cb3173a6`，
门禁转绿），#196/#197/#198 仍红在快速失败的 `quality gate` 成员 2 `zero-dep-check`。

## 9. 属主待办队列

| 待办 | 需要的资源 | 现状证据 |
|---|---|---|
| AC17：用能建库的账号（或自有 MySQL）复现 claim/fence 库身份 | `CREATE DATABASE` 权限账号或属主自有 MySQL；当前应用库账号无该权限，且对 `backtrader_web` 有 ALL PRIVILEGES（含 DROP），不可用于试验 | 幽灵迁移两条不在任何 ref（§5）；#289 的 ORM-drift 失败正是这一缺口的门禁形态 |
| AC-5\|07：在 CI 侧重跑 bandit/安全证据，把 `scan-stale, triage-stale` 变成本轮读数 | CI 侧一次干净运行读数（不要用笔记本读数进账） | OpenData job 日志 `VERDICT AC-5|07: gap — security evidence valid=no（issues=2 scan-stale, triage-stale）` |
| 决定两条缺失 alembic revision 的处置：重建迁移 / 只记台账 / 抬 `stamp` | 属主裁定（Wave 27 §2 已给出身份与两个 revision id） | `20261019_akshare_scheduler_claims`、`20261019_akshare_enum_values` 只有 pyc 证据 |
| 决定 `run_coordinator.py` 与 `app/models/akshare_scheduler.py` 是「重实现」还是「宣布不可复现」 | 属主裁定；#289 已是按反汇编契约重写的候选 | 65/72 无磁盘副本，二者不在可恢复集合（§5） |
| 是否现在真正应用 `dev` ruleset（清单里 `activation.remote_state="not_applied"`、gate D3） | 属主裁定；`GET /repos/.../rulesets` 实测只有 `Release v0.1.0: immutable tag` 一条在活 | 无服务端门禁意味着「红 PR 也能被合」，全靠作者侧就绪门（`/tmp/afi204_merge_sweep.py` 的四条件） |
| ETF 名录刷新走 Sina、**在调度器共享源门之外**：裁定它是否计入 AC13 跨进程源额度与 AC09 授予 | 属主裁定 + 一次 REAL_SOURCE 观测 | `scripts/ops/run_full_history_recovery_worker.py:622`（以及 `:1958`）原文自陈 |
| 983 个未处置采集脚本（AC11 §6） | 逐文件 sha256 的人工具名评审；74 条 proposed 尚未升格为 assigned | `.wt-afi-disp` 台账 1,057 行实测：`decision_state` = proposed 74 / out_of_batch 983，`review_decision` 全空，即 **74 proposed / 0 assigned / 983 untouched** |
| 系统性「平台注入参数」缺陷（≥6 个脚本：`_call_timeout` 注到 `stock_zh_index_daily`、`bond_info_cm`、`fund_portfolio_hold_em`、`hk_fund_dividend_em`、`index_zh_a_hist_min_em`）以及两处静态解算判反（`fund_portfolio_hold_em:symbol`、`index_global_hist_em:max_indices`） | #280 落地后的一次修复批次 | 审计↔运行时对账：11 次执行 / 8 个 (script,key) 对，静态只预测到 1 个（389 的 `source`）；**未核实**：本文只活体确认了 389 一条，未逐条复现其余 7 对 |
| 服务资产守卫的 9 条发现（含 `etf-nav-backfill@0..3` 缺 `run_etf_nav_shard.sh`、`policy-expiry-watchdog` 缺 `policy_expiry_watchdog.py`、`stock-amount-daily` 缺 `backfill_stock_amount_sina.py`） | 逐单元属主裁定：补文件 / 停 unit | #285 的扫描读数（**未核实**，本文未复跑该脚本；三个缺失目标对应的 user timer 与单元名当场可见） |

## 10. 平面声明

本文所有读数落在 **本机 DEPLOYMENT 观测** 与 **CODE/OFFLINE** 两面上：直接 SQL、
journald/systemd user scope、`.pyc` 与文件系统的本机盘点、GitHub API 的 head/check-run 回读，
以及用 #282 修正后代码对同一活库的离线复算。**没有任何一条构成 REAL_SOURCE 或
NATURAL_CYCLE 证据。** 具体地：§2 证明进程活着并按 cron 写执行行，不证明覆盖率、
也不证明字段级源一致；§3 修的是仪器，不是平台；§4 的绿是门禁机制，不是验收；
§5 的 claim 平面在 00:45 UTC 之后未写一行，AC13 仍是 NOT_RUN；
§7 的 monthly 与 50 个幽灵后端任务都还没到可判定的观测点。
因此**本波不关闭 AC05、AC09、AC10、AC13、AC14、AC17、AC18 中的任何一项**，
AC14 的连续计数最早要到下一次自然周期读数（且工作树已快进到合并后的 dev）才有意义。
