# 运行态与普查读数（2026-11-06，Asia/Shanghai 主机）

本文件记录 wave 29 在本机取到的运行态读数。方法：只读 `SELECT`/`SHOW` + `journalctl --user` +
本仓已合并的普查工具；对 `ak_scheduled_tasks` 的一次写操作在第 6 节单独列出并给出 before-image。
所有数字都是本机实测，未从任何文档复制。

## 1. 采集器确实在跑，而且失败原因可归因

窗口 2026-11-05 14:03 → 2026-11-06 13:33 UTC（23.5 h）：

| 指标 | 实测 |
|---|---|
| `ak_task_executions` completed | 418（180 个任务） |
| `ak_task_executions` failed | 94（62 个任务） |
| 每任务最多 completed | 14 |
| completed ≥ 48 / ≥ 24 / ≥ 7 的任务数 | 0 / 0 / 1 |

失败按原因归族（窗口内）：

| 次数 | 错误 | 归因 |
|---|---|---|
| 26 | `No callable entrypoint found for script fund_monetary_income_history` | 注册指向树中不存在的文件 |
| 24 | `Script call timed out after 600 seconds`（`crypto_hourly_market`） | 唯一可小时触发的任务 |
| 18 | `No callable entrypoint found for script forex_hist_sina` | 同上，幽灵注册 |
| 5 | `FuturesDailyMarket.run() got an unexpected keyword argument '_ingest_mode'` | 参数信封与 entrypoint 签名不匹配 |
| 4 | `No callable entrypoint found for script fund_reviewed_unit_nav_history` | 幽灵注册 |
| 4 / 3 / 2 / 2 / 1 | `returned no data and target table ...`（`futures_to_spot_dce` / `spot_quotations_sge` / `etf_fund_hist_em` / `stock_zh_index_daily` / `video_tv`） | 空返回 + `run()` 关键字参数 |

结论：窗口内 94 次失败里 **57 次（61%）是入口点/参数绑定平面的缺陷**，不是源站不可达。
这正是 #270 在静态面暴露、#284 在参数面普查的那一族，本窗口给出的是它的运行态对应物。

## 2. AC11 的权威分母：#284 普查工具在本树的读数

命令：`src/backend/.venv/bin/python scripts/task_param_audit.py --env-file .env --tree . --out-dir ...`

| 分类 | 任务数 |
|---|---|
| binds（签名可静态证明能绑定） | 155 |
| accepts_var_kwargs（静态不可证） | 886 |
| script_file_absent（注册的脚本文件不在树里） | 50 |
| unexpected_param | 7 |
| missing_required_param / unresolvable | 0 / 0 |

范围：`ak_data_scripts` 1066 行（active 1051），其中 **9 行的 `module_path` 在树中不存在**；
`ak_data_interfaces` 0 行；1098 个 armed 任务全部能连到脚本行。

普查与分子都取自 13:47:56 UTC 停用之前的总体（armed=1098）；停用后在同一批脚本上复跑，`script_file_absent` 变为 0（那 50 个正是被停用的集合），AC11 分子变为 155/1048（严格）与 193/1048（放宽）。这四项分类是按**源码签名**判的，因此不随执行记录漂移；而下面第 3 节的运行态分子会随时间上升
（13:32 UTC 读到 143，14:18 UTC 复读到 155），所以引用时必须带时间戳，不能当常量。

工具自带的运行态交叉核对：账里带绑定错误的执行 19 条，涉及 10 个 (script, key) 对，
其中 3 对能被当前源码预测；其余 7 对属于"历史上有过、当前行已不再产生"，不是普查漏检。

## 3. AC11 三个可直接分派的队列

* **队列 A（停用前 50 任务 / 7 脚本，现为 0）**：`fund_monetary_income_history` 26、`forex_hist_sina` 16、
  `fund_reviewed_unit_nav_history` 4，`etf_realtime_quote_sina` / `cffex_option_daily_history` /
  `commodity_option_daily_history` / `etf_option_daily_history` 各 1。修复后 **100% 失败**。
* **队列 B（7 任务）**：`daily_market_data` 5（`_ingest_mode`、`calendar_review_by_market`、
  `overlap_days`、`trading_days_by_market` 被 `run(self, markets, lookback_days, max_windows, _call_timeout)` 拒收）、
  `etf_fund_hist_em` 1、`stock_zh_index_daily` 1。修复后 **100% 失败**。
* **队列 C**：窗口内按其 cron 应当至少触发一次、但修复后没有执行记录的任务。
  第一轮我用 UTC 评估 cron 得到 56；**这是错的**——调度器按 `AKSHARE_SCHEDULER_TIMEZONE`
  （本机 Asia/Shanghai）解释 cron，于是重算后为 38。两个数都记在这里，因为错的那次恰好
  暴露了第 5 节的钟问题。

## 4. AC14：小时目标是结构性受阻，不只是"时间还不够"

对 armed 任务逐条解析 cron（列表/区间/步长/星期），停用队列 A 之后的 1048 个任务：

