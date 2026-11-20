# 迭代205 实施计划

> 配套文档：[README.md](README.md)、[AUDIT.md](AUDIT.md)、[ACCEPTANCE.md](ACCEPTANCE.md)。  
> 原则：先修“假成功/假绿”，再修性能与体验；每个工作包必须有可执行验收；不做无证据的重构。

## 1. 目标与非目标

### 1.1 目标

1. 数据写入回执与数据库 affected rows 一致，空写不能被判成功。
2. 空库迁移在 SQLite / MySQL / PostgreSQL 受支持版本上可复现。
3. 后端测试 **0 collection error**，全量可完整执行；e2e 要么真实执行，要么删除空 marker。
4. 本地/CI 门禁缺工具、有失败、有高危漏洞时必须红，不能 WARN 后继续。
5. MySQL 连接池、THS 异步采集、组合/回测大响应有测量、有上限。
6. 生产模式、默认凭据、数据库端口、外部 XML、策略 exec 边界默认失败关闭。
7. 巨型文件/高复杂度不再增长，并完成至少 2 个可回滚切片。

### 1.2 非目标

- 不新增交易策略、行情页面、AI 功能或数据源。
- 不完成迭代204 的 OpenData 迁移；不切换生产数据平台。
- 不重写 `bt_api_*` / backtrader / fincore 依赖。
- 不做无数据量证据的“性能优化”。
- 不在本迭代内处理历史凭据重写（见 REFACTORING_BACKLOG 的 P0 政策项）。

## 2. 工作包总览

| WP | 优先级 | 目标 | 负责人角色 | 并行道 | 依赖 | 预估 |
|---|---|---|---|---|---|---|
| WP01 | P0 | 数据写入真实性与空结果保护 | 数据后端 | A1/A2 | 无 | 2d |
| WP02 | P0 | 迁移可复现（SQLite/MySQL/PG） | 迁移/DB | B1/B2 | 无 | 2.5d |
| WP03 | P1 | 测试基线 hermetic 与真实 e2e | QA | C1/C2 | WP02 | 3d |
| WP04 | P1 | 门禁与供应链 fail-closed | DevOps | D1 | 无 | 2d |
| WP05 | P1 | 连接池、事件循环、大响应有界 | 性能/后端 | E1/E2 | WP01 | 3.5d |
| WP06 | P1 | 安全默认失败关闭 | 安全/后端 | F1 | 无 | 2d |
| WP07 | P2 | 可维护性切片与复杂度棘轮 | 架构 | F1（第二波） | WP03 | 3d |
| WP08 | P2 | 可观测性与运行手册 | SRE | E1/D1 | WP01/05/06 | 1.5d |

总计：约 **9–11 个工作日**（10 道并行时）；串行执行约 19–20 天。

## 3. WP01 数据写入真实性与空结果保护（P0）

### 3.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP01-T1 | `_execute_batch` 返回本批 `cursor.rowcount`，对负数/缺失回退为 batch 长度 | `data_fetch/core/mysql_base.py` | 单测：0/部分/全部重复三种批次 |
| WP01-T2 | `MysqlBase.save_data` 累加 affected，返回 affected；日志打印 offered/affected | `data_fetch/core/mysql_base.py` | 返回 0 时调用方能看到 |
| WP01-T3 | `AkshareProvider.save_data` 同样处理，保留 `disconnect_db` | `data_fetch/providers/akshare_provider.py` | 同上 |
| WP01-T4 | 回执结构增加 `offered_rows` / `affected_rows`，`committed_row_count` 只累计 affected | `services/akshare/script_worker.py`、`write_fence.py` | 回执 JSON 断言 |
| WP01-T5 | `_raise_if_empty_completion` 使用 affected；`offered>0 && affected==0` 默认抛错，显式 NOOP 才放行 | `services/akshare/script.py` | 回归：1030 offered / 0 affected -> 失败 |
| WP01-T6 | 诊断日志保留 symbol/series/adjustment/source/last_date | `scripts/stocks/daily/stock_zh_a_hist.py` | 不替代 rowcount 修复 |
| WP01-T7 | 用真实 MySQL 复跑 5 个尾部缺口标的，核对 `SELECT COUNT(*)` | 运行手册 | 行数与回执一致 |

### 3.2 关键设计

