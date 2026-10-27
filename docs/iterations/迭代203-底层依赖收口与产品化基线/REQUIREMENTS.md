# 迭代 203 需求与证据基线

> 复核日期：2026-10-20。证据等级以本轮实际命令为准；未复验的二手结论标 C，不得直接进入验收。

证据等级说明：

- **A｜已实测**：2026-10-19/20 由本轮排查直接执行并观测到结果。
- **B｜代码静态确认**：有 `文件:行`，但未运行触发路径。
- **C｜待复验**：来自二手分析，本迭代执行前必须自行复验后才可用于验收。

## R1 券商层不可复现（P0）

| 编号 | 等级 | 事实 | 出处 |
| --- | --- | --- | --- |
| R1-1 | A | 可导入的 `bt_api_py` 实际来自仓库外同级 checkout 的 editable 安装：`/Users/yunjinqi/Documents/new_projects/bt_api_py/`，该目录本身是独立 git 仓库 | `import bt_api_py` → `__init__.py` 路径；`pip` dist 记录为 `__editable__.bt_api_ctp-2.0.4+iteration41.i9.pth` |
| R1-2 | A | 仓库内 `src/bt_api_py` 只有 **1 个文件**（`configs/ibkr_cookies.example.json`），无 `pyproject.toml`、无 `brokers/`、无 `functions/` | `find src/bt_api_py -type f` |
| R1-3 | A | 该空壳被根 `pyproject.toml` 声明为 uv workspace 成员，并被镜像 COPY | `pyproject.toml:14`、`src/backend/Dockerfile:23` |
| R1-4 | A | `bt_api_*` 在依赖声明中**零命中**：`src/backend/pyproject.toml`、`requirements.txt`、`config/requirements-prod.lock` 均无 | grep 结果仅命中 workspace 路径 |
| R1-5 | A | CI 与 docker 配置中没有任何安装 `bt_api_*` 的步骤 | grep `.github/workflows/*.yml`、`docker/` |
| R1-6 | A | 当前安装的 `bt_api_py 0.15.5` **没有** `functions` 子模块，而业务代码引用 `bt_api_py.functions.ib_web_session`，靠 `except ModuleNotFoundError` + sys.path 注入同级目录兜住 | `app/services/manual_gateway/ib_clientportal.py:15-21`、`app/services/gateway/manual.py:599-601` |
| R1-7 | B | 券商档案层在找不到 `gateway_bridge.py` 时落入 `_FallbackGatewayBridgeAdapter` | `app/services/broker_profiles.py`（注意：路径为 `app/services/`，非 `app/services/live_trading/`） |
| R1-8 | A | 本地 3.11.8 下券商契约测试并非 skip：`pytest tests/test_broker_contract.py -rs -q` → `2 passed` | `tests/test_broker_contract.py:3`；CI 是否同样 passed 仍待复验 |
| R1-9 | A | 后端全量收集当前不干净：`8358 tests collected, 4 errors`。三个 HTTP/集成测试因缺 `bt_api_execution` 收集失败，`test_risk_policy_budget.py` 因 `KeyError: 'AFI_POLICY_BUDGET_SOURCE'` 失败 | `pytest --collect-only -q`；`tests/test_afi08_owner_freeze_control_http.py`、`tests/test_legacy_paper_import_http_host_integration.py`、`tests/test_strategy_reduction_http_host_integration.py`、`tests/test_risk_policy_budget.py:20` |
| R1-10 | A | 测试面实际依赖的不止 6 个 broker 包：还直接 import `bt_api_execution`、`bt_api_base`、`bt_api_risk`、`bt_api_monitor`。WP-01 当前验收只列 6 个 `bt_api_*`，覆盖不足 | `grep -rn "bt_api_execution\|bt_api_base\|bt_api_risk\|bt_api_monitor" src/backend/tests` |

