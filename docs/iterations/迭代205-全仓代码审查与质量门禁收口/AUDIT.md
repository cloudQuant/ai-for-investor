# 迭代205 审查证据与逐项分析

> 基线：`fix/combined-collection-plane` @ `70b7e3ed5`（2026-11-17）。  
> 口径：E1 本机已执行；E2 静态确认；E3 待 MySQL/PostgreSQL/生产形态复验。  
> 行号以当前工作树为准；如果后续改动导致漂移，以函数名和调用链为锚点重新定位。

## 0. 环境与边界

| 项 | 值 |
|---|---|
| OS | Linux（本机） |
| Python（项目 `.venv`） | 3.13.5；SQLite **3.45.3** |
| Python（`python` on PATH） | 3.13.5（Anaconda）；SQLite 3.45.3 |
| 后端本地 venv | `src/backend/.venv`；存在，但与 `config/requirements-dev.lock` 漂移：缺 `freezegun`、`hypothesis`、`ruff`、`mypy` |
| CI 锁定工具 | `ruff==0.16.2`、`mypy==1.20.2`、Python 3.11/3.12 |
| 前端 | Node 24.17.0、npm 11.13.0；`vue-tsc`/ESLint/Vitest 均使用仓库 `node_modules` |
| 未执行 | MySQL/PostgreSQL 实例、真实券商、生产部署、全量数据采集、LLM provider |

**边界说明**：后端全量测试是在 PATH 上的 Anaconda Python 3.13.5 中执行，项目 `.venv` 缺少 `freezegun/hypothesis`，因此那组“76 failed / 2395 passed / 28 errors”不是 CI 规范环境的最终结论，只用于暴露失败簇和复现路径。迁移失败已用项目 `.venv` 单独复现（见 D02），不是环境差异导致的假象。

## D01（P0）数据写入回执把“提交行数”当成“已写入行数”

**证据级别**：E1（代码与 git 历史）+ E2（调用链）。

**位置**：
- `src/backend/app/data_fetch/core/mysql_base.py:420-447`
- `src/backend/app/data_fetch/providers/akshare_provider.py:437-459`
- `src/backend/app/services/akshare/script_worker.py:82-92`
- `src/backend/app/services/akshare/script.py:443-468`
- `src/backend/app/services/akshare/write_fence.py:152-178`

**事实**：

```python
# core/mysql_base.py
values = [[...] for row in df.values.tolist()]
total_rows = len(values)
...
for i in range(0, total_rows, self.batch_size):
    batch = values[i : i + self.batch_size]
    self._execute_batch(insert_sql, batch)
    processed += len(batch)
...
return total_rows
```

`_execute_batch()` 只返回 `True/False`，没有把 `cursor.rowcount` 带回来；`akshare_provider.py:437-459` 是同一模式。`INSERT IGNORE` 命中重复时，MySQL 的 affected rows 可以是 0，但函数仍返回 `len(values)`。

子进程把它当成真实提交回执：

```python
# services/akshare/script_worker.py
written = save_data(*args, **kwargs)
if isinstance(written, int) and not isinstance(written, bool) and written > 0:
    record_committed_write(str(table_name or ""), written)
```

父进程的空结果保护又把它当成“确实写过”：

```python
# services/akshare/script.py
if int(rows_before or 0) > 0 or int(rows_after or 0) > 0:
    return
if int(committed_rows or 0) > 0:
    return
...
raise RuntimeError(f"Script {script_id} {detail} and target table {target} is empty")
```

**git 证据**：

- `6b916104b fix(data-fetch): report the rows the server persisted, not the rows offered`：把 `total_rows` 改成逐批累加 `cursor.rowcount`（capped at batch length），并返回 `affected`。
- `e57868f87 Revert "fix(data-fetch): report the rows the server persisted, not the rows offered"`：把该修复整体回退。
- `55e7fd8c5 chore(data-fetch): log the stock save payload's series identity`：只增加诊断日志，没有恢复 rowcount 语义。
- 提交说明直接记录了事故形态：`execution 34498 claimed 1030 rows for 001229 although none persisted`。

**触发链**：

