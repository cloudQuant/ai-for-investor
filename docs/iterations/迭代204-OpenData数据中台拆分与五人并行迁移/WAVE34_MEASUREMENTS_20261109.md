# 迭代 204 — Wave 34 实测（2026-11-09）

本轮的主线不是新功能，而是把「已做但没入账」的证据变成可复跑的读数，并把两条长期 OPEN 的行
（测量环境、合并看守工具）收掉。**不改写任何 AC 判定**；凡未到时间的项写明时间点。

---

## 1. 合并与门禁

| 事项 | 实况 |
|---|---|
| #331 密钥扫描门禁修法 | **已合入** `6d7e7735`；dev 上该作业 `128977241889` **40 秒成功**（04:17:56→04:18:36），不再是 14 秒崩在 `curl: (56)` |
| #332 分页全序（a59dca628） | **已合入** `de0802469`；`merge-tree` 对 dev 干净，受影响测试本机 96 passed / 79 skipped |
| #303 | **已关闭**并留指向 #332 的说明；未做 force-push；39 绿的历史保留可查 |
| `etf-nav-backfill@0–3` | 属主批准后 **stop + disable**；before `NRestarts=11738` 且处于 `activating/auto-restart`，after `inactive/disabled`；主服务未受影响（`/docs` 200） |

## 2. AC01：锚无漂移，两个「幽灵」类第一次被问到底

### 2.1 源文件面（在 `7c8f6f2f1` 上重跑）

```
refresh_script_migration_inventory.py --check --snapshot-commit 29afaeb47
tree head: 7c8f6f2f1
anchors: 1057 matched / 0 mismatched / 9 missing (of 1066 rows)
explanation kinds: ghost_registration=9, in_sync=1057
invariant: 0 unexplained row(s)
derivation gate: 1057/1057 anchor-matched rows reproduced (PASS)
```

此后合入的两个提交对**被锚路径的命中数为 0/0**、对 `src/backend/app/data_fetch/` 的命中数也是 0/0
（`GET /commits/{sha}` 的 files 列表与 1066 条 inventory `source_path` 求交集）：
`de08024691` 5 个文件、`6d7e7735591` 10 个文件。**因此该读数在 dev 头 `6d7e773559` 上同样成立。**

### 2.2 7 个运行时幽灵脚本：**从未提交，但字节码还在**

先更正本文初稿里写强的一句话。初稿写「不存在找回原脚本的路径」，那是在**只查了 git 与磁盘源码**之后写的，
不完整。完整事实是三段：

**(a) 它们从未被提交，且没有源码副本。** 对七个目标名逐条查：AFI `git log --all` 无记录、
OpenData 仓无记录、`/home/yun/Documents` 下 77 个 worktree 的 `find -name` 无结果、
`var/backups/iteration204/` 只有升级前的 SQL dump。所以「从历史或备份里 checkout 回来」这条路不存在。

**(b) 但它们曾经真的跑过。** journal 里有成功记录：`etf-nav-backfill@` 跑到 2026-10-27 08:56
（`processed_codes: 10, source_verified_codes: 10, remaining_seconds: 79.5`）；`dce-option-daily`
2026-10-26 成功并落了 `10,061,904` 行审计；`stock-amount-daily` 日志止于 `processed 5569 symbols`；
`stock-tail-daily` 4 片 × 1432 符号、completed 1429 / failed 0。**它们不是从未工作的占位，是丢失的实现。**

**(c) 关键：部分目标的 Python 字节码还活着。** 部署树里现存 4 个 `cpython-313` 的 `.pyc`，
连它们的**测试字节码**也在：

| 丢失的实现 | 存活的 `.pyc` |
|---|---|
| `policy_expiry_watchdog.py` | `scripts/ops/__pycache__/policy_expiry_watchdog.cpython-313.pyc`（38,589 B） |
| `backfill_stock_amount_sina.py` | `scripts/ops/__pycache__/backfill_stock_amount_sina.cpython-313.pyc`（24,459 B） |
| `backfill_stock_tail.py`（shard 包装器调用的实现） | `scripts/ops/__pycache__/backfill_stock_tail.cpython-313.pyc`（27,157 B） |
| `dce_option_history_ingest.py` | `scripts/ops/__pycache__/dce_option_history_ingest.cpython-313.pyc`（27,003 B） |
| 测试 | `tests/__pycache__/test_policy_expiry_watchdog.*.pyc`、`test_etf_nav_backfill_controller.*.pyc`（151,921 B）、`test_backfill_stock_tail.*.pyc` |
| 包装器内的控制器 | `scripts/__pycache__/backfill_etf_nav_controller.cpython-313.pyc`（116,280 B）、`audit_futures_daily_dce_browser.*.pyc`、`cffex_option_history_controller.cpython-313.pyc`、`commodity_option_history_controller.cpython-313.pyc` |

