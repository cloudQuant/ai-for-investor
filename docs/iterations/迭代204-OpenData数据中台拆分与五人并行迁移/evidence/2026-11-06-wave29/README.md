# Wave 29 取证脚本（2026-11-06）

这些脚本是本目录 `RUNTIME_READOUT_20261106.md` 里每个数字的产生方式；没有它们，那份记录就只是引用，
不能复跑。运行方式（均在 `src/backend` 下，用仓库 venv）：

| 脚本 | 产出 | 读写 |
|---|---|---|
| `runtime_ac14.py` | 窗口内 completed/failed、按频结果、入口点失败归因 | 只读 SELECT |
| `ac14_accrual.py` | cron 逐字段展开的应跑槽位、AC14 四档达标深度、CSV `legacy_frequency` 与 cron 形状交叉表 | 只读 SELECT |
| `ac11_evidence_split.py <census.json>` | #284 静态普查 × 修复后运行态证据的 AC11 分子（143/1098） | 只读 SELECT |
| `ac11_batches.py <census.json> [out.md]` | AC11 队列 A/B/C 的确切任务清单 | 只读 SELECT |
| `ghost_classify.py` | 9 条无文件注册的来源判定（树中、git 历史中、按文件名） | 只读 SELECT + git |
| `ac11_retire_queue_a.py` | 队列 A 的停用执行（**默认 dry-run**，`--apply` 才写） | 2026-11-06 13:47:56 UTC 由属主裁定后执行过一次 |
| `runtime_recovery_readout.py` | §19 的九天故障窗口、恢复后 completed/failed 分布、失败分类与 #284 普查交叉、幽灵停用后的可判性、armed 未执行数 | 只读 SELECT（`SET SESSION TRANSACTION READ ONLY` + rollback） |
| `runtime_recovery_readout.2026-11-06T1535Z.json` | 上一条在 15:35:22Z 的实际输出，逐字存档 | — |
| `inventory_anchor_provenance.py` | 把 1066 行锚分成 match / drifted / never_versioned / missing_file 四桶，并对 drifted 命中具体 commit | 只读（git log / git show + 读文件） |
| `inventory_anchor_provenance.2026-11-06T1545Z.json` | 上一条输出：**166 / 847 / 44 / 9**，drifted 命中 commit 的分布，44 行清单 | — |
| `scheduler_clock_duality.py` | §5：`last_execution_at` 与最新 `created_at` 的偏移分桶 + 单小时 cron 的墙钟命中率 | 只读 SELECT |
| `scheduler_clock_duality.2026-11-06T1614Z.json` | 上一条 16:14:50Z 读数：shifted 214 / agrees 821 / older 13；964 个单小时 cron 中 next 964、last 135 | — |
| `ci_duplicate_run_audit.py` | §24：每仓同一 sha 同时有 push 与 pull_request run 的数量（OD 56/476、AFI 0/229） | 只读 API |
| `ci_duplicate_run_audit.2026-11-06T1615Z.txt` | 上一条逐行输出 | — |
| `ac11_assign_gate_proof.py` | §23：AC11 签字门三种状态（空名拒 / 单文件 sha 拒 / 具名接受） | 只跑 `--work-dir`，不写仓库 |
| `source_egress_probe.py` | §25：出口对照 + akshare/AFI 两侧 endata 实测 + 逐主机可达性 | 只读网络探测与树内 client 调用，不写库 |
| `source_egress_probe.2026-11-06T1622Z.json` | 上一条输出：akshare 5 函数×4 日期全 0 行、AFI client 活、push2 两主机 3/3 不可达 | — |
| `record_provenance_audit.py` | 台账自检：每个有小数的段落是否都指向仪器/CI 作业/sha/file:line | 只读本文与 evidence 目录 |
| `verify_adapter_backed_functions.py` | §27：只打"被 OD fetcher 引用的 8 个上游函数"，非空才生成验证记录 | 只读外呼，不写库 |
| `adapter_backed_verification.2026-11-06T1629Z.json` | 上一条观测：6 个非空行数、2 个失败及其主机归因 | — |
| `source_verification_export.2026-11-06T1629Z.json` | 喂给 `--source-verification-export` 的记录（仅 6 条非空） | — |
| `unit_execstart_existence.py` | §28：unit/timer 实况 + ExecStart 目标在磁盘与 git 索引双侧存在性 | 只读 systemctl / git ls-files |
| `unit_execstart_existence.2026-11-06T1635Z.json` | 上一条输出：8 单元目标缺失、8 个都不在索引、5 个仍挂活定时器、max NRestarts 4738 | — |

共同约定：DSN 只从 `src/backend/.env` 的 `DATABASE_URL` 读取，不打印口令；除最后一个脚本外
全部只含 SELECT/SHOW；`ac11_retire_queue_a.py` 在写前落 before-image，且 cohort 完全由
`scripts/task_param_audit.py`（#284）的普查 JSON 决定——普查不可用时它拒绝运行。

注意：`ac14_accrual.py` 的窗口边界是 Asia/Shanghai 墙上时间（调度器按该时区解释 cron，
见记录第 5 节）。用 UTC 边界会得到不同的数字——这正是本波先算错、后更正的那一处。