1. 采集脚本返回一个非空 DataFrame，其中大部分/全部行与目标表唯一键重复。
2. `save_data(..., ignore_duplicates=True)` 执行 `INSERT IGNORE`，数据库实际写入 0 行。
3. `save_data` 返回 `total_rows > 0`，`recording_save_data` 记录 committed write。
4. `_raise_if_empty_completion` 看到 `committed_rows > 0`，不报错。
5. execution 被标记为完成，摘要/回执声称写入 N 行；数据库没有对应行。
6. 下游研究、回测、信号使用缺失数据，且告警不会触发。

**影响**：这是数据完整性问题，不只是日志问题。它会同时造成“空任务假成功”和“尾部缺口无法定位”；对量化平台，缺失行情与错误信号可能转化为错误交易依据。按用户口径属于 P0（数据损坏/错误交易依据）。

**修复方向**：

- `_execute_batch` 返回本批 `cursor.rowcount`（对 `executemany`，MySQL 返回受影响行数；对 `INSERT IGNORE` 为实际插入数）。
- `save_data` 累加 `affected`，返回值改为 affected；日志同时打印 `offered` 与 `affected`。
- 回执结构保留 `offered_rows` 与 `affected_rows`；`committed_row_count()` 只累计 affected。
- 当 `offered > 0 && affected == 0` 时：默认判失败；只有显式 `allow_idempotent_noop=True` 的脚本才允许成功，并记录 `IDEMPOTENT_NOOP`。
- 增加回归：全重复批返回 0；部分重复返回实际插入数；`INSERT IGNORE` + 唯一键；MySQL 与 SQLite 行为差异只作为参考，不替代 MySQL 集成测试。

**复验命令**：

```bash
cd src/backend
python -m pytest tests/test_akshare_provider.py tests/test_akshare_script_service.py -q
# 新增用例必须覆盖：offered=1030, affected=0 -> 失败/标记 NOOP，而不是 COMPLETED
```

## D02（P0）全新 SQLite 数据库迁移失败

**证据级别**：E1。

**位置**：
- `src/backend/alembic/versions/20260908_ai_research_approval_authority.py:1723-1737`

**事实**：

```python
def _ensure_checks(bind, table_name, checks):
    inspector = sa.inspect(bind)
    observed = {...}
    for name, expected in checks.items():
        if name in observed:
            if not _sql_matches(observed[name], expected):
                raise RuntimeError("APPROVAL_AUTHORITY_SCHEMA_CONFLICT")
        elif bind.dialect.name == "sqlite":
            raise RuntimeError("APPROVAL_AUTHORITY_SCHEMA_CONFLICT")
        else:
            op.create_check_constraint(name, table_name, expected)
```

`_upgrade_online()` 先通过 `_upgrade_existing_table` 增列/建约束，随后再次调用 `_ensure_checks()`。在 SQLite 3.45.3 上，SQLAlchemy 反射到的 check 名称与迁移期望的名称不一致（或缺失），于是直接抛错；SQLite 分支不允许“补建”，只能冲突。

**复现（项目 `.venv`）**：

```bash
cd src/backend
rm -f /tmp/afi-mig.db
DATABASE_URL=sqlite+aiosqlite:////tmp/afi-mig.db \
  .venv/bin/python -m alembic upgrade head
# exit 1
# ... 20260908_ai_research_approval_authority.py:1735: RuntimeError: APPROVAL_AUTHORITY_SCHEMA_CONFLICT
```

**测试失败簇**（E1，项目 `.venv` 单测 + 本机全量）：

- `tests/test_ai_research_approval_migration.py::test_approval_authority_sqlite_schema_matches_models` 单独运行 2.65s 失败，traceback 指向同一行。
- 全量运行中该文件 **27 failed**。
- `tests/market_data_platform/test_research_binding_migrations.py` **9 failed**；`test_multi_record_migration.py` **7 failed**；`tests/asset_research/test_migration.py` **7 failed**；`test_multi_record_evidence_migration.py` **4 failed**。

**影响**：

- 新建 SQLite 数据库（开发、测试、部分小规模部署）无法升级到 head。
- CI 的 `check-migrations` 执行 `alembic upgrade head`，`check_orm_schema_drift.py` 也会先升级空库；两者都可能被阻断。
- 迁移链不可复现会掩盖真正的 schema 漂移，后续迁移只能在已有库上“碰运气”。