用 `marshal.loads` 读这四个 ops 级 pyc，函数名、docstring 与关键常量都可读，例如：
`policy_expiry_watchdog` 的 `PolicySnapshot / _expiry_from / load_server_policy_catalog`；
`backfill_stock_amount_sina` 的 `_fetch_sina_kline_amounts`、表名 `STOCK_ZH_A_HIST_AMOUNT`、
源端点 `akshare.stock_zh_a_daily`；`backfill_stock_tail` 的
`resolve_window / acquire_lock` 与 `logs/stock_tail_backfill/progress.jsonl`。

**结论（改判）**：这七个 unit 的处置不是「只能从零猜」。
- `.py` 目标：**先从字节码恢复行为契约（函数边界、常量、参数）**，再决定是否需要逐字还原；
  本机没有任何反编译器（`pycdc`/`decompyle3`/`uncompyle6` 均不存在），主流工具对 3.13 字节码也没有保证，所以「恢复」不等于「拿到原文」；但函数边界与常量足以让重建有据，而不是从零猜。
- `.sh` 包装器：没有字节码，但它们的参数（shard 索引/总数、`tail|full`）与动作在 journal 里有实证，
  且它们调用的控制器 pyc 还在。
- 这四个 Python 目标与四个控制器 pyc 的存在，应当作为 D7 决策的第一手材料，而不是被忽略。

### 2.3 D7：七个 unit 的逐条决策简报

| unit | ExecStart 指向 | 状态 | 曾经成功？ | 它实际在做什么（证据） | 现有替代 | 可选处置 |
|---|---|---|---|---|---|---|
| `etf-nav-backfill@0..3` | `run_etf_nav_shard.sh %i 4` | inactive/disabled（本日属主批准停用），停前 `NRestarts=11738` | 是，至 2026-10-27 08:56 | 以 ~80 s 批次持续回补 ETF 净值；4 个分片各有 ~370 MB checkpoint 与游标 | `scripts/backfill_etf_nav_controller.py` 存在（2026-11-06 重建）但**无 `--shard`**，且 live adapter 全是 `NotRunError` | 恢复包装器（参数有据）／改指向（需先实现 live adapter + shard 模式）／删除（放弃 4 个游标与未探明代码） |
| `dce-option-daily` | `run_dce_option_recovery.sh tail` | failed，203/EXEC | 是，2026-10-26 | 每日增量抓取并入 `OPTION_COMMODITY_DAILY_HISTORY`，10,061,904 行、70,220 合约 | 无在用任务；`option_hist_dce` 任务 `is_active=0` | 按审计契约重建／改指向（需先启用任务）／删除（失去唯一 DCE 期权通道） |
| `dce-option-recovery` | `run_dce_option_recovery.sh full` | inactive，从未启动 | 无 journal；但 `full` 审计 2017-03-31..2026-10-22 已完成 | 一次性全量回补 | `full-history-recovery` timer 的 option 轮转**今天跑过**，`attention_required` | 删除（一次性任务已完成）／改指向 worker 的 option 轮转 |
| `dce-browser-capture` | `run_dce_browser_capture.sh` | failed，203/EXEC（timer 仍 enabled） | 是，2026-10-26（`prepared=1 saved=1 verified=1 rows=250`） | 浏览器绕过 WAF 抓 DCE 日行情 | `scripts/audit_futures_daily_dce_browser.py` 存在（plan/serve/snippet/ingest），无 armed task | 改指向该脚本 + 补一个 serve+browser 启动器／重建（journal 证据不足） |
| `option-history` | `run_option_history_loop.sh` | inactive/disabled，从未在 systemd 下运行 | 否（`-- No entries --`） | CFFEX 期权历史循环（无行为证据） | armed task 1082 `cffex_option_daily_history`（cron `5 19 * * mon-fri`）+ 控制器 + worker 轮转 | **删除**（已被取代）/改指向控制器 |
| `policy-expiry-watchdog` | `.venv/bin/python …/policy_expiry_watchdog.py --output …` | failed，每小时 status 2（timer enabled） | 是，最后输出 2026-10-27 08:00 | 只读的 reviewed 日历/策略到期审计，输出 `items[]`（market/policy/`expires_at` 2026-12-31/`manifest_sha256`/`evidence_path`/task_id） | 无 | **重建**（自有输出即契约，且有 pyc）／删除（则 2026-12-31 到期无人监控） |
| `stock-amount-daily` | `.venv/bin/python …/backfill_stock_amount_sina.py --max-minutes 300 --sleep-seconds 0.25` | failed，status 2（timer enabled） | 是 10-25/26/27，`processed 5569 symbols` | Sina 成交额 sidecar；`progress.jsonl`（schema_version 1）记 000001 1991-04-03..2026-10-20、已写 8,571 | 无（task 1007 只是单标的 qfq 试点） | **重建**（源端点/边界/schema 均有 pyc 与 ledger 证据） |
| `stock-tail-daily` | `run_stock_tail_slices.sh` | failed，203/EXEC（timer enabled） | 是 10-24/25/26（32 分钟 CPU） | 4 片 × 1432 符号的日增量，completed 1,429 / failed 0 | 无 | **重建**（分片/报表 schema 有据）／删除（失去日增量新鲜度） |

