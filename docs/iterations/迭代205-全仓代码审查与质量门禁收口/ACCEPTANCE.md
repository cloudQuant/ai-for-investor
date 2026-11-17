# 迭代205 验收计划

> 验收原则：**命令 + 退出码 + 输出摘要 + 证据路径** 四件套；没有证据的“已优化”不计入。  
> 环境：以 CI 规范环境（Python 3.11/3.12、`config/requirements-dev.lock`、Node 24）为准；本机结果只用于预检。  
> 状态：`PLANNED`。本文件定义“完成后怎么验”，不代表当前已通过。

## 1. 全局门槛（必须全绿）

| ID | 门槛 | 命令 | 期望 |
|---|---|---|---|
| G01 | 后端 lint | `cd src/backend && ruff check . && ruff format --check .` | exit 0 |
| G02 | 后端类型（棘轮） | `cd src/backend && python ../../scripts/ci/mypy_ratchet.py` | exit 0，错误数 ≤ baseline |
| G03 | 后端收集 | `cd src/backend && python -m pytest --collect-only -q` | **0 errors** |
| G04 | 后端全量 | `cd src/backend && python -m pytest -q -n auto -m "not performance"` | **0 failed / 0 errors** |
| G05 | 后端 e2e | `cd src/backend && python -m pytest -q -m e2e` | ≥4 passed，且不是 skip |
| G06 | 前端类型 | `cd src/frontend && npm run typecheck` | exit 0 |
| G07 | 前端 lint | `cd src/frontend && npm run lint` | exit 0 |
| G08 | 前端单测 | `cd src/frontend && npm run test -- --run` | 0 failed |
| G09 | 前端构建 | `cd src/frontend && npm run build` | exit 0 |
| G10 | 迁移链 | `cd src/backend && python ../../scripts/ci/check_alembic_heads.py` | 单 head，连续 |
| G11 | ORM/迁移漂移 | `cd src/backend && python ../../scripts/ci/check_orm_schema_drift.py` | `OK: schema aligned` |
| G12 | 大文件棘轮 | `python scripts/ci/large_file_ratchet.py` | exit 0 |
| G13 | 依赖审计 | `pip-audit -r config/requirements-prod.lock` + `npm audit --omit=dev --audit-level=high` | 0 high/critical，例外在 allowlist |
| G14 | 秘密扫描 | 按仓库现有 gitleaks 命令 | exit 0 |
| G15 | 门禁自检 | 隐藏 `ruff` 后运行 `bash scripts/dev/check_all.sh` | **必须非零**（证明 fail-closed） |

## 2. WP01 数据写入真实性

### 2.1 回归

```bash
cd src/backend
python -m pytest tests/test_akshare_provider.py tests/test_akshare_script_service.py -q
python -m pytest tests/test_akshare_script_service.py -q -k "rowcount or duplicate or empty"
```

必须新增/通过以下断言：

1. `offered=1030, affected=0` → `save_data` 返回 0；日志包含 offered/affected。
2. `offered=100, affected=37` → 返回 37；回执 `affected_rows=37`。
3. `offered=100, affected=0` 且未声明 NOOP → `_raise_if_empty_completion` 抛错。
4. 显式 `IDEMPOTENT_NOOP` → 任务成功但状态标记 `NOOP`，不写 committed_write 正数。

### 2.2 真实 MySQL 复跑

对 5 个尾部缺口标的（以当前故障清单为准）：

```sql
SELECT COUNT(*) FROM <target_table> WHERE <identity>;
```

| 标的 | 任务 | 回执 offered | 回执 affected | DB 实际行数 | 结论 |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | PASS/FAIL |

要求：`回执 affected == DB 实际新增/更新行数`；若为 0，任务不得标 COMPLETED（除非显式 NOOP）。

### 2.3 证据

- 测试输出（含新增用例名）。
- 任务 execution id、日志片段、SQL 查询结果。
- 代码 diff（`_execute_batch` / `save_data` / `script_worker` / `script.py`）。