| 形状（`evidence/2026-11-06-wave29/ac14_accrual.py` 的口径） | 任务数 |
|---|---|
| weekly（星期字段受限，`dom/month` 不限） | 941 |
| sub-daily（多小时；含星期受限者） | 83 |
| daily（星期 `*`、单小时、`dom/month` 均 `*`） | **2** |
| hourly（小时字段 `*`） | **1** |
| 受 day-of-month/month 限制（月度形状） | 21 |
| 正交维度：星期字段不是 `*` 的任务总数 | 1024 |

这张表是被一次自身错误纠正出来的，错误也一并留下：我第一版按"每天触发几次"分类时**没有看
`day-of-month` 字段**，于是把 21 个月度形状的任务算进"每天恰好一次"，得到 `daily-once 23`。
按带 dom/mo 分支的 `ac14_accrual.py` 重算，真正的 daily 只有 **2** 个。可引用的是后者。

再叠加窗口（23.5 h，按 Asia/Shanghai 求值）算应跑槽位：

| 频率形状 | 任务数 | 窗口内有应跑槽位 | 有执行记录 | 应跑但未跑 | 平均每任务应跑槽位 |
|---|---|---|---|---|---|
| sub-daily（多小时） | 85 | 85 | 85 | 0 | 3.9 |
| hourly（小时 `*`） | **1** | 1 | 1 | 0 | **24.0** |
| daily（星期 `*`、单小时） | 32 | 32 | 32 | 0 | 1.0 |
| weekly（星期受限） | 959 | 124 | 86 | 38 | 1.0 |
| 受 day-of-month/month 限制 | 21 | 0 | 0 | 0 | 0 |

（上表按停用前的 1098 计算，保留以便与 wave 28 对齐；停用队列 A 之后的形状分布即本节第一张表，两档之差恰好是被停用的 50 个：daily 32→2（-30）、weekly 959→941（-18）、sub-daily 85→83（-2），hourly 与月度形状不变，-30-18-2 = -50。）

* 全表只有 **1 个** armed 任务能每小时触发：`id=1049 Iteration203 crypto_hourly_market`，cron `3 * * * *`。
  它在窗口内 24 次全部以 600 s 超时结束，completed 0。
* 因此 AC14 的"48 次小时自然运行"证据在当前装填面上**只能由这一个任务产出**，而它一次都没成功过。
  把它写成"时间还没到"是不准确的：时间是必要条件，但不是本机的瓶颈。同时更正一句过头话：1049 **并非从未成功过**——它在 2026-10-19 至 10-27 间累计 completed 178 次，只是自 wave 27 认定的那次全量失败起点（2026-10-27 00:55）之后一次也没成过。
* 深度上限也受窗口限制：窗口 23.5 h < 目标 48，所以"≥48 completed 的任务数 = 0"是算术结果，
  不能当作对采集器的度量。
* **口径与 wave 28 不一致处，此处直说**：wave 28 §1.2 记 #282 修后仪器读出 `hourly 仍 103`，
  而本机按 cron 逐字段展开得到"小时字段为 `*`"的任务只有 1 个、多小时字段 84 个。
  两者不是同一指标——本机的数是把 cron 展开成触发集合后的形状计数，
  wave 28 的 103 是 #282 仪器自己的分档。本文不改写它的数，也不用自己的数覆盖它；
  需要的是在 AC14 判据里把"小时面"的定义写死，否则这一格永远可以各说各话。


## 5. 新缺陷：`ak_scheduled_tasks` 与 `ak_task_executions` 不同钟

代码：`app/services/akshare/scheduler.py:154` 用 `datetime.now()`（本机 Asia/Shanghai）写
`last_execution_at`，而 `AkshareExecutionService._utcnow_naive()`（`execution.py:70,84`）写同一列为 naive UTC；
调度器在 execute service 之后写，所以本地时间赢。`next_execution_at` 取 APScheduler 的
`job.next_run_time`，触发器运行在 `AKSHARE_SCHEDULER_TIMEZONE`，落进 naive 列即墙上时间。

数据（1048 armed 任务 × 各自最新 `created_at`，13:59 UTC）：

| 偏移 | 行数 |
|---|---|
| +8 h（墙上时间形状） | **192** |
| ±1 h（与执行钟一致） | 843 |
| 比自身最新执行更旧（列未被维护，另一问题） | 13 |
| 完全没有执行行 | 0 |

`next_execution_at` 需要 shift 的候选：1048（全部）。定义说清才谈得上复现：取【星期字段为 `*`、且小时与分钟均为单值】的 23 个任务，
`next_execution_at` 有 **23/23** 恰等于 cron 的墙上槽位，`last_execution_at` 只有 **2/23** 等于墙上槽位
（其余 21 个存的是 UTC 瞬时）。同一行两列与执行行的钟三向不一致。
上面原写作 53/53 与 2/53，用的是一个未固定的 daily 口径，按任何明确定义都复现不出 53 这个总体，故作废。

