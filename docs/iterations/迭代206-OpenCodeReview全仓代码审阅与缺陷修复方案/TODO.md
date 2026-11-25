# 迭代206：逐项修复 TODO 清单

> 对应方案：[README.md](README.md) | 详细证据：[AUDIT.md](AUDIT.md)  
> 进度统计：**44 / 44 已完成**（P0: 8/8 | P1: 24/24 | P2: 7/7 | P3: 5/5）  
> 执行约定：按 `P0 → P1 → P2 → P3` 顺序逐项修复；每勾选一项，须附回归测试或命令验证通过，并保持 PR 目标分支为 `dev`。

---

## P0 — 阻断级（优先清零，共 8 项）

- [x] **OCR-01（密钥止血与测试隔离）**：吊销/轮换泄露的 `OKX_API_KEY`；脱敏或移除 `docs/iterations/迭代205-全仓代码审查与质量门禁收口/evidence/full-suite-20261118.txt` 中的敏感信息；在 `src/backend/tests/conftest.py` 导入 `app.*` 前禁用 `Settings.model_config["env_file"] = None` 并清理本地券商环境变量。
  - **验收**：`git grep -i "OKX_API_KEY="` 无真实密钥命中；本地存在 `.env` 时运行 `pytest tests/test_config_validation.py` 完全不继承 `.env`。（仓库侧脱敏与测试隔离已验证通过，用户确认历史凭据均为模拟密码无风险，已完成闭环）
- [x] **OCR-02（Airflow 回调鉴权）**：为 `src/backend/app/api/airflow_callback.py`（`POST /api/v1/data/airflow/callback`）增加 HMAC 或 Bearer 回调密钥校验（`secrets.compare_digest`），生产环境未配置时返回 `503`。
  - **验收**：补充单测验证无密钥 `401/403`、错误密钥拒绝、生产未配置 `503`、合法回调 `200`。
- [x] **OCR-03（旧实盘网关跨租户 IDOR）**：将 `src/backend/app/api/live_trading/api.py` 中 `gateways/health`、`gateways/connected`、`gateways/{gateway_key}/account`、`gateways/{gateway_key}/positions` 收口至 `Depends(require_data_admin_user)`（或迁至 owner 隔离接口），并脱敏 `get_gateway_health` 的 500 响应。
  - **验收**：补充权限回归测试，普通用户访问上述 4 个端点均返回 `403`。
- [x] **OCR-04（修复 `large_file_ratchet` CI 红灯）**：抽离 `src/backend/app/db/database.py` 中的历史运行时兼容 DDL 与 `src/backend/app/api/portfolio/api.py` 中的净值辅助逻辑，使两文件回落至基线以内（不靠上调基线绕过）。
  - **验收**：`python3 scripts/ci/large_file_ratchet.py` 退出码 `0`。
- [x] **OCR-05（修复 `STOCK_ZH_A_HIST` 写入与 DDL 冲突）**：修改 `src/backend/app/data_fetch/scripts/stocks/daily/stock_zh_a_hist.py`，显式区分 `adjust=""`（不复权）不误标为 `"qfq"`；在 `create_table_sql` 与存量表迁移中补齐 `source`/`adjustment` 列及 `(symbol, data_date, adjustment, source)` 唯一键；消除 `source="tencent"` 二次重复调用与越权回退东财误标来源问题。
  - **验收**：新增单测覆盖 `adjust=""` / `"qfq"` / `"hfq"`、`source="tencent"` 失败不回退东财、`trends2` 回退正确标记来源与复权口径。
- [x] **OCR-06（恢复 150+ 采集脚本 `_call_timeout` 透传）**：修改 `src/backend/app/services/akshare/script_worker_runtime.py:421-425`，在过滤 `_` 开头调度元数据时保留 `_call_timeout`，仅对不支持该参数的原生函数由 `_signature_parameters` 剥离。
  - **验收**：新增单测验证带 `**kwargs` 或显式 `_call_timeout` 参数的脚本能正确接收到 `_call_timeout`。
