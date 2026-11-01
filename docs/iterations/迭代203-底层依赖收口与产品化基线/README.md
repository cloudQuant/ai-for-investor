# 迭代 203：底层依赖收口与产品化基线

> 2026-10-20 复核修订：修正 CZCE 修复提交状态、`interface_loader` 路径、e2e/fincore 实测结论；新增 WP-00 启动配置合同，补齐测试环境、数据新鲜度、许可五项阻塞与证据字段。

## 1. 结论

本迭代不新增业务功能，只做一件事：把平台赖以运行的四组底层能力——**fincore（指标/归因）、akshare（行情数据）、backtrader（回测引擎，cloudQuant fork）、bt_api_py 家族（券商/交易所接入）**——从“只在作者本机可用”收口成**可声明、可安装、可验证、可分发**的产品地基。

触发本迭代的是 2026-10-19/20 的故障排查与复核，已确认的根因不是单点 bug：

- **启动配置回落**：`src/backend/.env.example` 没有 `DATABASE_TYPE`/`DATABASE_URL`，而 `scripts/ops/start_app.sh:193` 会在 `.env` 缺失时直接复制示例文件；`app/config.py:107-113` 的默认值是 `sqlite`，因此新环境会静默落到 `data/dev/backtrader.db`。这不是“数据库坏了”，而是配置合同缺失。
- **启动脚本覆盖安全开关**：`scripts/ops/start_app.sh:202` 使用 `DEBUG="${DEBUG:-true}"`，会把开发者 `.env` 中的 `DEBUG=false` 覆盖成 `true`；而 `app/config.py:63-69` 的生产守卫只检查 `DEBUG`，没有独立的 `APP_ENV`。生产安全模式因此可被启动方式绕过。
- **行情停摆与日期缺陷**：行情仓库自 2026-07-03 全市场停摆；CZCE 整数日期被 `pd.to_datetime` 按 epoch 解析为 `1970-01-01`。修复已提交为 `c720a261c`，相关回归测试本轮实测 `4 passed`，不再是“未提交”。
- **v2 查询栈不可用**：`MARKET_DATA_QUERY_V2_ENABLED=false`、`MARKET_DATA_CURSOR_SIGNING_KEY` 为空、三张身份表均为 0 行；即使打开开关也无法解析标的。
- **测试基线不干净**：后端全量收集当前为 `8358 tests collected, 4 errors`，错误来自缺失的 `bt_api_execution` 与未设置的 `AFI_POLICY_BUDGET_SOURCE`；后端 `@pytest.mark.e2e` 命中数为 **0**，不存在可被 `-m e2e` 选中的测试。

这些不是孤立 bug，而是同一个结构性问题的表现：**底层依赖没有被当作产品边界来治理，配置/测试/数据/许可也没有可执行的合同。**

本迭代的判定口径：

- **静态确认 ≠ 已执行**：凡“代码具备某条路径”类结论，均标注为静态确认，不表示已运行攻击、故障注入、性能基准或线上复现（沿用迭代 202 口径）。
- 每个工作包必须有**可机器判定的验收**（导入成功、CI 绿灯、计数为 0、门禁报错），不接受“已优化”表述。
- 证据一律带 `文件:行` 或命令原文；未复验的推断在进入验收前必须补齐复验，否则降级为“待复验”。
- **不允许空绿作业**：新增的 `-m e2e` job 必须至少收集并执行一个真实后端 e2e 用例；只有 marker、没有测试的 job 视为未完成。
- **测试不得依赖开发者 `.env`**：必须有显式 `APP_ENV=test` 配置；默认 `pytest --collect-only` 不得因本地密钥/DB/IB 开关而失败。

## 2. 优先级和范围

| 优先级 | 工作包 | 一句话目标 |
| --- | --- | --- |
| P0 | WP-00 启动配置合同与 DB fail-fast | 缺显式 DB 配置时拒绝启动；启动脚本不得用 `DEBUG=true` 覆盖安全模式 |
| P0 | WP-01 券商层可复现化 | `bt_api_*` 家族从“仓库外 editable 安装”变成可声明、可锁版、可在 CI/镜像内导入的依赖 |
| P0 | WP-02 配置与密钥治理 | 启动期拒绝示例值密钥；`SECRET_KEY` 立即按已泄露处置；券商凭据脱离 `.env` 明文 |
| P0 | WP-03 akshare 数据面可信化 | 静默空值改为可区分的“无数据/取数失败”；新鲜度告警；有界、可恢复的回填与对账 |
| P0 | WP-04 统一标的身份模型 | 统一资产类别与 instrument identity，并让行情 v2 查询栈具备可开启的前提 |
| P1 | WP-05 fincore 口径统一 | 声明/锁定/实装三处对齐；本地与 CI 的 fincore 测试不再被误判为“全部 skip” |
| P1 | WP-06 backtrader fork 依赖面收敛 | 私有模块路径收进适配层，给出升级路径评估 |
| P1 | WP-07 测试与解释器矩阵 | 清理 4 个 collection error；让后端 e2e 真正执行；解释器口径收敛为一个声明矩阵 |
| P0 | WP-08 许可与分发前置 | 处置 `LICENSE-REVIEW.md:126-132` 的全部 5 项 must-clear，正式确定分发许可决策 |

