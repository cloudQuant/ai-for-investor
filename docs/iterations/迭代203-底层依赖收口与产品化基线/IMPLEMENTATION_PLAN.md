# 迭代 203 实施计划（2026-10-20 复核修订版）

每个工作包给出：目标、动作、**可机器判定的验收**、阻断依赖。验收不通过不得标记完成；“已尝试”不构成完成。本版新增 WP-00（启动配置合同），并把测试环境、collection error、数据新鲜度、许可五项阻塞和证据字段纳入关闭条件。

## 关闭规则

1. 验收条件必须是命令 + 期望输出，不接受描述性判定。
2. C 级证据（待复验）在动手前必须先复验为 A/B，否则该条从验收矩阵移除并注明移除原因。
3. 任何“跳过（skip）”的测试不计入通过；关键边界测试必须在 CI 中实际执行，且 skip 必须带明确原因。
4. 修改产品代码的包必须同批提交回归测试；纯观测/门禁类改动需给出被拦截的反例（negative control）与被放行的正例（positive control）。
5. 涉及外部网络/交易所的验收，若当日无数据（如结算未发布），记为 `BLOCKED_BY_PROVIDER` 而非 `PASS`。
6. 不允许空绿作业：新增的 e2e job 必须至少收集并执行真实用例；只有 marker 没有测试视为未完成。
7. 测试不得依赖开发者 `.env`；所有验收命令默认在显式 `APP_ENV=test` 下可复现。
8. 证据必须带 commit SHA、环境（OS/Python/APP_ENV）、命令原文、退出码、时间戳；只写“已验证”无效。

## 每个工作包的固定流程

复现取证 → 写失败测试 → 改实现 → 全量相关套件 → 证据收据写入 `evidence/<date>/` → 更新验收矩阵状态。

---

## WP-00 启动配置合同与 DB fail-fast（P0）

**目标**：消除“缺 DB 配置 → 静默 sqlite 回落”和“启动脚本用 `DEBUG=true` 覆盖安全模式”两个根因，让启动失败可解释、可测试。

**动作**

1. `Settings` 增加显式 `APP_ENV`（`development`/`test`/`staging`/`production`）；`production_security_mode` 以 `APP_ENV=production` 为主判定，`DEBUG` 只能收紧、不能放开生产守卫。
2. 非 `test` 环境必须显式提供 `DATABASE_TYPE` 与 `DATABASE_URL`；删除“缺省 sqlite”作为隐式生产/开发后备。`sqlite` 仅允许在 `APP_ENV=test` 或显式 `DATABASE_TYPE=sqlite` + 明确路径时使用。
3. `.env.example` 增加 `DATABASE_TYPE`/`DATABASE_URL` 占位符；`start_app.sh:193` 不再静默复制出“可启动配置”，缺失时打印初始化命令并以非零退出。
4. `start_app.sh:202` 移除 `DEBUG="${DEBUG:-true}"`；改为 `DEBUG=false` 默认，生产环境 `DEBUG=true` 直接拒绝启动。
5. 启动日志输出脱敏的 effective DB（type/host/database，不含 user/password），并输出 `APP_ENV`；增加日志断言。
6. 建立 `APP_ENV=test` 测试配置：sqlite in-memory 或临时文件、测试密钥、IB SSL 开关显式设置，不读取开发者 `.env` 的生产值。

**验收**

- 反例：`APP_ENV=production DATABASE_TYPE= DATABASE_URL= ...` → 退出码非 0，错误码 `CONFIG_DATABASE_REQUIRED`。
- 反例：`APP_ENV=production DEBUG=true` → 退出码非 0，错误码 `CONFIG_DEBUG_FORBIDDEN`。
- 正例：`APP_ENV=test` + 测试配置 → `pytest --collect-only` 不因配置失败。
- `grep -n 'DEBUG:-true' scripts/ops/start_app.sh` 命中 0；`grep -n 'DATABASE_TYPE' .env.example` 命中 1。
- 启动日志包含 `database_type=` 且不包含密码/DSN 凭据。

**依赖**：无。**这是 WP-02/WP-03/WP-07 的前置。**

## WP-01 券商层可复现化（P0）

**目标**：把 `bt_api_*` 家族从“作者本机同级 checkout 的 editable 安装”变成仓库内可声明、可锁版、CI 可验证的依赖，并覆盖测试实际 import 的全部包。

**动作**