- [x] **OCR-07（修复 `AkshareProvider` 未裁剪未知列与连接泄漏）**：修复 `src/backend/app/data_fetch/providers/akshare_provider.py`：`_align_df_to_table` 实际丢弃 `unknown` 列；`save_data` 用 `try...finally: self.disconnect_db()` 包裹 `connect_db()` 并处理非有限浮点/容器字段。
  - **验收**：新增单测验证含未知列、`inf`、`dict` 的 DataFrame 写入不报 `1054` 且异常时必调 `disconnect_db()`。
- [x] **OCR-08（修复 `save_data` 幂等返回 `0` 与 `ON DUPLICATE KEY UPDATE` 双倍计数）**：将 15+ 处 `data_fetch/scripts/` 中按 `if success:` 判定的调用方改为 `saved is not False`；修复 `mysql_base.py` 与 `akshare_provider.py` 中 `ON DUPLICATE KEY UPDATE` `rowcount=2` 导致的写入回执双倍计数。
  - **验收**：`pytest tests/test_data_fetch_write_receipts.py` 通过，且新增幂等 0 变更与部分更新批次行数单测。

---

## P1 — 高优先级（共 24 项）

### A. 安全、RBAC 与部署边界（5 项）

- [x] **OCR-09（Airflow DAG 编排 BFLA）**：为 `src/backend/app/api/airflow_dags.py` 全部端点启用 `Depends(require_data_admin_user)` 并校验 `dag_id`/`dag_run_id`/`task_id` 合法字符集。
  - **验收**：单测验证普通用户 `403`、非法 ID `422/400`、管理员正常放行。
- [x] **OCR-10（RSS 抓取 SSRF 防护与流式限长）**：在 `src/backend/app/services/news_intelligence.py` 的 `add_source` 与 `_default_rss_fetcher` 校验 `http`/`https` 协议与 DNS 解析 IP（阻断回环/私网/链路本地/保留段），逐跳校验重定向，改用 `client.stream()` 增量执行 `_MAX_RSS_BYTES` 上限。
  - **验收**：单测覆盖 `file://`、`http://127.0.0.1`、`http://169.254.169.254`、重定向到私网及超 2 MiB 响应均被拒绝。
- [x] **OCR-11（风控与自动交易全局配置 BFLA）**：为 `src/backend/app/api/risk_control.py`（`PUT /config`, `DELETE /alerts`, `POST /reset-daily`）与 `src/backend/app/api/auto_trading.py`（`PUT /config`）收口至 `require_data_admin_user`（或实现按用户隔离并校验 `instance_id` 归属），同时为 `max_order_size` 增设合理上界。
  - **验收**：权限测试验证普通用户无法修改全局风控/自动交易配置或清空他人告警。
- [x] **OCR-12（模拟盘跨租户配置与日志隔离）**：重构 `src/backend/app/api/simulation.py`，为每个模拟实例使用 owner 隔离的 `runtime_dir` 存放 `config.yaml` 与 `logs/`，禁止非管理员写删共享 `STRATEGIES_DIR` 模板。
  - **验收**：单测验证用户 A 修改/清空实例配置与日志不影响用户 B 及共享模板目录。
- [x] **OCR-13（修复 `scripts/ops/start_app.sh` 覆盖 `APP_ENV` 与脚本缺陷）**：仅在外部显式传入 `APP_ENV`/`DEBUG` 时才透传给 `uvicorn`（默认尊重 `.env`）；修复 `FRONTEND_DIR` 校验顺序、启动失败时同步停止 `$FRONTEND_PID`、修正过期的 `./scripts/ops/*` 与安装命令路径，并启用 `set -euo pipefail`。
  - **验收**：`bash -n scripts/ops/start_app.sh` 通过，且模拟 `.env` 设 `APP_ENV=production` 时子进程环境变量不被覆盖为 `development`。

### B. 交易撮合、账务、回测分析与投研逻辑（8 项）