## R2 配置与密钥治理（P0，安全）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R2-1 | A | 当前 `src/backend/.env` 有 195 个键，`.env.example` 有 123 个键，其中 **118 个键值相同**；`SECRET_KEY` 仍与 `.env.example` 同值（50 chars）；`JWT_SECRET_KEY`（64）与 `ADMIN_PASSWORD`（8）已不同；`ADMIN_USERNAME`/`ADMIN_EMAIL` 仍相同；`.env` 的 `DEBUG=false` |
| R2-2 | A | `SECRET_KEY` 是公开仓库中的示例值，任何拿到 repo 的人可伪造 JWT；它同时是 provider 配置 Fernet 密钥派生源与 `ai_research_provenance` 签名根（`app/services/ai_router/provider_config_store.py:193`、`app/services/ai_research_provenance.py:7`）。应按**已泄露**处置，而不是仅“新环境拒绝” |
| R2-3 | A | 交易账号凭据（`CTP_*`、`IB_WEB_*`、`MT5_*`、`BINANCE_*`、`HTX_*`、`OKX_*`）历史上放在另一份 `.env`，现已迁入项目 `.env`（约 69 个键），仍是明文文件形态 |
| R2-4 | A | `scripts/ops/start_app.sh:202` 使用 `DEBUG="${DEBUG:-true}"` 启动后端，会把 `.env` 中的 `DEBUG=false` 覆盖成 `true`；`app/config.py:49-69` 的 `_is_production`/`production_security_mode` 只检查 `DEBUG`，没有独立 `APP_ENV`。因此“生产守卫”可被启动方式绕过 |
| R2-5 | A | `.env.example` 缺少 `DATABASE_TYPE` 与 `DATABASE_URL`；`start_app.sh:193` 在 `.env` 缺失时执行 `cp .env.example .env`，`app/config.py:32-33,107-113` 默认 `sqlite` + `data/dev/backtrader.db`，新环境会静默回落 |
| R2-6 | A | 测试环境未隔离：默认 `pytest --collect-only` 因 `.env` 的 `DEBUG=false` + `IB_WEB_VERIFY_SSL=false` 触发 `ValidationError: ... not allowed in production`；直接 `Settings()` 还会因示例 `SECRET_KEY` 触发 `Default secret key detected`。`tests/conftest.py:25-35` 只覆盖了 `SECRET_KEY`/DB 等，未建立 `APP_ENV=test` 合同 |
| R2-7 | A | `ADMIN_PASSWORD` 当前仅 8 chars，低于计划要建立的最小口令策略；`.env.example` 的 `ADMIN_PASSWORD` 是 36 字符占位符，不代表真实强度 |

## R3 akshare 数据面可信化（P0）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R3-1 | A | 行情仓库全市场停摆：`akshare_data.STOCK_ZH_A_HIST` 中 5838/5864 个标的最后日期同为 2026-07-03；六个期货交易所同步停在 2026-07-01/07-03 |
| R3-2 | A | CZCE 整数日期被 `pd.to_datetime` 当 epoch 解析为 `1970-01-01` 的缺陷已修复并**提交**为 `c720a261c`；本轮 `pytest tests/test_akshare_script_service.py -k "futures_daily or trade_date" -q` → `4 passed`；308 行垃圾数据已清除 |
| R3-3 | A | 接口注册面过宽：实际路径是 `app/services/akshare/interface_loader.py:58,62`（`_discover_akshare_functions`、`dir(ak)`），另有 `app/data_fetch/scripts/common/hourly/akshare_catalog_batch.py:40` 的 `dir(ak)`。旧计划路径 `app/data_fetch/akshare/interface_loader.py` 不存在 |
| R3-4 | C | 静默吞异常点多处（静态清单约 6 处，含 `market_instrument.py` 的 `except Exception`；待逐项复验）→ 逐个复验后列入清单；须区分“确实无数据”与“取数失败” |
| R3-5 | B | 有超时（`AKSHARE_SCRIPT_TIMEOUT`/`AKSHARE_CALL_TIMEOUT`，`asset_adapter` 内 `timeout=10`）但**无重试退避**；`app/rate_limit.py` 只做请求级限流，无供应商级预算 |
| R3-6 | A | 行情 v2 查询栈处于三重关闭：`MARKET_DATA_QUERY_V2_ENABLED=false`、`MARKET_DATA_ONLINE_FETCH_ENABLED=false`、`MARKET_DATA_CURSOR_SIGNING_KEY=` 空 |
| R3-7 | A | `pd.to_datetime` 在 `app/data_fetch/scripts/**` 约 **295 处**；CZCE 只是其中一个形态。验收不能用“全仓命中 0”，必须用扫描器 + allowlist + 正反例 |
| R3-8 | B | 已有新鲜度/覆盖代码（`app/services/market_data/snapshot_freshness.py`、`coverage.py`、`store_evidence.py`），但调度与告警是否真正运行尚未确认；WP-03 应复用而非重复造 |

## R4 统一标的身份模型（P0，产品地基）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R4-1 | A | v2 所依赖的身份表全空：`asset_instruments`、`md_instrument_lookup_keys`、`md_instrument_identity_revisions` 均 0 行；即便打开开关也无法解析任何标的 |
| R4-2 | A | 规范化事实已有量：`md_observation_revisions` ≈ 1045 万行 / 26 GB；身份回填必须限定窗口、可恢复、可回滚 |
| R4-3 | A | 代码当前硬编码 **七类** 资产：`stock/futures/bond/fund/option/fx/crypto`（`market_instrument.py:777-783`）；ADR-012 却写 six asset classes。计划必须先把“六类还是七类”冻结为一个口径 |
| R4-4 | B | ADR-012（`docs/adr/012-market-data-license-registry.md:34`）明确 provider-specific adapters 尚未覆盖 six asset classes；它是许可注册表 ADR，不是身份模型 ADR |
| R4-5 | B | 身份相关实现已存在：`app/services/market_data/identity.py`、`app/models/market_data_platform.py`、迁移 `20260802_asset_research_foundation.py`、`20260908_market_data_observations.py`、`20260909_market_data_exact_identity_collation.py`；WP-04 是补数据和收敛，不是从零建表 |