1. 新增 ADR：三选一决策矩阵，至少比较许可兼容性、发布/锁版成本、CI 构建时间、live trading 维护归属、回滚难度。选项：(a) 各包发布可安装版本并声明/入锁；(b) git submodule/独立仓库成员纳入 uv workspace，`src/bt_api_py` 成为真实成员包；(c) 明确放弃仓库内券商层，移除引用并把 live trading 移出范围。ADR 必须有 owner、截止日与默认选项，并在 D1 前定稿；未定稿则 WP-01 记 `BLOCKED_BY_DECISION`，不得默认推进。
2. 若选 (a)/(b)：依赖集合不能只写 6 个 broker 包，至少覆盖 `bt_api_py`、`bt_api_ctp`、`bt_api_okx`、`bt_api_binance`、`bt_api_mt5`、`bt_api_ib_web`、`bt_api_base`、`bt_api_execution`、`bt_api_risk`、`bt_api_monitor`。测试实际 import 的后四个必须可解析。
3. 若选 (a)/(b)：消除空壳歧义——`src/bt_api_py` 若继续作为 workspace 成员，必须含 `pyproject.toml` 与真实模块；否则从根 `pyproject.toml:14` 移除并删除 `Dockerfile:23` 的 COPY。若选 (c)：同样移除 workspace 成员与 COPY。
4. 若选 (a)/(b)：处置 R1-6——`bt_api_py.functions.ib_web_session` 在当前版本不存在，要么在包内补齐，要么删除引用并让 sys.path 注入随之消失。若选 (c)：删除全部引用与注入。
5. 若选 (a)/(b)：新增 CI job，干净环境安装后 import 上述 10 个模块；运行 `pytest tests/test_broker_contract.py -rs` 并断言 `2 passed`、无 skip。若选 (c)：CI 运行 `check_broker_absent.py`，并断言用户入口已移除。
6. 修掉测试收集阶段的 `ModuleNotFoundError: bt_api_execution`：由 WP-01 提供真实包，或由 WP-07 在测试模块顶部 `importorskip` 并明确 skip 原因，或按方案 (c) 删除相关测试；不能两者都不做。

**验收**

- **方案 (a)/(b)**：`uv lock`/`requirements-prod.lock` 出现完整包集合；干净环境 import 10 个模块全绿；`pytest tests/test_broker_contract.py -rs` 为 `2 passed`，不是 `skipped`。
- **方案 (c)**：`python scripts/checks/check_broker_absent.py` 退出 0（`app/`/`tests/` 中无未 allowlist 的 `bt_api_*` 引用），live trading 用户入口已移除，README 写明能力移除；仅写“放弃”不算通过。
- 任一方案：`grep -rn "sys.path.insert" src/backend/app` 中与 `bt_api_ib_web/src` 相关的注入为 0。
- 任一方案：`pytest --collect-only` 不再出现 `ModuleNotFoundError: bt_api_execution`。
- ADR 已定稿且方案选择与上述证据一致。

**依赖**：WP-08 的许可决策必须先于 WP-01 **合并**（WP-01 可并行开工）。**这是迭代 195 `D4` 阻塞的解除条件。**

## WP-02 配置与密钥治理（P0，安全）

**目标**：把已公开的示例密钥按“已泄露”处置，建立可执行的轮换/注入/测试隔离路径。

**动作**

1. **立即处置 `SECRET_KEY`**：当前 `.env` 与 `.env.example` 同值，按已泄露处理。给出分阶段轮换：先双读/新旧密钥并存（如实现允许），再重加密 provider Fernet 密文、重签 `ai_research_provenance`、使既有 JWT 失效，最后移除旧密钥；记录影响面与回滚。`JWT_SECRET_KEY`、`ADMIN_PASSWORD` 至少做强度校验，若有暴露证据一并轮换。
2. 启动期示例值门禁：把 `.env.example` 的已知占位值建成集合，命中即拒绝启动，不依赖 `DEBUG`；同时拒绝明显低熵值（长度、字符分布、常见词）。
3. `.env` 全量清单：195 个键逐项分类为 secret/config/public；把券商/交易所口令迁出 `.env`。`ADMIN_PASSWORD` 最低 12 chars 或生成的 24+ 随机值。
4. secret provider 抽象：本地 `env`/受限权限文件，CI 用 CI secret，生产用 Vault/KMS 等外部管理器；不把“操作系统钥匙串”作为 CI/Docker 的硬依赖。文件权限至少 `0600`，日志脱敏。
5. `start_app.sh` 首启生成随机 `SECRET_KEY`/`JWT_SECRET_KEY` 并写入 0600 的本地 `.env`；后续启动复用，不得每次重生成导致 token/密文失效。管理员口令必须显式输入或生成后一次性展示，不得静默使用示例值。
6. 建立 `APP_ENV=test` 测试配置，确保默认 `pytest` 不因开发者 `.env` 的 `DEBUG=false`/`IB_WEB_VERIFY_SSL=false`/示例 `SECRET_KEY` 失败。

