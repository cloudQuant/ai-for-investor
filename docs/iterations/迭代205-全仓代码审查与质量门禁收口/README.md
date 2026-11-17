# 迭代205：全仓代码审查与质量门禁收口

> 编制日期：2026-11-17（Asia/Shanghai）  
> 状态：**PLANNED / 未执行**。本目录只新增审查与计划文档，不修改业务代码、测试、依赖、迁移、部署或数据库。  
> 审查基线：`fix/combined-collection-plane` @ `70b7e3ed5`；对照 `master`，merge-base `0203154fa7cb831f45b5213fa3666a3983198e7d`。  
> 证据口径：**E1 = 本机已执行并保留输出**；**E2 = 静态确认，有文件与调用链**；**E3 = 需在 MySQL/PostgreSQL/生产形态动态复验**。静态确认不等于已发生线上事故。

## 1. 结论

本轮**抽样审查**没有发现需要立即停服的、可直接复现的资金损失或越权入口；202 的 refresh/access token 分离、生产 CORS 校验仍然有效。但这不等于完成了全量 RBAC/对象级授权审计（本轮未做，见 §7）。前端质量面是当前最健康的部分：`vue-tsc` 通过，ESLint 通过，Vitest **183 个文件 / 2190 个测试全部通过**；后端在 CI 锁定版本 `ruff==0.16.2` 下也通过。

但仓库当前存在三类**会制造“假绿”的阻断性问题**，必须在继续扩功能前收口：

1. **数据面会“假成功”**：`save_data()` 把提交给数据库的行数当作已写入行数返回；`INSERT IGNORE` 全部重复时仍返回正数。该返回值被子进程写成 committed-write 回执，并能让 `_raise_if_empty_completion()` 直接放行。修复提交 `6b916104b` 已被 `e57868f87` 回退，当前 HEAD 仍是旧行为。这是本轮最高优先级。
2. **迁移面在当前环境不可复现**：在 SQLite 3.45.3 上执行全新 `alembic upgrade head`，会在 `20260908_ai_research_approval_authority.py:1735` 以 `APPROVAL_AUTHORITY_SCHEMA_CONFLICT` 失败；同一原因造成 27 个 approval 迁移测试、9 个 research-binding 迁移测试、7 个 multi-record 迁移测试、7 个 asset-research 迁移测试失败。新建数据库/CI 的 `check-migrations` 与 `check_orm_schema_drift` 都可能被阻断。
3. **质量门禁会“静默跳过”**：`scripts/dev/check_all.sh` 在 `ruff/mypy/pytest/npm` 不存在时只打印 WARN 并继续；`nightly.yml` 的 `pip-audit` / `npm audit` 使用 `|| true`；`pytest.ini` 默认 `--maxfail=5`，本地全量信号被截断；后端 `@pytest.mark.e2e` 命中数为 **0**。当前本地 `pytest --collect-only` 为 **9727 collected / 5 errors**，不是 0 error。

性能与安全面另有四项 P1/P2：MySQL 全量使用 `NullPool`；THS 采集在异步调度任务里做同步 HTTP、`time.sleep()` 和整包 Parquet 解析；组合页一次性加载全部 paper equity snapshot；生产判定仍只依赖 `DEBUG`，而 `scripts/ops/start_app.sh:202` 默认注入 `DEBUG=true`（启动时对默认密钥/默认管理员只告警不失败）。

**本迭代只做“收口”，不加功能**。目标是把“写入真实、迁移可复现、测试必须全跑、门禁不可跳过、性能可测量、安全默认失败关闭”变成机器可判定的门槛。

## 2. 审查方法与可复现命令

### 2.1 Open Code Review（Alibaba）

