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