**验收**

- 反例：`SECRET_KEY` 置为 `.env.example` 同值 → 启动拒绝，错误码明确。
- 正例：随机 48+ 字符密钥 → 启动成功，`/health` 正常；重复启动不改变密钥。
- `grep -c "^CTP_PASSWORD=\|^IB_WEB_PASSWORD=\|^MT5_DEMO_PASSWORD=" src/backend/.env` 为 0（迁移完成后）。
- `stat -f "%Lp" src/backend/.env` 为 `600`（或等价权限）；日志中无 secret。
- 轮换手册在可丢弃副本上演练通过，记录 JWT 失效、Fernet 重加密、provenance 重签三类结果。
- 默认 `pytest --collect-only` 不再出现 `not allowed in production` 或 `Default secret key detected`。

**依赖**：WP-00。

## WP-03 akshare 数据面可信化（P0）

**目标**：把“静默空值”改成可归因状态；把无界回填改成有界、可恢复、可对账；让停摆再次发生时能被告警发现。

**动作**

1. **收口正在进行的全深度回填**：记录 job id/PID、checkpoint、吞吐、磁盘占用、目标区间；禁止继续扩大范围；提供 kill switch。定义本轮只做“最近 90 个交易日 + 缺口对账”，全历史另立 WP/迭代。不得把“进行中”写成验收通过。
2. **日期形态普查**：对 `app/data_fetch/scripts/**` 约 295 处 `pd.to_datetime` 建扫描器（AST 优先，正则兜底），输出 CSV（文件:行、列、是否显式 format、是否整数日期风险）。建立 allowlist 与正反例；验收口径改为“**0 个未 allowlist 的整数日期风险命中**”，不是全仓 0。
3. 静默吞异常改造：把 `except Exception → rows=[]/continue/pass` 的站点统一返回带状态的结果（`NO_DATA`/`PROVIDER_ERROR`/`SCHEMA_DRIFT`），并把状态计入可查询指标，使“空”可归因。先复验 R3-4 的 6 处清单。
4. 重试与预算：为 provider 调用增加统一退避重试（指数退避 + jitter + 最大次数 + 熔断）与跨进程并发/配额预算；把 `rate_limit.py` 扩展出供应商维度，禁止无限重试。
5. 接口注册面收敛：`interface_loader` 不再注册 `dir(ak)` 全集；改为白名单 + 参数 schema 校验，拒绝无法描述入参的接口；保留只读迁移视图，不物理删除历史行。
6. 历史补缺与对账：为停摆区间提供受控回填入口与对账报告（按交易日并集对账，逐交易所列出缺失日期）；覆盖股票 + 六交易所。
7. 新鲜度 SLO：复用 `snapshot_freshness.py`/`coverage.py`，为股票、期货、期权、基金、外汇、加密分别定义“最后成功抓取时间”；股票/期货超过 1 个交易日、其余超过 24h 触发告警；用假时钟测试“2026-07-03 停摆”会被发现。

**验收**

- 扫描器输出中“整数日期未显式 format 且未 allowlist”命中数为 0；扫描器自身有正例/反例测试；CZCE 回归用例 `4 passed`。
- 单测：provider 抛错 → `PROVIDER_ERROR` 且指标 +1；真实空帧 → `NO_DATA`；schema 变化 → `SCHEMA_DRIFT`；三者在 API/UI 可区分。
- 接口注册数从 `dir(ak)` 全量降为白名单规模，且注册表内每个接口都有非空参数 schema。
- 对账报告：股票 + 六交易所在指定区间内缺失交易日数为 0，或有明确 `BLOCKED_BY_PROVIDER` 标注。
- 回填作业有 checkpoint/断点续跑/幂等唯一键/磁盘预算测试；不存在无界全深度作业作为验收依据。
- 新鲜度测试：把最后成功时间设为 2026-07-03，告警在 1 个调度周期内触发。

**依赖**：WP-00、WP-02（测试配置/密钥）。