**修复方向**：

- 不要在 SQLite 上对“刚由本迁移创建/重建的表”使用严格 `_ensure_checks`；应让建表时的命名约束成为唯一事实源。
- 若必须兼容半途数据库，读取 `sqlite_master.sql` 解析真实 CHECK 文本，而不是依赖 SQLAlchemy 反射名。
- SQLite 重建表时统一使用 `batch_alter_table(recreate="always")` 并显式命名 CHECK；重建后再次反射验证。
- 建立方言矩阵：SQLite 3.40/3.45/3.53、MySQL 8.0/9.4、PostgreSQL 16；每个矩阵都从空库升级到 head。
- 把 `tests/test_ai_research_approval_migration.py`、`test_research_binding_migrations.py`、`test_multi_record_migration.py`、`tests/asset_research/test_migration.py` 纳入阻断门禁。

**注意**：这不是“测试写得太严”。测试断言的是 schema 必须与 ORM 一致；迁移失败说明实际 schema 生成路径与声明不一致。修测试而不修迁移属于假绿。

## D03（P1）后端测试基线非 0 error、非全绿、非 hermetic

**证据级别**：E1（本机）。

**事实**：

```text
# .venv/bin/python -m pytest --collect-only -q
9727 tests collected / 5 errors

ERROR tests/test_datetime_utils.py                      # ModuleNotFoundError: freezegun
ERROR tests/test_jwt_migration.py                       # ModuleNotFoundError: hypothesis
ERROR tests/test_risk_policy_budget.py                  # KeyError: 'AFI_POLICY_BUDGET_SOURCE'
ERROR tests/test_service_read_authorized_http_integration.py  # JWT secret 断言读到开发者 .env
ERROR tests/test_service_read_reg04_workers.py          # 同上
```

`tests/test_risk_policy_budget.py:25` 在模块导入期直接执行 `os.environ["AFI_POLICY_BUDGET_SOURCE"]`；`tests/test_service_read_*` 在导入期断言 `get_settings().JWT_SECRET_KEY` 等于测试值，但 `conftest.py` 只设置了 `SECRET_KEY`，没有设置 `JWT_SECRET_KEY`，于是读到了 `src/backend/.env` 的 `local-dev-jwt-secret-key-...`。

全量运行（非规范 env；见 §0）：

```text
76 failed, 2395 passed, 10 skipped, 28 errors in 514.09s
xdist.dsession.Interrupted: stopping after 40 failures
```

`pytest.ini` 默认 `--maxfail=5`，本次命令行虽覆盖为 40，xdist 仍在 40 个失败后中断，说明“跑完整套件”这件事本身没有被验证。

**影响**：

- 开发者无法用一条命令判断 HEAD 是否健康；CI 之外的本地信号不可信。
- 关键迁移/交易/策略测试失败会被前 5 个失败截断，后面的失败不可见。
- 测试依赖开发者 `.env` 和未声明的本机包，换机器/换 Python 版本会改变结果。

**修复方向**：

- 增加 `APP_ENV=test` 配置；`conftest.py` 在任何 app import 之前设置完整 env（`JWT_SECRET_KEY`、`AFI_POLICY_BUDGET_SOURCE`、`DATABASE_URL`、`SECRET_KEY`、`ADMIN_PASSWORD` 等），或改用 fixture 注入，禁止模块导入期读 env。
- 删除默认 `--maxfail=5`；本地用 `--maxfail=0`，CI 用 `-n auto` 全量。
- `.venv` 按 lock 重建（`uv sync` 或 `pip install -r config/requirements-dev.lock`），把 `freezegun/hypothesis/ruff/mypy` 纳入自检。
- 区分 unit / integration / e2e；默认 `pytest` 不依赖网络、MySQL、券商、真实数据。
- 为迁移测试提供独立临时 DB 和固定方言矩阵。

## D04（P1）门禁可静默跳过或只告警

**证据级别**：E1 + E2。

**位置**：
- `scripts/dev/check_all.sh:79-103`
- `.github/workflows/nightly.yml:445-461`
- `scripts/ci/check_migration_safety.py:1-35`
- `scripts/ci/compare_bundle_size.sh:44-90`（多个 `exit 0`）
- `src/backend/pytest.ini`（`--maxfail=5`）

