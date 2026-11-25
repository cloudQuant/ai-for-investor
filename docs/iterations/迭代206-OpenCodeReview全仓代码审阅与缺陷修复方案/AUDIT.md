# 迭代206：OpenCodeReview 全仓审阅详细报告（AUDIT）

> 基线：`dev` @ `5b9a3a280`  
> 审阅框架：`open-code-review v1.13.11` Host-Agent Delegation（`ocr delegate` 规则集 + `ocr scan --preview` + 确定性 E1 检查）  
> 口径说明：**E1 = 本机命令实测复现**；**E2 = 源码与调用链静态确认**；**E3 = 需在 MySQL/PostgreSQL/生产环境动态验证**。所有条目均已对照源码核验，不重复报告迭代205已关闭项（仅记录新缺陷、回归或未闭环缺口）。

---

## 一、P0 — 阻断级缺陷（8 项）

### OCR-01 [P0 / 安全-密钥泄露 / E1] 跟踪证据日志明文暴露真实 `OKX_API_KEY`，且 `conftest.py` 泄漏 `.env`
- **位置**：
  - `docs/iterations/迭代205-全仓代码审查与质量门禁收口/evidence/full-suite-20261118.txt:322-371, 3872-3873, 6424-6425`
  - `src/backend/tests/conftest.py:24-70`
- **审阅证据**：
  - 已纳入 git 跟踪的 `full-suite-20261118.txt`（776 KB）在 22 行 pytest `AssertionError` 差异中明文记录了 `OKX_API_KEY='8cc6****ebd0'`（与本地 `src/backend/.env:207` 一致）。
  - 根因在于 `conftest.py` 导入 `app.main` 前未关闭 `Settings.model_config["env_file"]`，导致每次本地跑测都会读取开发者 `.env` 中的真实交易所密钥与 `DEBUG=True`，既破坏测试隔离性又导致失败日志泄露密钥。
- **修复建议**：
  1. 立即在交易所侧吊销/轮换该 `OKX_API_KEY`。
  2. 删除或脱敏 `full-suite-20261118.txt`（按团队安全流程评估 git 历史清理）。
  3. 在 `conftest.py` 导入 `app.db.database` / `app.main` 之前禁用 `Settings.model_config["env_file"] = None` 并清空敏感券商/交易所环境变量。

---

### OCR-02 [P0 / 安全-未鉴权伪造 / E2] Airflow 回调接口无鉴权，允许任意匿名请求伪造 `TaskExecution`
- **位置**：`src/backend/app/api/airflow_callback.py:22-66`（`receive_airflow_callback`，挂载于 `POST /api/v1/data/airflow/callback`）
- **审阅证据**：
  - 接口仅注入 `db: AsyncSession = Depends(get_db)`，无任何 Token、HMAC 签名或来源校验；直接根据请求体构造 `TaskExecution(status=..., rows_before=..., rows_after=..., result=...)` 并 `await db.commit()`。
  - 匿名攻击者可批量伪造 `COMPLETED`/`FAILED` 记录，污染数据任务监控或掩盖真实采集失败。
- **修复建议**：强制校验共享密钥 HMAC 签名或专用 Bearer Callback Token（使用 `secrets.compare_digest`），生产环境未配置密钥时 fail-closed 返回 `503`。

---

### OCR-03 [P0 / 安全-跨租户 IDOR / E2] 旧版实盘网关接口缺少归属/管理员校验，任意登录用户可读他人实盘账户与持仓
- **位置**：
  - `src/backend/app/api/live_trading/api.py:121-139, 186-238`（`get_gateway_health`, `list_connected_gateways`, `query_gateway_account`, `query_gateway_positions`）
  - `src/backend/app/services/live_trading/manager.py:445-484, 539-554`
- **审阅证据**：
  - 同文件第 105-107 行 `GET /gateways/credentials` 已要求 `Depends(require_data_admin_user)`，但紧随其后的 4 个网关接口仅校验 `Depends(get_current_user)`，且 `LiveTradingManager._gateways` 无 owner 字段，也不传 `current_user.sub`。
  - 任意普通注册用户可调用 `/gateways/connected` 或 `/gateways/health` 枚举所有 `gateway_key`，再调用 `/gateways/{gateway_key}/account` 与 `/positions` 读取他人实时资金、保证金与持仓。另 `get_gateway_health`（第 137 行）在 500 响应中直接返回 `{type(exc).__name__}: {exc}`。
- **修复建议**：将上述 4 个旧版全局网关接口收口至 `Depends(require_data_admin_user)`（或退役并迁移至带 `require_persisted_owner_scope` 的 `service_gateway_operator` / `service_read`），并脱敏 500 错误详情。

---

### OCR-04 [P0 / CI 阻断回归 / E1] `large_file_ratchet.py` 在当前 HEAD 红灯（EXIT 1）
- **位置**：
  - `scripts/ci/large_file_ratchet.py:26, 68-83`
  - `src/backend/app/api/portfolio/api.py`（1957 行 > 基线 1948 行）
  - `src/backend/app/db/database.py`（1030 行 > 新增文件上限 1000 行）
  - `.github/workflows/ci.yml:430-432`（阻塞 `backend-lint` 及下游全部测试任务）
- **审阅证据**：本机执行 `python3 scripts/ci/large_file_ratchet.py` 退出码 `1`，明确报告上述两文件回归（由迭代205 WP05 修改引入）。
- **修复建议**：将 `db/database.py` 中约 650 行历史运行时兼容 DDL 抽离出核心引擎模块，并将 `portfolio/api.py` 中的净值采样辅助逻辑抽至独立子模块，**禁止靠上调基线绕过**。

---

### OCR-05 [P0 / 数据静默损坏 / E2] `STOCK_ZH_A_HIST` 不复权覆盖前复权、DDL 缺列且唯一键冲突、东财回退误标腾讯来源
- **位置**：
  - `src/backend/app/data_fetch/scripts/stocks/daily/stock_zh_a_hist.py:22-33, 218-246, 266-290`
  - 触发调用方：`src/backend/app/services/akshare/script.py:1211-1218`
- **审阅证据**：
  1. `script.py:1216` 对 `stock_zh_a_hist` 传入 `"adjust": ""`（不复权），但 `stock_zh_a_hist.py:267` 写成 `str(kwargs.get("adjust") or "qfq")`，因 `""` 为 falsy 被静默标记为 `"qfq"` 并用不复权价格覆盖前复权记录。
  2. `create_table_sql`（第 22-33 行）未声明 `source`、`adjustment` 列，且 `UNIQUE KEY uk_symbol_date (symbol, data_date)` 与写入参数 `unique_keys=["symbol", "data_date", "adjustment"]` 矛盾；写入 `hfq` 会触发 `(symbol, data_date)` 冲突并把价格列覆写成 `hfq` 而 `adjustment` 仍残留 `'qfq'`。
  3. 当显式指定 `source="tencent"` 且第 220 行返回空时，第 233-236 行重复调用腾讯源一次，随后第 238 行仍无条件回退到东财 `trends2`（不复权分时聚合），却保留 `source_used = "tencent"` 且打上 `adjustment="qfq"`。