- **返回契约**：
  ```python
  @dataclass(frozen=True)
  class WriteReceipt:
      table: str
      offered: int
      affected: int
      batches: int
      idempotent_noop: bool = False
  ```
  兼容层可继续返回 `int`（affected），但内部回执必须携带 offered/affected。
- **失败语义**：`INSERT IGNORE` 全部重复不是异常，但必须在“任务成功”层面区分 `IDEMPOTENT_NOOP`；如果该脚本的业务语义要求“必须有新数据”，则视为失败。
- **禁止**：只改日志、只改测试、只改 `committed_row_count` 而不改 `save_data` 返回值。

### 3.3 回归测试

```bash
cd src/backend
python -m pytest tests/test_akshare_provider.py tests/test_akshare_script_service.py -q
python -m pytest tests/test_akshare_script_service.py -q -k "empty or duplicate or rowcount"
```

新增用例必须能复现 `6b916104b` 的意图，并证明回退后的行为已被拦住。

## 4. WP02 迁移可复现（P0）

### 4.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP02-T1 | 复现并定位 SQLite check 反射失败 | `alembic/versions/20260908_ai_research_approval_authority.py` | 保留失败命令与 traceback |
| WP02-T2 | 让 SQLite 建表/重建时的 CHECK 名称成为唯一事实源；`_ensure_checks` 不再对刚建表抛冲突 | 同上 | 空库 upgrade head exit 0 |
| WP02-T3 | 支持“半途库”修复：从 `sqlite_master` 解析 CHECK 文本或安全重建表 | 同上 | 旧库样本可升级 |
| WP02-T4 | 修复其他迁移测试的同类失败（research binding、multi-record、asset research） | 相应迁移/测试 | 失败簇清零 |
| WP02-T5 | 建立方言矩阵并纳入 CI：SQLite 3.40/3.45/3.53、MySQL 8.0/9.4、PostgreSQL 16 | `.github/workflows/ci.yml`、`docker/compose/ci.yml` | 矩阵全绿 |
| WP02-T6 | 运行时兼容 DDL 退役：删除 `ensure_schema_compatibility`/`create_tables` 的 schema patch 路径，保留一次性升级脚本 | `db/database.py`、`startup/database.py` | 启动只 verify，无 DDL |

### 4.2 关键设计

- `_upgrade_existing_table` 中对 SQLite 使用 `batch_alter_table(recreate="always")` 时，显式给每个 CHECK 命名；重建后再次反射，用“名称 + 归一化 SQL”比较，而不是只比名称。
- 对“表由本迁移新建”的路径，跳过 `_ensure_checks`；把校验放在建表 DDL 内。
- 迁移测试不要只测“有列”，要测“check 名称、表达式、可插入非法值被拒绝”。
- 空库升级与“从上一 revision 升级”分开测；两者都必须在矩阵上过。

### 4.3 验收

```bash
cd src/backend
for url in \
  "sqlite+aiosqlite:////tmp/afi-205-345.db" \
  "sqlite+aiosqlite:////tmp/afi-205-353.db"; do
  rm -f "${url#sqlite+aiosqlite:///}"
  DATABASE_URL="$url" python -m alembic upgrade head || exit 1
done
python -m pytest tests/test_ai_research_approval_migration.py \
  tests/market_data_platform/test_research_binding_migrations.py \
  tests/market_data_platform/test_multi_record_migration.py \
  tests/asset_research/test_migration.py -q
python ../../scripts/ci/check_orm_schema_drift.py
```

MySQL/PostgreSQL 用 CI service 或 compose 执行同一套 `alembic upgrade head`，并保存日志。

## 5. WP03 测试基线与 e2e（P1）

### 5.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP03-T1 | 增加 `APP_ENV=test` 与完整 env 初始化；禁止 import-time 读 env | `tests/conftest.py`、`pytest.ini`、`.env.test.example` | `pytest --collect-only -q` 0 error |
| WP03-T2 | 移除默认 `--maxfail=5`；本地/CI 显式设置 | `src/backend/pytest.ini` | 全量不被截断 |
| WP03-T3 | 按 lock 重建 venv；自检 `ruff/mypy/freezegun/hypothesis` | `scripts/dev/bootstrap_dev.sh`（新增） | `make check-all` 不跳过 |
| WP03-T4 | 拆分 unit/integration/e2e 的默认选择；默认不依赖网络/MySQL/券商 | `pytest.ini`、`tests/` | 离线可跑 |
| WP03-T5 | 新增 4 条后端 e2e（认证、工作区、采集回执、paper 下单） | `tests/integration/` | `pytest -m e2e` ≥4 passed |
| WP03-T6 | e2e workflow 增加后端 `pytest -m e2e` 并断言收集数 | `.github/workflows/e2e.yml` | 不再空绿 |
| WP03-T7 | 清理/登记 113 个 skip：区分平台限制、可选依赖、真跳过 | `tests/` | skip 清单与预算 |

