# 服务只读接入基线与兼容矩阵

本文是 P9A 要求的登记基线：AFI 作为应用后端读取共享服务包时，固定输入、来源身份、
单位与转换拒绝条件。配套的机器可校验清单在
`src/backend/app/services/service_read/consumers.py`；本文只记录人工核对过的基准与
兼容条件，不重复实现任何领域计算。

## 1 来源身份与权威归属

| 事实 | 权威 | AFI 侧身份 | 允许的读取能力 |
|---|---|---|---|
| provider 账户余额/估值 | `bt_api_gateway` 账户会话 | `application_client`（显式绑定到具体账户与 scope） | `service.account_read` |
| 策略心跳与普通指标 | 策略进程经 SDK 发射器上报，`bt_api_monitor` 保存 | `application_client`（显式绑定到具体 strategy scope） | `service.monitor_query` |
| 订单与成交事实 | `bt_api_execution` 账户 owner | 尚未接入 | `service.order_entry`／`service.order_query` |
| 风险政策与预留 | `bt_api_risk` | 尚未接入 | `service.risk_query`／`service.risk_policy` |
| 用户导入的交易行、审批、研究记录 | AFI 自有业务数据 | 不适用 | 不迁移、不当作 provider 事实 |

AFI 不持有 provider 凭据，也不建立 provider 会话；任何“读取失败”都不得退化为直连。
应用与服务不得互相 import 对方业务代码，共享 DTO 只保留在中立合同层。

## 2 单位与数值基准（脱敏固定输入）

以下基准用于人工核对投影是否只搬运数值而不改变语义；它们不是真实账户数据。

| 项 | 输入 | 期望投影 |
|---|---|---|
| 账户现金/净值 | 估值币种 USD，`available_cash=80`、`equity=105`，观测时间 `2026-10-14T00:00:00Z` | `cash="80"`、`value="105"`，`quality=fresh`，`observed_at_utc` 原样保留 |
| 缺失币种 | 观测里没有 EUR | `quality=not_collected`、`cash=null`、`value=null`、`detail_code=CURRENCY_NOT_OBSERVED` |
| 陈旧观测 | 观测存在但已超过新鲜度界限 | 保留原数值，`quality=stale`、`has_current_facts=false` |
| 心跳新鲜 | 生产者 1 秒前上报心跳 | `quality=fresh`、`is_healthy=true`、`heartbeat_age_seconds≈1` |
| 心跳过期 | 超过服务端 `heartbeat_timeout_seconds` | `quality=stale`、`is_healthy=false`，数值与序号仍保留 |
| 从未上报 | 服务端没有任何该 scope 的流 | `quality=not_collected`、`metrics={}` |
| 服务不可达 | 服务进程已停止 | `quality=unavailable`、`detail_code` 为有限诊断码、数值为 `null` |

硬性规则：`not_collected` 与 `unavailable` **不得携带任何数值**（合同层直接拒绝），
因此“未观测”永远不会被渲染成 0；“stale”保留数值但必须显式标记为非当前。

## 3 版本与兼容矩阵

| 组件 | 兼容要求 | 不满足时的行为 |
|---|---|---|
| 客户端配置 schema | `client_config_schema_version=1`，服务端 `service_config_schema_version=1` | 解析期拒绝，不启动 |
| 服务角色 | `monitor` 的 `telemetry_ingress` 角色（`service.telemetry_ingress` + `service.monitor_query`） | 端口不匹配即拒绝启动 |
| 遥测样本 | `schema_version=1`，字段集合精确匹配 | 服务端 `INVALID_SAMPLE`，不写入 |
| 快照信封 | 字段集合 `{state, streams}`，流字段集合固定 | 客户端 `INVALID_SNAPSHOT`，不投影 |
| 账户读取信封 | 由 SDK `ServiceAccountClient` 解析，未知字段拒绝 | 读取失败，不猜测 |
| 注册租约 | 回执必须含 `lease_remaining_seconds` | 旧服务缺少该字段即拒绝 |
| 可选依赖 | AFI 未安装 `bt_api_py` 时仍可启动 | 读取端点返回 `SERVICE_READ_NOT_CONFIGURED` |

## 4 转换拒绝条件

1. 客户端请求体自带 scope／账户归属：拒绝（归属只能来自认证后的 `WireScope`）。
2. 未登记账户或未授权 scope：拒绝，不降级成页面状态（HTTP 403／404）。
3. 快照里出现非本策略的流：不得据此推断本策略健康，视为未采集。
4. 数值非有限、类型不符、字段多余或缺失：拒绝整个视图，不做部分投影。
5. 用户导入账本被当作 provider 余额、或策略预算被当作账户现金：拒绝（语义越界）。

## 5 证据等级

当前已取得的等级：

- `contract`／`offline`：合同、登记表、适配器与 HTTP 端点（`tests/test_service_read_client.py`、`tests/test_service_read_api.py`）。
- `local-process`：`strategy-health` 读取在真实本机服务进程 + 真实 CURVE 传输上验证
  （`tests/test_service_read_local_process.py`：未上报 → 新鲜 → 陈旧 → 服务停止后不可用，
  未授权 scope 拒绝）。

尚未取得：`real-service`（部署环境）、真实账户读取、真实页面接线、写入链路与旧实现退役。