**当前 enabled 的 timer**：dce-browser-capture、dce-option-daily、policy-expiry-watchdog、stock-amount-daily、
stock-tail-daily —— 它们会在重启后继续重试并继续失败（watchdog 已每小时失败）。这五个是「今天仍会复发」的；
`etf-nav-backfill@` 与 `option-history` 已 disabled，`dce-option-recovery` 无 timer。
**本轮未改动这五个 unit**：处置属 D7 裁定。

### 2.4 停用四个 shard 之后的运行资产面 after-image（2026-11-09T05:11:55Z）

仪器：`evidence/2026-11-07-wave31/unit_runtime_asset_audit.py`，输出 `/tmp/it204/ac01_runtime_1109.json`。
**10 个 unit / 8 个仍有 missing-on-disk 目标 / 0 个未入库运行源码**（后者仍是空真）。

| unit | Active | UnitFile | 最近启动 | 说明 |
|---|---|---|---|---|
| `etf-nav-backfill@` | （模板，state 空） | — | — | 四个实例已 inactive/disabled，`NRestarts` 归零 → **崩溃循环停止** |
| `policy-expiry-watchdog` | failed | static | **2026-11-09 13:00:06 CST**（05:00Z） | timer 每小时触发，continue failing |
| `stock-amount-daily` | failed | static | 2026-11-09 04:00:45 CST（11-08 20:00Z） | timer enabled |
| `stock-tail-daily` | failed | static | 2026-11-08 21:11:10 CST | timer enabled |
| `dce-browser-capture` | failed | static | 2026-11-08 19:35:37 CST | timer enabled |
| `dce-option-daily` | failed | static | 2026-11-08 20:06:53 CST | timer enabled |
| `option-history` | inactive | **disabled** | — | 已被 task 1082 取代 |
| `dce-option-recovery` | inactive | static | — | 一次性任务，无 timer |
| `full-history-recovery` | failed | static | **2026-11-09 13:11:06 CST**（05:11Z） | 目标全在盘上（missing 0），失败原因正是 §2.2/PR #333 修的债券 SQL |
| `frontend` | active | enabled | 2026-11-05 08:47:32 CST | 不在 AC01 缺脚本类内 |

**两条结论**：

1. 停用四个 shard **只消除了那 4 个崩溃循环**，没有改变另外 5 个 timer 继续失败的事实；这 5 个还在 fire。
2. `full-history-recovery` 在测量前 49 秒（05:11:06Z）刚失败过一次——它的两个目标都在盘上且在 dev 里，
   所以它不是「缺脚本」类；它的失败正是 **PR #333 修的债券 SQL**。但**部署树仍是 `ce97f53f5`，不含 #333**，
   因此修法在部署之前不会生效，timer（每 2 分钟）会继续失败。**部署是服务状态变更，本轮未做。**