## 3. WP02 迁移可复现

### 3.1 空库升级矩阵

```bash
cd src/backend
for db in /tmp/afi-205-{sqlite-340,sqlite-345,sqlite-353}.db; do
  rm -f "$db"
  DATABASE_URL="sqlite+aiosqlite:///$db" python -m alembic upgrade head
  echo "$db rc=$?"
done
```

MySQL/PostgreSQL 使用 CI service：

```bash
DATABASE_URL="mysql+aiomysql://user:pass@127.0.0.1:3306/afi" python -m alembic upgrade head
DATABASE_URL="postgresql+asyncpg://user:pass@127.0.0.1:5432/afi" python -m alembic upgrade head
```

| 方言/版本 | 空库 -> head | 上一 revision -> head | 降级 -> 再升级 | 结论 |
|---|---|---|---|---|
| SQLite 3.40 | | | | |
| SQLite 3.45 | | | | |
| SQLite 3.53 | | | | |
| MySQL 8.0 | | | | |
| MySQL 9.4 | | | | |
| PostgreSQL 16 | | | | |

### 3.2 迁移测试

```bash
cd src/backend
python -m pytest \
  tests/test_ai_research_approval_migration.py \
  tests/market_data_platform/test_research_binding_migrations.py \
  tests/market_data_platform/test_multi_record_migration.py \
  tests/market_data_platform/test_multi_record_evidence_migration.py \
  tests/asset_research/test_migration.py -q
```

期望：0 failed。当前基线（本机，E1）为 27+9+7+4+7 = **54 个失败/错误**，必须清零。

### 3.3 负向断言

- 插入违反 CHECK 的行必须被拒绝（不是“迁移有列就算过”）。
- 半途库（已有部分列/约束）升级必须成功或给出可执行的修复命令，不能裸抛 `SCHEMA_CONFLICT`。
- 运行时 `DB_AUTO_CREATE_SCHEMA=false` 启动不得执行 DDL；用日志/SQL 审计证明。

## 4. WP03 测试基线与 e2e

### 4.1 环境

```bash
cd src/backend
python -m pytest --collect-only -q
# 期望最后一行：9727+ tests collected, 0 errors（数量以实际为准）

APP_ENV=test python -m pytest -q -m "not performance"
# 期望：0 failed / 0 errors
```

### 4.2 e2e

```bash
APP_ENV=test python -m pytest -q -m e2e
python -m pytest --collect-only -q -m e2e | tail -1
```

要求：

- 至少 4 条真实后端 e2e：`auth_refresh`、`workspace_switch`、`data_fetch_receipt`、`paper_order_lifecycle`。
- 每条 e2e 使用临时 DB 和 fake provider；不得依赖真实券商/行情/网络。
- workflow 中 `pytest -m e2e` 步骤存在，且日志显示实际执行数 > 0。

### 4.3 skip 预算

| 类别 | 当前 | 目标 |
|---|---:|---:|
| `pytest.mark.skip/xfail` | 113 | ≤ 80，且每项有原因 |
| 无原因 skip | 0 | 0 |
| `e2e` marker 命中 | 0 | ≥ 4 |

## 5. WP04 门禁与供应链

### 5.1 fail-closed 负向测试

```bash
# 1) 隐藏 ruff：必须失败
tmp=$(mktemp -d); mkdir -p "$tmp/bin"; cp "$(command -v python3)" "$tmp/bin/" 2>/dev/null || true
PATH="$tmp/bin:/usr/bin:/bin" bash scripts/dev/check_all.sh
test $? -ne 0

# 2) 审计负向：构造一个已知高危版本（在临时 venv，不污染仓库）
python -m venv /tmp/afi-audit && /tmp/afi-audit/bin/pip install 'urllib3==1.26.0'
/tmp/afi-audit/bin/pip install pip-audit
/tmp/afi-audit/bin/pip-audit --path /tmp/afi-audit/lib/python*/site-packages
test $? -ne 0
```