- 仓库：`https://github.com/alibaba/open-code-review`（`alibaba/open-code-review`）。
- 本地克隆：`/tmp/open-code-review`；CLI 通过 `npx -y @alibaba-group/open-code-review` 调用。
- OCR 的 LLM 审查模式需要 provider 凭据；本机未配置 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY`，因此**没有伪造 LLM 审查结果**。实际使用了它的确定性流水线：
  - `ocr delegate preview --from master --to HEAD`：识别 **1289 个可审查文件 / 1714 个总文件**，`+324,376 / -20,575` 行，merge-base 为 `0203154fa`。
  - `ocr rules check <file>`：对后端 Python 命中系统内置规则（异常处理、死代码、可变默认参数、边界、资源管理等），对 Vue 命中通用正确性/安全/性能/可维护性/测试规则。
- 结论：OCR 的“选文件、分桶、规则匹配”可用；LLM 行级评论因缺少 provider 未执行。后续如需接入，按 `ocr config set provider ...` 配好凭据后跑 `ocr review --format json --output result.json`，不要把未配置状态写成“已审查”。

### 2.2 本机确定性工具（E1）

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端 Ruff（CI 锁定版） | `src/backend: ruff==0.16.2 check .` | **通过**（0 error） |
| 后端 Ruff（本机新版） | `ruff 0.17.5 check app tests` | 479 项（472 项 I001、7 项 T201），说明本机工具版本与 CI 不一致，不作为代码结论 |
| 后端 mypy | `mypy 1.14.1 app`（项目 venv） | 内部错误 + 缺 stubs；与 CI 的 `mypy==1.20.2` 不一致，未作为结论 |
| 后端 Bandit | `bandit -r app --severity-level medium` | 73 Medium / 188 Low；53 项 B608、3 项 B301、3 项 B310、3 项 B102、1 项 B314，逐项见 AUDIT |
| 复杂度 | `radon cc app -j -s` | 1478 个块，平均 **D (20.3)**；64 个函数 CC≥50，最高 147 |
| 后端测试收集 | `src/backend: python -m pytest --collect-only -q` | **9727 collected / 5 errors** |
| 后端全量测试 | `pytest -q -m "not e2e" -n 4 --timeout=120 --maxfail=40` | **76 failed / 2395 passed / 10 skipped / 28 errors / 514s**（本机非规范 venv；见 AUDIT 的边界说明） |
| 全新 SQLite 迁移 | `DATABASE_URL=sqlite+aiosqlite:////tmp/... alembic upgrade head` | **exit 1**，`APPROVAL_AUTHORITY_SCHEMA_CONFLICT` |
| 前端类型检查 | `src/frontend: vue-tsc --noEmit` | **通过** |
| 前端 ESLint | `src/frontend: ./node_modules/.bin/eslint . --max-warnings 0` | **通过** |
| 前端单测 | `src/frontend: npm run test -- --run` | **183 files / 2190 tests passed / 23.4s** |
| 前端生产依赖审计 | `npm audit --omit=dev` | **0 vulnerabilities** |
| 大文件棘轮 | `python scripts/ci/large_file_ratchet.py` | **通过**（但基线本身包含 4912 行 `useDataPage.ts`） |

### 2.3 十个只读子代理

按认证安全、数据事务、AI 研究、行情采集、交易风控、前端、测试 CI、配置部署供应链、性能、可维护性十个方向并行启动只读子代理（`claude -p --permission-mode plan --allowedTools Read Grep Glob`）。其中一个性能代理产出了可用的分析摘要，其余多数在返回阶段被工具截断/污染。**本计划只采纳经主审直接用源码、命令或测试复验的条目**；未复验的代理推断不进入发现表。这个失败本身也说明：长上下文审查必须有确定性的文件/行号回执，不能只依赖自然语言总结。

## 3. 发现总表

> P0：可造成数据损坏、错误交易依据或部署阻断；P1：高概率可靠性/性能/安全问题；P2：中等或可维护性问题；P3：低风险改进。  
> “E1”为本机已复现，“E2”为静态确认，“E3”为待 MySQL/PostgreSQL/生产形态复验。

