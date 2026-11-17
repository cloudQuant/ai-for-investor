# 迭代205 验收结果（2026-11-18）

> 基线：`iter205/quality-closure`，实现提交 `c7cc445a0`。  
> 证据目录：[evidence](evidence/)。  
> 结论：**PARTIAL / ACCEPTED_LOCAL（P0 与主要 P1 已收口；全量套件仍非全绿，残项已列明）**。  
> 没有把“部分完成”写成 PASS；本文件取代 ACCEPTANCE.md 中的理想化全绿目标，作为本轮实际交付记录。

## 1. 已完成并验证

| 工作包 | 结果 | 证据 |
|---|---|---|
| WP01 数据写入真实性 | 完成 | `evidence` 未单列；运行 `pytest tests/test_data_fetch_write_receipts.py tests/test_akshare_script_worker_unit.py tests/test_akshare_killable_script_worker.py` = **65 passed**；新增 7 条 rowcount 回归 |
| WP02 迁移可复现 | 完成 | 全新 SQLite `alembic upgrade head` = exit 0；`tests/test_ai_research_approval_migration.py` 等 5 个迁移文件 = **182 passed**（`evidence/wp02-migration-tests.txt`） |
| WP03 测试收集 | 完成 | `pytest --collect-only -q` = **11134 collected / 0 errors** |
| WP04 门禁 fail-closed | 完成 | 隐藏 `ruff` 后 `scripts/dev/check_all.sh` = **EXIT 2**，错误为 `required tool 'ruff' is not in PATH`（`evidence/check-all-negative.txt`） |
| WP05 连接池与响应边界 | 完成（代码侧） | MySQL 改为按事件循环缓存 pooled engine（`pool_size=5/max_overflow=10/pool_recycle=1800/pool_pre_ping=True`）；portfolio snapshot 上限 20 万；backtest series 上限 5 万、trades 上限 1 万；`tests/test_iteration202_deployment_database.py` = 2 passed/1 skipped |
| WP06 安全默认失败关闭 | 完成（代码侧） | 新增 `APP_ENV`（development/test/production）与校验；生产模式以 `APP_ENV` 为准；`start_app.sh` 不再默认 `DEBUG=true`；prod compose 设 `APP_ENV=production` 并把 MySQL 改为 `expose`；RSS 拒绝 DTD/ENTITY 且限制 2MB；THS 下载/解析移入 `asyncio.to_thread` |
| 类型/格式 | 通过 | `mypy app --ignore-missing-imports` = **Success: no issues found in 761 source files**；`ruff check`（touched modules）= `All checks passed!` |
| 前端 | 通过 | `vue-tsc` exit 0；ESLint exit 0；Vitest 全量曾 **2188 passed / 2 timeouts**，两例隔离重跑 **34 passed**（`evidence/vitest-full.txt`） |

## 2. 全量套件实际结果

```text
96 failed, 10839 passed, 169 skipped, 26 errors in 1156.71s (0:19:16)
EXIT=1
```

证据：`evidence/full-suite-20261118.txt`。

### 2.1 已确认由本轮修复的失败

- `tests/test_config_validation.py`：本轮 `APP_ENV` 改造后先出现 5 failed；已把生产校验测试改为显式 `APP_ENV="production"`，重跑 = **25 passed / 2 skipped**。

### 2.2 已在干净基线 `70b7e3ed5` 复现的既有失败（非本轮引入）

在独立 worktree `/tmp/afi-base`（`70b7e3ed5`）上运行同一用例，结果相同：

- `tests/test_ai_research_v2_migration.py::test_evidence_command_graph_reentry_rejects_partial_command_unique_index[...]` — 失败（迁移 check/index 校验顺序，既有问题）。
- `tests/test_service_read_account_book_contract.py::test_sdk_financial_extension_is_frozen_but_not_promoted_to_account_total` — 失败（`bt_api_py.service_execution_account_books` 的 pinned SHA256 与当前安装 SDK 不一致）。
- `tests/test_portfolio_compositions_api.py::test_financial_projection_reaches_composition_http_response` — 失败（`no such table: users`，既有 fixture/DB 隔离问题）。

### 2.3 仍需后续迭代处理的主要簇

| 簇 | 数量 | 判定 |
|---|---:|---|
| `test_ai_research_v2_migration.py` | 16 | 既有迁移校验顺序问题；基线可复现 |
| `test_service_read_account_book_contract.py` | 13 | 既有 SDK pin 漂移；基线可复现 |
| `test_service_read_authorized_http_integration.py` | 9 | 重型 SDK/进程集成；需固定 SDK 与运行形态 |
| `test_opendata_temporal_identity.py` / `test_opendata_instrument_reference.py` | 13 errors | `base_url` fixture scope 与 open-data 配置；环境/测试配置问题 |
| 其他小簇（`test_ai_trading`、`test_portfolio_*`、`test_*_api` 等） | 其余 | 需逐项 triage；其中 `test_ai_trading::test_confirm_trade_success` 在基线单跑通过、在当前分支单跑失败，列入最高优先 triage |

## 3. 未完成项

| 项 | 状态 | 说明 |
|---|---|---|
| WP07 可维护性切片 | **未开始** | 大文件/复杂度切片未在本轮实施；`radon` 基线仍为 64 个 CC≥50、最高 147 |
| WP08 可观测性 | **未开始** | 空写/连接池/THS 指标与运行手册未实施 |
| 后端 e2e | **未完成** | `@pytest.mark.e2e` 仍为 0；未新增 4 条 e2e |
| 全量套件全绿（G04） | **未达成** | 96 failed / 26 errors；既有失败为主，但 `test_ai_trading` 一例需确认是否为本轮回归 |
| 生产锁 hash / 依赖审计阻断 | **部分** | nightly 已去掉 `\|\| true`；prod lock 仍未生成 hash；Python 3.13 下 `pip-audit -r` 仍因 backtrader/numpy 解析冲突无法执行，需 CI 3.11/3.12 |

## 4. 结论与放行建议

- **P0 已关闭**：数据写入回执不再用 offered 冒充 affected；全新 SQLite 迁移可复现。
- **主要 P1 已关闭**：测试收集 0 error、门禁 fail-closed、连接池/THS/响应边界、生产模式与默认凭据/端口/RSS 加固。
- **不能宣布全量 PASS**：全量套件仍有 96 failed/26 errors，且 WP07/WP08 与后端 e2e 未完成。
- 建议状态：**ACCEPTED_LOCAL for P0/P1 scope；iteration overall PARTIAL**。后续 206 应优先：
  1. `test_ai_trading` 回归 triage（唯一疑似本轮引入的失败）；
  2. 既有迁移 check/index 顺序修复；
  3. SDK pin/集成测试固定；
  4. WP07/WP08 与后端 e2e。
