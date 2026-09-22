# 迭代 198 THS 激活链 operator 操作说明

THS 路由遵循迭代 197 的**多层 fail-closed 门控链**（DESIGN D7）。任何一层缺失，THS 路由
都不会对页面可见、也不会发起出站请求。本说明列出四层以及生产环境如何逐层写入证据。

> 重要：capability ledger 的 deployment attestation 是 **operator 控制的 append-only 数据库
> 记录**——环境变量、浏览器或 provider 名都不能在运行时铸造。写入必须由授权运维通过
> 受控脚本/SQL 完成，并保留证据。

## 四层激活链

| 层 | 表/机制 | 缺失时行为 |
| --- | --- | --- |
| 1. provider 注册 | `dg_providers` 表插入 `provider_id="ths"` 行并置 active | 路由被 `_active_routes` 过滤，`PROVIDER_UNREGISTERED` 警告 |
| 2. source authorization | `asset_data_source_registry` 表插入 `source_id="ths"` 行 | 出站前 `SOURCE_REGISTRY_UNREGISTERED` 失败关闭 |
| 3. capability ledger attestation | `md_capability_ledger_entries` 为每个 THS route 写 operator append-only 记录 | 路由不在 `effective_route_ids`，对页面不可见 |
| 4. settings kill-switch | `MARKET_DATA_THS_ENABLED=true` + `THS_API_KEY` 环境变量 | 所有 THS 路由不参与组装 |

## 需要写入的记录

### 第 1 层：provider 注册

```sql
INSERT INTO dg_providers (id, provider_id, name, category, auth_type, api_key_env, rate_limit, is_active)
VALUES (gen_uuid(), 'ths', '同花顺金融数据 API', 'market_data', 'api_key', 'THS_API_KEY', 60, true);
```

- `api_key_env='THS_API_KEY'` 声明凭据引用（不存明文）。
- `is_active=true` 是 `ensure_provider_active` 通过的必要条件。

### 第 2 层：source authorization（许可/保留/再分发，G0 必做）

```sql
INSERT INTO asset_data_source_registry
  (source_id, asset_types, jurisdictions, license_status, allowed_uses,
   redistribution_policy, derived_data_policy, retention_policy,
   effective_from, enabled, updated_at)
VALUES
  ('ths', '["stock"]', '["CN"]', 'APPROVED', '["DISPLAY","RESEARCH","BACKTEST"]',
   'NO_REDISTRIBUTION', 'ALLOWED', '<按 THS 实际条款填写>',
   NOW(), true, NOW());
```

> **G0 硬性要求**：`retention_policy` / `redistribution_policy` / `allowed_uses` 必须依据
> 同花顺实际条款核对后填写，不能推定。`license_status` 必须为 `_APPROVED_LICENSES` 之一。

### 第 3 层：capability ledger attestation

每个 THS route 需要一条 `md_capability_ledger_entries` 记录，`descriptor_sha256` 必须与
route 的精确 descriptor 一致（含 `request_provider`/`expected_result_provider_ids` 等全轴）。
descriptor 由 `capability_ledger.route_capability_descriptor_sha256(route)` 计算，**不能手写**。

当前 THS 有两条 route：
- `ths-stock-primary-v1`（stock.realtime，1d bars）
- `ths-stock-liquidity-v1`（stock.liquidity，1d reference_series）

写入记录需满足所有 CheckConstraint：
- `declared_capability = installed_capability = verified_capability = authorized_capability = true`
- `verified_at < verified_until`、`authorized_at < authorized_until`、`effective_until IS NULL OR effective_until > effective_from`
- `descriptor_sha256` / `evidence_sha256` 均为 64 位 hex

> 建议用受控脚本（见下方"脚本化写入"）而非手写 SQL，以避免 descriptor 计算错误。

### 第 4 层：settings

`.env`（不提交）：
```
THS_API_KEY=<你的同花顺 API Key>
MARKET_DATA_THS_ENABLED=true
MARKET_DATA_QUERY_V2_ENABLED=true
MARKET_DATA_ONLINE_FETCH_ENABLED=true
```

## 脚本化写入（推荐）

`scripts/acceptance/iteration198_ths.py --live` 的 harness 在**一次性 SQLite** 里自动完成
上述第 1—3 层 seed（供验收），但它使用的是测试专用的许可/保留占位值，**不代表生产许可核对**。

生产环境请使用受控迁移/SQL 并附证据。一个可复用的写入门面是
`app.services.market_data.capability_ledger.route_capability_descriptor_sha256` 与
`route_capability_id`，配合 `app.services.market_data.bootstrap` 之外的受控脚本执行。

## 回滚

- 关闭 `MARKET_DATA_THS_ENABLED=false`（第 4 层 kill-switch）→ 所有 THS 路由移除，回退 AkShare。
- 或撤销任一下层记录（`dg_providers.is_active=false` / 删除 source registry 行 /
  capability ledger 记录过期）。
- 已落库的 THS 数据保留可读，不删除；页面终态须给出可解释原因码（不静默空白）。
