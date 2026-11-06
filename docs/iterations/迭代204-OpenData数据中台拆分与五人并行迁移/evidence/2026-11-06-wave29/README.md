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

共同约定：DSN 只从 `src/backend/.env` 的 `DATABASE_URL` 读取，不打印口令；除最后一个脚本外
全部只含 SELECT/SHOW；`ac11_retire_queue_a.py` 在写前落 before-image，且 cohort 完全由
`scripts/task_param_audit.py`（#284）的普查 JSON 决定——普查不可用时它拒绝运行。

注意：`ac14_accrual.py` 的窗口边界是 Asia/Shanghai 墙上时间（调度器按该时区解释 cron，
见记录第 5 节）。用 UTC 边界会得到不同的数字——这正是本波先算错、后更正的那一处。