### 2.5 那 9 个幽灵注册的去向：7 个承载着已停用的 50 个任务，2 个没有任务

普查给出的 9 个 `ghost_script_ids`，逐个查它们的任务与执行：

| 幽灵注册 | 挂着的任务 | 状态 |
|---|---|---|
| `cffex_option_daily_history` / `commodity_option_daily_history` / `etf_option_daily_history` / `etf_realtime_quote_sina` | 各 1 个 | 全部 `is_active=0` |
| `forex_hist_sina` | **16** 个 | 全部 `is_active=0` |
| `fund_monetary_income_history` | **26** 个 | 全部 `is_active=0` |
| `fund_reviewed_unit_nav_history` | 4 个 | 全部 `is_active=0` |
| `release_policy` / `yield_release_policy` | **无任务** | 纯死注册行 |

合计 7 个注册承载 **50 个任务**，与「按属主批准停用的那 50 个幽灵任务」逐一对应；另 2 个注册没有任何任务。
**没有任何在用任务挂在幽灵注册上（active = 0）**，最后执行时刻停在 2026-11-07 01:42/01:43 一线，
与「停用后不再新增」一致。

**因此 AC01 的注册侧残差不再是「9 个未解释项」**，而是可解释的两类：7 个由已停用任务承载 + 2 个无任务。
仍未闭合的是**运行侧的 7 个幽灵脚本**（`systemd` 指向、任何 ref 都没有），见 §2.2/§2.3。

## 3. AC11：运行时与处置台账的两把尺子

- 运行时证据（同一仪器、同一 `--since 2026-11-05T14:00:00+00:00`）：**443/1048** @ `2026-11-09T03:01:29Z`；
  `completed_and_grew 443 + completed_no_delta 148 + failed_only 29 + not_run 428`。
- 处置台账（`assign_script_dispositions.py --limit 0`，两个 export 都给了）：
  1057 行、**assigned 0**、提议 `EXTEND_PROVIDER 954 / HELPER_ONLY 8 / REUSE_PROVIDER 6 /
  UNDECIDED_INSUFFICIENT_EVIDENCE 89`；库存 sha 一致 1057/1057；对账问题 0；有行无文件 9。
- **89 个在给了 `source-verification-export` 之后仍是 89** —— 说明该出口还没覆盖它们，再审一遍不会降。
- 6 行 `REUSE_PROVIDER` 的签字包 `/home/yun/afi204-evidence/2026-11-07-ac11-review/review-file.reuse-6.unsigned.json`
  经本人逐个复核：**6/6 的 `file_sha256` 与当前文件仍匹配**，只有 `reviewer`/`reviewed_at_utc` 为空。
  **未填这两个字段。**

### 3.1 89 个 UNDECIDED 到底缺什么：**不是「再审一遍」，是 68 个没有调用记录**

我一开始的假设是「89 个可能共享同一根缺失轴，修一次元数据就能解一批」。实测把这个假设否掉了。

89 行的 `missing_axes` 确实高度集中：`source_function` 66、`source_function;target_table` 6、
`single_source_function` 17 —— 表面看是「都缺 source_function」。但把每行路径接回 catalog 的
`files[].calls` 之后：

| 能不能从 catalog 解出 source function | 行数 |
|---|---|
| **没有 akshare 调用记录**（`calls` 里没有 `source_root=akshare` 的条目） | **68** |
| 有多个 akshare 调用（需要一条消歧规则） | 14 |
| 恰好一个 akshare 调用 | 7 |

而且那 7 个「恰好一个」也不能直接采信：样本 `funds/hourly/option_minute_em.py` 解出来的是
`request_with_retry`——一个传输辅助函数，不是源端点。

**结论**：89 个里 **76%（68/89）在 catalog 里根本没有可用的调用记录**，所以不存在「一次元数据修复解一批」；
它们要么需要逐行补证据，要么需要改进 `calls` 的抽取器（当前对动态分发/间接调用不可见）。
这也解释了为什么给了 `source-verification-export` 之后仍是 89：**缺的是记录，不是复核意愿**。