- **修复建议**：显式区分 `adjust == ""`（如规范化为 `"none"` 或空串口径，不回退 `"qfq"`）；更新 `create_table_sql` 与存量表迁移，将 `(symbol, data_date, adjustment, source)` 纳入 DDL 与唯一键；消除腾讯源二次调用，并在显式 `source="tencent"` 时禁止回退东财；`auto` 回退 `trends2` 时如实标注来源与复权口径。

---

### OCR-06 [P0 / 采集运行回归 / E2] `script_worker_runtime._execute_callable` 剥离全部 `_` 参数，静默丢弃 150+ 脚本的 `_call_timeout`
- **位置**：
  - `src/backend/app/services/akshare/script_worker_runtime.py:421-425`
  - 受影响调用方：`src/backend/app/services/akshare/script.py:518-1639`（150+ 处）、`src/backend/scripts/bond_convertible_history_controller.py:1420`、`stock_zh_a_hist.py:67-68`、`akshare_to_mysql.py:101`、`daily_market_data.py:324`
- **审阅证据**：第 421-425 行用 `if not str(key).startswith("_")` 过滤所有下划线参数，导致全部脚本与回填控制器下发的 `_call_timeout`（如 8s/30s 快速失败阈值）被静默丢弃，退回全局 120s 超时。
- **修复建议**：将 `"_call_timeout"` 列入白名单保留（仅过滤调度元数据键），并交由 `_signature_parameters` 仅对不接收 `**kwargs` 且未声明 `_call_timeout` 的原生 `ak.*` 函数做剔除。

---

### OCR-07 [P0 / 数据写入缺陷 / E2] `AkshareProvider._align_df_to_table` 宣称忽略未知列却未裁剪，且 `save_data` 异常路径泄漏连接
- **位置**：`src/backend/app/data_fetch/providers/akshare_provider.py:344-377, 423-480`
- **审阅证据**：
  1. `_align_df_to_table` 第 373 行记录日志 `"表 {table_name} 将忽略 {len(unknown)} 个不存在的列"`，但第 377 行直接返回 `df.rename(columns=column_mapping).copy()` 未丢弃 `unknown` 列，导致任意上游新增字段都会在 `executemany` 报 `OperationalError(1054, Unknown column)`。
  2. `save_data` 第 423 行在 `try...finally: self.disconnect_db()`（第 449 行）之前执行 `self.connect_db()`，非法标识符校验、提前 `return False` 或 SQL 构造异常均会泄漏 `PooledDB` 连接；且第 445-446 行缺少 `math.isfinite` 与 `dict/list` 序列化保护。
- **修复建议**：先按 `column_mapping` 裁剪列再重命名；将 `try...finally: self.disconnect_db()` 提前包裹 `self.connect_db()`；对齐 `mysql_base.py` 的非有限浮点与容器值清洗逻辑。

---

### OCR-08 [P0 / 数据写入契约回归 / E2] `save_data` 返回 `affected` 破坏 15+ 处布尔调用方，且 `ON DUPLICATE KEY UPDATE` 双倍计数
- **位置**：
  - `src/backend/app/data_fetch/core/mysql_base.py:223-244, 436-460`
  - `src/backend/app/data_fetch/providers/akshare_provider.py:286-304, 452-474`
  - 受影响脚本：`akshare_catalog_endpoint.py:87-88`、`index_zh_a_hist_min_em.py:314-333`、`stock_hk_index_spot_em.py:156-165` 等 15+ 个 `data_fetch/scripts/` 脚本
- **审阅证据**：
  1. 幂等重跑时全部行无变化，`save_data` 返回 `0`（falsy），导致按 `if success:` / `bool(ok)` 判断的脚本将其误报为 `"Failed to save data"` 并返回 `False`。
  2. MySQL 对 `ON DUPLICATE KEY UPDATE` 每更新 1 行返回 `rowcount = 2`；`_execute_batch` 使用 `min(reported, len(batch))` 在部分更新批次中会把更新行数放大 2 倍并写入 `committed_writes` 回执。
- **修复建议**：将脚本侧成功判定统一为 `saved is not False`（或明确的 `SaveResult` 结构）；区分 MySQL 原始 `affected_rows` 与去重写入行数（或按需使用 `ClientFlag.FOUND_ROWS` 并诚实记录语义）。

---

## 二、P1 — 高优先级缺陷（24 项）

### A. 安全、RBAC 与部署边界（OCR-09 ~ OCR-13）

#### OCR-09 [P1 / 安全-BFLA / E2] Airflow DAG 编排接口缺少管理员权限校验
- **位置**：`src/backend/app/api/airflow_dags.py:46-137`（`list_dags`, `get_dag`, `trigger_dag`, `toggle_dag_pause`, `list_dag_runs`, `get_task_instances`, `get_task_log`, `get_orchestration_status`）
- **证据**：全部端点使用 `Depends(get_current_user)` 而非 `Depends(require_data_admin_user)`，普通用户可带任意 `conf` 触发/暂停生产 DAG 并读取内部 worker 任务日志。
- **修复建议**：路由级强制 `dependencies=[Depends(require_data_admin_user)]`，并对 `dag_id`/`dag_run_id`/`task_id` 增加严格正则校验。

#### OCR-10 [P1 / 安全-SSRF / E2] 新闻情报 RSS 抓取存在 SSRF、盲测预言机与内存放大
- **位置**：`src/backend/app/api/news_intelligence.py:13-48`、`src/backend/app/services/news_intelligence.py:53-85, 177-222, 354-379`
- **证据**：`add_source()` 不校验 URL scheme 或目标 IP，`_default_rss_fetcher()` 开启 `follow_redirects=True` 发起服务端请求，可探测内网/元数据服务（`169.254.169.254`、`127.0.0.1` 等）；`fetch_failed` vs `invalid_feed` 提供盲 SSRF 预言机；`_MAX_RSS_BYTES`（2 MiB）仅在 `response.text` 全量缓冲后校验。
- **修复建议**：限制仅允许 `http`/`https`，DNS 解析后阻断回环/私网/链路本地/保留 IP 段，关闭自动重定向或逐跳校验目标，改用 `client.stream()` 流式限长读取。

