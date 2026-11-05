# 运行时修复与资产清点实测（2026-11-05）

本文件只记录**本机实测读数**，用于 AC01「运行入口有带环境身份/采集时间的清单」和 AC12「先验包/环境/库身份」。
它不关闭任何验收行：下面每个绿都标注它属于哪个平面。

## 0 执行环境身份

| 项 | 值 |
|---|---|
| 采集时间 | 2026-11-05 21:42–22:12（Asia/Shanghai）＝ 13:42–14:12 UTC |
| AFI 基线 | `dev = dfa009cffca302c046ab4456ab4e469efecab80e`（同步前本地落后 4 个提交） |
| OpenData 基线 | `dev = 051824bd386ccfebb6e6257cb4eb4e62d2450be5`（同步前工作树 detached 在 `6db4382f`，落后 11） |
| 同步后两树状态 | `git status --porcelain` 行数均为 0 |
| 解释器 | 运行时 `src/backend/.venv` = Python 3.13.5；CI 为 3.11/3.12，两者不可互换引用 |
| 元数据库 | MySQL 8.0.46 @ `127.0.0.1:3306`，库 `ai_for_investor`（168 表 / 2,013.2 MB） |
| 数仓 | 同实例 `akshare_data`（1,042 表 / 45,492.4 MB） |
| `created_at` 时区 | **UTC**：同一连接上 `NOW()=22:04:32`、`UTC_TIMESTAMP()=14:04:32`、`MAX(created_at)=14:03` —— 台账时间按 UTC 读，按 CST 读会把一切晚 8 小时 |

## 1 事故事实：运行时不是「失败」，是不存在

- API 服务处于崩溃循环：21:43 读到 `NRestarts=1457`，当天 `logs/backend.log` 里 `Application startup failed` 出现 **20** 次。
- 直接原因（日志原文）：`Database migration revision mismatch: expected heads ['20261101_stock_analysis_report_evidence_vector'], found ['20261019_akshare_enum_values']`。
- 采集自 **2026-10-27 01:01 UTC** 起全量失败，到 **2026-11-05 00:45 UTC** 共 **4,279 条 `failed` / 0 条 `completed`**，覆盖 1,081 个任务；错误文本只有一句 `AKShare script worker exited with code 1 without a result`，`CHAR_LENGTH(error_trace)=0`、`CHAR_LENGTH(result)=0`。
- 该 raise 所在的代码路径（`app/services/akshare/script.py` 的 `_execute_callable_in_worker`）在 dev 上**已不存在**（`grep` 在 `dev`、`origin/master`、`docs/iteration-204-wave26` 三个 ref 都找不到这句字面量）。也就是说：产生这些失败的进程，跑的既不是 dev 也不是任何分支的代码 —— 这是 AC01 要求的「运行身份」缺口的直接证据，不是猜测。
- `ai-for-investor-full-history-recovery.service` 每分钟失败，`ExecMainStatus=2`，journal 原文 `can't open file '…/run_full_history_recovery_worker.py': [Errno 2] No such file or directory`。`list-timers` 的 PASSED 列对该 unit 毫无意义。

## 2 幽灵迁移：库状态无法由仓库重建

库里的 `alembic_version` 是 `20261019_akshare_enum_values`，而这个 revision 在仓库里不存在，`alembic current`/`alembic stamp` 都报 `Can't locate revision`。它的来源只在字节码里：

| 文件 | sha256 前 13 位 | 恢复出的身份 |
|---|---|---|
| `…__pycache__/20261019_akshare_enum_values.cpython-313.pyc` | `1a2ef06c542b2` | `revision=20261019_akshare_enum_values`，`down_revision=20261019_akshare_scheduler_claims` |
| `…__pycache__/20261019_akshare_scheduler_claims.cpython-313.pyc` | `514fdcff185a1` | `revision=20261019_akshare_scheduler_claims`，`down_revision=20261017_legacy_paper_import_cutover` |
| 两个 `.py` 源文件 | — | 在磁盘、在 `var/**`、在任何 ref 都不存在（`git log --all --diff-filter=A` 为 0） |

从字节码常量读出的实际内容（不是推断）：