后果：任何跨列比较（调度器 reload、AC14 累加、freshness 读数）差 8 小时。wave 28 在 AC14
仪器里发现并修的是"比较侧"（#282），本次发现的是"写入侧"本身。修复在 PR #306；数据校正是
`src/backend/scripts/ops/normalize_scheduler_clock.py`，**必须在代码部署且采集器重启之后**执行，
否则仍在运行的调度器会把墙上时间写回去。

## 6. 属主裁定后已执行的生产写操作

裁定："停用幽灵任务"。对象 = 队列 A 的 50 个 armed 任务。

* before-image：`/tmp/it204/ac11-queue-a-before-20261106T134756Z.json`（50 行，全部 `is_active=1`）
* 语句：`UPDATE ak_scheduled_tasks SET is_active=0 ... WHERE id IN (<census ids>) AND is_active=1`
* 结果：翻转 50，翻转后仍 armed 0，armed 面 **1098 → 1048**，时间 13:47:56 UTC
* 明确不做的：不重建那 9 个文件（它们从未存在于任何 ref 与 opendata 树，重建即臆造），
  不改 `ak_data_scripts` 注册行，不改 `function_name`
* 三条代价，必须一起读：
  1. 停用**不会立刻生效**。`reload_active_tasks` 只遍历 active 任务，从不注销已转 inactive 的 job，
     `run_task_now` 也不回查 `is_active`（`scheduler.py:106/129/138`），所以运行中的采集器会继续触发它们，
     直到重启。PR #306 修的是这条路径。
  2. 这 50 个任务的失败是那些幽灵注册**唯一的可见信号**；停用后可见性下降，除非处置台账逐条记理由。
  3. 它们对应的目标表（`OPTION_ETF_DAILY_HISTORY`、`OPTION_COMMODITY_DAILY_HISTORY`、
     `OPTION_CFFEX_DAILY_HISTORY`、`FOREX_SINA_DAILY_HISTORY`、`FUND_MONETARY_INCOME_HISTORY`、
     `FUND_REVIEWED_UNIT_NAV_HISTORY`、`ETF_REALTIME_QUOTE_EM`）**有存量数据但没有生产者**：
     它们在采集数据 schema `akshare_data` 里存在且非空（最大 22,093,150 行），只是写它们的代码不在任何 ref 里
     （见 §13）。因此 AC05/AC10 对这些数据集既不能写已覆盖，也不能像我最初那样写表不存在。

## 7. 频率词表不能作为分派维度

把 1098 个 armed 任务的 cron 形状与两份"频率"来源对齐：

| CSV `legacy_frequency` \ cron 实际形状 | daily | sub-daily | hourly | weekly | dom/mo 限制 |
|---|---|---|---|---|---|
| daily（694） | 2 | 2 | 0 | **690** | 0 |
| weekly（298） | 30 | 2 | 0 | 266 | 0 |
| hourly（85） | 0 | 81 | 1 | 3 | 0 |
| monthly（21） | 0 | 0 | 0 | 0 | 21 |

CSV 自称 daily 的 694 个任务里，690 个实际是星期受限的周任务；
而 `ak_data_scripts.frequency` 列对全部 1098 个 armed 任务的值都是 `manual`，不携带信息。
因此 wave 26 记在 `INVENTORY_AUDIT_20261105.md` 的"分频 daily 680 / weekly 266 / hourly 85 /
monthly 21 / unspecified 5"只能理解为 **CSV 声明值**，不能当作调度事实；
AC11 的分派必须按 cron 表达式取频，不能按 `legacy_frequency`。

## 8. 幽灵注册的来源现在可以判定

9 行无文件的 `ak_data_scripts` 注册与迁移台账 CSV 里的 9 行 `source_path` 一一对应，且：

* 在 AFI 全仓 tracked `.py` 的 sha256 集合中（3169 个文件、去重后 3099 个不同摘要——先前我把这两个数混写成"3099 个文件"，此处更正），这 9 个 `source_sha256` 前缀 **0 命中**（本机实测）；
* `git log --all --diff-filter=A` / `--diff-filter=D` 对这 9 个路径均 0 命中（从未入库、也从未删除）；
* 按文件名在 `/home/yun/Documents/opendata` 树 0 命中（wave 26 已测，本次沿用）；
* CSV 仍为它们声明了 `static_role`（7 行 `entrypoint_run`、2 行 `helper_review_only`）
  与 `migration_route`（`PENDING_PROVIDER_MAPPING` / `HELPER_REVIEW`）。

判定：`static_role` 只能由读源码得出，而这 9 个文件在版本控制里从未存在——所以 CSV 是在一棵
**带有未提交文件的工作树**上生成的。由此得出两条对本迭代有约束力的结论：

1. 台账 CSV 与 DB 注册**同源**，二者互为"印证"是假的，AC01 的反查不能把它们当两个独立证据；
2. CSV 中任何 `static_role`/`sha256` 陈述的可靠性上界，就是"生成它的那棵工作树"的可复现性，
   而那棵树现在无法复现。故 `INVENTORY.md:11` 的 1,066 与 CSV 的整体口径自此只可引用为
   "某次未提交工作树的读数"，不可引用为"脚本已有迁移映射"。