| ID | 优先级 | 问题 | 关键证据 | 工作包 |
|---|---|---|---|---|
| D01 | **P0** | `save_data()` 用“提交行数”冒充“已写入行数”，空回执可绕过空结果保护 | `core/mysql_base.py:420-447`、`providers/akshare_provider.py:437-459`、`services/akshare/script_worker.py:82-92`、`services/akshare/script.py:460-463`；修复被回退：`6b916104b` → `e57868f87` | WP01 |
| D02 | **P0** | 全新 SQLite 数据库迁移在 approval authority 处失败，迁移链不可复现 | `alembic/versions/20260908_ai_research_approval_authority.py:1723-1737`；E1：`alembic upgrade head` exit 1；27+9+7+7 个迁移测试失败 | WP02 |
| D03 | **P1** | 后端测试基线非 0 error、非全绿、非 hermetic | E1：`9727 collected / 5 errors`；`76 failed / 2395 passed / 28 errors`；`pytest.ini` `--maxfail=5`；113 个 skip | WP03 |
| D04 | **P1** | 本地与 CI 门禁可静默跳过或只告警 | `scripts/dev/check_all.sh:79-103`；`nightly.yml:453-461` `\|\| true`；`check_migration_safety.py` 恒 exit 0 | WP04 |
| D05 | **P1** | MySQL 使用 `NullPool`，每请求新建物理连接 | `db/database.py:72-88`；生产 compose 使用 `mysql+aiomysql`、`WEB_CONCURRENCY=2` | WP05 |
| D06 | **P1** | THS 采集在异步任务中执行同步 HTTP、重试 `time.sleep` 和整包解析 | `ths_dump_importer.py:253,291-301`、`ths_history_runner.py:696-697`、`ths_scheduler.py:100-109` | WP05 |
| D07 | **P1** | 生产模式只由 `DEBUG` 推断；启动脚本默认 `DEBUG=true`；默认密钥仅告警 | `config.py:60-76`、`scripts/ops/start_app.sh:202`、`startup/security_check.py:17-23` | WP06 |
| D08 | **P2** | 组合页一次性加载全部 paper equity snapshot，在 Python 侧降采样 | `api/portfolio/api.py:1416-1439`，`_sample_indices` 在 1410 | WP05 |
| D09 | **P2** | 回测结果接口一次性构造完整 equity/drawdown/klines/trades/signals | `api/analytics.py:86-286` | WP05 |
| D10 | **P2** | 外部 RSS 使用 `xml.etree.ElementTree.fromstring`，无大小/实体限制 | `services/news_intelligence.py:350-367` | WP06 |
| D11 | **P2** | 生产 compose 将 MySQL 3306 绑定到所有网卡 | `docker/compose/prod.yml:21-22` | WP06 |
| D12 | **P2** | 2284 个宽泛 `except Exception`，20 个仅 `pass`；部分数据/网关路径把故障降级为“无数据” | `market_instrument_asset_adapter.py:154-173`、`stock_analysis/data_collector.py:346`、`gateway/runtime.py:443` | WP06 |
| D13 | **P2** | 后端 `e2e` marker 命中 0，e2e 只有前端 Playwright | E1：`grep -rn '@pytest.mark.e2e' tests` = 0；`e2e.yml` 只启动后端供前端测试 | WP03 |
| D14 | **P2** | 巨型文件与高复杂度继续存在，可维护性和回归成本高 | `useDataPage.ts` 4853、`useStrategyPage.ts` 5272、`StrategyPage.vue` 3254、`ai_strategy_research_service.py` 5866；64 个 CC≥50，最高 147 | WP07 |
| D15 | **P2** | 生产锁文件无 hash，依赖审计不阻断；本地 `.venv` 与 lock 漂移；审计在 3.13 下无法完成 | `config/requirements-prod.lock` 0 个 `--hash`；venv 缺 `freezegun/hypothesis/ruff/mypy`；`pip-audit` 因 backtrader fork 与 `numpy==1.26.4` 冲突无法安装 | WP04 |
| D16 | **P2** | 运行时兼容 DDL 与 Alembic 双轨；仅在 `DB_AUTO_CREATE_SCHEMA=true` 时触发 | `db/database.py:807-841`、`startup/database.py:18-25` | WP02 |
| D17 | **P3** | 可维护性优化：拆分超长函数、统一错误码、补性能指标 | AUDIT 的 S/优化项 | WP07/WP08 |