**事实**：

```bash
# check_all.sh
if ! command -v ruff > /dev/null 2>&1; then
  echo "WARN: ruff not in PATH — skipping ruff steps" >&2
else
  run_step ... ruff check .
fi
# mypy、pytest、npm 同样：缺工具 -> WARN -> 继续
```

当前 `src/backend/.venv` 正好缺 `ruff`/`mypy`/`freezegun`/`hypothesis`，所以在本机执行 `make check-all` 会跳过 lint/type/test，最后仍打印“all members green”。这不是理论风险，是当前环境的实际路径。

夜间审计：

```yaml
pip-audit --desc --format json ... 2>&1 || true
pip-audit --desc 2>&1 || true
npm audit --json ... 2>&1 || true
npm audit 2>&1 || true
```

高/严重漏洞只用于创建 issue，不阻断。迁移安全 lint 明确“never fails the build”，只发 warning。

**影响**：门禁变成“建议”，而不是“合同”。缺失工具、依赖漏洞、迁移风险都可以在绿色输出下通过。

**修复方向**：

- `check_all.sh` 默认 fail-closed：工具缺失直接 exit 2；只允许显式 `--allow-missing-tools` 用于纯文档环境。
- 增加启动自检：打印每个工具的版本，并与 `config/requirements-dev.lock` 比对。
- 夜间审计改为阻断：`pip-audit -r config/requirements-prod.lock`、`npm audit --omit=dev --audit-level=high`，用 allowlist 处理已评估例外。
- `check_migration_safety` 至少对新增迁移的 `nullable=False` 无默认值、drop table/column 设为阻断。
- 把 `--maxfail` 从 pytest.ini 移除，CI 显式设置。

## D05（P1）MySQL 使用 NullPool

**证据级别**：E2 + E3（需 MySQL 压测）。

**位置**：`src/backend/app/db/database.py:72-88`。

```python
if settings.DATABASE_URL.startswith("mysql"):
    extra_kwargs["poolclass"] = NullPool
else:
    extra_kwargs["pool_pre_ping"] = True
_engine = create_async_engine(settings.DATABASE_URL, ..., **extra_kwargs)
```

注释说明是为了规避 async driver 的 “Future attached to a different loop”。但代价是每个 session/请求都建立新的 TCP + 认证连接；生产 compose 使用 `mysql+aiomysql`，默认 `WEB_CONCURRENCY=2`，多 worker 时连接数随并发线性增长。

**影响**：

- 请求延迟增加（尤其 MySQL 与 API 跨主机时，每次 TCP/TLS/认证可能 1–20ms）。
- 高并发时出现连接风暴，打满 MySQL `max_connections`。
- `NullPool` 没有池指标，连接耗尽不可观测。

**修复方向**：

- 以事件循环为键维护 engine（每个 loop 一个 pool），或让所有 DB 使用同一个 loop（uvicorn 单 loop + worker 进程），再启用 `AsyncAdaptedQueuePool`/`pool_size`/`max_overflow`/`pool_pre_ping`。
- 对 `service_read` 的跨 loop 场景，用独立 loop 的独立 engine，不要全局 `NullPool`。
- 加 `pool.checkedout()`、`pool.overflow()`、连接耗尽告警和压测基线（p95、连接数、错误率）。

**注意**：不能简单把 `NullPool` 换成默认 pool 就结束；必须先解决 loop 绑定，否则会把 “Future attached to a different loop” 重新引入。这是一个需要压测和回滚预案的 WP。

## D06（P1）THS 采集阻塞事件循环

**证据级别**：E2 + E3（需启用 THS scheduler 或调用 CLI）。

**位置**：
- `src/backend/app/services/market_data/ths_dump_importer.py:248-261, 278-303`
- `src/backend/app/services/market_data/ths_history_runner.py:696-697`
- `src/backend/app/services/market_data/ths_scheduler.py:100-109`

**事实**：

```python
# ths_dump_importer.py
download = httpx.get(presigned_url, timeout=..., trust_env=False)  # sync
if len(download.content) > self._max_bytes: ...                     # after full body
...
return httpx.get(url, ..., timeout=...)                            # sync retry
...
time.sleep(1.0 * (attempt + 1))                                    # blocks thread
```