- `…_scheduler_claims` 建 `ak_task_run_claims`（主键 `claim_key`，含 `fencing_token`、`lease_expires_at`、`parameter_hash` 等 17 列 + 3 个索引）与 `ak_scheduler_control`（`control_id`、`source_next_allowed_at` JSON、`updated_at`）。
- `…_enum_values` 是数据归一化，作用面恰好 5 个 `(表, 列, 允许值)`：`ak_data_scripts.frequency`、`ak_interface_parameters.param_type`、`ak_scheduled_tasks.schedule_type`、`ak_task_executions.status`、`ak_task_executions.triggered_by`；其 downgrade 主动拒绝（`AkShare enum normalization cannot be reversed safely; restore the pre-upgrade backup.`）。

结论：这两个迁移**不需要**由 dev 重建 —— `alembic check` 现在把这两张表报成 `remove_table`，说明 dev 的模型已不再引用它们（旧任务认领机制被替换）。缺的只是「本机库状态带着仓库无法复现的历史」这一事实，必须记录而不是抹掉。

## 3 修复动作与顺序（每步都可复核）

1. **备份**：`mysqldump --single-transaction --routines --triggers --hex-blob ai_for_investor`，凭据经 0600 defaults-file 传入，不出现在 argv。产物 `var/backups/iteration204/ai_for_investor_pre_upgrade_20261105T2148.sql.gz`，135,093,875 字节，`gzip -t` 通过，含 867 条 `CREATE TABLE`/`INSERT INTO`，`sha256 = 5bca70ab417e04b1b4d518bd4f7d7a01a9eb8db61fb8a83cb5b10599234c…`。
2. **定位真实祖先**：两个幽灵迁移的链条是 `20261017_legacy_paper_import_cutover → (ghost) → (ghost)`，而 `20261017_legacy_paper_import_cutover` 在仓库里 tracked，且 tracked 待补链只有 `20261030 → 20261031 → 20261101` 三个新增对象（两张空表 + 一个列），与幽灵迁移的作用面无重叠 —— 这是「可以向前钉」的判据，不是「随便钉」。
3. `alembic stamp 20261017_…` 仍被未知 revision 挡住 → 用 `alembic stamp --purge 20261017_legacy_paper_import_cutover`（`--purge` 清空版本行；已在步骤 1 有备份，且被清掉的那行本来就不可解析）。
4. `alembic upgrade head` 依次执行 `20261030_stock_analysis_snapshot_grants`、`20261031_stock_daily_snapshot_grants`、`20261101_stock_analysis_report_evidence_vector`；`alembic current` == `alembic heads` == `20261101_stock_analysis_report_evidence_vector`，单 head。
5. `systemctl --user restart ai-for-investor.service`。注意冷启动约 70 秒（加载嵌入模型），其间 8000 端口 connection refused 属正常，`/docs` 随后返回 **200**，`NRestarts=0`。

**没有做**的：不降级、不删表、不动 `ak_task_run_claims`/`ak_scheduler_control` 里的历史行，不改任何 workflow 或分支保护。

## 4 `alembic check` 的既有漂移（记录，不修）

这些在修复前后都存在于同一份代码/库组合，与本次修复无因果，且**任何一项都不该被自动 upgrade 抹平**：

- `remove_table ak_task_run_claims`、`remove_table ak_scheduler_control`（见 §2）。
- `LONGTEXT` vs `Text`：`chat_messages.content`、`chat_messages.reasoning`、`document_chunks.content`、`kb_documents.content`。
- `INTEGER` vs `Float`：`paper_trades.size`、`paper_trading_orders.size`、`paper_trading_orders.filled_size`、`paper_trading_positions.size`；另有 5 个 `paper_trading_positions` 列的 nullable 差异。
- 缺 2 个索引：`ix_workspaces_user_type_updated_id`、`ix_workspaces_user_updated_id`。

## 5 恢复运行时资产：只恢复能证明的那一个

- 从 `var/reports/afi204/2026-10-28-recovery-worker-candidate/` 原样取回 worker（`sha256 8715a285f2c38ef7…`），而不是重写 2,306 行实现。
- 只读验证：`--plan` 正常输出且 `source_or_database_calls: 0`、`scheduler_started: false`；`ruff check` = All checks passed，`ruff format --check` = already formatted。
- 装好后 `--apply` 变成**具名失败关闭**：`run_id 20261105T140002Z-6a51aa6b97a0`、`asset crypto`、`error: required runtime inputs missing: …/scripts/crypto_full_history_recovery.py`、`write_possible: false`、`source_failure_recorded: false`、`exit_code 2` —— 没有伪造源失败、没有伪造冷却、没有写库。
- worker 通过 subprocess 调度的 5 个控制器，`git log --all --diff-filter=A` 逐个实测 **added-in-any-ref = 0**；本机留档副本：`crypto_full_history_recovery.py` 有 2 份（都是 proposal 快照，不能证明等于当时部署版本），`stock_full_history_controller.py`、`backfill_etf_nav_controller.py`、`bond_convertible_history_controller.py`、`cffex_option_history_controller.py` **一份都没有**，只有它们产出的 progress JSONL 证明曾经存在。
- 因此不恢复那 5 个：把一个写数仓的脚本按「大概是这份」放回运行时是猜测，不是证据。属主决定：重建 / 停用该 unit / 只按留档恢复 crypto 一条腿并另行复核。PR #273 只含 worker 本身。