## 9. 采集脚本类型平面（属主新增范围）

* 度量命令：`src/backend` 下 `python ../../scripts/ci/mypy_ratchet.py --scope collection --advisory`
  （mypy 1.20.2，与 `config/requirements-dev.lock` 一致；本机 `.venv` 的 1.14.1 在 `app/config.py:71` INTERNAL ERROR）。
* 我在 `dev` `0a4c5ab31` 实测：**159 errors / checked 1108 files**。
* PR #305（head `bce164cb4`，机械族 + 2 个真缺陷）在同一工具下实测 **125 errors / checked 1108**，
  平面未缩小；我在它的 worktree 里独立复跑确认，不是引用 PR 正文。
* 剩余 125 条的族分布（#305 后）：import-untyped 40、call-overload 22、return-value 15、operator 13、
  arg-type 10、union-attr 9、str-bytes-safe 7、assignment 6、override 3 等。
* 属主裁定：`operator`/`union-attr`/`str-bytes-safe` 这一族**按站点依据 DDL 收窄**（不做 DB 层访问器，
  也不带着它们冻结基线）；实现见 PR（本文件写作时仍在跑）。
* `import-untyped` 40 是 `types-requests` 的锁文件决定，单列，不在清债波次里顺手改。
* 平面此刻仍是 advisory，且必须继续 advisory：基线要由 **CI 自己的读数**经评审式
  `--update` 冻结（`scripts/ci/baseline_update_guard.py` 禁止同一 PR 既改代码又抬基线），
  因此"代码修复 PR"与"基线冻结 PR"必须分开。本文件的 159/125 都是笔记本读数，只作引用。

## 10. AC01 另一半：环境身份，以及"部署了但没重启"是事实

14:05–14:07 UTC 复测（只读：`systemctl --user show`、`journalctl --user`、`git`、`pip list`、`SELECT`）：

| 口径 | 实测 |
|---|---|
| 工作树 HEAD | `0a4c5ab3`（提交于 13:16 UTC） |
| `ai-for-investor.service` 主进程 | PID 1746649，启动于 2026-11-05 22:44:45 CST，NRestarts=0，Result=success |
| 启动时的 HEAD | `9f573d34d3d0` |
| 启动之后落到 dev 的提交数 | 7 |

即**运行中的进程跑的是比工作树更旧的代码**（不含 #304、#305、#273 恢复出的 worker 之后的改动）。
这不是推测：启动时刻早于那 7 个提交，而 `ExecMainStartTimestamp` 未被重启更新。
含义有两条，都必须写清：本文件所有"运行态"读数描述的是**旧代码的行为**；
而任何"修复已在生产生效"的陈述，在重启之前都不成立（含 PR #306 的调度器钟修复）。

ExecStart 所用 venv 的关键包版本：Python 3.13.5、fastapi 0.121.2、APScheduler 3.11.1、
SQLAlchemy 2.0.39、PyMySQL 1.1.1、pydantic 2.12.4、akshare 1.18.64、uvicorn 0.35.0。
DSN：`backtrader_web@127.0.0.1/ai_for_investor`（只打印 user@host/db）。
钟：`ak_task_executions.created_at` 为 UTC（MAX 14:03 vs `UTC_TIMESTAMP()` 14:05），
`next_execution_at` 为 Shanghai 墙上时间——与第 5 节互相印证。

## 11. 运行资产平面：8/10 个 sidecar 单元因"任何 git ref 里都不存在的宿主文件"确定性失败

| 单元 | 状态 | 最近启动 (CST) | 直接原因 |
|---|---|---|---|
| ai-for-investor | active/running，NRestarts=0 | 11-05 22:44 | 今日无 warning 级日志 |
| ai-for-investor-frontend | active/running | 11-05 08:47 | 正常 |
| full-history-recovery (+timer) | **failed**，timer 每分钟触发（`OnCalendar=*:*:00`） | 11-06 22:06 | exit 2 `attention_required`：缺 `scripts/crypto_full_history_recovery.py`、`scripts/bond_convertible_history_controller.py` |
| stock-amount-daily (+timer) | failed | 11-06 04:03 | `scripts/ops/backfill_stock_amount_sina.py` 缺失（树与 git 都无） |
| stock-tail-daily (+timer) | failed | 11-06 21:10 | `run_stock_tail_slices.sh` 缺失 |
| dce-option-daily (+timer) | failed | 11-06 20:05 | `run_dce_option_recovery.sh` 缺失 |
| dce-browser-capture (+timer) | failed | 11-06 19:37 | `run_dce_browser_capture.sh` 缺失 |
| policy-expiry-watchdog (+timer，小时) | failed 21:00、22:00 | — | `policy_expiry_watchdog.py` 缺失，`git log --all` 0 命中（从未提交） |
| option-history | inactive **disabled** | — | `run_option_history_loop.sh` 缺失 |
| etf-nav-backfill@0-3 | **activating auto-restart**，RestartSec=30 | 每 ~30 s | `run_etf_nav_shard.sh` 缺失——此刻正在崩溃循环 |