```python
# ths_history_runner.py (async)
content = self._downloader.fetch_dump(dump_kind, cache_path=cache_path)  # sync
bars = parse_daily_k_parquet(content)                                    # sync CPU + memory
```

```python
# ths_scheduler.py (APScheduler AsyncIOScheduler, in API process)
async def _run_daily_ths_collection():
    ...
    report = await runner.collect_daily()
```

**影响**：

- 下载、重试 sleep、Parquet 解析都会阻塞 API 事件循环；期间 health、行情、鉴权等请求延迟升高甚至超时。
- `len(download.content)` 在完整下载后才检查大小，无法阻止超大响应占用内存。
- 逐标的 `begin_nested()` + `import_daily_k` 可能形成 N 次 savepoint/写入；大批量时事务时间过长。
- 调度器与 API 同进程，采集抖动会直接影响在线服务。

**修复方向**：

- 下载改为 `httpx.AsyncClient.stream()`，先检查 `Content-Length` 并做增量上限；重试用 `await asyncio.sleep()`。
- Parquet 解析与逐标的导入放入 `asyncio.to_thread()` 或独立 worker 进程。
- 调度器迁到独立 worker/进程；API 进程只读状态。
- 批量事务按 `commit_every` 明确边界，避免长事务和 N 次 savepoint；对失败标的记录可重试队列。

## D07（P1）生产模式只由 DEBUG 推断，默认值可绕过安全守卫

**证据级别**：E1 + E2。

**位置**：
- `src/backend/app/config.py:60-76`
- `scripts/ops/start_app.sh:190-204`
- `src/backend/app/startup/security_check.py:15-24`
- `docker/compose/prod.yml:50-85`（生产 compose 显式 `DEBUG: "false"`）

**事实**：

```python
def _is_production(debug=None, *, debug_was_explicit=False):
    normalized_debug = _coerce_bool(debug)
    if debug_was_explicit and normalized_debug is not None:
        return not normalized_debug
    env_debug = _coerce_bool(os.environ.get("DEBUG"))
    if env_debug is not None:
        return not env_debug
    return False
```

只要 `DEBUG` 没有被显式设为 false，`production_security_mode()` 就是 False；此时 `config.py` 的生产校验（默认密钥、默认管理员、通配 CORS、TLS 校验、AI sandbox）全部不生效。`start_app.sh` 仍然：

```bash
BACKEND_DEBUG="${DEBUG:-true}"
... env DEBUG="$BACKEND_DEBUG" ...
```

启动检查只 `warning`，不抛错：

```python
if settings.SECRET_KEY in _DEFAULT_SECRETS or settings.JWT_SECRET_KEY in _DEFAULT_SECRETS:
    startup_logger.warning("Using default security key...")
if settings.ADMIN_PASSWORD.lower() in _DEFAULT_PASSWORDS:
    startup_logger.warning("Default admin password detected...")
```

**影响**：任何用 `start_app.sh` 启动、或忘记设置 `DEBUG=false` 的部署，都会以默认 JWT 密钥/默认管理员运行，且只看到 warning。生产 compose 当前是正确的，但安全不能依赖“记得用 compose”。

**修复方向**：

- 引入独立 `APP_ENV`（`development|test|production`）；生产守卫以 `APP_ENV=production` 为准，`DEBUG` 只控制调试行为。
- 生产模式下默认密钥/默认管理员必须 **raise**，不是 warning。
- `start_app.sh` 禁止默认 `DEBUG=true`；缺省应读取 `.env`，或显式要求 `APP_ENV`。
- 在启动日志中打印脱敏后的模式与守卫列表，便于验收。

## D08（P2）组合页一次性加载全部 paper equity snapshot

**证据级别**：E2 + E3（数据量相关）。

**位置**：`src/backend/app/api/portfolio/api.py:1416-1439`；`_sample_indices` 在 1410 附近。

**事实**：

```python
result = await session.execute(
    select(PaperEquitySnapshot)
    .where(PaperEquitySnapshot.user_id == user_id,
           PaperEquitySnapshot.instance_id.in_(instance_ids))
    .order_by(...)
)
snapshots = result.scalars().all()
```