## 4. 工作包

| 工作包 | 目标 | 主要交付 | 并行道 | 依赖 |
|---|---|---|---|---|
| WP01 数据写入真实性 | 让“写了多少行”与数据库真实 affected rows 一致 | `save_data` 返回 affected；回执记录 offered/affected；空结果保护使用 affected；回归测试 | A1/A2 | 无 |
| WP02 迁移可复现 | 任意受支持方言/版本从空库升级到 head | 修复 SQLite check 约束反射；MySQL/PostgreSQL 复验；删除双轨 DDL | B1/B2 | 无 |
| WP03 测试基线 | 0 collection error、全量可跑、e2e 真实执行 | `APP_ENV=test`、无 import-time env、去 `--maxfail`、真实 e2e 或删除 marker | C1/C2 | WP02（迁移测试） |
| WP04 门禁真实性 | 缺工具/有漏洞/有失败时必须红 | `check_all.sh` fail-closed、审计阻断、hash 锁、CI 证据 | D1 | 无 |
| WP05 性能与容量 | 连接池、事件循环、查询/响应有界 | MySQL pool、THS offload、snapshot/backtest 分页与 SQL 降采样 | E1/E2 | WP01（数据正确性） |
| WP06 安全边界 | 生产模式、默认凭据、端口、XML、exec 边界 | 显式 `APP_ENV`、fail-closed、端口收敛、defusedxml、exec 信任边界 | F1 | 无 |
| WP07 可维护性 | 降低巨型文件/复杂度增长 | 垂直切片、CC 棘轮、characterization tests | F1（第二波） | WP03 |
| WP08 可观测性 | 让降级/空写/连接池/调度可观测 | 结构化错误码、指标、告警、运行手册 | E1/D1 | WP01/05/06 |

## 5. 并行执行方式（最多 10 个子代理）

### 5.1 波次

| 波次 | 时间盒 | 并行道 | 目标 |
|---|---|---|---|
| Wave 0 | 0.5 天 | 主审 + D1 | 冻结基线、固化复现命令、建立证据目录；任何人不得改共享文件 |
| Wave 1 | 2 天 | A1/A2 + B1/B2 | 先修 P0：数据写入真实性、SQLite 迁移；每日合并一次 |
| Wave 2 | 3 天 | C1/C2 + D1 + E1/E2 | 测试基线、门禁、MySQL 连接池、THS/查询性能 |
| Wave 3 | 3 天 | F1 + E1/D1 | 安全边界、可维护性切片、可观测性；最后统一验收 |
| 集成 | 1 天 | 主审 | 全量门禁 + 文档回填 + 发布/不发布结论 |

### 5.2 十条并行道