### 5.2 锁文件

```bash
grep -c -- '--hash' config/requirements-prod.lock   # > 0
pip install --require-hashes -r config/requirements-prod.lock --dry-run
```

### 5.3 门禁证据

- `check_all.sh` 的 exit code 截图/日志。
- 夜间审计 job 的 exit code。
- allowlist 文件（含负责人、到期日、理由）。

## 6. WP05 性能与容量

### 6.1 连接池

```bash
# 压测脚本（WP05 新增）
python scripts/perf/load_test_api.py --endpoint /api/v1/portfolio --concurrency 50 --duration 60
```

验收：

- 无 `Future attached to a different loop`、无 `QueuePool limit` 错误。
- `pool.checkedout()` 稳定，连接数 ≤ `pool_size + max_overflow`。
- p95 延迟与改造前基线相比不劣化；目标见 IMPLEMENTATION_PLAN §7.2。

### 6.2 大响应

| 场景 | fixture | 目标 |
|---|---|---|
| 组合页 100 万 snapshot | 生成 fixture | p95 < 1s，响应 < 1MB |
| 回测 50 万点 | 生成 fixture | summary < 300ms；series ≤ 5000 点/页 |
| THS 300MB dump | 本地 fake 文件 | 在 `max_bytes` 处中止，内存峰值 < 1.5× 文件大小 |
| THS 采集期间 health | 并发 50 | p95 ≤ 基线 2 倍 |

### 6.3 事件循环

```bash
PYTHONASYNCIODEBUG=1 python -m pytest tests/test_ths_async.py -q
# 或 py-spy record --pid <api> --duration 30
```

验收：单次同步阻塞 < 50ms；THS 路径不在主 loop 执行同步 HTTP/解析。

## 7. WP06 安全

### 7.1 生产模式

```bash
cd src/backend
APP_ENV=production DEBUG=false \
  SECRET_KEY=your-secret-key-change-in-production \
  JWT_SECRET_KEY=your-jwt-secret-change-in-production \
  ADMIN_PASSWORD=admin123 \
  python -c "from app.config import Settings; Settings()"
test $? -ne 0   # 必须拒绝默认值
```

### 7.2 端口

```bash
docker compose -f docker/docker-compose.yml -f docker/compose/prod.yml config | grep -A3 'mysql:'
ss -lntp | grep 3306 || true   # 不应出现 0.0.0.0:3306
```

### 7.3 XML / exec

- 用带 DTD/ENTITY 的 RSS 样本测试：解析必须拒绝或安全降级，CPU/内存不爆炸。
- 策略 exec：证明 profile 目录/文件由 root 拥有、运行用户不可写；sha256 不匹配必须拒绝；运行日志记录 profile_ref 与 hash。

### 7.4 安全评审

- 默认密钥/默认管理员/端口/XML/exec 五项各有测试或评审记录。
- 无 `eval`/`exec` 新增面；存量 `exec` 在运行手册中标注信任边界。

## 8. WP07 可维护性

| 指标 | 当前 | 目标 |
|---|---:|---:|
| `useDataPage.ts` | 4853 | ≤ 3000 |
| `StrategyPage.vue` | 3254 | ≤ 2000 |
| `ai_strategy_research_service.py` | 5866 | 不增长，且至少拆出 1 个模块 |
| CC≥50 的函数 | 64 | ≤ 50 |
| 最高 CC | 147 | ≤ 80 |

验收命令：

```bash
python -m radon cc src/backend/app -j -s > /tmp/afi-radon.json
# WP07 新增 scripts/ci/check_complexity_budget.py 后改为：
# python scripts/ci/check_complexity_budget.py --input /tmp/afi-radon.json --max-cc 80 --max-count-50 50
cd src/frontend && npm run test -- --run
cd src/backend && python -m pytest -q -m "not performance"
```