范围边界（本次不做）：新增策略/回测功能、前端页面重构、数据库引擎迁移、无界全量生产回填、真实 CTP/交易所连账（仅做合同与故障面收敛）、付费模型接入。WP-03 允许**有界、可恢复、可对账**的数据回填，但不得把“全深度补数进行中”当作验收通过。

## 3. 文档入口

- 需求与证据基线：[REQUIREMENTS.md](./REQUIREMENTS.md)
- 工作包与量化验收：[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)
- 验收矩阵与证据收据：[ACCEPTANCE.md](./ACCEPTANCE.md)

## 4. 与已有迭代的关系

- **迭代 196/197**：v2 市场数据与研究审批链路的发布门禁仍未闭合（197 ACCEPTANCE 有 15 项未勾选，`E-197-15` 大文件棘轮为 `BLOCKED / NO-GO`）。WP-04 是它们的前置——身份表为空时 v2 无法服务任何标的。
- **迭代 195**：`D4 在真实 bridge 证据出现前保持阻塞`。WP-01 产出可复现的 bridge 安装与契约测试，是解除该阻塞的唯一路径；但 WP-01 的合并必须晚于 WP-08 的许可决策。
- **迭代 202**：`DEFERRED_TO_OPENDATA`（D04/D05 历史补缺与 THS dry-run 写入）由 WP-03 承接；其“静态确认”口径被本迭代沿用。
- **ADR-012**：`docs/adr/012-market-data-license-registry.md:34` 的 `Provider-specific adapters are not yet implemented for all six asset classes` 是 WP-04 的正式依据；该 ADR 只覆盖许可注册表，不自动解决“六类 vs 代码七类”的口径冲突。
- **CZCE 修复**：`c720a261c fix(akshare): correct FX mid-rate derivation, CZCE dates and trading-day calendar` 已提交；`tests/test_akshare_script_service.py` 的日期回归用例本轮 `4 passed`。WP-03 要求把同类缺陷做**全脚本普查**，而不是留一处补丁。

## 5. 本次交付边界

交付物为：可复现依赖声明与锁、CI 中真正执行的边界测试（券商契约或券商层移除证据 / fincore 指标 / akshare 数据状态 / 统一身份）、一处不改业务语义的安全门禁、显式测试环境配置、以及许可阻断项清单。

判定本迭代成功与否只有一个标准：**在一个全新、干净的机器上，按仓库内的声明执行安装后，`import bt_api_py.brokers / bt_api_ctp / bt_api_okx / bt_api_binance / bt_api_mt5 / bt_api_ib_web / bt_api_base / bt_api_execution / bt_api_risk / bt_api_monitor / fincore / akshare / backtrader` 全部成功；`pytest --collect-only` 为 0 error；券商契约与 fincore 测试不是 skip；后端 e2e 作业有真实用例执行；缺 DB 配置或示例密钥时启动必须失败。** 若 WP-01 的 ADR 选择方案 (c)（放弃仓库内券商层），则第一项“10 个 `bt_api_*` 导入”替换为 `check_broker_absent.py` 退出 0 且 live trading 用户入口移除，其余条件不变。

## 6. 本次复核新增/修正的关键点

| 项 | 旧计划 | 修订后 |
| --- | --- | --- |
| 启动配置 | 只修密钥 | 新增 WP-00：DB 缺失 fail-fast + 禁止脚本 `DEBUG` 覆盖 |
| 测试环境 | 未定义 | `APP_ENV=test` 显式配置，默认 `pytest --collect-only` 不得失败 |
| CZCE | 未提交 | 已提交 `c720a261c`，4 个相关测试 passed |
| interface 路径 | `app/data_fetch/akshare/interface_loader.py` | `app/services/akshare/interface_loader.py:58,62` |
| 后端 e2e | 增加 `-m e2e` job | 当前 marker=0；先定义/编写真实 e2e 套件，禁止空绿 |
| fincore | “测试全部 skip” | 本地 3.11.8 实测 74 passed；版本仍为 0.4.0.dev0，需升 0.5.0 |
| 券商契约 | 可能常态 skip | 本地 2 passed；CI 仍需证明 |
| 全量测试 | 未记录 | 8358 collected / 4 errors；先清零再谈全绿 |
| 许可 | 2 项阻塞 | `LICENSE-REVIEW.md:126-132` 共 5 项 must-clear |
| 大文件 | 3,672 行 | 当前 `useDataPage.ts` 4,194 行，需冻结并拆分，不得上调基线 |