随后在 Python 里按时间点去重、按 `max_points` 降采样。

**影响**：一个长期运行的 paper 实例可能积累数十万到数百万条快照；一次组合页请求把全部行读入内存，再在 Python 过滤，响应时间和内存随历史线性增长。用户越多、实例越多，越明显。

**修复方向**：

- SQL 侧按时间窗口/步长聚合（窗口函数或 `GROUP BY` 时间桶），只返回 `max_points` 个点。
- 明确默认时间范围（如最近 90 天）和最大点数；超限时返回降采样标记。
- 对 `(user_id, instance_id, observed_at)` 建/确认索引，并用 `EXPLAIN` 验证。

## D09（P2）回测结果接口一次性构造完整曲线/日志

**证据级别**：E2 + E3。

**位置**：`src/backend/app/api/analytics.py:86-286`；`parse_value_log`/`parse_data_log`/`parse_trade_log` 同步解析日志。

**事实**：`get_backtest_data()` 读取 `result.equity_curve`、`drawdown_curve`，循环构造 equity/drawdown；再解析 K 线日志、交易日志，构造 `trades` 与 `signals`，全部放入一个 dict 返回。没有分页、没有流式、没有点数上限。

**影响**：长周期/高频回测可能产生数十万点，单次响应体过大、内存峰值高、前端渲染卡顿；同步日志解析也可能阻塞事件循环（取决于调用位置）。

**修复方向**：

- 拆分 `/summary` 与 `/series`/`/trades` 分页接口；默认只返回摘要 + 最近 N 点。
- 曲线在 SQL/服务层降采样；交易/信号分页。
- 日志解析放入 thread/worker，设置最大行数与超时。

## D10（P2）外部 RSS 使用标准库 ElementTree 解析

**证据级别**：E2 + E3。

**位置**：`src/backend/app/services/news_intelligence.py:350-367`。

```python
response = await client.get(url, follow_redirects=True, headers=...)
return response.text
...
root = ET.fromstring(feed_text)
```

**影响**：外部 RSS 是半可信输入；标准库 `ElementTree` 对实体扩展/超大文档没有防护，可能造成 CPU/内存耗尽。当前还缺少响应体大小上限。

**修复方向**：

- 使用 `defusedxml.ElementTree.fromstring`，或在解析前拒绝 DTD/ENTITY。
- `httpx` 读取时限制最大字节数；超限直接拒绝。
- 对 feed 项数、标题/摘要长度做上限。

## D11（P2）生产 compose 暴露 MySQL 3306

**证据级别**：E2。

**位置**：`docker/compose/prod.yml:21-22`。

```yaml
mysql:
  ports:
    - "3306:3306"
```

**影响**：MySQL 端口绑定到宿主机所有网卡。若防火墙/安全组配置不严，数据库直接暴露公网；配合 `mysql_native_password` 和弱密码风险更高。后端与 MySQL 已在同一 compose network，不需要宿主机端口。

**修复方向**：

- 删除 `ports`，只保留 `expose: ["3306"]`；如必须宿主机访问，绑定 `127.0.0.1:3306:3306`。
- 使用 `caching_sha2_password`（若驱动支持）并限制来源网段。
- 加部署验收：`ss -lntp` 确认 3306 未监听公网。

## D12（P2）宽泛异常吞噬导致“故障=无数据”

**证据级别**：E1（AST 统计）+ E2（抽样）。

**统计**：`except Exception` 共 **2206** 处（AST 统计；grep 文本口径 2223），`except BaseException` 44 处；仅 `pass` 的宽泛处理器 20 处。

**代表性位置**：

- `src/backend/app/services/market_instrument_asset_adapter.py:154-173`：债券历史查询 `except Exception: row = None`，继续尝试下一张表，最终返回空日期。数据库连接失败、权限错误、SQL 错误都会被降级成“没有数据”。
- `src/backend/app/services/stock_analysis/data_collector.py:346`：新闻聚合失败直接 `pass`，接口仍返回空列表，无错误码。
- `src/backend/app/services/gateway/runtime.py:443`：symbol alias 解析失败 `pass`，可能静默丢失别名。
- `src/backend/app/services/research/holdout_claim.py:232`：审计写入失败后 `pass` 再抛业务错，至少还 fail-closed；这类可以保留，但应记录错误码。

