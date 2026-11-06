# AC01 范围与基线：七面清单现行刷新（2026-11-06，Asia/Shanghai 主机）

判据原文（`ACCEPTANCE_AND_CUTOVER.md` §1，不改写）：

> AC01 | 范围与基线 | 重新冻结两个仓库和未提交差异hash；源文件、实际DB任务（含inactive）、
> systemd/cron/worker、进程、表、消费者、OpenData重叠能力均有带环境身份/采集时间的清单；
> 各自分母明确且双向anti-join无未解释项。旧盘点中的1,066个脚本候选和1,103个任务只能作为历史快照，
> 不能代替当前刷新或被当作现行总数。

采集时间：2026-11-06 13:23–14:43 UTC（CST 21:23–22:43）。方法：只读 SQL（脚本内含只读断言）、
`git` 只读子命令、`systemctl --user` / `journalctl --user` 只读、两仓磁盘上的目录对象计数。
本文每个数字后面都跟着它的产生方式；不能测的写"未测"，不猜。
运行本目录 `evidence/2026-11-06-wave29/` 内脚本可复跑其中五面。

## 0. 环境身份

| 口径 | 值 | 方式 |
|---|---|---|
| 主机时区 | Asia/Shanghai（调度器与 cron 按它解释；执行行按 UTC 存） | 见 `RUNTIME_READOUT_20261106.md` §5 |
| 可见 MySQL 库 | `ai_for_investor` 171 表、`akshare_data` 1045 表、`backtrader_web` 75 表 | `information_schema.tables` 分组计数 |
| 控制面 DSN 身份 | `backtrader_web@127.0.0.1:3306/ai_for_investor`（口令不外泄） | `src/backend/.env` 的 `DATABASE_URL` |
| 数据面 DSN | 另有 `AKSHARE_DATA_DATABASE_URL` 指向 `akshare_data` | 同上 |
| 运行 venv | Python 3.13.5 / fastapi 0.121.2 / APScheduler 3.11.1 / SQLAlchemy 2.0.39 / PyMySQL 1.1.1 / pydantic 2.12.4 / akshare 1.18.64 / uvicorn 0.35.0 | `pip list --format=freeze` |

## 1. 两个仓库的冻结与未提交差异（判据第一句，此前从未做过）

`git rev-parse HEAD` + `git status --porcelain=v1 -uno` + `git diff HEAD` 的 sha256
（全零树哈希 `e3b0c442…b855` 即 sha256("")，代表该通道为空）：

| 仓 | HEAD | 已跟踪差异 sha256 | status porcelain sha256 | 未跟踪条目数 | 未跟踪清单 sha256 |
|---|---|---|---|---|---|
| ai-for-investor | `0a4c5ab319c1195972a027fefea686dad179c26d` | `e3b0c442…`（干净） | `e3b0c442…`（干净） | 1 | `35439087e87dd1c9…` |
| opendata | `051824bd386ccfebb6e6257cb4eb4e62d2450be5` | `e3b0c442…`（干净） | `e3b0c442…`（干净） | 0 | `e3b0c442…` |

两条必须一起读的事实：

1. **OD 本地 checkout 落后于它自己的 origin/dev**（`051824bd` vs 今天合入后的 `02fb79a2f`）。
   上面对 OD 的冻结读数是**旧提交**的读数，不能当现行总数。
2. `git worktree list` 共 **62** 个工作树，其中 **5 个带未提交改动**：

| 工作树 | HEAD | 改动文件数 | `git diff HEAD` sha256 前 16 |
|---|---|---|---|
| `.wt-afi-ctp` | `26b096005f5c` | **36** | `873dd818ed53e2be` |
| `.wt-afi-castrow` | `bce164cb4a6a` | 6 | `b7cc9e8e78e69bc2` |
| `.qoder/worktrees/agent-general-purpose-afbd0ac5` | `3fad48a280d2` | 16 | `88bfefd42bdcbdf8` |
| `.wt-afi-capwriter` | `3a2318014a16` | 3 | `1251f63e1a020ad9` |
| `.wt-afi-killable` | `ccddb2687af2` | 1 | `b9b32e1c67708779` |