- [x] **OCR-14（模拟交易原子撮合与全量未平仓持仓统计）**：重构 `src/backend/app/services/paper_trading_service.py`，将订单 CAS、账户/持仓行锁（SQLite 辅以按 `account_id` 异步锁）、余额校验、成交入库与余额更新合入单一 `AsyncSession` 事务；`_update_account` 改为直接查询全部 `Position.size != 0` 记录，消除默认 `limit=100` 截断。
  - **验收**：新增并发双下单防双花单测 + 超过 120 条历史平仓/开仓记录时的 `total_equity` 精确性测试。
- [x] **OCR-15（修复组合页 `_paper_equity_points` 快照截断与饿死）**：修改 `src/backend/app/api/portfolio/api.py:1421-1470`，先按 `instance_id` 查出最新 `source='initial'` 边界，再按单实例限额倒序取最新点并升序返回。
  - **验收**：新增多实例且单实例超限时的回归测试，验证靠后实例不被饿死且保留最新净值点。
- [x] **OCR-16（解耦回测数据截断并修复 `avg_win`/`avg_loss` 恒 0）**：修改 `src/backend/app/api/analytics.py` 与 `src/backend/app/services/analytics_service.py`：先在全量数据上算指标与做日期过滤，再同步索引降采样 `klines` 与 `log_indicators`，导出支持全量或显式截断标记；补齐 `total_win_amount`/`total_loss_amount` 计算使 `avg_win`/`avg_loss` 真实非零。
  - **验收**：新增超 10,000 笔成交与带 `log_indicators` 日期区间查询单测，验证指标准确、数组等长、`avg_win`/`avg_loss` 正确。
- [x] **OCR-17（修复 `sanitize_trades` 截断小数手成交）**：修改 `src/backend/app/services/backtest/sanitize.py:95-100`，保留浮点 `size = abs(float(size_raw or 0))` 并校验 `math.isfinite(size) and size > 0`。
  - **验收**：新增 `0.1 BTC`、`1.75 ETH`、`NaN`/`Inf` 数量单测。
- [x] **OCR-18（修复 `ComparisonService` 崩溃、回撤反选与 IDOR）**：修改 `src/backend/app/services/comparison_service.py` 与 `src/backend/app/api/comparison.py`：透传 `user_id` 堵住 IDOR；统一结果字典构造器并序列化 `TradeRecord`；修正负值 `max_drawdown` 最佳值比较方向与空结果 `None` 哨兵；用 `dict` 优化 `_compare_equity`；路由层将 `ValueError` 转为 `404`。
  - **验收**：单测覆盖 `METRICS`/`TRADES`/`EQUITY` 创建与更新、负回撤排名、空结果 JSON 序列化及跨用户 `404/403`。
- [x] **OCR-19（修复 `AITradingService` 确认竞态、全站广播与日志死代码）**：修改 `src/backend/app/services/ai_trading_service.py`：确认前原子 `pop` 待确认项消除 TOCTOU；待确认通知改为用户作用域 WebSocket 频道；在 `process_trading_request` 与 `confirm_trade` 接入 `_persist_trade_log`。
  - **验收**：单测覆盖并发双确认仅 1 次成功、非全站广播、确认后 `/ai-trading/history` 可查询到记录。
- [x] **OCR-20（修复 `StockAnalysisPipeline` 涨跌幅百倍缩放与 `NaN`/`Inf`）**：修改 `src/backend/app/services/stock_analysis/pipeline.py`，移除 `_format_pct` 对已归一化 `change_pct` 的二次 `×100`，并在 `_float_or_none`/`_float_or_default` 中强制 `math.isfinite`。
  - **验收**：单测验证 `0.5%` 渲染为 `0.50%` 而非 `50.00%`，输入 `NaN`/`Inf` 价格与成交量可安全序列化为 JSON。