## WP-04 统一标的身份模型（P0）

**目标**：先冻结资产类别口径，再补齐身份数据，最后才允许 v2 影子读取。

**动作**

1. **口径冻结**：代码当前七类（`stock/futures/bond/fund/option/fx/crypto`），ADR-012 写 six。新增 ADR-013 或在 ADR-012 增补“canonical asset class list”，明确保留 7 类还是合并为 6 类；同步 README/REQUIREMENTS/ACCEPTANCE，禁止再出现两套口径。
2. 定义跨 venue 的 instrument identity：canonical key、venue、symbol、asset class、effective dates、revision、source、confidence；映射来源（交易所/官方清单/FIGI/ISIN 等）与冲突规则必须写入 ADR。
3. 回填范围限定：先覆盖“最近 30 个交易日有观测的标的”，历史全量身份另立任务；回填必须 dry-run、幂等、可回滚、有覆盖率报告；复用 `market_data/identity.py` 与现有迁移，不重复建表。
4. 用统一身份替换 `market_instrument.py` 中按资产类型硬编码的私有仓库查询与临时 symbol 归一化；保留 legacy 适配器作为回退。
5. v2 开启前置：补 `MARKET_DATA_CURSOR_SIGNING_KEY` 生成/轮换/校验、分页游标合同、灰度影子对比与回滚开关；`MARKET_DATA_QUERY_V2_ENABLED` 在 AC-203-13/14 通过前保持 `false`。

**验收**

- 三张身份表行数 > 0，且同一迁移执行两次行数/内容一致（幂等）。
- 最近 30 个交易日有观测的标的身份覆盖率 ≥ 95%；`md_instrument_lookup_keys` 孤儿引用为 0；冲突清单可解释。
- 资产类别口径只有一处声明；README/REQUIREMENTS/ADR 引用同一列表。
- 统一身份查询与 legacy 在抽样标的上历史条数一致；差异报告可解释。
- v2 影子对比完成，默认读路径未切换；关闭开关后行为与今日一致。

**依赖**：WP-03（数据可用/对账完成）。

## WP-05 fincore 口径统一（P1）

**目标**：声明/锁定/实装三处对齐，并把“静默降级”变成可观测降级。

**动作**

1. 升级本地 `fincore` 到 `0.5.0`（或锁定版本），`pip show fincore` 与 lock 一致；记录升级步骤。
2. 明确解释器预期：3.10 的 skip 是设计行为，3.11/3.12 必须实际执行；不要要求 3.10 `passed`，也不要再把“全部 skip”当结论。
3. `FincoreAdapter` 降级改为可观测：`metrics_source` 落库/暴露计数，降级日志从 `debug` 升为 `warning`（带 reason），补正/反例测试。
4. `calculate_win_rate` 要么走 fincore，要么在文档/指标中显式记录不采用理由，不能静默绕过。

**验收**

- `pip show fincore` 在本地与 CI 均为 `0.5.0`（或声明版本）。
- Python 3.11/3.12：三个 fincore 测试文件 `74 passed`；Python 3.10：skip 数与原因明确，且不是 collection error。
- 降级计数指标有正例/反例；日志包含 reason 与 `metrics_source`。
- 本地 3.11.8 的 74 passed 收据保留，作为基线。

**依赖**：WP-00（测试配置）；可与 WP-03/04 并行。

## WP-06 backtrader fork 依赖面收敛（P1）

**目标**：把 fork 私有能力关进适配层，量化升级成本。

**动作**

1. 修正文档中的 commit：`4f3e6a1ca3c41c1e5a726d11cce162faec25b140`，删除 `04adc08c…` 旧值。
2. 建静态检查：覆盖 4 个私有路径（`feeds.pandafeed`、`feeds.ccxtdata`、`stores.ccxtstore`、`observers.broker`）以及动态 import/字符串引用；允许清单只含适配层文件；CI 加“故意新增一处应报错”的 negative control。
3. 为 4 处建适配层，禁止 app 其他位置直接 import fork 私有能力。
4. 产出升级评估：fork 相对 upstream 的差异、`numpy<2` 张力、可合并性、替代方案与成本；给出“继续钉版/回迁 upstream/换引擎”的建议，不要求本轮实施。

**验收**

- 静态检查阻断新增私有 import；现存 4 处均在 allowlist；negative control 生效。
- 评估报告入库（`docs/adr/` 或 `docs/explanation/`），包含 commit diff 与 numpy 约束量化。
- 文档中的 backtrader commit 与实际 lock 一致。