## 6 采集恢复（平面：本机 DEPLOYMENT 观测，非验收）

修复后同一 UTC 窗口 `2026-11-05 13:57:03 → 14:10`：

| 计数 | 值 |
|---|---|
| 执行总数 | 10 |
| `completed` | **9** |
| `failed` | **0** |
| `running` | 1（task 1049 `crypto_hourly_market`，14:03 UTC 起） |

写入量按 `rows_after - rows_before` 逐条读回：task 732 `stock_esg_msci_sina` **+5,371**；task 476 `option_commodity_contract_table_sina` **+29**；task 370 `spot_hog_lean_price_soozhu` **+15**；task 186 `macro_china_insurance` 与 task 782 `stock_hk_famous_spot_em` 为 **0**（幂等，已是当日最新）。日志同期出现 `akshare_to_mysql.fetch_ak_data` 的「调用Akshare函数 / 获取数据成功」，即真实源请求确实发生。

对照 §1 的九天 4,279/0：这不是「变好了」的形容词，是 0→9 的计数。

## 7 对验收矩阵的影响（逐条，不越界）

- **AC14 自然周期**：进程级节奏从 2026-11-05 13:57:03 UTC 恢复（该窗口实测 22 条执行 / 20 completed / 2 failed，截至 14:29:07 UTC）。但**小时腿尚未连续**：task 1049 `crypto_hourly_market` 的 14:03 occurrence 在 601 s 被判超时失败（§9），所以「连续 48 次小时运行」的起点不能算作 14:03，只能等 §9 的两类缺陷修完再重新起算；日任务的 7 个应运行交易/发布周期按交易日历另计。**这是「恢复计数能力」，不是「已开始满足」。**
- **AC13 单写者与运行恢复**：未触碰。租约过期后恢复、跨进程源额度、旧 worker fence 等仍未闭合；§5 的 worker 缺失反而说明该域曾长期在无版本控制的脚本上运行。
- **AC05 全历史覆盖**：仍 `UNKNOWN`。逐 `instrument × dataset` 的分母、退市集合、分页完整性一项都没变；恢复控制器缺失意味着这条腿现在根本没有执行者。
- **AC11 逐脚本与逐任务适配**：`ak_data_scripts` 1,066 行、非 `__init__` 脚本 1,057 个，处置仍为 0/1057（见 `INVENTORY_AUDIT_20261105.md`）。
- **AC12 存量迁移与环境防线**：本文件的备份身份、钉→升级序列、漂移清单是该行要求的「先验环境/库身份」的现行证据；该行整体仍未闭合（分区行键对账、真实 apply 演练未做）。
- **AC01 范围与基线**：脚本一半已在 #271 刷新；本文件补上运行入口/服务/进程这一半的现行读数。
- **AC09/AC10/AC17/AC18**：本文件零影响。

## 8 仍然开放的属主决定（新增两条，不含旧的 9 条）

1. 5 个恢复控制器：重建 / 停用 unit / 只恢复 crypto 腿（§5）。
2. 1098 个 armed 任务是否就是本意：`scheduler.py:106/132` 会把每条 `is_active` 都武装起来，而 2026-10-25 的台账记录的是「1,103 行里 69 条 active」。当前实际是 1,098 armed 全量跑真实源。本次修复按属主指示放行了全量，因此源侧配额与 AC13 的跨进程预算问题立刻变成活问题，而不是以后再说。

## 9 修复后新查出的运行态缺陷（记录，不在本文修）

同一台机器、同一份 dev 代码，修复之后 30 分钟窗口实测 14 completed / 2 failed。两条失败各有明确成因：