这第五行正是判据"未提交差异 hash"要钉住的东西：**存在多棵树带着改动活了几小时**。
`.wt-afi-ctp` 的那 36 文件是本波接手时已经在的遗留工作（采集平面清债的一半），
我把它备份成 patch 后交给 #305 评估合并，没有丢弃也没有直接提交。

## 2. 源文件面（分母与双向 anti-join）

| 口径 | 值 | 方式 |
|---|---|---|
| AFI tracked 非 `__init__` 脚本 | **1057** | `git ls-files src/backend/app/data_fetch/scripts` |
| AFI tracked `.py`（全部） | 1058 含 `__init__`；本目录另有全仓 3169 个 `.py`、去重后 3099 个 sha256 | 同上 / `sha256sum` |
| 迁移台账 CSV 行数 | 1066（历史快照，不可当现行总数） | CSV 计数 |
| CSV→树 正查缺项 | **9**（见下） | 逐行按 basename 匹配 |
| 树→CSV 反查缺项 | **0** | 集合差 |

9 条 CSV-only 行的来源已在 §8 判定为"CSV 生成自带未提交文件的工作树"，
因此这里不重复展开；**未解释项 = 0（已归类，不是已解决）**。

## 3. 实际 DB 任务面（含 inactive）

| 口径 | 值 |
|---|---|
| `ak_scheduled_tasks` 行 | 1103（`schedule_type` 全为 cron） |
| armed | 今天 13:23 UTC 读到 **1098**；13:47:56 UTC 按属主裁定停用队列 A 的 50 个后为 **1048** |
| inactive | 5 + 50 = **55** |
| `ak_data_scripts` 行 / active | 1066 / 1051；其中 9 行 `module_path` 无文件 |
| 任务→脚本反查孤儿 | 0 |
| 有文件但未注册 | 0 |

## 4. systemd / cron / worker 面

`crontab -l`：**no crontab for yun**（cron 通道为空，全部调度来自 systemd user timer + 应用内 APScheduler）。
`systemctl --user list-timers` 里 ai-for-investor 相关 timer **6** 个：
dce-browser-capture、dce-option-daily、full-history-recovery、policy-expiry-watchdog、
stock-amount-daily、stock-tail-daily。

单元状态与 `ExecStart` 目标可解析性见 `RUNTIME_READOUT_20261106.md` §11：
**12 个被 live unit 指向的宿主脚本不在树里**（7 个 `scripts/ops/` + 5 个控制器/回填脚本），
9 个受影响 sidecar（8 个 failed/disabled/looping + `dce-option-recovery`）。
worker 侧：`src/backend/scripts/ops/run_full_history_recovery_worker.py` 今天已由 #273 恢复到版本控制里
（此前它只在 `var/` 里有副本，正是九天前那个"打不开文件"的成因）。

## 5. 表面

| 库 | 表数 | 说明 |
|---|---|---|
| `ai_for_investor` | 171 | 控制面：任务、注册、执行、能力台账等 |
| `akshare_data` | 1045 | 数据面；采集写入实际发生在这里 |
| `backtrader_web` | 75 | 与本迭代无关的旧应用 |

`ak_data_scripts.target_table` 去重后与 `akshare_data` 的表名做双向 anti-join：
`md_capability_ledger_entries` = **0 行**（无生产写入者，AC02/03/09/18 的真实阻塞点）。
7 个幽灵注册对应的表**在 `akshare_data` 里存在且有存量数据**（合计约 2,400 万行），
在 `ai_for_investor` 里不存在——只在元数据库里查会得出错误结论，本波已纠正。

## 6. 消费者面

UTC 日 2026-11-06 截至 14:07：执行 272 completed / 65 failed / 1 running。

| 口径 | 值 |
|---|---|
| 今日有正行增量的目标表 | **109**（合计 +128,336 行） |
| `ak_data_tables` 今日更新 | 155 / 1061 |
| 目标表今日无成功写入的 armed 任务 | 892 / 1044（分母 1044：4 个任务的脚本行没有可用 `target_table`） |

892 这个数**不可**读成"892 个数据集缺数"：多数是周/月形状当天未轮到，按各自 cron 的应跑槽位判定才是诚实口径。

## 7. OpenData 重叠能力面

用 OD 磁盘上最新的跨仓目录（`var/reports/afi204/*-r12-final/source/docs/afi204-migration-catalog.json`，
生成于 2026-10-30）与 AFI 今天的树做双向 anti-join：