**影响**：可观测性下降；用户看到“无数据”，运维无法区分供应商无数据、数据库故障、代码 bug。对于行情/授权/风控路径，可能把基础设施故障误判为业务空结果。

**修复方向**：

- 定义错误分类：`NOT_FOUND`、`PROVIDER_EMPTY`、`PROVIDER_ERROR`、`DB_ERROR`、`PARSE_ERROR`；只有前两类允许降级为空。
- 宽泛捕获必须记录 `error_code` + `table/operation` + 脱敏上下文；基础设施错误重新抛出或标记 degraded。
- 用 AST/ruff 规则限制新增 `except Exception: pass`；对存量做 allowlist 和逐项清理。

## D13（P2）后端 e2e marker 为 0

**证据级别**：E1。

```bash
grep -rn '@pytest.mark.e2e' src/backend/tests | wc -l   # 0
grep -rn '@pytest.mark.integration' src/backend/tests | wc -l  # 10
```

`.github/workflows/e2e.yml` 启动后端后运行的是前端 Playwright 测试，没有 `pytest -m e2e` 的后端用例。`pytest.ini` 声明了 `e2e` marker，但没有测试命中。

**影响**：所谓“e2e 通过”只覆盖前端浏览器流程；后端真实 HTTP/DB/调度链路没有 e2e 保护。203 已把“空绿 job”列为禁止项，但当前仍是 0 命中。

**修复方向**：

- 新增 4 条后端 e2e：注册/登录/刷新、工作区创建与切换、数据采集任务入队与回执、paper 下单/撤单/持仓；使用临时 SQLite/MySQL 与 mock provider。
- 在 e2e workflow 增加 `pytest -m e2e` 步骤，并断言至少收集 N 条。
- 如果短期不做，删除 `e2e` marker 和对应 workflow 步骤，禁止“有名无实”。

## D14（P2）巨型文件与高复杂度

**证据级别**：E1（行数/radon）。

**前端**：

| 文件 | 行数 |
|---|---:|
| `src/frontend/src/views/strategy/useStrategyPage.ts` | 5272 |
| `src/frontend/src/views/data/useDataPage.ts` | 4853（棘轮基线 4912） |
| `src/frontend/src/views/PortfolioPage.vue` | 3588 |
| `src/frontend/src/views/StrategyPage.vue` | 3254 |

**后端**：

| 文件 | 行数 |
|---|---:|
| `src/backend/app/services/ai_strategy_research_service.py` | 5866 |
| `src/backend/app/services/asset_research/orchestrator.py` | 3045 |
| `src/backend/app/services/research/paper_handoff.py` | 2787 |
| `src/backend/app/services/gateway/manual.py` | 2682 |

**复杂度**：`radon cc` 分析 1478 个块，平均 **D (20.3)**；64 个函数 CC≥50。最高的包括：

- `services/research/promotion.py:1368 _require_command_promotion_authority` — **F (147)**
- `services/service_read/access.py:62 ReadAccess` — **F (129)**
- `services/position_valuation.py:378 contract_spec_for` — **F (129)**
- `services/service_read/access.py:108 ReadAccess.__post_init__` — **F (128)**
- `services/ai_strategy_research_service.py:746 _run_pipeline` — **F (122)**

**影响**：修改成本高、回归面大、并发/异常路径难验证；与 D01/D02 这类“状态机 + 迁移”缺陷高度相关。大文件棘轮虽然通过，但它只保证“不再增长”，不保证“可维护”。

**修复方向**：

- 选 2 个切片先做：`save_data` 的批处理/回执拆分；`promotion.py` 的授权校验拆成纯函数 + 表驱动。
- 前端把 `useDataPage` 的请求/分页/筛选/错误处理拆成 composables；`StrategyPage` 按面板拆子组件。
- 增加 CC 棘轮（新增函数 CC>20 需说明），并补 characterization tests 后再搬代码。

## D15（P2）锁文件无 hash，本地 venv 漂移

**证据级别**：E1。