### 3.2 AC11 `failed_only` 29 行的处置分类（2026-11-09T05:19Z）

从 AC11 报告取出 `outcome=failed_only` 的 29 个任务，逐个读它们最近一次执行的状态与错误：

| 签名族 | 任务数 | 代表 | 判定 |
|---|---|---|---|
| `FuturesDailyMarket.run() got an unexpected keyword argument '_ingest_mode'` | **5**（514 / 1051 / 1052 / 1101 / 1102，全部 `daily_market_data`） | 与普查里 `unexpected_param:_ingest_mode` 的 7 行同源 | **参数注入与签名不匹配**；可修，但**必须先确认 `_ingest_mode` 是不是类型平面故意注入的**，不能盲目剥掉 |
| `… unexpected keyword argument 'source'` / `'end_date'` | 2 | `etf_fund_hist_em`（33 跑 / 19 败）、`stock_zh_index_daily`（31 跑 / 22 败） | 同类签名漂移；这两个失败量大、持续时间长 |
| `'…' object has no attribute 'require_cursor' / 'require_connection'` | 2 | `FuturesDeliveryMatchDce`、`FuturesContractInfoShfe` | provider 类缺方法，属代码缺陷 |
| `returned no data and target table … is empty` | 20 | `spot_quotations_sge`（39 跑 / 39 败）、`futures_to_spot_dce`（39 跑 / 38 败）等 | 先判「真无数据（停更/退市）vs 抓取坏」，**不能直接当迁移对象** |

合计 29 个任务、24 个不同签名。三点值得注意：

1. `_ingest_mode` 一族 5 个任务与普查的 7 行完全对得上——**一次签名修复可能清掉 5 个任务**，但前提是搞清
   这个参数是注入侧多余还是脚本侧缺失，所以本轮只登记、不改。
2. `returned no data` 占 20/29；其中两个任务跑了 39 次只成功 1 次，属长期空源，不是「今天坏了」。
3. 这 29 个任务在 AC11 的处置台账里都还没有 `assigned`；它们是 **B4/B6 的输入**（先修/先判定，再谈迁移）。


**具体到 `daily_market_data` 这一族**（任务 514 / 1051 / 1101 逐条读参数得到）：

- 任务 `parameters` JSON 里带 `_ingest_mode: "live"`、`overlap_days: 7`、`trading_days_by_market: {...}`；
- 脚本 `app/data_fetch/scripts/futures/weekly/daily_market_data.py:324` 的签名是
  `run(self, markets=None, lookback_days=None, max_windows=None, _call_timeout=None)`
  —— **这三个键一个都不接受**，而调度器按任务参数展开调用，于是 `TypeError`；
- 三个可选修法：**(a)** 让 `run()` 接受并忽略这三键；**(b)** 在分派边界按目标签名过滤未知键
  （全局生效，但会静默吞掉拼错的参数，风险更大）；**(c)** 清理这 7 个任务的 `parameters`（数据变更，可回滚）。

**本轮不实施**：让 5 个休眠任务开始写数据是行为变更，且 (a)/(b) 的取舍会影响全部 1048 个任务，需属主定。

## 4. AC14：33/48，无断点

`evidence/2026-11-08-wave32/ac14_hourly_chain.py`，读数 `2026-11-09T05:02Z`：
task 1049（cron `3 * * * *`）自部署锚 `2026-11-07T19:26:47Z` 起 33 条执行，
11-07 20Z … 11-09 04Z 每小时一个 `completed`，连续 **33** 槽、0 失败 0 缺行。
05Z 的「非完成」只是该小时还没到点（cron 在 :03 触发）。
**目标 48**：还差 15 个自然小时，第 48 槽约 `2026-11-09T19:05Z`。**不预告、不提前判定。**


### 4.1 另外三个自然周期目标：不是没达标，是窗口还不够长

锚仍是 #316 部署瞬间 `2026-11-07T19:26:47Z`；测量时刻 `2026-11-09T05:24Z` —— **只过了 1.4 天**。
按每个任务自己的 cron 逐个到期日数「当天是否有 completed 执行」：

