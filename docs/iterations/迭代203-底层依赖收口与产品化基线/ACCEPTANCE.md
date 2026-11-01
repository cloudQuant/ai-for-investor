# 迭代 203 验收矩阵（2026-10-20 复核修订版）

## 状态词汇（只允许以下五种）

| 状态 | 含义 | 必填 |
| --- | --- | --- |
| `NOT_RUN` | 尚未执行；默认状态 | — |
| `PASS` | 命令已执行且输出符合期望，收据完整 | commit、环境、命令、退出码、时间戳、证据路径 |
| `FAIL` | 已执行但不符合期望 | 失败输出、关联 issue |
| `BLOCKED_BY_PROVIDER` | 外部数据源/交易所当日不可用 | provider、复验日期、已拿到的部分输出 |
| `BLOCKED_BY_DECISION` | 需要 owner/法务/架构决策，工程无法单方面关闭 | 决策人、截止日、阻塞范围 |

`STATIC_CONFIRMED` 不是通过状态，只能写在备注里；它不能替代 `PASS`。skip 不计入 passed；只有 marker 没有测试的 e2e job 视为 `FAIL`。

## 当前基线（复核日 2026-10-20，均为 A 级实测）

| 基线项 | 当前值 |
| --- | --- |
| 后端全量收集 | `8358 tests collected, 4 errors` |
| CZCE 日期回归 | `4 passed`（修复已提交 `c720a261c`） |
| 券商契约 | 本地 `2 passed`（非 skip）；CI 待复验 |
| fincore 三文件 | 本地 Python 3.11.8 `74 passed` |
| 后端 e2e marker | `0` 个测试 |
| 前端大文件 | `useDataPage.ts` 4,194 行（197 基线 2,024） |
| `.env` / `.env.example` | 195 / 123 键，118 个键值相同；`SECRET_KEY` 仍同值 |
| 启动脚本 | `DEBUG="${DEBUG:-true}"` 可覆盖 `.env` 的 `false` |

这些基线只用于对照，不是验收通过值；任何一项在验收时劣化都应先解释。

## 验收矩阵