- `config/requirements-prod.lock` 有 126 个 `==` 固定版本，但 `--hash` 数量为 **0**。
- 本机 `src/backend/.venv` 缺 `freezegun==1.5.2`、`hypothesis==6.156.6`、`ruff`、`mypy`，与 lock 不一致。
- `pip-audit -r config/requirements-prod.lock` 在 Python 3.13 下**未能完成审计**：`pip-audit` 先解析/安装依赖，报 `backtrader` fork 与 `numpy==1.26.4` 冲突：
  ```text
  ERROR: Cannot install -r .../config/requirements-prod.lock (line 31) and numpy==1.26.4
  because these package versions have conflicting dependencies.
  ERROR: ResolutionImpossible
  ```
  这说明依赖审计必须在与 lock 匹配的解释器（CI 的 Python 3.11/3.12）中执行；在当前 3.13 环境连“审计前安装”都过不去。
- `npm audit --omit=dev` 为 **0 vulnerabilities**。

**影响**：安装可复现性依赖 PyPI 完整性与网络；无法保证 CI/开发/镜像拿到同一字节。venv 漂移会直接导致 D03/D04 的假绿。

**修复方向**：

- 用 `uv pip compile --generate-hashes` 或 `pip-compile --generate-hashes` 生成 hash 锁；安装时 `--require-hashes`。
- CI 增加 `check_lockfile_sync.py` 与 `uv sync --locked`；开发环境用同一命令重建。
- 依赖审计改为阻断，允许显式 allowlist 与到期日。

## D16（P2）运行时兼容 DDL 与 Alembic 双轨

**证据级别**：E2。

**位置**：`src/backend/app/db/database.py:807-841`；`src/backend/app/startup/database.py:18-25`。

`ensure_schema_compatibility()` / `create_tables()` 会运行 12 组 `_ensure_*_schema_compatibility_sync`，其中包含 `ALTER TABLE`、`MODIFY COLUMN`、重建表等。只有 `DB_AUTO_CREATE_SCHEMA=true` 时触发；生产 compose 设为 false，所以生产路径目前不走，但开发/测试/部分自建部署仍会走。

**影响**：

- 同一 schema 有 Alembic 与运行时 DDL 两个事实源，容易出现“开发库能跑、迁移库不能跑”。
- 启动时 DDL 可能持有锁、在只读副本上失败、或与迁移并发冲突。
- 与 D02 的迁移不可复现相互放大。

**修复方向**：

- 删除运行时兼容 DDL；所有 schema 变更只经 Alembic。
- 对历史库提供一次性 `scripts/ops/upgrade_legacy_schema.py`，显式运行并记录版本。
- 启动只做 `verify_database_revision`，不执行 DDL。

## S01（优点）前端与部分门禁当前健康

- `vue-tsc --noEmit`：EXIT 0。
- `eslint . --max-warnings 0`：EXIT 0。
- `vitest --run`：183 files / 2190 tests passed。
- `npm audit --omit=dev`：0 vulnerabilities。
- `ruff==0.16.2 check .`（后端）：通过。
- `large_file_ratchet.py`：通过（但基线很高，见 D14）。

这些是后续迭代的“不能退化”基线；WP03/WP04 要把它们变成阻断门禁，而不是口头结论。

## S02（优点）认证 token 分离与 CORS 生产校验仍然有效

- `utils/security.py:136-229`：access token 带 `token_type=access`，refresh token 带 `token_type=refresh`；解码时分别校验，202 的 D01 修复没有回退。
- `config.py:150-158`：生产模式拒绝通配 CORS；生产 compose 设置 `DEBUG=false` 与显式 `CORS_ORIGINS`。
- 但生产模式推断仍依赖 DEBUG（D07），需要改为 `APP_ENV`。

## S03（方法）OCR 与子代理的可信度边界

- OCR `delegate preview` 的 1289 文件/324k 插入是**范围**证据，不是缺陷证据。
- OCR `rules check` 只证明规则命中，不证明代码有缺陷。
- 子代理输出必须落到 `file:line` 与可执行命令；本轮多数子代理输出被截断，因此没有把“代理说有问题”直接写成发现。
- 所有 D01–D16 都由主审用源码/命令/测试复验或明确标注 E2/E3。
