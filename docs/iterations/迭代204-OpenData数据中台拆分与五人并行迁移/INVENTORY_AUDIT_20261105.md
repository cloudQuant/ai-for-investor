# 采集脚本清单刷新与双向对账（2026-11-05）

本文件是 AC01「源文件…有带环境身份/采集时间的清单，且分母明确且双向 anti-join 无未解释项」在
**脚本这一半**上的一次现行刷新。它不替代 `script_migration_inventory.csv`，也不改动它：
对不上的行一律列出并交属主裁定，不自行删除、不自行解释成通过。

## 采集环境身份

| 项 | 值 |
|----|----|
| 采集时间 | 2026-11-04T23:51:00Z 起，对账检查 23:51–23:52Z（UTC） |
| 主机 | `yun`，Linux 7.0.0-28-generic x86_64，本机 CPU-only，无生产凭证 |
| 解释器 | Python 3.12.3（对账脚本）；mypy 1.20.2（类型面读数） |
| 仓库基线 | `ai-for-investor` `origin/dev = dfa009cffca302c046ab4456ab4e469efecab80e`；清点树 `2b601de56ea72a8038b6a6d14ce544069cc7a415` |
| 对照仓库 | `/home/yun/Documents/opendata` 工作树（用于跨仓重名假设） |

## 分母（现行，非历史快照）

| 口径 | 数 | 测法 |
|------|----|------|
| `app/data_fetch/scripts/` 下 tracked `.py` | **1108** | `git ls-files` 全量 |
| 其中非 `__init__.py`（迁移对象口径） | **1057** | 同上，按文件名剔除 |
| 该目录下未跟踪 `.py` | **0** | `git ls-files --others --exclude-standard` |
| `script_migration_inventory.csv` 行 | 1066（无重复） | CSV 解析，唯一路径 1066 |

`INVENTORY.md:11` 写的「非 init Python文件 1,066」是把 CSV 行数当成文件数；按文件实测为 1,057，
差的正好是下面 9 行。

## 正查：清单 → 树

1066 行中 1057 行能在树里找到同名文件；**9 行找不到**。对这 9 行做了三重独立检验，全部落空：

| 检验 | 命令口径 | 结果 |
|------|----------|------|
| 工作树 | `(root / path).is_file()`，主检出与各 worktree 各跑一遍 | 9/9 缺失 |
| git 历史 | `git log --diff-filter=A` 与 `--diff-filter=D` 逐路径 | 9/9 既无新增也无删除记录，即从未入库 |
| 内容哈希 | 全仓 `.py`（排除 `.venv`/`__pycache__`/`node_modules`）建 sha256 反向索引 | 9/9 的 `source_sha256` 不匹配仓内任何文件 |
| 跨仓重名 | 在 `opendata` 工作树按文件名 find | 9/9 命中 0 |

9 行原文（`role` = `static_role`，`route` = `migration_route`）：