另有一个未列入 AC01 单元清单的 `ai-for-investor-dce-option-recovery.service` 存在于磁盘。

我随后按每个 unit 的 `ExecStart` 逐条取目标路径自行复核（不用代理给的清单）：
**9 个被 live unit 指向的 ops 脚本全部不在工作树，且 9 个全部不在 `git ls-files` 里**（不是"其中 8 个"）：

```
src/backend/scripts/ops/run_dce_browser_capture.sh      ABSENT
src/backend/scripts/ops/run_dce_option_recovery.sh      ABSENT   （dce-option-daily 与 dce-option-recovery 共用）
src/backend/scripts/ops/run_etf_nav_shard.sh            ABSENT   （etf-nav-backfill@%i 的实参脚本）
src/backend/scripts/ops/run_option_history_loop.sh      ABSENT
src/backend/scripts/ops/policy_expiry_watchdog.py       ABSENT
src/backend/scripts/ops/backfill_stock_amount_sina.py   ABSENT
src/backend/scripts/ops/run_stock_tail_slices.sh        ABSENT
src/backend/scripts/crypto_full_history_recovery.py     ABSENT   （full-history-recovery 的资产之一）
src/backend/scripts/bond_convertible_history_controller.py ABSENT
```

单元状态复核：`ai-for-investor`、`ai-for-investor-frontend` = active/running；
`full-history-recovery`、`stock-amount-daily`、`stock-tail-daily`、`dce-option-daily`、
`dce-browser-capture`、`policy-expiry-watchdog` = failed；
`option-history` = inactive/dead 且 **disabled**；`dce-option-recovery` = inactive/dead；
`etf-nav-backfill@0-3` = activating/auto-restart（exit 203，RestartSec=30，此刻仍在循环）。
exit 2 与 exit 203 的差别本身可读：203 是 systemd 无法 exec（脚本文件不存在），
2 是 python 起来后失败或 `python file.py` 打不开文件（同样报 No such file，但由解释器返回 2）。

这条与第 8 节的幽灵注册是**同一个 provenance 模式**：宿主上被 systemd 依赖的文件，
不在任何 git ref 里。因此：

1. 准确量化是 **12 个被 live unit 指向的宿主文件不在树里**：7 个在 `src/backend/scripts/ops/`，
   另 5 个在 `src/backend/scripts/`（journal 点名 crypto、bond、stock_full_history、cffex_option、
   backfill_etf_nav 这批控制器/回填脚本）；受影响的 sidecar 单元是 **9 个**而不是 8 个
   （`dce-option-recovery` 也指向缺失的 `run_dce_option_recovery.sh`）。上一段列的 9 个 ops 路径
   **全部**不在 `git ls-files` 里，不是"其中 8 个"。
   因此 AC01 的清单若只按 `git ls-files` 取分母（1108 个 `.py`），对运行资产平面是盲的；
   真实分母必须包含 systemd `ExecStart`/`EnvironmentFile` 指向的路径。
2. `etf-nav-backfill@0-3` 的崩溃循环是当前仍在发生的资源浪费与日志噪声，不是历史读数。
3. `full-history-recovery` 在 exit 2 的同时记录 `cursor_advanced: true`——**失败时游标仍前移**，
   这条单独就是可观测性缺陷：失败会消耗游标，下次运行不再重试同一段。

## 12. 今天的消费者：写入面与零写入面

UTC 日 2026-11-06（截至 14:07）：执行 272 completed / 65 failed / 1 running；
`ak_task_executions` 总行 32313（本波早些时候为 32291）。

* 有非零行增量的目标表：**109 个**，今日合计 **+128,336 行**（`ak_data_scripts.target_table` 连执行行的
  `SUM(rows_after - rows_before) > 0`）。
* `ak_data_tables` 元数据中今日被更新的表：155 / 1061。
* **892 / 1044** 个不同 armed 任务的目标表今日**没有任何成功写入**（分母 1044 而非 1048：4 个 armed 任务的脚本行没有可用的 `target_table` 值，这一小差也要记，别让读者以为是同一集合）。
  其中多数是周/月形状（第 3 节队列 C 的 56→38 是它的子集），因此这个数字**不能**读成"892 个数据集缺数"，
  只能读成"今天没轮到"。要把它变成 AC05/AC10 的证据，需要按 §4 的应跑槽位逐任务判定，
  即 #282 那台仪器的职责范围。

## 13. 队列 A 停用后的可观测性后果，以及那 2,400 万行数据的写入者（已绑定）

这一节在本波里被推翻过两次，两次都留下痕迹，因为误判的过程本身就是信息。

第一次误判：我只查了元数据库 `ai_for_investor`，看到 9 个表名 `information_schema.tables` 计数为 0，
就写下"表对象不存在"。错。采集数据写在 `AKSHARE_DATA_DATABASE_URL` 指向的 **`akshare_data`**，
在正确的库里 7 张表都存在且有真实存量：