**依赖**：无；与 WP-00/02 可并行。

## WP-07 测试与解释器矩阵（P1，但 collection 清零是硬门槛）

**目标**：先让测试“能收集、能执行、不空绿”，再谈覆盖率和矩阵。

**动作**

1. **collection 清零**：当前 `8358 collected, 4 errors`。三处缺 `bt_api_execution` 的测试由 WP-01 提供包，或在模块顶部 `importorskip` 并给明确 reason；`test_risk_policy_budget.py:20` 的 `AFI_POLICY_BUDGET_SOURCE` 加测试默认路径或 `importorskip`。目标 `pytest --collect-only` 为 0 error。
2. **测试配置合同**：`APP_ENV=test`、测试 `SECRET_KEY`、`DEBUG`、`IB_WEB_VERIFY_SSL`、`AFI_POLICY_BUDGET_SOURCE` 在 `conftest.py`/测试配置中显式设置；不读取开发者 `.env` 的生产值。
3. **后端 e2e**：当前 marker=0。定义并编写至少 3 个真实后端 e2e（建议：认证→数据查询、身份解析→历史查询、v2 影子对比）；CI 增加 `-m e2e` job，验收日志必须显示 `>=3 passed`。若决定不做后端 e2e，则删除 marker 声明并明确改用前端 Playwright，不得保留空 job。
4. **解释器矩阵**：建立单一来源（如 `config/python-matrix.json` 或 CI 变量），让 CI 3.10/3.11/3.12、Docker 3.12、mypy 3.10、lock 3.11 都引用/校验它；写 `scripts/checks/check_interpreter_matrix.sh`。不要求所有版本同值，要求“差异有声明、CI 覆盖”。
5. **大文件棘轮**：`useDataPage.ts` 当前 4,194 行，197 基线 2,024。冻结当前值为 no-growth 上限，**不得把基线上调到 4,194 来关闭 E-197-15**；给出拆分计划与目标（回到 2,024 以下），本轮至少阻止继续增长。
6. **覆盖率**：维持 CI 70，不把 85% 目标伪装成已达成；为 WP-04/05 新增测试设置 diff-cover 目标。

**验收**

- `pytest --collect-only -q` → `0 errors`；默认命令不再因 `.env` 安全配置失败。
- `pytest -m e2e --collect-only -q` 收集 ≥ 3 个用例；CI e2e job 实际 `>=3 passed`，日志可查。
- `scripts/checks/check_interpreter_matrix.sh` 通过；矩阵差异有文档。
- `useDataPage.ts` 行数不超过 4,194（no-growth），拆分计划入库；不得宣称 `E-197-15` 已关闭。
- 覆盖率仍为 70 gate；新增代码 diff-cover ≥ 60。

**依赖**：WP-00（测试配置）、WP-01（`bt_api_execution`）、WP-02（测试密钥）。

## WP-08 许可与分发前置（P0）

**目标**：把 `LICENSE-REVIEW.md:126-132` 的 5 项 must-clear 逐项变成可审计决策，并给 WP-01 合并/分发上闸。

**动作**

1. 逐项处置 5 项：①文件级版权来源/贡献权利/重新许可授权；②Fincept 审查及签署；③Backtrader（GPL）集成与组合分发义务；④新版本/提交边界与白名单；⑤共同条款中的代理资金、收费服务、企业内部使用及贡献商业再许可安排。每项指定 owner、证据、截止日、三态结论。
2. 对 `LICENSE-SCOPE-DRAFT.md`、`LICENSE-SOURCE-AVAILABLE-DRAFT.md` 做正式决策（采纳/废弃/延期），不得长期停留在“草案未生效”；`DISCLAIMER.md` 同步决定发布版本。
3. 产出分发清单：SBOM、NOTICE、第三方依赖许可、文件级 provenance、Docker 镜像分发边界；明确“Backtrader GPL 组合分发”是否需要法务签署，工程不得自行下结论。
4. WP-08 未完成“已处置/已豁免+理由”前，WP-01 不得合并到发布分支；WP-04 的对外数据分发同理。

**验收**

- 5 项 must-clear 每项有“已处置/已豁免+理由/仍阻断”三态之一，且附证据。
- 两个草案与 `DISCLAIMER.md` 状态更新为正式决议或移除。
- SBOM/NOTICE/第三方许可清单入库；分发边界文档可审计。
- 若仍有“仍阻断”，本迭代不得发布；只能记 `BLOCKED_BY_DECISION`。

