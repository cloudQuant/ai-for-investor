# 迭代205 运行手册：写入回执、迁移与采集

## 1. 任务显示完成但数据库没有新行

1. 查 execution 的 `result.offered_rows` / `result.affected_rows`（新回执字段）。
2. `affected_rows == 0` 且 `offered_rows > 0` 时，先确认是否全量重复：
   ```sql
   SELECT COUNT(*) FROM <table> WHERE <identity>;
   ```
3. 若业务要求“必须有新数据”，该 execution 应判失败/NOOP，而不是 COMPLETED。
4. 复验：
   ```bash
   cd src/backend
   python -m pytest tests/test_data_fetch_write_receipts.py -q
   ```

## 2. 全新数据库迁移失败

1. 保存完整 traceback（含 revision 文件名和行号）。
2. 确认方言与版本（SQLite `sqlite3.sqlite_version`；MySQL `SELECT VERSION()`）。
3. 不要改测试绕过；先修迁移。SQLite 的 `CHECK`/`FK` 必须作为独立命名约束重建，不能塞进同一个 `ALTER TABLE ADD COLUMN`。
4. 复验：
   ```bash
   rm -f /tmp/afi-mig.db
   DATABASE_URL=sqlite+aiosqlite:////tmp/afi-mig.db python -m alembic upgrade head
   python -m pytest tests/test_ai_research_approval_migration.py tests/test_ai_research_v2_migration.py -q
   ```

## 3. MySQL 连接池耗尽

1. 看 `db_pool_checkedout` / `db_pool_overflow`（或 SQLAlchemy pool 日志）。
2. 确认没有跨事件循环复用同一个 pooled engine；每个 loop 应拿到自己的 engine。
3. 临时降载：降低 `WEB_CONCURRENCY` 或提高 `pool_size`/`max_overflow`，并记录变更。
4. 回归：`tests/test_iteration202_deployment_database.py`。

## 4. THS 采集期间 API 变慢

1. 确认 `THS` scheduler 是否在 API 进程内运行；推荐独立 worker。
2. 下载/解析必须走 `asyncio.to_thread` 或独立进程；禁止在事件循环里同步 `httpx.get`/Parquet 解析。
3. 检查 `THS_DUMP_TOO_LARGE` 是否触发；阈值内才允许落盘。
4. 观察 health/quote p95 是否超过基线 2 倍。

## 5. 生产模式误判

1. 生产必须显式 `APP_ENV=production`；`DEBUG=false` 只作为兼容回退。
2. 启动失败时检查：默认密钥、默认管理员密码、通配 CORS、TLS 校验、AI sandbox。
3. `start_app.sh` 不再默认 `DEBUG=true`；compose 生产文件必须设置 `APP_ENV=production`。