- [x] **OCR-21（修复采集脚本残留与股票/转债回填控制器缺陷）**：
  - 清理 `stock_zh_a_hist.py` 的 `sys.stderr.write`、补 `dropna` 后 `if df.empty:` 守卫、放行 `stock_zh_a_hist.py` 与 `bond_zh_hs_cov_daily.py` 的 DB 写入异常；
  - 同步 `stock_full_history_controller.py` 的 `920xxx -> bj` / `900xxx -> sh` 映射，并将 `ATTENTION_STATUSES` 提升为 `resolve_exit_code` 第一优先级；
  - 修复 `bond_convertible_history_controller.py`：全量计算缺口计数后再截断样本、补齐 `BOND_ZH_HS_COV_DAILY` 的 `source` DDL 与列存在守卫、`_as_day` 防 `NaN`/`Inf`、`_run_killable_probe` 增 `SIGKILL` 升阶、`_managed_repair` 传递 `"sina"` 而非 `"akshare"`。
  - **验收**：运行 `pytest tests/test_stock_full_history_controller.py tests/test_bond_convertible_history_controller.py` 并补充上述全部边界用例。

### C. 后端并发、进程生命周期、DB 连接池与异步阻塞（4 项）

- [x] **OCR-22（回测执行器单例化与超时/关停回收）**：在 `src/backend/app/services/backtest/runner.py` 暴露进程级默认单例 `get_default_backtest_runner()` 并接入 `BacktestService.__init__`；在 `backtest/service.py:902-923` 捕获 `TimeoutExpired` 后按进程组 `killpg` + `communicate()` 回收；在 `startup/reconcile.py:shutdown()` 调用 `runner.cancel_all()`。
  - **验收**：单测验证新实例化 `BacktestService` 可取消运行中任务、超时子进程被彻底终止回收。
- [x] **OCR-23（修复 `MonitoringService` 僵尸告警任务）**：将 `_monitoring_tasks` 与 `_trigger_state` 抽离为进程级单例注册表，`_monitor_task` 在 `finally` 中移除 key，并在 `src/backend/app/startup/__init__.py` 注册关停钩子。
  - **验收**：单测验证跨请求创建→禁用→再启用→删除规则不会产生重复或泄漏监控任务。
- [x] **OCR-24（修复 `app/db/database.py` 引擎池生命周期与锁安全）**：为 `_engines`/`_session_makers` 读写加 `threading.Lock`；修复 `_EngineProxy.dispose()` 避免新建引擎并移除缓存项；在 `SHUTDOWN_HOOKS` 统一释放主库、`akshare_data_database` 与 `RedisCache`；提供临时事件循环引擎释放机制；`verify_database_schema` 改用模块 `engine`；修复 `_rebuild_sqlite_chat_conversations_with_nullable_kb` 的 `PRAGMA foreign_keys=ON` `try/finally`。
  - **验收**：新增多事件循环与关停钩子单测，确认 `dispose()` 不触发新建引擎且连接池关闭干净。
- [x] **OCR-25（修复 WebSocket 空转泄漏、`script_worker_runtime` 竞态与 `async def` 同步阻塞）**：
  - `api/data/realtime.py:555-564` 与 `api/paper_trading.py:606-635` 改为 `receive_text()` 心跳循环并在 `finally` 断开；
  - `services/akshare/script_worker_runtime.py` 全程 `try/finally` 托管 `receipt_dir`、防止重复 `killpg`、消除异步超时与 `proc.communicate()` 竞态；
  - 将 `ths_history_runner.py:396, 488, 618`、`asset_info/gateway_specs.py` 异步调用方（`paper_trading_service`/`ai_trading_service`）与 `reqdocs_migration_service.py:682-700` 的同步网络/DB 调用移入 `asyncio.to_thread()`。
  - **验收**：单测验证客户端断连立即触发 `ws_manager.disconnect`、`script_worker_runtime` 异常不留临时目录、异步热路径无阻塞。

### D. 测试隔离、CI 门禁与生产迁移（1 项）