| ID | WP | 验收条件（命令 → 期望） | 证据 | 状态 | 硬门槛 |
| --- | --- | --- | --- | --- | --- |
| AC-203-01 | WP-00 | `APP_ENV=production DATABASE_TYPE= DATABASE_URL= python -m app.main` → 非 0，`CONFIG_DATABASE_REQUIRED`；`APP_ENV=test` + sqlite → 启动成功 | 启动日志 + 退出码 | `NOT_RUN` | 是 |
| AC-203-02 | WP-00 | `grep -n 'DEBUG:-true' scripts/ops/start_app.sh` → 0；`APP_ENV=production DEBUG=true python -m app.main` → `CONFIG_DEBUG_FORBIDDEN`；无 `.env` 时 `pytest --collect-only` → 0 配置错误 | grep + 启动日志 + 收集输出 | `NOT_RUN` | 是 |
| AC-203-03 | WP-01 | ADR 选 (a)/(b)：`python scripts/checks/check_broker_imports.py` → `10/10 ok`（`bt_api_py`、`bt_api_ctp`、`bt_api_okx`、`bt_api_binance`、`bt_api_mt5`、`bt_api_ib_web`、`bt_api_base`、`bt_api_execution`、`bt_api_risk`、`bt_api_monitor`）；选 (c)：`check_broker_absent.py` 退出 0 且入口移除 | 脚本输出 + ADR + lock/removal diff | `NOT_RUN` | 是 |
| AC-203-04 | WP-01 | ADR 选 (a)/(b)：`pytest tests/test_broker_contract.py -rs -q` → `2 passed`，无 `skipped`；选 (c)：契约测试随能力移除，并有 ADR/入口移除证据 | pytest 输出或移除证据 | `NOT_RUN` | 是 |
| AC-203-05 | WP-01 | (a)/(b)：`grep -rn "sys.path.insert" src/backend/app \| grep -i bt_api` → 0，`bt_api_py.functions.ib_web_session` 不依赖路径注入；选 (c)：`app/` 对 `bt_api_*` 未 allowlist 引用为 0 | grep + import/absence 脚本 | `NOT_RUN` | 否 |
| AC-203-06 | WP-02 | `SECRET_KEY` ≠ `.env.example`；轮换演练：旧 JWT → 401、provider 密文可解、provenance 可验；`stat` 权限 600 | 轮换收据 + 脱敏日志 | `NOT_RUN` | 是 |
| AC-203-07 | WP-02 | `grep -c "^CTP_PASSWORD=\|^IB_WEB_PASSWORD=\|^MT5_DEMO_PASSWORD=" src/backend/.env` → 0；密钥从外部注入后启动成功；日志无 secret | grep + 启动日志 | `NOT_RUN` | 是 |
| AC-203-08 | WP-03 | `python scripts/checks/scan_akshare_dates.py --check` → `0 unallowlisted integer-date risks`；扫描器正/反例测试 passed；CZCE 回归 `4 passed` | 扫描 CSV + pytest | `NOT_RUN` | 是 |
| AC-203-09 | WP-03 | 三类状态测试：provider 抛错 → `PROVIDER_ERROR`、真实空帧 → `NO_DATA`、schema 变化 → `SCHEMA_DRIFT`；指标计数各 +1 | pytest + 指标输出 | `NOT_RUN` | 是 |
| AC-203-10 | WP-03 | 假时钟把最后成功时间设为 2026-07-03 → 1 个调度周期内触发股票/期货告警；其余资产 24h 告警 | pytest + 告警截图/日志 | `NOT_RUN` | 是 |
| AC-203-11 | WP-03 | 股票 + 六交易所对账报告：指定区间缺失交易日为 0，或逐项标注 `BLOCKED_BY_PROVIDER` + 复验日期 | 对账报告 | `NOT_RUN` | 是 |
| AC-203-12 | WP-03 | 回填 job 具备 checkpoint/断点续跑/幂等唯一键/磁盘预算/kill switch；不存在无界全深度作业被当作验收 | job 配置 + 恢复测试 | `NOT_RUN` | 是 |
| AC-203-13 | WP-04 | 三张身份表行数 > 0；同一迁移二次执行结果一致；最近 30 个交易日有观测标的覆盖率 ≥ 95%；孤儿引用 = 0 | SQL + 覆盖率报告 | `NOT_RUN` | 是 |
| AC-203-14 | WP-04 | v2 影子对比完成，差异有解释；`MARKET_DATA_QUERY_V2_ENABLED` 默认仍为 `false`；回滚开关验证通过 | 对比报告 + 配置 | `NOT_RUN` | 否 |
| AC-203-15 | WP-05 | `pip show fincore` → 0.5.0；3.11/3.12 三文件 `74 passed`；3.10 的 skip 数与原因明确；降级有 `metrics_source` 与 warning | pytest + pip 输出 | `NOT_RUN` | 否 |
| AC-203-16 | WP-06 | 私有路径扫描器阻断新增 import；现存 4 处 allowlist；negative control 生效；升级评估入库；文档 commit = `4f3e6a1c…` | 扫描输出 + 报告 | `NOT_RUN` | 否 |
| AC-203-17 | WP-07 | `pytest --collect-only -q` → `0 errors`（当前 4 errors）；默认命令不因 `.env` 安全配置失败 | 收集输出 | `NOT_RUN` | 是 |
| AC-203-18 | WP-07 | `pytest -m e2e --collect-only -q` → ≥ 3 个用例；CI e2e job 日志显示 `≥3 passed`，非空跑 | 收集 + CI 日志 | `NOT_RUN` | 是 |
| AC-203-19 | WP-08 | `LICENSE-REVIEW.md:126-132` 五项 must-clear 均有“已处置/已豁免+理由/仍阻断”三态与证据；SBOM/NOTICE/分发边界入库；无“仍阻断”才可发布 | 法务收据 + 文档 diff | `NOT_RUN` | 是 |
| AC-203-20 | WP-07 | `scripts/checks/check_interpreter_matrix.sh` 通过；CI 3.10/3.11/3.12、Docker 3.12、mypy 3.10、lock 3.11 的差异有单一来源与说明 | 脚本输出 + 矩阵文档 | `NOT_RUN` | 否 |
| AC-203-21 | WP-07 | `wc -l src/frontend/src/views/data/useDataPage.ts` ≤ 4,194（no-growth）；未上调 197 基线；拆分计划入库 | 行数 + diff + 计划 | `NOT_RUN` | 否 |

## 硬门槛汇总

以下任一非 `PASS`，迭代 203 直接 `NO-GO`，不得以“部分完成”关闭：

`AC-203-01`、`AC-203-02`、`AC-203-03`、`AC-203-04`、`AC-203-06`、`AC-203-07`、`AC-203-08`、`AC-203-09`、`AC-203-10`、`AC-203-11`、`AC-203-12`、`AC-203-13`、`AC-203-17`、`AC-203-18`、`AC-203-19`。

`AC-203-14` 允许保持 v2 关闭；但不得在影子对比未完成时打开默认读路径。`AC-203-15/16/20/21` 未通过不单独阻断 203，但必须在 196/197 或下一迭代指定 owner 与截止日，否则不得宣称“底层依赖已收口”。

## 收据模板

```text
receipt_id: R-203-<AC>-<seq>
ac: AC-203-XX
iteration: 203
commit:
branch:
environment: APP_ENV=..., python=..., os=..., db=...
command:
exit_code:
expected:
actual:
artifact_path:
artifact_sha256:
timestamp:
operator:
negative_control:
notes: 不含 secret；例外需写原因与批准人
```

## 更新规则

1. 只有 AC owner 提交完整收据后才能把状态改为 `PASS`；评审人可要求重跑。
2. `FAIL` 必须关联 issue，并在同一 PR/迭代记录修复提交；不得静默改期望值。
3. `BLOCKED_BY_DECISION` 必须写明决策人、截止日、影响范围；到期未决策升级为 `FAIL`。
4. `BLOCKED_BY_PROVIDER` 必须写明 provider、失败时间、已拿到的部分证据、下次复验日期；不得写成 `PASS`。
5. 任何 skip 必须在收据 `notes` 中解释；关键边界测试的 skip 视为 `FAIL`。
6. 证据不得包含密码、token、完整 DSN；日志中的 secret 一律脱敏。
7. 关闭迭代前，四份计划文档与代码在同一提交；未跟踪状态视为未交付。