#### OCR-11 [P1 / 安全-BFLA / E2] 风控与自动交易全局单例配置可被任意普通用户修改/清空
- **位置**：`src/backend/app/api/risk_control.py:156-195, 253-312`、`src/backend/app/api/auto_trading.py:36-54`
- **证据**：`PUT /risk-control/config`、`DELETE /risk-control/alerts`、`POST /risk-control/reset-daily`、`PUT /auto-trading/config` 均仅要求 `get_current_user` 且直接修改全局单例，普通用户可关闭全局止损/仓位风控、清空他人告警或改写全局自动交易时段。
- **修复建议**：全局操作收口为 `Depends(require_data_admin_user)`，按实例操作校验 `instance_id` 归属（或迁移至按用户隔离配置）。

#### OCR-12 [P1 / 安全-跨租户篡改 / E2] 模拟盘 API 直接读写共享策略模板目录的 `config.yaml` 与 `logs/`
- **位置**：`src/backend/app/api/simulation.py:281-308, 354-431, 473-625`
- **证据**：`_get_strategy_config_path` 与 `_get_strategy_log_dir` 解析 `get_strategy_dir(inst["strategy_id"])`（磁盘共享 `strategies/<type>/<name>/` 目录），任何普通用户创建引用共享模板的模拟实例后，即可覆盖所有用户的 `config.yaml` 并读取/清空他人模拟日志。
- **修复建议**：为每个模拟实例分配 owner 隔离的 `runtime_dir` 存放配置与日志，禁止非管理员写删共享模板目录。

#### OCR-13 [P1 / 部署安全 / E2] `scripts/ops/start_app.sh` 覆盖 `.env` 中的 `APP_ENV=production` 及多处脚本缺陷
- **位置**：`scripts/ops/start_app.sh:7, 112, 122, 158, 191-208, 227-232, 266-274, 303-304`、`src/backend/app/config.py:71-88`
- **证据**：
  1. `start_app.sh:205-207` 未加载 `.env` 却始终透传 `env APP_ENV="${APP_ENV:-development}" DEBUG="${DEBUG:-false}"`，进程环境变量优先级高于 `.env` 且 `config.py:79-81` 优先信任显式 `APP_ENV`，导致 `.env` 配 `APP_ENV=production` 时所有生产安全守卫被静默关闭。
  2. 第 227 行在校验 `FRONTEND_DIR` 存在前先 `cd`（在 `set -e` 下提前退出）；第 266-274 行健康检查失败仅清理 `$BACKEND_PID` 遗留孤儿前端进程；第 112/122/158/303-304 行脚本与 `requirements.txt` 路径均过期；缺少 `set -euo pipefail`。
- **修复建议**：仅当调用方环境显式设置 `APP_ENV`/`DEBUG` 时才透传给 `uvicorn`（默认交由 `pydantic-settings` 读取 `.env`）；修复目录校验顺序、孤儿进程清理、提示路径并启用 `set -euo pipefail`。

---

### B. 交易撮合、账务、回测分析与投研逻辑（OCR-14 ~ OCR-21）

#### OCR-14 [P1 / 账务并发与截断 / E2] 模拟交易撮合非原子化可双花现金，且 `_update_account` 截断超百条持仓
- **位置**：`src/backend/app/services/paper_trading_service.py:927, 986-1161, 1457-1499`、`src/backend/app/services/legacy_paper_migration.py:551-570`
- **证据**：
  1. `legacy_paper_writer_lease` 写完租约立即提交释放锁；`submit_order` 读取的陈旧 `account` 在 `_process_order` 中跨多个自动提交 `SQLRepository` 会话分别更新订单、成交、持仓与账户，并发下单可绕过余额检查造成双花/丢更新，中途失败会留下 `FILLED` 订单却未扣钱/加仓。
  2. `_update_account:1457` 调用 `position_repo.list(filters={"account_id": account.id})` 未传 `limit`（默认 `100` 且无 `ORDER BY`），而平仓记录 `size=0.0` 永不删除，超过 100 条历史持仓后打开仓位被截断，导致 `total_equity`、`profit_loss` 算错。
- **修复建议**：将订单状态 CAS、余额/持仓加锁更新与成交入库包入单一 `AsyncSession` 事务（MySQL/PG 用 `SELECT ... FOR UPDATE`，SQLite 辅以按 `account_id` 粒度异步锁）；`_update_account` 仅查询 `Position.size != 0` 的未平仓持仓且不设隐式 100 条上限。

#### OCR-15 [P1 / 分析回归 / E2] 组合页 `_paper_equity_points` 全局 `ASC + LIMIT 200_000` 丢弃近期净值并饿死其他实例
- **位置**：`src/backend/app/api/portfolio/api.py:220, 1421-1470`
- **证据**：单条 SQL 按 `instance_id ASC, observed_at ASC, id ASC LIMIT 200_000` 拉取多实例快照，再在 Python 中按 `source == "initial"` 截取当前轮次；历史快照超 20 万行时会丢弃最新净值与当前轮 `initial` 标记，并导致字典序靠后的实例返回 0 行被误判 `paper_snapshot_unavailable`。
- **修复建议**：先在 SQL 按 `instance_id` 分组查出最新 `source='initial'` 边界，再基于窗口函数按单实例限额倒序取最新点后升序还原。

#### OCR-16 [P1 / 分析回归与指标错误 / E2] 回测 `get_backtest_data` 前置截断失真，且 `avg_win`/`avg_loss` 恒为 `0.0`
- **位置**：`src/backend/app/api/analytics.py:354-368, 394-412, 463-496, 581-641`、`src/backend/app/services/analytics_service.py:47-110`、`src/backend/app/services/metrics_service.py:11-45`
- **证据**：
  1. `get_backtest_data` 无条件截断 `trades[:10_000]`/`signals[:10_000]` 并降采样 `equity_curve`/`klines`，导致 `get_backtest_detail` 基于截断数据算错核心绩效指标、`get_kline_with_signals` 的 `log_indicators` 未同步降采样/过滤导致数组错位、区间缩放丢失后期信号、CSV/JSON 导出静默截断。
  2. `AnalyticsService.calculate_metrics:84-87` 读取 `total_win_amount`/`total_loss_amount`，但 `calculate_metrics_from_log_data` 与 `MetricsService._STANDARD_KEYS` 均不包含这两项，导致详情接口 `avg_win` 与 `avg_loss` 恒返回 `0.0`。
- **修复建议**：将原始加载与响应裁剪解耦——先在全量数据上计算指标并完成日期过滤，再对 `klines` 与 `log_indicators` 同步索引降采样，导出接口流式输出全量或显式标记截断；在 `calculate_metrics`（或 `MetricsService`）补算 `total_win_amount`/`total_loss_amount`。

#### OCR-17 [P1 / 交易正确性 / E2] `sanitize_trades` 将成交数量强转 `int`，静默丢弃全部 `< 1.0` 小数手交易
- **位置**：`src/backend/app/services/backtest/sanitize.py:95-100`
- **证据**：尽管 `TradeRecord.size` 为 `float`，`sanitize_trades` 仍执行 `size = int(abs(float(size_raw or 0)))`，导致 `0.1 BTC`、`0.5 ETH`、`0.05` 手外汇成交全部归零并被 `if size <= 0: continue` 静默丢弃，`1.75` 被截断为 `1`。
- **修复建议**：保留浮点 `size = abs(float(size_raw or 0))`，校验 `math.isfinite(size) and size > 0`。