1. **失败被记录之后，脚本还在写库。** task 1049 `crypto_hourly_market` 的台账行是
   `created_at 14:03 / status=failed / end_time 14:13:01 / duration 601.0 /
   error='Script call timed out after 600 seconds'`；而 `logs/backend.log` 显示同一脚本在
   `22:13:54`（=14:13:54 UTC）处理 10000/59983 行，`22:18:43` 写「成功保存 59983 行数据到 CRYPTO_HOURLY…」，
   `22:18:44` 再写 87 行。也就是说台账宣布失败并写下 `end_time` 之后约 5 分钟，写入仍在继续。
   根因可在 `app/services/akshare/script.py:501-514` 直接读出：执行走
   `asyncio.wait_for(asyncio.to_thread(...), timeout)`，`wait_for` 取消的是 awaitable，**线程不可杀**。
   这违反本仓既有操作不变量：脚本入口必须跑在可杀的 child process group 里，超时/取消时先杀组再收割、
   然后才抛错，并把父侧写栅栏（`claim_key`/`owner_id`/`fencing_token`/`execution_id`）传进子进程、
   把子进程的已提交写回执并回父侧 tracker。该实现曾在树里（`app/services/akshare/__pycache__/script.cpython-313.pyc`
   仍含 `_execute_callable_in_worker`，2026-10-27 编译），现已从 dev 源码消失——即这是一次**回归**，不是新缺陷。
   验收含义：`failed` 不等于「无副作用」，任何按执行状态推导覆盖/新鲜度的做法在该路径上不成立（AC06 崩溃一致性、AC13 取消与重试）。
2. **参数签名不匹配。** `"EtfFundHistEm.run() got an unexpected keyword argument 'source'"`：驱动按
   `script.run(**params)` 调用，而该脚本的 `run` 不接受 `source`。这与 #270 的
   「831 个 `main()` 调用不存在的 `run`」同源，属同一类静态形状问题。

另记一条与 §1 同类的身份事实：产生 4,279 条失败的 raise 语句不在任何 ref 里，说明当时运行的进程与仓库无对应关系。
## 10 「不在任何分支」是一类缺陷，不是孤例（本会话逐个实测）

修复过程中每往里挖一层就多发现一个未入库的运行资产。以下每一条都是 `git ls-files` / `git log --all --diff-filter=A` /
文件系统三查的读数，不是推断：

| 运行资产 | 谁需要它 | 工作树 | 任一 ref | 本机副本 |
|---|---|---|---|---|
| `scripts/ops/run_full_history_recovery_worker.py` | `ai-for-investor-full-history-recovery.timer`（每分钟） | 缺 | 0 | 有（留档 candidate）→ #273 已入库 |
| `tests/test_full_history_recovery_worker.py` | CI diff-coverage 步 | 缺 | 0 | 有（同 candidate 目录）→ #273 第二提交补回，**44 passed** |
| `deploy/systemd/ai-for-investor-full-history-recovery.{service,timer}.example` | 上面那条测试自己要求存在 | 缺 | 0 | 有 → #273 一并取回 |
| `scripts/ops/run_etf_nav_shard.sh` | `ai-for-investor-etf-nav-backfill@.service` 的 `ExecStart=%h/…/run_etf_nav_shard.sh %i 4` | 缺（find 无命中） | `git ls-files` = 0 | 无 → 实例 @0 停在 `activating` |
| `scripts/{stock_full_history_controller,backfill_etf_nav_controller,bond_convertible_history_controller,cffex_option_history_controller,crypto_full_history_recovery}.py` | 恢复 worker 的五个资产腿 | 全缺 | 逐个 `added-in-any-ref = 0` | 仅 crypto 有两份 proposal 快照 |
| `scripts/bond_full_history_audit.py` 与生产侧 `normalize_bond_symbol` / `normalize_daily_frame` | 可转债腿的历史审计路径 | 缺 | 未追 | 无（重建因此改为自包含，不 import 死资产） |

规律很清楚：**这套运行时有相当一部分从未进入版本控制**，所以「服务在跑」与「仓库能重建这台机器」长期是两件事。
这正是 AC01 要求双向 anti-join、AC12 要求先验环境身份的原因，也解释了为什么 4,279 条失败的错误文本在任何 ref 里 `grep` 不到。

对验收的直接影响：AC05 的执行者正在由「不存在」变成「可执行但未证」——五个控制器已按属主决定重建（三条已完成：
stock 46 项、bond 36 项、etf 38 项本机测试通过，适配器分别以 `NotRunError`/未调用诚实标注），
但每一条都仍是 CODE/OFFLINE + 本机；真实源、真实数仓、真实定时器运行一律 NOT_RUN。