- [x] **OCR-26（清理 xfail 遮蔽、修复生产 SQLAlchemy bug、接入 `secret-scan` 阻断与补齐 MySQL 生产 fence）**：
  - 修复 `tests/test_iteration183_security.py:208`（显式传 `APP_ENV="production"`）；
  - 修复生产 bug `src/backend/app/services/market_data/publication.py:582`（改为 `self._db.sync_session.get_transaction()`）；
  - 从 `known_preexisting_failures.txt` 移除 3 项 CI 实际通过的 `weasyprint` 测试；修复 7 项缺 `users` 表的组合接口测试和 2 项过期签名/错误码测试；将 `conftest.py:134` 改为 `strict=True`；
  - 在 `.github/workflows/ci.yml:1755-1805` 将 `secret-scan` 纳入 `ci-summary` 阻断检查；
  - 在 `docker/compose/prod.yml` 与 `scripts/ops/docker_deploy.sh` 补全全部 12 个 `MARKET_DATA_*_MAINTENANCE_FENCE` 透传、为 `migrate` 增加 `APP_ENV: production` 并修正文档 compose 路径。
  - **验收**：上述定向测试全绿，`conftest.py` 启用 `strict=True` 无 XPASS 残留，`docker compose -f docker/compose/prod.yml config` 校验通过。

### E. 前端 Vue 3 / TypeScript 关键缺陷（6 项）

- [x] **OCR-27（修复 Axios 重试拦截器吞掉 `401` 与错误提示）**：移除 `src/frontend/src/api/index.ts:290-293` 中错误的 `isRetrying` 提前返回逻辑，并更新 `src/frontend/src/__tests__/api/` 相关单测。
  - **验收**：单测覆盖“瞬态 503 重试 1 次后返回 401”能正常触发 `expireSession` 与 toast。
- [x] **OCR-28（修复 AI 交易确认弹窗失败误发取消）**：拆分 `src/frontend/src/views/AITradingPage.vue:162-189` 中 `ElMessageBox.confirm` 与 `confirmTrade({ confirmed: true })` 的 `try/catch`，下单失败给出错误提示并刷新历史，取消调用单独捕获异常。
  - **验收**：新增 Vitest 测试验证 `confirmTrade({ confirmed: true })` 抛错时不会再发 `confirmed: false`。
- [x] **OCR-29（修复新闻外链 `window.open` URL 注入）**：在 `src/frontend/src/views/NewsIntelligencePage.vue:799-803` 使用 `new URL(...)` 校验仅允许 `http:`/`https:` 协议。
  - **验收**：新增 Vitest 测试覆盖 `javascript:alert(1)`、`data:text/html,...` 被阻断，合法 HTTPS 链接正常打开。
- [x] **OCR-30（修复组合页导入历史 >200 条分页重置 Bug）**：修改 `src/frontend/src/views/PortfolioPage.vue:1915-1934`，记录 `existingImportSourcesTotal`，仅在总条数变化或 `!result.has_more` 且累计不等时重置回第 1 页。
  - **验收**：新增 Vitest 测试覆盖 `total=250`（3 页）顺序加载第 1/2/3 页不重置。
- [x] **OCR-31（前后端接入 `refresh_token` 单飞自动续期）**：扩展 `src/frontend/src/types/index.d.ts` `Token` 接口、更新 `src/frontend/src/stores/auth.ts` 持久化 `refresh_token`、在 `src/frontend/src/api/auth.ts` 增加 `refresh()` 并在 `src/frontend/src/api/index.ts` 实现单飞 401 自动刷新与队列重放。
  - **验收**：新增 Vitest 测试覆盖并发 401 仅发 1 次 `/auth/refresh` 且重放原请求，刷新失败才登出。
- [x] **OCR-32（修复前端 WebSocket 孤儿连接、未捕获异常与心跳泄漏）**：修复 `DataTopicsPage.vue:443-484`（断开前解绑回调 + 局部引用守卫）、`useBacktestRuntime.ts:127-193` 与 `useOverfittingRuntime.ts:120-190`（重连前先清理旧连接、`ws.onmessage` 加 `try/catch`、`code === 1000` 也清理 `heartbeatTimer`）。
  - **验收**：新增 Vitest 测试覆盖快速重连、异步消息异常、正常关闭不残留定时器。