#### OCR-18 [P1 / 正确性+IDOR / E2] `ComparisonService` 必现 `KeyError`、最大回撤排名反置、`±inf` 序列化崩溃与 IDOR
- **位置**：`src/backend/app/services/comparison_service.py:70-87, 192-224, 257-260, 290-292, 363-378`、`src/backend/app/api/comparison.py:41-66`
- **证据**：
  1. `create_comparison` 缺少 `profitable_trades`/`losing_trades` 且塞入原始 Pydantic `TradeRecord` 对象，创建 `TRADES` 对比必崩；`update_comparison` 缺少 `annual_return`/`total_trades` 等字段，更新 `METRICS`/`TRADES` 必崩。
  2. `max_drawdown` 按负百分比存储（如 `-25.0` vs `-5.0`），但 `_find_best_metrics` 用 `<` 比较，把**最深回撤**选为最佳；空结果时保留 `±inf` 导致 JSON 序列化失败。
  3. 调用 `self.backtest_service.get_result(task_id)` 未传 `user_id=user_id`，任意用户可对比他人私有回测；`api/comparison.py` 未捕获 `ValueError` 返回 500；`_compare_equity` 在循环内用 `list.index()` 造成 $O(N \cdot M^2)$。
- **修复建议**：透传 `user_id=user_id`；抽出统一结果字典构造器并用 `model_dump(mode="json")`；按 `abs(val)` 最小（或负值最大）比较回撤并用 `None` 作初始哨兵；改用 `dict` 映射日期对齐；路由层将 `ValueError` 转为 `HTTPException(404)`。

#### OCR-19 [P1 / 并发+安全+死代码 / E2] `AITradingService` 存在确认竞态、全站 WebSocket 广播私密交易与日志落库死代码
- **位置**：`src/backend/app/services/ai_trading_service.py:303-379, 482-523, 949-974`
- **证据**：
  1. `confirm_trade` 在 `await _reassess_confirmed_trade(...)` 之后才 `del _pending_trades[request.trade_id]`，并发确认会重复评估并引发 `KeyError`。
  2. `_notify_confirmation_needed:972` 调用 `ws_manager.broadcast(message)`，将用户私密待确认交易广播给全站所有已连接客户端。
  3. `_persist_trade_log` 从未被任何路径调用，导致 `GET /ai-trading/history` 与 `POST /ai-trading/reflect/{trade_id}` 恒为空/404。
- **修复建议**：校验归属与过期后在 `await` 前原子 `pop` 待确认项；改为按用户频道定向推送；在 `process_trading_request` 与 `confirm_trade` 接入 `_persist_trade_log`。

#### OCR-20 [P1 / 金融计算 / E2] `StockAnalysisPipeline` 涨跌幅二次乘 100 失真且未过滤 `NaN`/`Inf`
- **位置**：`src/backend/app/services/stock_analysis/pipeline.py:183, 823-826, 867-872, 956-962, 1041-1046, 1107-1129`
- **证据**：`_normalize_change_pct` 已将 `0.005`（0.5%）转为 `0.5`，`_format_pct` 再次判断 `abs(numeric) <= 1` 并乘 100，使 `[-1%, +1%]` 区间涨跌幅被放大 100 倍（`0.5%` → `50.00%`）；`_float_or_none`/`_float_or_default` 放行 `NaN`/`Inf`，导致 `int(volume)` 崩或 JSON 序列化失败。
- **修复建议**：明确区分百分比值与小数比率格式化函数，移除 `_format_pct` 中的二次启发式缩放；在 `_float_or_none`/`_float_or_default` 强制 `math.isfinite` 校验。

#### OCR-21 [P1 / 采集与回填管道 / E2] 日线脚本调试残留/吞异常，股票与转债回填控制器多处契约与边界缺陷
- **位置**：
  - `src/backend/app/data_fetch/scripts/stocks/daily/stock_zh_a_hist.py:249-296`、`bonds/daily/bond_zh_hs_cov_daily.py:81-83`
  - `src/backend/scripts/stock_full_history_controller.py:555-567, 817-830, 945, 1196-1204`
  - `src/backend/scripts/bond_convertible_history_controller.py:225-258, 417-472, 507, 1129-1182, 1341-1461`
- **证据**：
  1. `stock_zh_a_hist.py` 残留 `sys.stderr.write("stock save payload ...")`、`dropna` 后空表触发 `df["symbol"].iloc[-1]` 越界、并与 `bond_zh_hs_cov_daily.py` 一样捕获所有 DB 写入异常返回空 DataFrame。
  2. `stock_full_history_controller.py` 的 `_prefixed_symbol` 未同步北交所 `920xxx -> bj` 与沪 B `900xxx -> sh`；`resolve_exit_code` 先判 `STATUS_SOURCE_FAILED`/`STATUS_DEFERRED_BUDGET` 再判 `ATTENTION_STATUSES`，掩盖真实失败状态并与 `run_full_history_recovery_worker.py:805` 分类契约冲突。
  3. `bond_convertible_history_controller.py` 基于截断后的 `source_only[:400]` 统计缺口计数（缺 >400 交易日时尾缺口归零）；`MySQLConvertibleReader` 未检查列存在即查询 `source`（新表缺该列直接 SQL 报错）；`_as_day` 未防 `NaN`/`Inf`；`_run_killable_probe` 仅 `terminate()` 无 `kill()` 升阶易留孤儿进程；`_managed_repair` 传入 `DataScript.source` 默认值 `"akshare"` 覆盖 `"sina"` 导致 `sina_row_count` 漏计。
- **修复建议**：逐项清理调试输出与空表守卫、放行 DB 异常；统一符号前缀映射与 `ATTENTION_STATUSES` 最高退出码优先级；全量统计缺口后再截断样本、补齐 `BOND_ZH_HS_COV_DAILY` 的 `source` DDL/防御查询、增加 `math.isfinite`、`SIGKILL` 升阶与 `"sina"` 来源透传。

---

### C. 后端并发、进程生命周期、DB 连接池与异步阻塞（OCR-22 ~ OCR-25）