| source_path | role | route | 记录的 sha256 前 12 位 |
|-------------|------|-------|------------------------|
| `bonds/daily/yield_release_policy.py` | helper_review_only | HELPER_REVIEW | `8364df777f94` |
| `common/daily/forex_hist_sina.py` | entrypoint_fetch_data | PENDING_PROVIDER_MAPPING | `0257a10ce39d` |
| `funds/hourly/etf_realtime_quote_sina.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `2cf147c361b6` |
| `funds/weekly/fund_monetary_income_history.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `a10b40add47c` |
| `funds/weekly/fund_reviewed_unit_nav_history.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `190180d062ef` |
| `futures/release_policy.py` | helper_review_only | HELPER_REVIEW | `7844c6e60da1` |
| `options/daily/cffex_option_daily_history.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `d9725e98d24e` |
| `options/daily/commodity_option_daily_history.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `aef85da51e26` |
| `options/daily/etf_option_daily_history.py` | entrypoint_run | PENDING_PROVIDER_MAPPING | `332bc018dbe8` |

（路径均相对 `src/backend/app/data_fetch/scripts/`。）

## 反查：树 → 清单

1057 个非 `__init__` 脚本**全部**出现在 CSV 里，未列 0 条；51 个 `__init__.py` 按 CSV 口径不计入，
不构成 anti-join 缺项。

## 判定与限制

* AC01 的脚本侧：分母确定（1057 / 1108），双向 anti-join 的两个方向都已解释——一个方向 0 缺项，
  另一个方向 9 条**已定位但未定源**。因此这一半可称「已刷新」，不能称「已闭合」：`无未解释项` 要求
  说明这 9 行从哪来（候选解释：未提交的草稿文件、另一台机器的路径、生成期写入的错误条目），
  而本会话拿不出证据把它们归到任何一类。属主裁定前，CSV 不得作为「1,066 个脚本已有迁移映射」的依据。
* AC01 的另一半（实际 DB 任务含 inactive、systemd/cron/worker、进程、表、消费者、与 OpenData 能力重叠，
  以及这些口径各自的分母）**本次没有刷新**：它需要只读连库查询，本会话被明确约束不碰运行库，
  故 AC01 整体保持 `NOT_PROVEN`，本文只推进脚本半区。
* AC11（逐脚本映射与处置）的分母自此按 **1057** 计，不按 1066；上述 9 行属无源映射，不计入已处置。
* 平面状态顺带记录：这 1057+51 个文件此前不在类型面里（`pyproject.toml:150` 的 mypy `exclude`
  用非锚定子串 `scripts/` 把整棵树吞掉）；ruff 侧本已覆盖且 0 findings、1108 文件已格式化；
  覆盖侧仍被 `.coveragerc` 排除，且仅 120/1057（11.35%，13 个测试文件）被测试引用。
  类型面自 AFI #270 起以独立 scope 存在（advisory，实测 1103 → 270 errors），基线须由 CI 读数冻结。
* 本文所有结论均属 CODE/OFFLINE 平面：一次本机清点。不涉及 REAL_SOURCE、DEPLOYMENT、NATURAL_CYCLE。

## 处置进度（AC11）：已分派处置的脚本是 **0 / 1057**

读同一份 `script_migration_inventory.csv` 的 1057 条活行（路径存在者），三列一致地说明它们都还没有 §5 要求的处置：

| 列 | 取值与计数 |
|----|------------|
| `status` | `待盘点/待映射` 1049、`review_only` 8 |
| `migration_route` | `PENDING_PROVIDER_MAPPING` 1049、`HELPER_REVIEW` 8 |
| `target_dataset` | `待数据契约与目标映射` 1049、`不适用；需人工判定` 8 |

**词表漂移**：计划 §5 规定的处置只有七种——`REUSE_PROVIDER / EXTEND_PROVIDER / CONSOLIDATE / HELPER_ONLY /
REPLACE_SOURCE / SOURCE_LIMITED / RETIRE_PROPOSED`；清单使用的这两个占位值都不在其中，且在本仓任何 markdown
里都没有定义（`grep -rn PENDING_PROVIDER_MAPPING docs/ --include=*.md` → 0 命中）。后果是直接的：§6 要求每周报告的
「已处置脚本 / 总脚本」按现清单只能是 **0/1057**，把 1049 条 `PENDING_*` 读成「已映射」就是虚报。

静态盘点口径顺带记全（这些只描述文件形状，**不构成处置**）：

* `static_role`：`entrypoint_fetch_data` 885、`entrypoint_run` 162、`helper_review_only` 8、`entrypoint_main` 2
  （合计 1057）。这与类型平面实测互相印证：885 个类自带 `fetch_data`，其中 **831 个**的 `main()` 却调用 MRO 里
  并不存在的 `run`（AFI #270 已按调用点修好）；162 个自带 `run`。
* `asset_family`：stock 384、other 317、index 93、fund 87、futures 64、option 46、bond 41、fx 20、crypto 5。
* `legacy_frequency`：daily 680、weekly 266、hourly 85、monthly 21、**unspecified 5**。
* `owner`：B 604、C 445、review 8。

判定：AC11 保持未完成，进度记为 0/1057 已分派。这一项不是 CI 能变绿的项，需要按 §5 词表逐条分派；
其中 `unspecified` 5 与 `other` 317 还说明频率与资产族本身尚未人工确认，不能自动当作已知输入。
平面：以上全部是 CODE/OFFLINE（读台账与源码形状），不涉及 REAL_SOURCE / DEPLOYMENT / NATURAL_CYCLE。

## 运行态读数（同一台机器、同一份库，只读 SELECT + `journalctl --user`）

AC01 的另一半（实际 DB 任务，含 inactive）本次也做了只读盘点：

| 口径 | 实测 |
|------|------|
| `ak_scheduled_tasks` 行数 | **1103**（全部 `schedule_type='cron'`） |
| 其中 armed（`is_active=1`） | **1098**，且这 1098 行 `next_execution_at` 全部非空 |
| inactive | 5 |
| `ak_data_scripts` 注册行 | **1066**，`module_path` 全不重复 |
| 注册但树里没有文件的 | **9**（正是上面 9 行幽灵；其中 7 行 `is_active=1`、2 行 `is_custom=1`、8 行 `function_name='main'`） |
| 有文件但未注册的 | **0** |
| 任务 → 注册脚本 反查孤儿 | **0** |

结论先说清两件事：

1. **「69 个精选 active 任务」不再是事实。** 2026-10-25 的迭代203 台账与本机笔记记的是 69 active / ~1034 inactive；
   2026-10-26 之后到本次读数之间，`updated_at` 分布在 2026-10 的 459 行与 2026-11 的 639 行上，armed 数变成
   **1098**。调度器 `app/services/akshare/scheduler.py:106/132` 只按 `is_active` 注册，没有任何白名单，
   所以现在被装填的切换面比 AC13/AC14 取证时的面大 ~16 倍。这不需要判断对错，但需要有人认领。
2. **采集运行态从 2026-10-27 00:57 起 100% 失败。** `ak_task_executions`：
   最后一次没有 `error_message` 的运行是 **2026-10-27 00:55:00**；此后到 **2026-11-05 00:19** 共 **4270** 次运行，
   错误信息全部是同一条 `AKShare script worker exited with code 1 without a result`，覆盖 **1080** 个不同任务；
   近 7 天 3204 次运行里 completed **0**、failed **3204**。存行的 `error_trace`/`result` 全为空（60/60 无栈），
   所以台账里只剩一句状态词，九天的全量失败在账面上不可见——这本身就是一条可观测性缺陷。
   同机的 `ai-for-investor-full-history-recovery.service` 每分钟以
   `can't open file '.../src/backend/scripts/ops/run_full_history_recovery_worker.py': [Errno 2] No such file or directory`
   失败；该文件**从未进过任何分支**（`git log --all --diff-filter=A` 0 命中），只在
   `var/reports/iteration203/**` 与 `var/reports/afi204/2026-10-28-recovery-worker-candidate/**` 里有候选/备份副本，
   也就是说 unit 依赖的一直是一个未纳入版本控制的工作树文件。