| 口径 | 值 |
|---|---|
| 目录文件行 | 1066 |
| 目录 ∩ AFI 今日 tracked | **1057**（全覆盖） |
| 目录有、AFI 树无 | **9**（即幽灵注册同一批，同源） |
| AFI 有、目录无 | **0** |
| 目录生成时 baseline_hash_match | True ×1066（当时是全的；今天 891 条已不匹配，见 §9） |
| 目录 status | `MISSING_PROVIDER` 877 / `REQUIRES_MANUAL` 189 |
| 目录 sink_status | `LEGACY_SINK_REQUIRES_OPENDATA_DATASET_MAPPING` 921 / `UNKNOWN_SINK_REQUIRES_REVIEW` 135 / `NO_STATIC_SINK_FOUND` 10 |
| 目录 runtime_verification | **NOT_RUN ×1066** |
| OD provider 模型文件 | 319 个，其中 `source=akshare` 仅 **10** 个，覆盖 **12** 个 akshare 函数名 |
| OD endpoint 目录 | 974 条：`MISSING_PROVIDER` 870 / `REQUIRES_MANUAL` 103 / `READY_FOR_ADAPTER` 1 |
| OD 调度模板 | `opendata/pipeline/schedules.yaml` 7 个模板 |

这一面给出一句此前没被量化过的结论：**接收侧目前的 akshare 能力是 12 个函数对 1057 个脚本**。
所以"迁移未完成"不是盘点的缺失，而是被接收侧能力真实限制着——
把它写成"等分类"会误导；`runtime_verification NOT_RUN ×1066` 也说明这批候选从未做过运行态核验。

## 8. 未解释项清单（判据要求"无未解释项"）

| 项 | 数量 | 当前归类 | 是否闭合 |
|---|---|---|---|
| CSV/注册有、树里无文件的脚本 | 9 | 由带未提交改动的工作树生成（三重证据：git 历史 0、全仓 sha256 0 命中、OD 树 0 命中） | 已归类，未闭合 |
| live unit 指向的缺失宿主文件 | 12 | 同一 provenance 模式：宿主未提交文件被当运行资产 | 已归类，未闭合 |
| 幽灵注册对应表里的存量数据 | 约 2,400 万行 / 7 表 | 写入者无法绑定（新鲜度未测） | **未解释** |
| `accepts_var_kwargs` 任务 | 886 | 静态不可证；运行态已证 155/1048 | 部分解释 |
| `ak_data_scripts.frequency` 恒为 `manual` | 1098(停用前)/1048 | 字段不携带信息，分派须按 cron 取频 | 已解释 |
| 5 个工作树带未提交改动 | 36+16+6+3+1 文件 | 本波交接态，非未知 | 已解释 |

## 9. 与既有文档的矛盾（本文优先，旧数不改写）

1. `INVENTORY.md:11` 的"1,066"是 CSV 行数，现行分母是 **1057**；本文不再用 1066 当总数。
2. `INVENTORY_AUDIT_20261105.md` 的分频（daily 680/weekly 266/…）是**目录名派生的 CSV 声明值**；
   与 armed cron 对不上（自称 daily 的 694 个里 690 个实为星期受限），且
   `ak_data_scripts.frequency` 全为 `manual`。分派维度必须换成 cron。
3. 迁移台账 CSV 的 `source_sha256` 对今天 891/1057 已不成立；被 #270/#275 改过的文件
   **无一条**仍匹配。它不能再充当"重新冻结 hash"的锚。

## 10. 对 AC01 判定的影响

七面里：**源文件、DB 任务、systemd/cron/worker、进程、表、消费者六面已刷新**（带命令与时间），
**OpenData 重叠能力已刷新**（第七面），仓库冻结与未提交差异 hash **本轮第一次产出**。
但判据要求"无未解释项"，而 7 个幽灵表的 2,400 万行存量**写入者仍无法绑定**，
新鲜度未测；CSV 的 hash 锚也已失效需重生成。

因此 **AC01 维持 PARTIAL / NOT_PROVEN**，本文的作用是把它从"没做过"变成
"只剩两项具体缺口：重生成迁移清单的 hash 锚、绑定 7 张表的存量数据来源"。
任何声称 AC01 已通过的表述都不成立；本文也不改动其它 AC 的判定。