## R5 fincore 口径（P1）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R5-1 | A | 声明与实装不一致：`pyproject.toml:36`/`requirements.txt:27` 要求 `fincore>=0.5.0,<0.6.0; python_version>='3.11'`，`config/requirements-prod.lock:76` 锁 `0.5.0`，而开发解释器实装 **0.4.0.dev0** |
| R5-2 | B | 仅延迟加载于 `app/services/backtest/analyzers.py` 的 `FincoreAdapter`，失败时降级到手算且只记 `debug`；`calculate_win_rate` 不走 fincore |
| R5-3 | A | “fincore 测试全部 skip”不成立：本地 Python 3.11.8 下三个测试文件 `74 passed`。真正的风险是开发环境版本 0.4.0.dev0 与声明 0.5.0 不一致，以及 CI 解释器矩阵未确认 |
| R5-4 | B | 测试中的 `skipif(sys.version_info < (3,11))` 是**预期**行为，不是缺陷；验收必须按 3.10 与 3.11/3.12 分别给期望，不能要求 3.10 也 `passed` |

## R6 backtrader fork（P1）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R6-1 | A | 实际钉版 commit 是 `4f3e6a1ca3c41c1e5a726d11cce162faec25b140`（`pyproject.toml:77`、`config/requirements-prod.lock`），旧计划写的 `04adc08c…` 已过时；`Dockerfile:12` 为此安装 git |
| R6-2 | B | app 内静态清单为 4 处 upstream 不存在的私有模块路径（`backtrader.feeds.pandafeed`、`backtrader.feeds.ccxtdata`、`backtrader.stores.ccxtstore`、`backtrader.observers.broker`）；需 scanner 覆盖动态 import/字符串引用，不能只 grep 一处 |
| R6-3 | B | `pyproject.toml:74-79` 记录 fork 强制 `numpy<2.0`（`numpy==1.26.4`），与上游/其他依赖的版本张力需在升级评估中量化 |

## R7 测试与解释器矩阵（P1）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R7-1 | A | 后端 `@pytest.mark.e2e` 命中数为 **0**；CI 的 `pytest ... -m "not performance"` 若存在 e2e 测试会选中，但当前没有测试可选中。前端 Playwright E2E 已存在（`.github/workflows/e2e.yml`、`nightly.yml:168`），不能混为后端 e2e 证据 |
| R7-2 | A | CI 单元矩阵本身已覆盖 3.10/3.11/3.12；真正的“不一致”是 Dockerfile 3.12、mypy 目标 3.10、lock 按 3.11 编译、本机 dev 3.11。WP-07 应建立单一矩阵声明，而不是再“增加一个矩阵” |
| R7-3 | B | 后端 CI 阈值 `--cov-fail-under=70`、diff-cover 60；`README.en.md:302` 宣称 v0.2 目标 85%+ 覆盖率（未达成） |
| R7-4 | A | 大文件棘轮阻断：`src/frontend/src/views/data/useDataPage.ts` 当前 **4,194 行**；迭代 197 记录基线 2,024 行，`E-197-15` 仍为 `BLOCKED / NO-GO`。不得把基线上调到 4,194 来“通过” |
| R7-5 | A | 全量收集当前 `8358 tests collected, 4 errors`；默认 `pytest --collect-only` 还会因 `.env` 安全配置失败。测试基线必须先清零，再谈覆盖率 |
| R7-6 | A | `tests/conftest.py` 已覆盖部分环境变量，但没有 `APP_ENV=test`、`DEBUG`、`IB_WEB_VERIFY_SSL`、`AFI_POLICY_BUDGET_SOURCE` 的统一默认值；这就是 R2-6/R1-9 的直接原因 |

## R8 许可与分发前置（P0）

| 编号 | 等级 | 事实 |
| --- | --- | --- |
| R8-1 | B | 生效许可为 MIT（`LICENSE`）；`LICENSE-SCOPE-DRAFT.md:3` 与 `LICENSE-SOURCE-AVAILABLE-DRAFT.md` 均为**草案未生效**，后者若采纳则商业使用需单独授权 |
| R8-2 | B | `LICENSE-REVIEW.md:126-132` 的 must-clear 共 **5 项**：①文件级版权来源/贡献权利/重新许可授权；②Fincept 审查及签署；③Backtrader（GPL）集成与组合分发义务；④新版本/提交边界与白名单；⑤共同条款中的代理资金、收费服务、企业内部使用及贡献商业再许可安排。旧计划只列前 2 项，覆盖不足 |
| R8-3 | B | `DISCLAIMER.md`、`LICENSE-REVIEW.md`、两个 license 草案当前为未跟踪文件；产品化分发前必须决定其去留与正式版本 |