| 表 | 行数 | 业务日期列 | MAX 业务日（=新鲜度） | 去重业务日 | 对 `TRADING_DAYS` 的缺口 | 物理最后写入 |
|---|---|---|---|---|---|---|
| `OPTION_COMMODITY_DAILY_HISTORY` | 22,093,150 | `TRADE_DATE` | 2026-10-26 | 2322 | 0 / 2322 | 2026-10-26 20:07 (+08) |
| `OPTION_CFFEX_DAILY_HISTORY` | 858,096 | `TRADE_DATE` | 2026-10-26 | 1656 | 0 / 1656 | 2026-10-26 23:39 |
| `OPTION_ETF_DAILY_HISTORY` | 854,174 | `TRADE_DATE` | 2026-10-23 | 2847 | 0 / 2842 | 2026-10-23 19:45 |
| `FUND_MONETARY_INCOME_HISTORY` | 91,419 | `VALUE_DATE` | 2026-10-26 | 4889 | 12 / 3353 | 2026-10-27 08:55 |
| `FOREX_SINA_DAILY_HISTORY` | 37,327 | `TRADE_DATE` | 2026-10-26 | 4033 | 1 / 2907 | 2026-10-26 22:45 |
| `ETF_REALTIME_QUOTE_EM` | 13,156 | `QUOTE_DATE`+`OBSERVED_AT` | 2026-10-26 | **8** | 305/312（无意义，见下） | 2026-10-26 15:50 |
| `FUND_REVIEWED_UNIT_NAV_HISTORY` | 4,491 | `VALUE_DATE` | 2026-10-26 | 3299 | 5 / 3295 | 2026-10-27 08:45→08:51（全表同一批） |

`MAX(业务日)` 是数据新鲜度，`MAX(OBSERVED_AT/UPDATED_AT)` 是物理写入时刻，两者不同：
新鲜度停在 2026-10-26，物理写入停在 2026-10-27——后者正是 wave 27 认定的全量失败起点。

第二次误判：纠正之后我写成"存量有、生产者无法绑定"。这句现在也被证据推翻了——**7 张表的写入者
全部 BOUND**，绑定方式是两条独立链路的交叉：

1. `ak_task_executions` 按注册 slug 记的执行历史：`cffex_option_daily_history` 728 次（713 completed）、
   `fund_monetary_income_history` 471（211）、`forex_hist_sina` 250（106）、
   `fund_reviewed_unit_nav_history` 73（36）、`etf_realtime_quote_sina` 16（7）、
   `commodity_option_daily_history` 14（4）、`etf_option_daily_history` 11（2）。
   每个 slug 的**最后一次 completed 与对应表的物理最后写入秒级吻合**（执行行是 UTC，
   `OBSERVED_AT` 是 +08，换算后一致）。且这些 slug 在 2026-10-19 之前没有任何执行行，
   而台账本身能追到 2026-06-21——即生产从 10-19~10-22 起来，10-26/27 停。
2. 磁盘上残留的字节码：`app/data_fetch/scripts/{options/daily,common/daily,funds/weekly,funds/hourly}/__pycache__/<slug>.cpython-313.pyc`
   的 `co_filename` 逐字等于注册的 `module_path`，常量池里恰好只有其目标表名。
   七个 sha256：cffex `db8ecc5d…`、commodity `1cad7c92…`、etf-option `e2b21021…`、forex `a8e84b4c…`、
   monetary `f6270abb…`、reviewed `1fc90a70…`、realtime `288fdfde…`；内嵌源文件 mtime 2026-10-20 02:23
   至 2026-10-22 17:38、5,664–30,028 字节。副本已存 `/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/pyc/`。

因此当前诚实的表述是：**数据有、新鲜度已知、生产者已由执行台账与字节码双向绑定，
但生产者的源代码文本不在任何 git ref 里**（OD 侧只有目录记录，无所有权；
`git log --all -S<表名>` 找不到写入者；HEAD 上只剩读方与
`run_full_history_recovery_worker.py` 里的 `OPTION_TABLE_NAME` 常量；
`cffex_option_history_controller.py` 只存在于 `feat/afi-recovery-controllers`，是 11-05 的重建，
不是 10 月的生产者）。

三条仍然不可知，写明以免被误当已闭合：

1. **`.py` 源文本本身**：只有字节码。反编译未验证；且 `log_bin=ON`、`binlog_format=ROW`，
   但本用户无 `REPLICATION CLIENT`（`SHOW BINARY LOGS` 报 1227），无法用 binlog 给删除定日。
2. **谁删的、为什么删**：`var/reports`、`var/backups`（只有
   `ai_for_investor_pre_upgrade_20261105T2148.sql.gz`）与 `afi204-evidence` 里都没有删除动作的记录。
3. **逐标的的内部缺口**：上表的缺口是表级并集。按 `SOURCE_SYMBOL`/`FUND_CODE` 各自的日历
   （期权到期日、基金估值日、外汇周末）需要源原生日历，本机没有。