#### OCR-22 [P1 / 进程生命周期 / E2] `BacktestService` 非单例 Runner 导致运行中回测无法取消，且超时子进程永不回收
- **位置**：`src/backend/app/services/backtest/service.py:149, 902-923, 1186-1192`、`workspace/run_ops.py:862, 1224, 1268`、`ai_strategy_research_task_manager.py:449-450`、`ai_strategy_research_service.py:4751-4752`、`startup/reconcile.py:49-50`
- **证据**：`BacktestService.__init__` 默认新建独立 `BacktestExecutionRunner()`，而工作区与 AI 研究每次调用都新建 `BacktestService()`，导致 `cancel_task()` 始终查不到进程句柄返回 `False`；`_run_strategy_subprocess` 在 `TimeoutExpired` 时未 `kill()`/`reap` 子进程并直接注销句柄；关停钩子只改 DB 状态不中止本地子进程。
- **修复建议**：提供进程级默认单例 `get_default_backtest_runner()`；超时分支用进程组 `killpg` + `communicate()` 回收；在 `startup/reconcile.py:shutdown()` 调用 `runner.cancel_all()`。

#### OCR-23 [P1 / 生命周期 / E2] `MonitoringService` 按请求实例化却持有任务表，导致僵尸监控循环与重复告警
- **位置**：`src/backend/app/api/monitoring.py:247-260`、`src/backend/app/services/monitoring_service.py:81-83, 132-193, 326-408`、`startup/__init__.py:32-40`
- **证据**：`get_monitoring_service()` 每次请求新建实例，但 `_monitoring_tasks`/`_trigger_state` 是实例属性；禁用/删除规则时无法取消之前创建的 `while True` 睡眠任务，反复启停会产生并发重复告警，且退出循环未清理 key、应用关闭未取消任务。
- **修复建议**：将任务注册表与触发状态抽离为进程级单例管理器，`_monitor_task` 在 `finally` 中移除 `rule_id`，并在 `SHUTDOWN_HOOKS` 中注册关停清理。

#### OCR-24 [P1 / DB 连接池生命周期 / E2] `app/db/database.py` 存在连接池未释放、临时事件循环泄漏、无锁并发与双轨 DDL
- **位置**：`src/backend/app/db/database.py:31-35, 104-166, 191-882, 898-902`、`startup/database.py:15-28`、`db/akshare_data_database.py:47-64`、`db/cache.py:150-154`
- **证据**：
  1. `SHUTDOWN_HOOKS` 从未调用主库 `engine.dispose()`、`akshare_data_engine.dispose()` 或 `RedisCache.redis.aclose()`。
  2. `_engines` 使用 `WeakKeyDictionary` 缓存 MySQL 池化引擎，短生命周期 `asyncio.run()` 循环回收时引擎未 `dispose()` 即被丢弃，泄漏 MySQL TCP 连接。
  3. `_EngineProxy.dispose()` 调用 `_get_engine().dispose()`，当前循环无缓存时会新建一个引擎再销毁；多线程读写 `_engines`/`_session_makers` 缺少 `threading.Lock`。
  4. `verify_database_schema` 绕过模块级 `engine` 代理；~650 行运行时兼容 DDL 仍与 Alembic 双轨并存，且 `_rebuild_sqlite_chat_conversations_with_nullable_kb` 开启 `PRAGMA foreign_keys=OFF` 缺少 `try...finally` 恢复。
- **修复建议**：加 `threading.Lock` 保护引擎缓存；`dispose()` 不触发新建引擎且从缓存弹出；注册 `database.shutdown` hook 统一释放主库/AkShare/Redis；为临时循环提供显式释放上下文；`verify_database_schema` 改用模块 `engine`；拆离历史兼容 DDL 以收口双轨并修复 `large_file_ratchet`。

#### OCR-25 [P1 / 异步阻塞与资源泄漏 / E2] WebSocket 空转泄漏、`script_worker_runtime` 资源竞态及 `async def` 热路径同步 I/O
- **位置**：
  - `src/backend/app/api/data/realtime.py:555-564`、`src/backend/app/api/paper_trading.py:606-635`
  - `src/backend/app/services/akshare/script_worker_runtime.py:212-257, 303-358`
  - `src/backend/app/services/market_data/ths_history_runner.py:396, 488, 618`
  - `src/backend/app/services/asset_info/gateway_specs.py:59, 107`（调用点：`paper_trading_service.py:939, 1019`、`ai_trading_service.py:196, 411, 803, 812`）
  - `src/backend/app/services/reqdocs_migration_service.py:641, 682-700`
- **证据**：
  1. 两处 WebSocket 处理器循环仅 `await asyncio.sleep(1)` 不读 socket 帧，Starlette 永远检测不到断开，每断连 1 次泄漏 1 个常驻协程与 `ws_manager` 注册项。
  2. `script_worker_runtime.py` 中 `mkdtemp` 在 `try/finally` 之外（序列化/启动异常泄漏临时目录）、超时对已回收 PID 二次 `killpg`、异步超时时事件循环阻塞 `proc.wait()` 与工作线程 `proc.communicate()` 并发竞态。
  3. `ths_history_runner.py` 仍有 3 处 `fetch_ths_json` 同步阻塞 HTTP+`time.sleep`；交易热路径 `paper_trading_service`/`ai_trading_service` 直接调用同步 `pymysql.connect`；`reqdocs_migration_service` 在 `async def` 中同步连 MySQL/Mongo。
- **修复建议**：WebSocket 改为 `receive_text()` 心跳循环并在 `finally` 断开；`script_worker_runtime` 全程托管临时目录、防重复 kill、用进程组信号+等待线程替代竞态；所有 `async def` 同步网络/DB 调用移入 `asyncio.to_thread()` 或改用异步驱动。

---

### D. 测试隔离、CI 安全门禁与生产迁移（OCR-26）

#### OCR-26 [P1 / 测试遮蔽+CI 绕过+生产迁移 / E1+E2] `conftest` xfail 遮蔽安全回归与生产 bug、`secret-scan` 未阻断 `ci-summary`、MySQL 生产迁移缺 fence 变量
- **位置**：
  - `src/backend/tests/conftest.py:25, 112-138`、`src/backend/tests/known_preexisting_failures.txt:1-30`
  - `src/backend/tests/test_iteration183_security.py:203-222`
  - `src/backend/app/services/market_data/publication.py:582`
  - `.github/workflows/ci.yml:1755-1805`
  - `docker/compose/prod.yml:5, 8, 126-154`、`scripts/ops/docker_deploy.sh:384-385`
- **证据**：
  1. `conftest.py:134` 以 `strict=False` 批量 xfail 30 个测试，实测根因包括：**1 项迭代205 安全回归**（`test_iteration183_security.py:208` 未传 `APP_ENV="production"` 导致生产安全测试不报 `ValidationError`）、**1 项真实 SQLAlchemy 2.0 生产 bug**（`publication.py:582` `self._db.get_transaction()` 抛 `NotImplementedError`，应改用 `self._db.sync_session.get_transaction()`）、**3 项在 CI 实际通过的 PDF 安全测试**（因 `strict=False` 会静默掩盖未来 XSS 回归）、**7 项缺少 `users` 表的组合接口测试**、**2 项过期签名/错误码测试**及 16 项环境/SDK 集成测试。
  2. `ci.yml:1755-1805` 将 `secret-scan` 标为 advisory 且未加入 `Fail if any blocker job failed`，PR 泄露密钥时 `ci-summary` 仍为绿灯。
  3. `docker/compose/prod.yml` 与 `docker_deploy.sh` 仅透传 12 个 MySQL 迁移所需 `MARKET_DATA_*_MAINTENANCE_FENCE` 中的 2 个，且 `migrate` 服务缺 `APP_ENV: production`，文档引用不存在的根 `docker-compose.yml`。