对验收的影响，按平面说：

* REAL_SOURCE / NATURAL_CYCLE：**这两条现在都是红的，不是「未测」。** AC14 的 48 次小时 / 7 个日周期自然运行证据
  取自 69-任务制度下的旧窗口，既不能续期也不能代表现在的 armed 面；AC05 的全历史覆盖、AC10 的真实源逐字段对照
  在此状态下不可能有新证据。任何 freshness/覆盖率陈述若晚于 2026-10-27 00:55 都必须作废重取。
* DEPLOYMENT：以上是**本机**运行态（`ai_for_investor@127.0.0.1:3306`、用户级 systemd timer），不是生产部署读数；
  它说明的是「这台机器上的部署形态现在采不到数」，不能外推为生产环境结论。
* 修复归属：恢复 worker 文件、决定 1098 armed 是否是有意的、以及把子进程 stderr 落到台账，都需要属主/运维决定；
  本迭代我只做只读盘点与记录，不重启服务、不补文件、不改 systemd 单元、不动 `is_active`。
* 顺带一条与 #270 相互印证的读数：9 行幽灵注册的 `function_name` 有 8 行写的是 `main`——正是「`main()` 是唯一入口」
  这个假设的产物，而 #270 的实测表明 831 个脚本的 `main()` 连 `run` 都不存在。