### 5.2 关键设计

- `conftest.py` 最顶部设置：
  ```python
  os.environ.setdefault("APP_ENV", "test")
  os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-...")
  os.environ.setdefault("AFI_POLICY_BUDGET_SOURCE", str(TEST_FIXTURE_PATH))
  ```
  且这些值不得从开发者 `.env` 继承。
- `get_settings()` 的缓存要在测试间可控：提供 `reset_settings_cache()` fixture，避免“先导入者赢”。
- e2e 使用临时 SQLite 或 CI MySQL service；provider 用 fake；不访问真实券商/行情。

### 5.3 验收

```bash
cd src/backend
python -m pytest --collect-only -q          # 0 errors
python -m pytest -q -n auto -m "not performance"  # 0 failed
python -m pytest -q -m e2e                  # >= 4 passed
```

## 6. WP04 门禁与供应链 fail-closed（P1）

### 6.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP04-T1 | `check_all.sh` 工具缺失 exit 2；增加 `--allow-missing-tools` | `scripts/dev/check_all.sh` | 隐藏 ruff 后 `make check-all` 失败 |
| WP04-T2 | 打印工具版本并与 lock 比对 | `scripts/dev/check_all.sh`、`scripts/ci/check_lockfile_sync.py` | 版本漂移可见 |
| WP04-T3 | 夜间审计阻断高危/严重；allowlist 带到期日 | `.github/workflows/nightly.yml` | 构造漏洞时 job 红 |
| WP04-T4 | 生产锁生成 hash；安装 `--require-hashes` | `config/requirements-prod.lock`、生成脚本 | `--hash` 覆盖全部包 |
| WP04-T5 | 迁移安全 lint 对高风险操作阻断 | `scripts/ci/check_migration_safety.py` | drop table/column 用例失败 |
| WP04-T6 | bundle/大文件/覆盖率门禁明确阻断/建议边界 | `scripts/ci/*` | 文档 + 测试 |

### 6.2 验收

```bash
# 负向测试：隐藏 ruff 后必须失败
PATH=/usr/bin:/bin bash scripts/dev/check_all.sh; test $? -ne 0

# 审计负向测试：allowlist 之外的高危必须失败
# pip-audit 默认在发现漏洞时返回非零；WP04-T3 负责把这一步接入 CI，并把已评估例外写入 allowlist
pip-audit -r config/requirements-prod.lock --format json --output /tmp/afi-pip-audit.json
```

## 7. WP05 性能与容量（P1）

### 7.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP05-T1 | MySQL pool：按 loop 隔离的 engine 或统一 loop + `AsyncAdaptedQueuePool`；配置 `pool_size/max_overflow/pool_pre_ping` | `db/database.py` | 压测无 “Future attached to a different loop” |
| WP05-T2 | 连接池指标与告警（checkedout/overflow/invalidated） | `db/database.py`、`telemetry.py` | 指标可见 |
| WP05-T3 | THS 下载改 async streaming + 增量大小上限；sleep 改 await | `market_data/ths_dump_importer.py` | 大响应在阈值处中止 |
| WP05-T4 | Parquet 解析/逐标的导入 offload 到 thread/process；调度器移出 API | `ths_history_runner.py`、`ths_scheduler.py` | 采集期间 health p95 不劣化 |
| WP05-T5 | paper equity snapshot SQL 侧降采样 + 时间窗 + 最大点数 | `api/portfolio/api.py` | 100 万行 fixture 响应 < 1s / < 1MB |
| WP05-T6 | 回测结果 summary/series/trades 分页；日志解析 offload | `api/analytics.py` | 大结果响应有上限 |
| WP05-T7 | 建立性能基线：API p95、DB 连接数、THS 采集时长、内存峰值 | `tests/`、`reports/` | 前后对比表 |

### 7.2 性能验收阈值（建议）