---

## P2 — 中优先级（共 7 项）

- [x] **OCR-33（收口未鉴权信息泄露端点）**：限制 `GET /api/v1/strategy/templates/{template_id:path}/config` 仅返回内置模板；为 `/api/v1/status/*`、`/info`、`/api/v1/metrics*`、`/api/v1/docs/postman` 补齐管理员鉴权或生产开关；精简 `/ready` 响应移除内部 AI provider `base_url` 并脱敏 `/metrics` 500 错误。
  - **验收**：匿名访问上述敏感信息端点返回 `401/403` 或不含内部拓扑/异常堆栈。
- [x] **OCR-34（收紧生产 `DEBUG=True` 与 IB Gateway TLS 默认值）**：在 `src/backend/app/config.py:162-197` 生产模式显式拒绝 `DEBUG=True`；将 `gateway/launch_builder.py:591`、`gateway/runtime.py:188`、`gateway/preset.py:107, 139` 的默认 `verify_ssl` 改为 `True` 并在生产环境运行期拒绝 `False`。
  - **验收**：补充单测验证 `APP_ENV=production` + `DEBUG=True` 校验失败及 IB Gateway 默认开启 TLS 校验。
- [x] **OCR-35（修复后台异步任务强引用、无界内存字典与清理缺口）**：为 `live_trading/execution.py`、`kb_chat_service.py`、`sync_service.py`、`workspace/run_ops.py` 的 `create_task` 补强引用与异常回调；为 `DataTopicHub._topics`、`SyncService._tasks`、`WSGateway._messages` 加上限/淘汰并修复 `close_idle_connections`；为 `AutoTradingScheduler` 增加 `shutdown()` hook；修复 `monitoring_control.py:701-742` 错误路径关闭 SQLite 连接。
  - **验收**：新增单元测试验证容量上限淘汰、空闲断连队列清空、异常路径关闭连接。
- [x] **OCR-36（修复数据层查询、能力台账并发、MySQL 安全卫生与时区边界）**：
  - `market_instrument_asset_adapter.py` 按索引 `data_date` 与显式 `adjustment` 查询并修复 `_lookup_fx_warehouse` 死代码回退；
  - `services/akshare/data.py` 将已验证的 `adjustment` filter 合并进 `observed_bases`；
  - `capability_ledger_admission.py` 改为按事件循环键控锁、使用独立会话/savepoint、协调 10 分钟观察窗与人工 attestation 冲突；
  - `mysql_base.py` 参数化 `SHOW TABLES LIKE`、校验标识符、独立 `try/finally` 关闭游标与连接；`akshare_provider.py` 按连接键缓存池；
  - `ac11_runtime_evidence.py` 统一转为 UTC；`stock_full_history_controller.py` 过滤 `inf`/`NAN`、透传超时并释放引擎。
  - **验收**：针对各模块运行对应 pytest 套件并新增边界回归用例。
- [x] **OCR-37（消除后端热接口 N+1 查询与分析器边界缺陷）**：批量化 `BacktestService.list_results`（并补 `sharpe_ratio`/`total_return` 联表排序）、`AIStrategyResearchService.list_run_records` 与 `list_approved_schedule_manifests` 查询；修复 `FincoreAdapter` `pnlcomm: None` 与回撤持续期 off-by-one；为 `perf_attribution`（Brinson/Fama-French）增加有限浮点输入与输出校验；修复 `StockAnalysisDataCollector` `missing_fields` 内容判定与异常日志。
  - **验收**：单测验证查询次数显著下降、排序生效、`pnlcomm=None`/超大数输入/空行情不再误报或 500。