特例 `ETF_REALTIME_QUOTE_EM`：`information_schema.update_time` 与 `MAX(UPDATE_TIME)` 都是
2025-07-11，是陈旧 DDL 假象；真实信号是 `OBSERVED_AT` 2026-10-26 15:50 且每个快照日约 1,710 行
——它是只保留 8 个业务日的滚动快照表，那 305/312 的缺口**不是** AC05 的欠覆盖。

对验收的作用方向：AC05/AC10 对这 7 个数据集**第一次可以有具体内容**（新鲜度到 2026-10-26/23，
缺口表级为 0~12），但"历史是否从标的上市日起连续"仍未证明，且生产者源码缺失意味着
这套数据现在**无法被重新生产**——这是 AC12/AC13 的问题，不是覆盖率问题。
停用队列 A 之后连失败信号也没有了，这句仍然成立。

`release_policy` / `yield_release_policy` 在任何 schema 都不存在，且这两个注册从未有任务，此结论不变。
## 14. 停用是否已生效：尚未可判，且预期为"否"

实测：13:47:56 UTC 之后，那 50 个 task_id 的执行数为 **0**（`tasks_still_firing=0`）。
但这**不能**读成"已停"：它们的 cron 落在 CST 06/08/09/15/19 时，
观测窗（CST 21:48–22:05）内一个槽位都没到。

代码侧判断（`scheduler.py:95/138/129`）：`_run_task_job → run_task_now` 不回查 `is_active`，
`reload_active_tasks` 只遍历 active 集合、从不注销已转为 inactive 的 job，
而运行中的进程是 11-05 以全量 armed 启动的（第 10 节），其内存 jobstore 仍含这 50 个 job；
它们的 `next_execution_at` 也仍是 06:30–19:45 CST 的旧值、未被置空——说明没有 reload 发生过。

首个可判观测点：11-07 约 00:35 UTC（CST 08 时那批）。
预期"仍触发"，与 PR #306 的前提一致。若届时确有执行，则第 6 节的停用动作在运维上是**未完成的**，
必须配合重启或 #306 合并部署才算闭环。
## 9. 处置台账跑通了全量，但它暴露出迁移清单的 hash 基准从来不是干净树

用 #286 的仪器（`scripts/ops/assign_script_dispositions.py`，只读输入、AST 取证、
proposed 与 assigned 严格分权）对**全部 1057 个脚本**跑一批：

```
ledger rows: 1057 (one per tracked script)
assigned: 0
proposed (unreviewed): 1057
proposed bucket detail: {EXTEND_PROVIDER: 960, HELPER_ONLY: 8, UNDECIDED_INSUFFICIENT_EVIDENCE: 89}
inventory sha agreement: {no: 891, yes: 166}
inventory rows without a file on disk: 9
reconciliation problems: none
```

三条结论，一条比一条硬：

1. **`assigned` 不可能由代理抬高。** 仪器把 `assigned` 定义为"具名人工在 `--review-file` 里
   对同一文件 hash 批准"，1057 条 proposed 全部未审。§6 周报要的分子因此只能由属主签字产生，
   这不是进度问题而是权限设计。
2. **迁移清单对 891/1057 个脚本的 `source_sha256` 已经不与树一致**，其中 **868 条（97.4%）**
   正是 #270（854 文件）与 #275（35 文件）改过的；反过来，**任何被这两批改动碰过的文件都没有一条
   仍然一致**（交集补集检验：agreeing ∪ touched = 0）。也就是说 CSV 的 hash 基准整体早于本迭代
   对采集脚本的大规模真实修复，它不能继续充当 AC01"重新冻结 hash"的锚点。
3. **剩下 23 条更糟：不一致，但没有任何提交能解释。** 它们的 `git log -1` 都停在
   `1dbd991d7` / `d001052bc` / `73324f83b` / `b1ddf66fa` 这类本迭代之前的提交上，
   也就是说自那次提交后文件没动过，而 CSV 记的 hash 仍对不上——与第 8 节那 9 行幽灵
   是同一个成因：**CSV 是在一棵带未提交改动的工作树上生成的**。
   名单（23）：`_amac_limited, _endata_yien, currency_fallback, _jin10_macro, _sina_macro,
   akshare_catalog_endpoint, macro_china_swap_rate, print, dict_result, akshare_catalog_batch,
   scalar_result, get_dce_rank_table, crypto_daily_market, crypto_hourly_market, _fund_codes,
   option_hist_dce, _dict_result, futures_dce_position_rank, futures_warehouse_receipt_dce,
   stock_zh_index_daily, stock_zh_index_daily_em, _gdfx_limited, stock_zh_a_tick_163`
   —— 其中 `crypto_hourly_market` 与 `stock_zh_index_daily` 同时是本窗口失败归因里的活跃脚本，
   不是无关名字。

对验收的作用方向因此很明确：AC01 的第一句"重新冻结两个仓库和未提交差异 hash"不是形式要求，
它是 AC11 的**前置**——在 CSV 从干净树重生成之前，任何 `assigned` 签字都是对一份不绑定当前代码的
证据背书。复现命令：