| 指标 | 现状 | 目标 |
|---|---|---|
| 组合页 100 万 snapshot | 全量加载，未测 | p95 < 1s，响应 < 1MB |
| 回测结果 50 万点 | 一次性构造 | summary p95 < 300ms；series 分页 ≤ 5000 点/页 |
| MySQL 每请求连接 | 每次新建 | 复用率 > 90%，连接数 ≤ pool_size + overflow |
| THS 采集期间 health p95 | 未测 | 不超过基线 2 倍 |
| 事件循环阻塞 | 未测 | 单次阻塞 < 50ms（用 `asyncio` debug/`py-spy` 采样） |

## 8. WP06 安全默认失败关闭（P1）

### 8.1 任务

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP06-T1 | 引入 `APP_ENV`；生产守卫以 `APP_ENV=production` 为准 | `config.py`、`settings/application.py` | 单测：production 下默认密钥 raise |
| WP06-T2 | 生产模式默认密钥/默认管理员 **raise**；开发/测试才 warning | `config.py`、`startup/security_check.py` | 负向测试 |
| WP06-T3 | `start_app.sh` 不再默认 `DEBUG=true`；缺省要求显式 env | `scripts/ops/start_app.sh` | shell 测试 |
| WP06-T4 | 生产 compose 移除 MySQL 公网端口，绑定 127.0.0.1 或仅 expose | `docker/compose/prod.yml` | `ss` 验收 |
| WP06-T5 | RSS 使用 defusedxml + 响应大小上限 | `services/news_intelligence.py` | 实体扩展/超大 feed 用例 |
| WP06-T6 | 策略 exec 信任边界：profile 目录 root-owned、sha256 校验、禁止运行期写入；文档化威胁模型 | `services/live_trading/service_execution_launch.py`、运行手册 | 安全评审签字 |
| WP06-T7 | 宽泛异常清理：先清 20 个 pass-only，再对数据/网关路径加错误码 | 相关服务 | AST 统计下降，回归通过 |

### 8.2 安全验收

```bash
# 生产模式负向测试
APP_ENV=production DEBUG=false SECRET_KEY=your-secret-key-change-in-production \
  python -c "from app.config import Settings; Settings()"   # 必须非零退出

# 端口
docker compose -f docker/docker-compose.yml -f docker/compose/prod.yml config | grep -A2 '3306'
ss -lntp | grep 3306   # 不应监听 0.0.0.0
```

## 9. WP07 可维护性切片（P2）

| ID | 任务 | 文件 | 验收 |
|---|---|---|---|
| WP07-T1 | 拆分 `save_data` 的 DataFrame 归一化 / SQL 构造 / 批处理 / 回执 | `core/mysql_base.py` | 行数下降，行为不变 |
| WP07-T2 | 把 `promotion._require_command_promotion_authority`（CC147）拆成表驱动校验 | `services/research/promotion.py` | 新函数 CC ≤ 20，测试全过 |
| WP07-T3 | `useDataPage` 拆 composables：请求、分页、筛选、错误 | `views/data/` | 文件 ≤ 3000 行，Vitest 全过 |
| WP07-T4 | `StrategyPage` 按面板拆子组件 | `views/StrategyPage.vue` | 文件 ≤ 2000 行，e2e 通过 |
| WP07-T5 | CC 棘轮：新增/修改函数 CC>20 需说明 | `scripts/ci/` | CI 可判定 |

**约束**：先补 characterization tests 再搬代码；每个切片独立 PR、可回滚；不改变对外 API/错误码。

## 10. WP08 可观测性与运行手册（P2）

| ID | 任务 | 验收 |
|---|---|---|
| WP08-T1 | 空写/NOOP/写入失败指标：`data_fetch.offered_rows`、`affected_rows`、`noop_total` | Prometheus/日志可见 |
| WP08-T2 | 连接池指标与连接耗尽告警 | dashboard + alert |
| WP08-T3 | THS 采集耗时/下载字节/解析耗时/跳过标的 | 运行手册 |
| WP08-T4 | 宽泛异常错误码统计：`error_code_total` | 按服务/操作聚合 |
| WP08-T5 | 运行手册：数据缺口、空写、迁移失败、连接池耗尽、THS 阻塞 | docs/runbooks |

## 11. 10 道并行执行计划

### 11.1 人员/代理配置