- **修复建议**：立即修复上述生产 bug 与可修单测，从白名单移除 CI 已过项并将 `conftest.py` 改为 `strict=True`；将 `secret-scan` 纳入 `ci-summary` 阻断列表；在 `prod.yml`/`docker_deploy.sh` 补全全部 12 个 fence 透传（或统一维护开关）及 `APP_ENV: production`。

---

### E. 前端 Vue 3 / TypeScript 关键缺陷（OCR-27 ~ OCR-32）

#### OCR-27 [P1 / 前端鉴权与错误吞没 / E2] Axios 重试拦截器在 1~2 次瞬态重试后吞掉 `401` 登出与全部错误提示
- **位置**：`src/frontend/src/api/index.ts:270-293`
- **证据**：瞬态重试第 1~2 次若收到非重试错误（`400/401/403/404/422`），因 `config.__isRetrying` 为真且 `__retryCount < 3`，第 290-293 行提前 `Promise.reject(error)`，跳过第 306-328 行的 `401` 会话过期清理与全部错误 toast。
- **修复建议**：删除第 290-293 行的 `isRetrying` 提前返回逻辑（重试路径已在第 284 行提前返回）并同步更新拦截器单测。

#### OCR-28 [P1 / 前端交易误判 / E2] `AITradingPage.handleConfirmDialog` 将下单执行失败误当用户取消
- **位置**：`src/frontend/src/views/AITradingPage.vue:162-189`
- **证据**：`ElMessageBox.confirm`、`confirmTrade({ confirmed: true })` 与 `loadHistory()` 共用同一 `try/catch`；确认执行失败（如超时/500）会落入 `catch`，错误触发未保护的 `confirmTrade({ confirmed: false })` 并提示“已取消”。
- **修复建议**：将弹窗取消与下单执行拆分为独立 `try/catch`，下单失败给出明确错误提示并刷新历史，取消调用亦需捕获异常。

#### OCR-29 [P1 / 前端安全 / E2] `NewsIntelligencePage.openArticle` 直接 `window.open` 外部 URL 未校验协议
- **位置**：`src/frontend/src/views/NewsIntelligencePage.vue:799-803`
- **证据**：外部新闻/RSS 源返回的 `article.url` 未校验 `http:`/`https:` 协议即传入 `window.open`，存在 `javascript:`/`data:` URL 注入风险。
- **修复建议**：通过 `new URL(articleUrl, window.location.origin)` 解析，仅放行 `http:` 与 `https:` 协议。

#### OCR-30 [P1 / 前端分页缺陷 / E2] `PortfolioPage.loadMoreImportedSources` 总数 > 200 时永远重置回第 1 页
- **位置**：`src/frontend/src/views/PortfolioPage.vue:1915-1934`
- **证据**：第 1921 行无条件判断 `result.total !== existingImportSources.value.length + result.items.length`，未限定 `!result.has_more`，导致总数超过 200（>2 页）时加载第 2 页必定重置回第 1 页。
- **修复建议**：记录第 1 页 `existingImportSourcesTotal`，仅在总条数漂移或 `!result.has_more` 且累计条数不等时触发重置。

#### OCR-31 [P1 / 前后端鉴权契约 / E2] 后端登录已下发 `refresh_token`，前端仍丢弃且无 `401` 自动续期
- **位置**：`src/frontend/src/stores/auth.ts:53-54, 236-239`、`src/frontend/src/api/auth.ts:4-7`、`src/frontend/src/types/index.d.ts:27-31`、`src/frontend/src/api/index.ts:306-314`
- **证据**：后端 `/api/v1/auth/login` 已改为 `login_with_refresh` 返回 `RefreshTokenResponse`，但前端 `Token` 类型缺少 `refresh_token`、`authStore.login` 显式置 `refreshToken.value = null`、无 `/auth/refresh` 封装，令牌过期即强退。
- **修复建议**：补全类型与 `authApi.refresh`，持久化保存 `refresh_token`，并在 `api/index.ts` 实现单飞（single-flight）401 刷新与请求队列重放。

#### OCR-32 [P1 / 前端 WebSocket 竞态与泄漏 / E2] `DataTopicsPage`、`useBacktestRuntime`、`useOverfittingRuntime` 存在孤儿连接、未捕获异步异常与心跳泄漏
- **位置**：`src/frontend/src/views/data/DataTopicsPage.vue:443-484`、`src/frontend/src/composables/useBacktestRuntime.ts:127-193`、`src/frontend/src/composables/useOverfittingRuntime.ts:120-190`
- **证据**：
  1. `DataTopicsPage.disconnectStream` 未清空旧 socket 回调，重连后旧 socket 的 `onclose` 把新 `socket` 置空造成孤儿连接。
  2. `useBacktestRuntime`/`useOverfittingRuntime` 重连前未调用 `closeWebSocket()`；`ws.onmessage = async` 缺少 `try/catch` 导致未处理拒绝和 `loading` 卡死；`event.code === 1000` 提前返回未清理 `heartbeatTimer`。
- **修复建议**：断开前解绑回调并以局部引用守卫 `if (socket !== currentSocket) return`；重连先清理旧资源、`onmessage` 包裹 `try/catch` 并统一清理心跳定时器。

---

## 三、P2 — 中优先级缺陷与优化（7 项）

### OCR-33 [P2 / 安全信息泄露 / E2] 多处未鉴权端点暴露私有策略配置、内部 AI 地址与原始异常
- **位置**：`src/backend/app/api/strategy/base.py:564-605`、`api/status.py:143-302`、`main_routes.py:166-242`、`api/metrics.py:18-75`、`api/docs.py:182-204`
- **证据**：`GET /strategy/templates/{template_id:path}/config` 未限定内置模板，知晓 UUID 可免登录读取用户私有策略 `config.yaml`；`/status/{cache,routers,capabilities}` 未鉴权返回原始导入异常；`GET /ready` 未鉴权暴露 AI provider `base_url`/模型/环境变量名；`/metrics` 未鉴权且 500 返回原始异常文本；`/docs/postman` 全环境免登录导出完整 OpenAPI。
- **修复建议**：`get_template_config` 仅允许内置模板（否则鉴权校验归属）；对 `/status/*`、`/info`、`/metrics*`、`/docs/postman` 实施管理员鉴权或生产环境开关；`/ready` 仅返回粗粒度状态并脱敏 `/metrics` 500 输出。