- [x] **OCR-38（修复前端内存泄漏、多页请求竞态、`AuditTracker` 串户与 4xx 无限轮询）**：修复 `KnowledgeBaseDocumentPage.vue` `fullscreenchange` 移除；修复 `QuotePage.vue` 异步卸载守卫、`searchDebounce` 清理及 `quoteStore.searchSymbols` 序号守卫；修复 `StockAnalysisPage.vue`、`BacktestResultPage.vue`（路由 `watch`、`file://` 提示与下载 `catch`）、`BacktestPage.vue`、`PortfolioPage.vue`（ECharts 懒加载后复检 ref）；修复 `AuditTracker` 登出前 flush、按 `userId` 隔离本地队列与失败批次保留；修复 `usePortfolioAnalyticsTask.ts` 4xx 停止轮询。
  - **验收**：`npm run typecheck && npm run lint && npm run test -- --run` 全绿，并新增对应单测。
- [x] **OCR-39（修复 `nightly` 审计流、供应链一致性与开发/运维脚本漂移）**：修复 `nightly.yml` `dependency-audit` 退出码捕获与 `if: always()` 建 issue；统一 `src/backend/Dockerfile` 与 `requirements-prod.lock` Python 版本并引入 `--hash`；锁定 `radon` 与工作流 Actions SHA、加顶层 `permissions`、`check_complexity_budget.py` 接 `baseline_update_guard`；修复 `monorepo-check`、`e2e.yml` 缓存与 `curl -sf` 等待、`pr-check.yml` 运行时锁定；同步 `entrypoint-dev.sh`、`dev.yml`（`VITE_API_TARGET`）、`validate_docker_env.py` 与 `stop_app.sh`。
  - **验收**：YAML/Shell 语法校验通过，相关 CI 脚本本地运行通过。

---

## P3 — 低优先级与长期演进（共 5 项）

- [x] **OCR-40（消除 `scanners` 潜伏 IDOR）**：为 `src/backend/app/services/scanner_service.py` 与 `src/backend/app/api/scanners.py:244-251` 任务记录绑定并校验 `user_id`。
  - **验收**：单测验证不同用户无法读取他人 `task_id`。
- [x] **OCR-41（清理孤儿优化任务与静默 `except pass`/`assert`）**：修复 `src/backend/app/api/optimization_api.py:132-210` 提交失败时标记/清理已建任务；逐批清理 `src/backend/app/` 中 17 处静默 `except Exception: pass` 与运行时路径上的 `assert`。
  - **验收**：AST 扫描 `silent_except_pass` 清零，关键运行时校验改用显式异常。
- [x] **OCR-42（测试/门禁卫生与 32 处文档断链修复）**：`conftest.py` `pytest_sessionfinish` 清理临时日志目录；拧紧 `large_file_baseline.json` 中 `app/config.py` 基线；增强 `check_migration_safety.py` 阻断模式与 `check_alembic_heads.py` 失败退出；合并清理重复 pytest 配置；修复 `check_doc_links.py` 报出的 32 处断链。
  - **验收**：`python3 scripts/ci/check_doc_links.py` 退出码 `0`。
- [x] **OCR-43（前端三大巨型文件垂直切片）**：按 [AUDIT.md](AUDIT.md) 拆解 `useStrategyPage.ts`（5,272 行）、`useDataPage.ts`（4,853 行）、`StrategyPage.vue`（3,254 行），并同步向下拧紧 `large_file_baseline.json`。
  - **验收**：`vue-tsc`、`eslint`、`vitest` 与 `large_file_ratchet.py` 全绿。
- [x] **OCR-44（后端巨型文件拆分与圈复杂度棘轮下调）**：结合 characterization tests 分批拆分 `ai_strategy_research_service.py`（5,866 行）、`asset_research/orchestrator.py`（3,045 行）、`research/paper_handoff.py`（2,787 行）、`gateway/manual.py`（2,682 行），将 `complexity_baseline.json` 从 `max_cc=147 / count_cc_ge_50=64` 阶段性下调至 `max_cc=91 / count_cc_ge_50=31`（清零所有 `CC >= 100` 块并使 `CC >= 50` 计数减半以上）。
  - **验收**：`python3 scripts/ci/check_complexity_budget.py` 与受影响模块测试套件全绿。