| 道 | 负责范围 | 产出 | 建议模型/角色 |
|---|---|---|---|
| A1 | `save_data` rowcount | 代码 + 单测 | 数据后端 |
| A2 | 回执/空结果保护 | 代码 + 回归 | 数据后端 |
| B1 | SQLite 迁移 | 代码 + 迁移测试 | DB/迁移 |
| B2 | MySQL/PG 方言矩阵 | CI + 集成测试 | DB/迁移 |
| C1 | 测试 hermetic | conftest/pytest 配置 | QA |
| C2 | e2e/marker | 4 条 e2e + workflow | QA |
| D1 | 门禁/供应链 | check_all/审计/hash 锁 | DevOps |
| E1 | pool + 查询有界 | 代码 + 压测 | 性能/后端 |
| E2 | THS/回测异步 | 代码 + 压测 | 性能/后端 |
| F1 | 安全 + 可维护性切片 | 代码 + 安全评审 | 安全/架构 |

### 11.2 波次与依赖

```text
Wave 0 (0.5d)
  D1: 冻结命令、环境、证据目录
  A1/A2/B1/B2: 只读复现，不改共享文件
        |
Wave 1 (2d)
  A1 -> A2         (WP01)
  B1 -> B2         (WP02)
        |
Wave 2 (3d)
  C1 -> C2         (WP03)
  D1               (WP04)
  E1/E2            (WP05, 依赖 WP01 的写入语义)
        |
Wave 3 (3d)
  F1               (WP06)
  F1 第二波        (WP07)
  E1/D1            (WP08)
        |
集成 (1d)
  主审：全量门禁 -> 验收 -> 文档
```

### 11.3 合并规则

1. 一条道一个分支/PR；PR 标题带 `iter205/<WP>-<lane>`。
2. 同一文件同一时间只允许一个道修改；跨道接口在 Wave 0 冻结。
3. 每日 17:00 集成一次：`bash scripts/dev/check_all.sh` + 定向 pytest。
4. 任何 PR 必须附：变更点、失败复现、验收命令、回滚方法、证据路径。
5. 不允许“先合后修”共享文件；不允许降低门槛来变绿。
6. P0 工作包（WP01/WP02）未绿前，不启动 WP07 的大规模搬代码。

## 12. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| rowcount 在 `executemany` 下语义随驱动/版本变化 | 中 | 回执仍不准 | MySQL 8.0/9.4 集成测试；对 `rowcount<0` 回退并记录 |
| MySQL 连接池改造重新引入跨 loop 错误 | 中 | API 500 | 按 loop 隔离 engine；压测 + 灰度；保留 NullPool 回退开关 |
| SQLite 迁移修复破坏已有库 | 中 | 升级失败 | 先备份/样本库；从上一 revision 与空库双路径测试 |
| e2e 增加导致 CI 时间过长 | 高 | 合并变慢 | 只保留 4 条关键路径；nightly 跑全量 |
| 安全 fail-closed 导致开发启动失败 | 中 | 开发体验 | `APP_ENV=development` 明确放行；错误信息给出修复命令 |
| 大文件拆分引入回归 | 中 | 功能损坏 | characterization tests；切片小步；Feature flag 不需要，保留 API |
| 依赖 hash 锁导致安装失败 | 中 | 构建阻断 | 先生成 hash 并在独立 job 验证；保留 lock 回滚分支 |

## 13. 完成定义（Definition of Done）

本迭代只有同时满足以下条件才可标记 `ACCEPTED_LOCAL`：

1. WP01：新增 rowcount/空写回归全部通过；真实 MySQL 复跑 5 个尾部缺口标的，回执与 `COUNT(*)` 一致。
2. WP02：空库 `alembic upgrade head` 在 SQLite 3.40/3.45/3.53 + MySQL 8.0/9.4 + PostgreSQL 16 全绿；迁移失败簇清零；`check_orm_schema_drift` exit 0。
3. WP03：`pytest --collect-only` 0 error；全量 `pytest -m "not performance"` 0 failed；`pytest -m e2e` ≥4 passed。
4. WP04：隐藏工具时 `check_all.sh` 非零；高危依赖审计阻断；prod lock 全量 hash。
5. WP05：压测报告显示无跨 loop 错误、组合/回测响应有上限、THS 采集期间 health p95 不超基线 2 倍。
6. WP06：production 下默认密钥/默认管理员启动失败；3306 不监听公网；XML/exec 边界有测试或评审记录。
7. WP07：至少 2 个切片完成，目标文件行数下降，Vitest/后端测试全绿。
8. WP08：指标/告警/运行手册可查，且有一次演练记录。

未满足任一项：状态只能是 `PARTIAL`，不得写 `PASS`，不得发布。