```
src/backend/.venv/bin/python <instrument> --repo-root . --out-dir <dir> --limit 0
```

## 10. 两台 AC11 仪器对同一分母给出不同分档，这个分歧必须先对齐

本波实际跑了一份，另一份是同日属主证据 `/home/yun/afi204-evidence/2026-11-06-ac11-dispositions/`
（`build_ac11_ledgers.py` + `disposition_ledger.csv` + `task_ledger.csv`，分母 1066 脚本行 / 1103 任务行）：

| 语义 | #286 仪器（本波跑） | 属主证据（同日另一路径） |
|---|---|---|
| 有真实 OpenData 落点、已确认 | （该工具不提这档，只提 §5 路线） | `mapped_confirmed` **11** |
| 需扩展 provider | `EXTEND_PROVIDER` 960 | `no_target_found` **964**（上游调用已解析 702 / 部分 262，但对 10 个 akshare callable、319 个模型注册表、数据集编码三处检索均无对应） |
| 证据不足，不塞进处置词表 | `UNDECIDED_INSUFFICIENT_EVIDENCE` 89 | `undetermined` **76**（53 无可达 HTTP 站点 + 23 无静态可别名为 callable） |
| 辅助文件 | `HELPER_ONLY` 8 | `helper_not_a_task` **10** |
| 已在源码侧停用 | （未提） | `already_retired_in_source` **5** |
| 同名上游多脚本 | （未提） | `duplicate_fan_out` 0 降级（13 组 / 27 脚本，因组内无人有落点，降级会掩盖缺口） |

两份不是"一个更严"的关系，而是**问的问题不同**：#286 按 §5 的七个处置词表分类"接下来怎么迁"，
属主证据按"OpenData 侧到底有没有对应物"分类。真正被两边同时压住的是同一批 960~964 个脚本，
而两边给出的可行动作差别极大——一个是"去扩 provider"，一个是"检索三处后确认无对应物"。

因此 AC11 的诚实当前状态是（且这是本波对该格最重要的补充）：

* 分母：脚本 1057（tracked 非 `__init__`）/ 1066（注册行）；任务 1103，armed 现 1048。
* 分子：`assigned` **0**，且按 #286 的权限设计只能由具名属主逐文件 hash 签字产生。
* 目标面能力：`opendata/pipeline/schedules.yaml` 只有 **7 个 job 模板**，
  OD akshare provider models 暴露 **10 个 callable**；`od_job_definitions` 表在本会话可及的
  任何库里都不存在（`SHOW DATABASES` → `ai_for_investor`、`akshare_data`、`backtrader_web`）。
* 因此"964 个脚本待迁"与"OpenData 侧目前只有 10 个可落点"之间的差，不是盘点不足，
  而是**落点面本身还没建**。把 964 读成"等分类"会掩盖这一点。

需要属主定的两件事随之明确：`EXTEND_PROVIDER` 与 `no_target_found` 之间选哪个口径进 §6 周报；
以及 11 个已确认落点是否构成第一批可签字的 `assigned`。本波不做选择。

## 14. AC11 分子不再是手算：仪器已入库（PR #307），且读数随运行单调上升

本波前面给出的 143/155 都是我手跑脚本的临时读数。现在它有了受测仪器
`src/backend/scripts/ops/ac11_runtime_evidence.py`（PR #307，15 项无 DB 测试 + 邻居约定共 27 passed），
输入是 #284 普查 JSON，只读单条聚合 SELECT，**不读** `last_execution_at`/`next_execution_at`
（那两列钟的缺陷在 PR #306 里，未部署前不可信），并显式声明：
runtime-evidenced 是处置的**输入**，不是处置本身；`assigned` 不在这里计算。

同一天三个读数，全部由同一族逻辑产出，差别只在总体与时刻：

| as-of (UTC) | 总体 | completed 且行增 | completed 无行增 | 只失败 | 窗口内未跑 |
|---|---|---|---|---|---|
| 13:32 | 1098（停用前） | 143 | 36 | 5 | 703 |
| 14:18 | 1098（停用前） | 155 | 38 | 12 | 842（放宽口径 193） |
| **14:50:07** | **1048（停用后）** | **161** | 39 | 13 | 835 |

14:50 那次按族展开的矩阵（`accepts_var_kwargs` 是主缺口）：

| 族 | 且写行 | 完成无增量 | 只失败 | 未跑 |
|---|---|---|---|---|
| accepts_var_kwargs | 160 | 38 | 5 | 683 |
| binds | 1 | 1 | 1 | 152 |
| unexpected_param | 0 | 0 | **7** | 0 |

两点必须写下来，否则这张表会被误读：

1. `binds` 155 个里只有 2 个有运行证据——不是仪器坏，而是绝大多数 binds 任务的 cron 槽位
   还没到（窗口不足 24 h，多数是星期受限）。
2. `unexpected_param` 恒为 100% failed_only，与 §3 队列 B 完全一致，
   是这张表里唯一"证据已足够下结论"的一行。