（`check_complexity_budget.py` 为 WP07 新增；如不新增，用 `radon` 输出人工比对，但必须可重复。）

## 9. WP08 可观测性

| 指标 | 查询 | 期望 |
|---|---|---|
| `data_fetch_offered_rows` | Prometheus | 每次采集可见 |
| `data_fetch_affected_rows` | Prometheus | 与 DB 行数一致 |
| `data_fetch_noop_total` | Prometheus | 全重复批次可见 |
| `db_pool_checkedout` | Prometheus | 有上限告警 |
| `ths_collect_duration_seconds` | Prometheus | 分位数可见 |
| `error_code_total` | Prometheus | 按服务/操作聚合 |

验收：dashboard 截图 + 一次故障演练（模拟空写/连接耗尽/THS 超时）记录。

## 10. 证据目录与模板

建议在 `docs/iterations/迭代205-全仓代码审查与质量门禁收口/evidence/` 下按 WP 建目录：

```text
evidence/
  WP01/
    code-diff.patch
    pytest.txt
    mysql-counts.tsv
    execution-<id>.log
  WP02/
    sqlite-3.40.log
    sqlite-3.45.log
    mysql-8.0.log
    pg-16.log
    migration-tests.txt
  WP03/
    collect.txt
    full-suite.txt
    e2e.txt
  WP04/
    check-all-negative.txt
    pip-audit.json
    npm-audit.json
  WP05/
    load-test-before.txt
    load-test-after.txt
    py-spy.txt
  WP06/
    prod-secret-negative.txt
    ports.txt
    rss-xxe.txt
```

每条证据文件头部写：

```text
date:
commit:
command:
cwd:
exit_code:
environment (python/node/os/db):
summary:
```

## 11. NO-GO 条件

出现以下任一情况，迭代不得标记 PASS：

1. `pytest --collect-only` 仍有 error。
2. 全量后端测试仍有 failed/error，且未给出“与本迭代无关”的证据与隔离 issue。
3. 空库 `alembic upgrade head` 在任一受支持方言失败。
4. `save_data` 仍返回 offered 而不是 affected，或空写仍能绕过保护。
5. `check_all.sh` 缺工具仍 exit 0。
6. 高危依赖漏洞未阻断且无 allowlist。
7. `pytest -m e2e` 仍为 0 命中，或 e2e 只跑前端。
8. 生产模式下默认密钥/默认管理员仍能启动。
9. MySQL 3306 仍绑定 0.0.0.0。
10. 性能改造没有 before/after 数据，或引入跨 loop 错误。

## 12. 当前基线快照（验收对照用）

| 项 | 2026-11-17 本机结果 | 备注 |
|---|---|---|
| `pytest --collect-only` | 9727 collected / **5 errors** | 项目 venv；freezegun/hypothesis 缺失 + env |
| 全量 pytest | **76 failed / 2395 passed / 10 skipped / 28 errors / 514s** | 非规范 venv；迁移失败簇为主 |
| `alembic upgrade head`（SQLite 3.45.3） | **exit 1** | `APPROVAL_AUTHORITY_SCHEMA_CONFLICT` |
| `vue-tsc` | exit 0 | 通过 |
| ESLint | exit 0 | 通过 |
| Vitest | 183 files / **2190 passed** | 通过 |
| `npm audit --omit=dev` | **0 vulnerabilities** | 通过 |
| `pip-audit -r requirements-prod.lock` | **未能完成审计** | Python 3.13 下 backtrader fork 与 `numpy==1.26.4` 解析冲突；需在 CI 3.11/3.12 复验 |
| Ruff 0.16.2（后端） | exit 0 | 通过 |
| 大文件棘轮 | exit 0 | 通过但基线高 |
| 后端 `e2e` marker | **0** | 空绿风险 |
| `check_all.sh` 缺工具 | WARN + 继续 | 假绿风险 |

验收时用同一张表填写 after，并附证据路径。