### OCR-34 [P2 / 安全配置收口 / E2] 生产模式未禁止 `DEBUG=True`，IB Gateway 默认 `verify_ssl=False`
- **位置**：`src/backend/app/config.py:162-197`、`middleware/security_headers.py:58-62, 98-102`、`services/gateway/launch_builder.py:591`、`services/gateway/runtime.py:188`、`services/gateway/preset.py:107, 139`
- **证据**：`APP_ENV=production` 与 `DEBUG=True` 同时配置时不会被 `validate_runtime_security_guards` 拒绝，导致 CSP 退化为 `unsafe-inline`/`unsafe-eval` 且关闭 HSTS；IB Gateway 运行时缺省 `verify_ssl=False` 呈 fail-open。
- **修复建议**：生产模式显式拒绝 `DEBUG=True`；将 IB Gateway 运行时与预设默认 `verify_ssl` 改为 `True`，生产环境运行期同样拒绝 `verify_ssl=False`。

### OCR-35 [P2 / 并发与内存泄漏 / E2] Fire-and-forget 异步任务、无界内存字典及清理缺口
- **位置**：
  - Fire-and-forget：`live_trading/execution.py:396, 440`、`kb_chat_service.py:582-584`、`sync_service.py:293`、`workspace/run_ops.py:172, 1167-1169`
  - 无界内存泄漏：`data_topic_hub.py:49, 151, 172, 230` + `news_intelligence.py:168-172`；`sync_service.py:42, 292, 2523`；`ws_gateway.py:24, 41, 47, 67-75`（`close_idle_connections` 未清 `_messages`）
  - 清理缺口：`auto_trading_scheduler.py:180-190, 264-274`（缺 shutdown hook）；`monitoring_control.py:701-742`（异常路径泄漏 `sqlite3.Connection`）
- **修复建议**：所有后台 `create_task` 纳入强引用集合并挂异常日志回调；为 `_topics`/`_tasks`/`_messages` 增加容量上限或 LRU/TTL 淘汰，修复 `close_idle_connections` 清理；补齐 `AutoTradingScheduler.shutdown()` 与 SQLite 连接关闭。

### OCR-36 [P2 / 数据层一致性与安全卫生 / E2] 仓库查询、能力台账锁/会话、MySQL 工具与回填控制器边界问题
- **位置**：
  - `market_instrument_asset_adapter.py:33-47, 724-758`（`STOCK_ZH_A_HIST` 未按 `adjustment`/索引 `data_date` 过滤；`_lookup_fx_warehouse` 历史回退死代码）
  - `services/akshare/data.py:494-617`（表超 20 万行按 `adjustment` 筛选后 `observed_bases` 与实际 `filter` 矛盾）
  - `capability_ledger_admission.py:280, 341-390`（模块级 `asyncio.Lock()` 跨事件循环崩溃；在调用方 `db` 会话上直接 `commit()`/`rollback()`；10 分钟观察窗与人工 attestation 重叠触发 `CAPABILITY_LEDGER_AMBIGUOUS`）
  - `mysql_base.py:160-170, 300, 477-559`、`akshare_provider.py:71-100`（`SHOW TABLES LIKE` 未参数化、部分标识符未校验、`disconnect_db` 异常泄漏连接、全局连接池忽略不同 `db_config`）
  - `scripts/ops/ac11_runtime_evidence.py:148-170`（非 UTC `--since` 偏移被直接丢弃造成 8 小时误判）
  - `scripts/stock_full_history_controller.py:194-206, 1148-1170`（`_as_optional_float` 放行 `inf`/`NAN`；`ManagedScriptWriterAdapter.write` 未透传超时且逐标的 `asyncio.run` 未释放引擎）
- **修复建议**：按索引与复权口径查询并修复 FX 回退；合并已验 `adjustment` 到 `observed_bases`；改为按事件循环键控锁与独立会话/savepoint，协调 attestation 观察窗；参数化 `SHOW TABLES LIKE`、分离 `close()` 清理并按连接键缓存池；统一 UTC 转换与 `math.isfinite` 校验。

### OCR-37 [P2 / 性能 N+1 与分析边界 / E2] 多处热接口 N+1 查询、排序静默失效及分析器边界 Bug
- **位置**：
  - `backtest/service.py:1075-1258` & `api/backtest_enhanced.py:299-318`（列表页 N+1 查询 robustness；`sort_by=sharpe_ratio|total_return` 因字段不在 `BacktestTask` 上被静默忽略）
  - `ai_strategy_research_service.py:2124-2500`（`list_run_records` 跨全工作区 N×M 查询后再截断）
  - `api/asset_research.py:442-451` & `asset_research/orchestrator.py:687-699`（`list_approved_schedule_manifests` N+1 查询）
  - `backtest/analyzers.py:591, 612-613, 716-760`（`FincoreAdapter` 遇 `pnlcomm: None` 抛 `TypeError`；最大回撤持续期 off-by-one 且未校验有限值）
  - `perf_attribution/fama_french.py:31-101` & `brinson.py:27-49`（大数溢出产生 `NaN`/`Inf` 绕过奇异矩阵判定导致 JSON 500）
  - `stock_analysis/data_collector.py:274-581`（包装 dict 恒非空导致 `data_quality` 恒报 `"ok"`，全文件未导 `logging` 静默吞异常）
- **修复建议**：全部 N+1 路径改为 `IN` 批量查询并补齐 `BacktestResultModel` 联表排序；修复 `pnlcomm: None`、`>= peak` 边界与 `isfinite` 校验；重构 `missing_fields` 内容判定并记录警告日志。

### OCR-38 [P2 / 前端内存泄漏、竞态与审计串户 / E2] 监听器/定时器泄漏、多页请求竞态、`AuditTracker` 跨用户污染与 4xx 无限轮询
- **位置**：
  - `KnowledgeBaseDocumentPage.vue:595-604`（匿名 `fullscreenchange` 监听未移除）
  - `QuotePage.vue:979-986, 1427-1442` & `stores/quote.ts:470-484`（异步 `onMounted` 未防卸载泄漏定时器/监听、`searchDebounce` 未清理、`searchSymbols` 无请求序号守卫）
  - `StockAnalysisPage.vue:713-776`、`BacktestResultPage.vue:533-1026`（缺路由参数 `watch`、`file://` 打开提示误导、下载无 `catch`）、`BacktestPage.vue:344-367`、`PortfolioPage.vue:2638-2767`（ECharts 懒加载后未重检 DOM ref）
  - `main.ts:81-91` & `utils/auditTracker.ts:145-275`（登出后 401 落盘导致 User A 审计事件在 User B 登录后上报；`sendStoredEvents` 提前 `splice` 导致失败批次丢失）
  - `composables/usePortfolioAnalyticsTask.ts:112-117`（4xx 永久错误每 2.5s 无限轮询）