| cadence | 代表任务 | 到期槽（锚之后） | 连续 completed | 目标 | 判定 |
|---|---|---|---|---|---|
| hourly | 1049 `3 * * * *` | 33 | **33** | 48 | 窗口最大 33，**33/33 无断点** |
| daily | 1048 `10 8 * * *` | 2 | **2** | 7 | 窗口最大 2，**2/2** |
| weekly | 2 `38 8 * * mon` | 1（11-09 周一） | **1** | 2 | 窗口最大 1，**1/1** |
| sub-daily | — | — | — | 1 | 本轮方法没有识别出 `*/n` 形式的 sub-daily cron，**未测**（不写 0） |

**结论**：四个目标**全部处于「窗口不足」状态，而不是失败**——每条链都等于锚之后窗口允许的最大值，且
没有任何断点。7 天目标需要 7 天、2 周目标需要 2 周，都没到期。因此本轮**既不判通过也不判失败**；
到点（hourly 约 `19:05Z` 今天，daily 11-14 前后，weekly 11-23 前后）再用同一仪器重测。

## 5. 测量环境：本机终于能复现 CI 的采集平面读数

```
cd src/backend
PATH=/tmp/it204/venv-ci/bin:$PATH MYPY_CACHE_DIR=/tmp/it204/mypy-cache-fresh-1109 \
  python ../../scripts/ci/mypy_ratchet.py --scope collection --advisory
mypy_ratchet[collection]: errors=2 baseline=2 delta=+0 checked=1108
```

镜像 venv 的 mypy 是 **1.20.2**（与基线钉的版本一致），cache-dir 指向空目录。读数与 CI 冻结基线
（dev 作业 `128569391629`）逐字相同。这消解了表里两条「测量危害」行的可执行部分：
本机不再只能引用 CI 那一行，而是能用同一条命令复现它。**仍未证明**的是「带旧 cache 会少报」的
具体触发路径（那需要构造一个跨树污染的 cache），故该行只登记到「已给出可复现的正确姿势」。

### 5.1 row 276（ruff 版本分裂）的实测：当前树上两版互认

分歧为真：CI 硬装 `ruff==0.16.2`（`ci.yml:397`），而 `config/requirements-dev.lock:431` 钉 `ruff==0.15.13`。

在 lint 作业的作用域 `src/backend` 上分别跑：

| 版本 | `format --check` | `check` |
|---|---|---|
| 0.16.2 | 2663 files already formatted | All checks passed |
| 0.15.13 | 2648 files already formatted | All checks passed |

再做双向交叉验证（把 `app/` 与仓库的 `pyproject.toml` 一起复制到 /tmp，1872 个 `.py`）：

- 用 **0.15.13 格式化**后让 **0.16.2 检查** → `1873 files already formatted`（0 处要改）；
- 用 **0.16.2 格式化**后让 **0.15.13 检查** → `1872 files already formatted`（0 处要改）；
- 两版 `ruff check` 都 `All checks passed`。

**结论**：row 276 那句「两个版本的 `ruff format` 输出不同，因此本地按 lock 格式化干净 → CI 红」
**在当前树上不成立**——两个方向的格式互认，没有任何一处会被另一版改掉。所以处置可以是纯版本对齐
（lock 与 CI 钉同一版），不需要一次全树格式化迁移。**但这只是「今天这棵树」的实测**：
一旦出现某个新版独有的构造，互认未必继续成立，所以对齐仍然值得做。

（探针本身也踩过一次坑并已修正：第一版副本没带 `pyproject.toml`，两版都退回默认配置，
`format` 一下改了 836/1868 个文件——那个数字无效，不能拿来当结论。）

### 5.2 同一件事我连错两次：债券表其实存在，但本机无法完成端到端验证

这一节替换我先前的两个草稿，两个都错，错的根源相同：**探针的前提（连哪个 DSN）没有先验证就下结论**。

1. 草稿一：「修复后的生产路径在真实库上不再抛错」。我连的是**应用 DSN**（`ai_for_investor`），
   表不在那个 schema 里，方法走了退化路径（返回 0 行、无异常），`DATE_FORMAT` 那句 SQL **根本没发出**。
   所以这条「验证」无效。