| 道 | 范围 | 允许修改的文件 | 禁止修改 |
|---|---|---|---|
| A1 | `MysqlBase.save_data` / `AkshareProvider.save_data` 的 rowcount | `core/mysql_base.py`、`providers/akshare_provider.py` | 回执层、测试 |
| A2 | `script_worker` 回执、`_raise_if_empty_completion` | `services/akshare/script_worker.py`、`services/akshare/script.py`、`services/akshare/write_fence.py` | 两个 `save_data` |
| B1 | SQLite 迁移 check 约束 | `alembic/versions/20260908_ai_research_approval_authority.py`、迁移测试 | 其他迁移 |
| B2 | MySQL/PostgreSQL 迁移与方言矩阵 | 迁移测试、CI matrix、`docker/compose/ci.yml` | B1 的文件 |
| C1 | 测试环境 hermetic | `tests/conftest.py`、`pytest.ini`、测试 env 文件 | 业务代码 |
| C2 | 真实 e2e / marker 治理 | `tests/integration/`、`.github/workflows/e2e.yml` | C1 的文件 |
| D1 | 门禁与供应链 | `scripts/dev/check_all.sh`、`scripts/ci/*`、`nightly.yml`、lock 生成脚本 | 业务代码 |
| E1 | MySQL pool + 查询有界 | `db/database.py`、`api/portfolio/api.py`、`api/analytics.py` | THS |
| E2 | THS/回测异步与内存 | `services/market_data/ths_*.py`、`api/analytics.py`（仅流式部分） | E1 的 pool 文件 |
| F1 | 安全 + 可维护性切片 | `config.py`、`startup/security_check.py`、`docker/compose/prod.yml`、`news_intelligence.py`、目标拆分文件 | 其他道文件 |

**合并规则**：一条道一个分支/PR；同一文件同一时间只允许一个道编辑；跨道接口先在 Wave 0 冻结（函数签名、返回结构、错误码）；每日用 `bash scripts/dev/check_all.sh` 和定向 pytest 做一次集成；任何“先合后修”的共享文件改动必须由主审重排。

## 6. 与已有迭代的关系

- **迭代202**：D01/D09/D10/D11 等认证/会话/前端竞态已修复，本轮不重复；D13 生产 Alembic 只完成了“启动不建表”，本轮的 D16 进一步要求删除运行时兼容 DDL 双轨。O03 的“大工件下载占用事件循环”仍未关闭，本轮 D09 承接。
- **迭代203**：WP-00/02 已把 `DEBUG=false` 写入示例与生产 compose，但 `start_app.sh` 仍默认 `true`，且没有独立 `APP_ENV`；WP-03 的“0 collection error”没有达成（本轮 5 errors）；WP-07 的“后端 e2e 真正执行”仍是 0 marker。本迭代把这些未完成项作为正式输入。
- **迭代204**：OpenData 迁移仍是大范围进行中。本迭代不迁移数据平台，只保证 AFI 侧“写入回执、迁移、测试、门禁、性能”不再制造假证据；WP01 的 rowcount 修复对 OpenData 迁移后的对账同样必要。
- **REFACTORING_BACKLOG**：`manual_gateway_service.py` 的异步阻塞、Vue 大文件切片等条目仍在；本轮 D14 只做“冻结 + 选 2 个切片”，不试图一次清空历史债。

## 7. 本次交付边界

- 本目录只包含审查与计划文档，**不修改代码、测试、依赖、迁移、部署、数据库或用户数据**。
- 不启动真实交易、不连接券商、不写入生产数据库、不执行全量补数。
- **未完成全量 RBAC/对象级授权（IDOR）矩阵审计**；本轮只抽查了 token 类型分离、CORS 与生产模式。该矩阵应作为 205 之后的独立安全评审，不能因为本迭代通过就视为授权面已验收。
- 不把静态确认写成线上已发生；不把本机非规范 venv 的失败写成 CI 已失败；不把 OCR 的 delegate 结果写成 LLM 审查结论。
- 任何 WP 的“完成”必须附命令、退出码、输出摘要和 `文件:行`；没有证据的“已优化”不计入验收。

## 8. 文档入口

- [AUDIT.md](AUDIT.md)：逐项证据、调用链、影响、修复方向与复验命令。
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)：工作包、并行道、依赖、工期、合并规则、风险。
- [ACCEPTANCE.md](ACCEPTANCE.md)：全局门槛、逐项验收命令、证据模板与 NO-GO 条件。