- **修复建议**：补齐卸载守卫与监听器移除；关键异步加载引入序号/取消令牌；路由切换监听参数重拉；`AuditTracker` 登出前先 flush、按 `userId` 隔离持久化队列并在失败时回写批次；4xx 错误立即停止轮询并加退避上限。

### OCR-39 [P2 / CI 流水线、供应链与运维脚本 / E2] `nightly` 审计提前中断、锁文件/镜像 Python 版本漂移与脚本失同步
- **位置**：
  - `.github/workflows/nightly.yml:445-591, 624-629`（`pip-audit` 失败直接中止后续 `npm audit` 与自动建 issue 步骤；未审计 `requirements-prod.lock`；汇总不因审计失败而红）
  - `config/requirements-prod.lock:2`（0 `--hash` 且锁 Python 3.11）vs `src/backend/Dockerfile:2`（`python:3.12-slim`）；`ci.yml:696` 未锁版本 `pip install radon`；`check_complexity_budget.py` 缺 `baseline_update_guard`；工作流动作未 SHA 锁定且缺顶层 `permissions`；`prod.yml` 使用 `certbot:latest` 且 MySQL 8.0 vs CI 9.4.0
  - `ci.yml:1492-1515`（`monorepo-check` 无工具链必败被 `continue-on-error` 掩盖）；`e2e.yml` 缓存路径无效、等待健康检查缺少 `curl -f` 与超时失败退出、`browser` 输入未使用；`pr-check.yml:81-98` 未锁定运行时并静默回退
  - `docker/entrypoint-dev.sh:77`（旧路径 `scripts/seed_dev_data.py`）；`docker/compose/dev.yml:114`（`VITE_API_BASE_URL` 与 `vite.config.ts:10` `VITE_API_TARGET` 不匹配）；`scripts/ops/validate_docker_env.py`（未同步 `APP_ENV` 与占位密钥）；`scripts/ops/stop_app.sh`（误杀无关端口进程）
- **修复建议**：捕获退出码并给建 issue 加 `if: always()`；统一 3.11/3.12 构建基线并生成 `--hash` 锁文件、锁定 `radon` 与 GitHub Actions SHA；修复或清理坏掉的 CI job 与 `e2e.yml` 健康等待；同步开发/运维脚本路径与环境变量契约。

---

## 四、P3 — 低优先级与长期演进（5 项）

### OCR-40 [P3 / 潜伏 IDOR / E2] `GET /api/v1/scanners/tasks/{task_id}` 未按 `user_id` 隔离
- **位置**：`src/backend/app/api/scanners.py:244-251`、`src/backend/app/services/scanner_service.py:63-72`
- **证据**：其他路由均透传 `_user_id(current_user)`，唯独 `get_scanner_task` 未传 `user_id`（当前因 `ScannerService.run()` 暂抛异常未落任务而潜伏）。
- **修复建议**：在任务条目记录 `user_id` 并在 `get_task(task_id, user_id=...)` 强制校验。

### OCR-41 [P3 / 错误处理卫生 / E1+E2] 优化提交失败遗留孤儿任务，以及生产代码 17 处静默 `except pass` / 86 处 `assert`
- **位置**：`src/backend/app/api/optimization_api.py:132-210`；以及 AST 扫描检出的 17 处 `except Exception: pass`（如 `index_zh_a_hist.py:60`、`gateway/runtime.py:443`、`monitoring_control.py:544`、`research/holdout_*.py`）与 86 处生产 `assert`（`python -O` 下会被剥离）。
- **修复建议**：`optimization_api` 提交异常时将已建任务标为 `failed` 或清理；逐批将静默 `except Exception: pass` 改为显式日志/窄异常，将运行时输入/状态校验中的 `assert` 替换为显式 `ValueError`/`RuntimeError`。

### OCR-42 [P3 / 测试与门禁卫生 / E1+E2] 临时目录泄漏、宽松棘轮基线、只告警迁移脚本与 32 处文档断链
- **位置**：`tests/conftest.py:59, 141-145`、`scripts/ci/large_file_baseline.json:8`（`app/config.py` 基线 1488 vs 实际 237 行）、`scripts/ci/check_migration_safety.py:229-230`、`scripts/ci/check_alembic_heads.py:109-111`、`src/backend/pytest.ini` vs `pyproject.toml:121-129`、`scripts/ci/check_doc_links.py`（32 处断链）。
- **修复建议**：`pytest_sessionfinish` 清理临时日志目录；拧紧 `app/config.py` 大文件基线；给 `check_migration_safety.py` 增加阻断模式、使 `check_alembic_heads.py` 遇错失败；清理重复 pytest 配置并修复失效文档链接。

### OCR-43 [P3 / 前端巨型文件重构 / E1+E2] 垂直切片 `useStrategyPage.ts`、`useDataPage.ts` 与 `StrategyPage.vue`
- **位置与实测规模**：
  - `src/frontend/src/views/strategy/useStrategyPage.ts`（5,272 行 / 226 函数 / 90 响应式状态）→ 拆为 `useAIResearchMandate.ts`、`useAIResearchConfigProfiles.ts`、`useAIResearchRunHistory.ts`、`aiResearchPipelineSelectors.ts`。
  - `src/frontend/src/views/data/useDataPage.ts`（4,853 行 / 173 函数 / 98 响应式状态）→ 拆为 `useMarketDataChart.ts`、`marketDataFormatters.ts`、`useMarketDataV2Query.ts`、`useMarketDataCatalog.ts`。
  - `src/frontend/src/views/StrategyPage.vue`（3,254 行，模板 2,976 行）→ 拆为 `AIResearchMandatePanel.vue`、`AIResearchConfigDialog.vue`、`AIResearchRunHistoryPanel.vue`、`AIResearchLiveHandoffCard.vue`。

### OCR-44 [P3 / 后端巨型文件与复杂度降债 / E1+E2] 分阶段下调圈复杂度预算与拆分头部后端巨型模块
- **位置与实测规模**：`scripts/ci/complexity_baseline.json`（当前 `max_cc=147, count_cc_ge_50=64`）；头部大文件 `ai_strategy_research_service.py`（5,866 行）、`asset_research/orchestrator.py`（3,045 行）、`research/paper_handoff.py`（2,787 行）、`gateway/manual.py`（2,682 行）、`research/promotion.py`（2,603 行）、`sync_service.py`（2,525 行）。
- **修复建议**：每次触及高复杂度函数时附带 characterization tests 拆分，并将 `complexity_baseline.json` 与 `large_file_baseline.json` 持续向下拧紧（目标阶段性将 `max_cc` 压降至 `< 100`、`count_cc_ge_50` 减半）。