**依赖**：无；其决策闸门阻塞 WP-01 合并与任何对外分发。

---

## 依赖顺序

```
WP-00 ─→ WP-02 ─→ WP-03 ─→ WP-04 ─→（解除 196/197 的 v2 门禁）
  │                     └─→ WP-07（测试配置/collection 清零）
  └─→ WP-07（测试配置）

WP-08 ──(许可决策)──→ WP-01（合并/发布）
WP-01（开工） ───────→ WP-07（bt_api_execution 可导入）

WP-05 / WP-06 可与上述并行，不阻塞 P0 主链。
```

说明：WP-01 可以并行开工，但 **merge 必须等 WP-08**；WP-07 的 collection 清零依赖 WP-00 与 WP-01，故不能把 WP-07 当作“最后再补”的 P1。

## 时间盒与 owner

| 工作包 | Owner（角色） | 估时 | 关键闸门 |
| --- | --- | --- | --- |
| WP-00 配置合同 | backend maintainer | 1–2 d | D0 完成，后续所有测试依赖 |
| WP-02 密钥治理 | security + backend | 3 d | D2；SECRET_KEY 轮换演练 |
| WP-03 数据面 | data engineer + backend | 5–7 d | D5；先收口回填再改代码 |
| WP-04 身份模型 | data engineer + backend | 5–7 d | D7；口径 ADR 先于回填 |
| WP-01 券商层 | backend/infra | 3–5 d | D3 开工；D8 merge（需 WP-08） |
| WP-08 许可 | legal/product | 5 d | D5 决策；阻塞 merge |
| WP-05 fincore | backend | 1–2 d | D2 |
| WP-06 backtrader | backend | 2–3 d | D3 |
| WP-07 测试矩阵 | QA + backend | 3–4 d | D5；collection 清零为硬门槛 |

若 D0 结束仍无 owner，相关工作包状态记 `BLOCKED_BY_DECISION`，不得用“进行中”掩盖。

## 退出条件

- WP-00、WP-01、WP-02、WP-03、WP-04、WP-08 全部达到验收；否则本迭代记为 `NO-GO`，不得以“部分完成”关闭。
- 硬门槛 AC（见 ACCEPTANCE）全部 `PASS`；任一为 `NOT_RUN`/`FAIL` 即 `NO-GO`。
- `pytest --collect-only` 为 0 error；`pytest -m e2e` 至少有真实用例执行并通过；关键边界测试无未解释 skip。
- 每个 C 级证据要么复验升级、要么显式移除。
- 证据收据字段完整（commit/环境/命令/退出码/时间戳）；缺字段视为无效。
- 提交前 PR 附 `## Governance declaration`（目标分支 / 风险等级 R0–R3 + 命中路径 / 测试证据）与 `## i18n 变更清单`（本迭代预期无 i18n 变更）。
- 计划文档与代码同一提交；不得把四份计划文档留为未跟踪文件后宣称迭代完成。

## 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| DB fail-fast 让本地启动变难 | `APP_ENV=test` 显式 sqlite；提供一次性初始化命令；错误码指向修复步骤 |
| 轮换 `SECRET_KEY` 使 JWT/Fernet/provenance 全部失效 | 分阶段双读/重加密/重签；先在可丢弃副本演练；记录回滚点 |
| 券商层纳入仓库触发 GPL/许可连锁 | WP-08 先于 WP-01 合并；未清不合并 |
| 有界回填仍打爆 provider 配额 | 供应商级预算 + 退避 + 断点 + kill switch；先 90 日窗口 |
| 身份映射冲突导致 v2 结果偏差 | dry-run + 冲突清单 + 影子对比；默认开关保持 false |
| e2e 空绿/不稳定 | 至少 3 个确定性用例；固定 fixture；日志断言；禁止空 job |
| 大文件基线被上调 | no-growth 冻结在 4,194；拆分计划；不得关闭 E-197-15 |
| 测试继续依赖开发者 `.env` | `APP_ENV=test` + conftest 显式变量；CI 无 `.env` 也能跑 |

## 证据收据模板

```text
receipt_id:
iteration: 203
ac: AC-203-XX
commit:
branch:
environment: APP_ENV=..., python=..., os=..., db=...
command:
exit_code:
expected:
actual:
artifact_sha256:
timestamp:
operator:
notes: 正例/反例/例外说明；不得包含 secret
```