2. 草稿二：「第二个阻断是表不存在」。同样错。`information_schema` 全库检索显示：
   `BOND_ZH_HS_COV_DAILY` 在 **`akshare_data`** 里（`TABLE_ROWS≈773,949`），
   `BOND_ZH_HS_COV_SPOT` 也在（`≈2,873`）；而控制器解析出的 `DB_CONFIG['database'] = 'akshare_data'`
   （经解析配置确认，未打印任何凭据）。**表和库都是对的。**

**最终可核实的陈述**：

- `%` 插值缺陷是真的、已修（#333），并有 38 个测试钉住契约；
- 采集脚本 `bonds/daily/bond_zh_hs_cov_daily.py` 建的就是 `BOND_ZH_HS_COV_DAILY`，
  任务 33（`10 18 * * mon-fri`，armed）历史 15 次执行里 8 次 completed / 7 次 failed，最近成功 2026-11-06 10:10；
- **本机无法完成端到端只读验证**：`DB_CONFIG` 的 `root` 用户经 TCP 被拒
  （`(1698, "Access denied for user 'root'@'localhost'")`），我没有 `akshare_data` 的可用凭据。
  所以「部署后债券腿会转绿」仍是**未验证**。

**判定标准不变**：该 unit 是否修好，只能由**一次成功运行**判定，不能由某个错误消失判定。
另外记一条方法教训：跨 schema 的验证必须先打印 `DATABASE()` 再下结论，否则会把「连错库」写成「表不存在」。



### 5.3 采集平面最后 2 条：加一个 stub 依赖就归零（实测）

镜像 venv（mypy 1.20.2，与 CI 一致）里**临时**安装 `types-python-dateutil` 后，同一条命令读出：

```
mypy_ratchet[collection]: errors=0 baseline=2 delta=-2 checked=1108
mypy_ratchet[collection]: errors dropped by 2. Ratchet down by running `--update` …
```

把它卸掉后立刻回到 `errors=2 baseline=2 delta=+0 checked=1108`。**一装一卸只差这一个包**，
所以「采集平面 2 → 0」的全部剩余成本是：

1. 把 `types-python-dateutil` 加进 `config/requirements-dev.lock`（并确保 CI 的 lint 作业装上它）；
2. 跑一次 `mypy_ratchet.py --scope collection --update` 把基线降到 0；
3. 重新冻结基线文件（现在那份是 `errors=2 checked=1108`）。

**本轮不改 lock**：新增依赖是属主决定（依赖面），且它会改变 CI 的安装集合。这里只给出实测影响。
另请注意：这 2 条是 `dateutil.relativedelta` 的 `import-untyped`，属于**缺 stub**，不是类型错误本身；
所以「类型平面归零」不等于「采集脚本都过了类型检查」，两者不能混为一谈。

## 6. 迁移计划（#335）：B0.0 的答案

- 974 个端点只有 **10** 个带 `target_models`；964 个未绑定，全部 `runtime_verification: NOT_RUN`。
- 319 个 provider model 里**只有 10 个是 akshare**（fmp 69 / fred 40 / sec 24 / …）——
  **这个库是为别的数据商建的**，不是为 AFI 的 akshare 资产建的。
- 用 `files[].calls` 反查 + 处置台账 `asset_family`：**661** 个端点可挂到 8 个已有 akshare 家族
  （stock 368 / index 77 / fund 74 / futures 56 / option 46 / bond 40），**299** 个落在无 model 的族
  （other 278 / fx 18 / crypto 3），4 个多族，0 个无调用者。
- 可复跑仪器：`evidence/2026-11-09-migration-binding/provider_binding_candidates.py`
  （默认出汇总，`--include-rows` 出 964 行）。
- **D5（AC13 单写者）**已写成具体补丁：`script.py:1690` 现在用 `fencing_token=int(execution.id)`
  （每次执行的局部序号），应改为 claim 的单调令牌；接线是「一个调用点 + 一个开关」的 S 级改动，
  三个代码替属主决定不了的参数（开关默认值、29,126 条历史 claim、`period_key`/`parameter_hash` 口径）已点名。

## 7. 本轮明确不做

不重建/不改指向/不删除任何幽灵 unit（D7）；不填 AC11 的签字字段；不把本机读数当 CI 基线；
不因 AC13 的 19 个离线测试绿就宣称 AC13 闭合（生产接线仍缺）；不因目录里 `READY_FOR_ADAPTER: 1`
就说任何数据集已迁移。
