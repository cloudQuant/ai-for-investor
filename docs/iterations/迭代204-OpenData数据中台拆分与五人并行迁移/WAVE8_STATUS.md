# 第八批 股票标的参考目录 REST 接线验证记录

日期：2026-10-27（Asia/Shanghai）。状态：**SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED / NOT_PRODUCTION_ACCEPTED**。本批代码、专项测试、跨仓离线链路及最终静态组件已通过；162文件归档的独立核对25项全部通过。整仓 `make gate`、生产数据验收和生产切换未完成。

## 交付与代码位置

| 仓库 | 集成工作树 | 当前代码锚点 |
| --- | --- | --- |
| OpenData | `/home/yun/Documents/opendata-od204` | `ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f` |
| ai-for-investor | `/home/yun/.codex/worktrees/od204-integration/ai-for-investor` | `6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c` |

OpenData 新增显式 registry→reference publication 投影，并在既有 v2 records/snapshot API 中接纳严格的 `table + none + time_field=null` 无日期窗分支。AFI 新增有界 async REST adapter、默认关闭配置及经权限校验的 options 接入；页面将目录成员身份与行情可用性分开呈现。

启用 stock 目录模式时，AFI 必须完整验证整个快照后搜索；接口失败不拼接本地 warehouse、cache 或 seed。手输 symbol 未获目录确认时不能触发行情查询。`unknown` 可用性保留为 unknown/null。别名匹配要求显式业务生效日期；不以今天代替。浏览器 stock options 请求采用一次请求和页面手动重试，使用固定安全错误提示。

OpenData 发布批次是 delta；未变化的 fact 保留原行 publication ID/sequence。AFI 已修正此前错误的逐行“必须属于最新批次”要求：行序号在 `1..snapshot.sequence` 内，当前序号对应当前 publication ID，且整个快照内 ID 与序号双向一致。快照级 pins 仍逐页固定。空目录没有可证明的 registry/profile version，provenance 相应值保留 null。

## 当前验证结果

| 验证 | 结果 | 精确范围及限制 |
| --- | --- | --- |
| OpenData 专项 pytest | 112 passed，12.42s | producer、registry、table API、既有 published API 共4文件；producer 98.90710382513662%，API 89.88621997471554% |
| AFI 后端专项 pytest | 203 passed，11.33s | 新建 Python 3.11.15 锁文件子集环境，3个显式文件，`--noconftest`；adapter 92.55319148936171%，route helper 94.68085106382979% |
| AFI 前端新增用例 | 18 passed，2.37s | 新增 API 与页面两个文件 |
| AFI 前端兼容用例 | 91 passed，4.13s | 既有 marketData 与 DataPage 两个文件 |
| AFI 前端类型检查 | PASS | Vite 生成忽略的 component/auto-import 声明后运行全局 `vue-tsc --noEmit` |
| AFI 前端构建 | PASS，39.65s | 稳定源码 pins；保留既有大 chunk warning |
| 跨仓 wire bridge | 2 passed，1.25s | 真实 producer→显式临时 SQLite store→v2 ASGI router→hash-pinned AFI adapter；首次及增量发布，两页读取；无 live HTTP |
| OpenData scoped static | PASS | 两个 production 文件及两个新增测试的 Ruff/format；production mypy/Bandit；zero-dep、public API gates |
| AFI scoped static | PASS | 7个 Python 文件 Ruff/format、4个 production 文件 mypy/Bandit、7个前端文件 ESLint；锁文件环境重跑通过 |
| 当前源码独立审查 | GREEN | producer/API、adapter（含增量发布修复）、route/UI、边界测试与 bridge harness 分项审查 |
| OpenData 全量 A2 / history secret | PASS | 1,203 resolver文件、787个mypy roots全通过；Gitleaks 8.30.1扫描872提交，0泄漏；未运行整仓 aggregate gate |
| 原工作树保护 | PASS | 原 AFI 的255个受保护源码文件与既有基线逐字节一致；仅证明这些文件的内容 |
| 私有归档独立核对 | PASS | 25项检查、0发现；162文件/8 ZIP、旧W7归档、收据/当前production pins及公开修正复扫链均匹配 |

AFI 后端三个文件为 `test_opendata_instrument_reference.py`、`test_opendata_instrument_reference_boundaries.py`、`test_market_instrument_reference_options.py`。root 使用导入前环境白名单、无 `.env` 的源目录及空临时工作目录；测试仅使用 MockTransport、ASGI 和显式 owned SQLite。OpenData conftest 保护已知默认 engines，但不构成任意 driver 或操作系统沙箱。bridge 通过 conftest 加载 OpenData main，未进入其 lifespan；没有导入 AFI app.main。

## 环境与可复算证据

最终 AFI 专项环境禁用 system-site-packages。运行依赖及静态工具从 `config/requirements-dev.lock` 选取窄集合并使用其传递约束，SQLAlchemy 2.0.54、pydantic-settings 2.14.2、mypy 1.20.2；coverage 7.9.2 和 pytest-cov 6.2.1 为另行固定的 runner 工具。52项安装元数据中，除 bootstrap 的 pip/setuptools 及两项 runner 工具外均匹配锁文件，`pip check` 通过。这不是完整 backend extras 安装或 full CI。Python 3.10 grammar 已检查，3.10 runtime 未运行。

此前共用质量环境中的 SQLAlchemy 2.0.39、pydantic-settings 2.12.0 低于 AFI 声明下限，其通过记录只作历史参考。最终203项和静态检查在新环境重跑，专项依赖版本缺口已解决。

私有证据已冻结到 `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave8`：162文件、14,408,256 bytes，目录0700、文件0600，旧Wave 7的106文件保持不变。公开摘要为OpenData的 `docs/afi204-wave8-validation.json` 和 `docs/afi204-wave8-archive.json`，当前SHA-256分别为 `926255ab9c82ef7f7a63842efe25b3cdba75a528edd1f7c14ded266f31c3a058`、`1b6062101f29676db9c7beb39f8de70210de781f398b08de6bdd6640e53b46ca`。这是同机忽略目录归档，不是异地备份或恢复演练。关键命令/日志均为独立文件，失败尝试保留：

- `wave8-od-second-root-command.json`：OpenData 四文件专项；`wave8-od-static-command.json`：scoped static。
- `wave8-afi-backend-lock-root-command.json`：最终 AFI 203项及 coverage；`wave8-afi-static-lock-command.json`：最终静态检查。
- `wave8-afi-lock-environment-setup.json`、`wave8-afi-lock-environment-verification.json`：锁文件子集、wheel 报告、安装元数据和 pip check。
- `wave8-reference-wire-bridge-root-command.json`：跨仓两个节点；`wave8-reference-wire-bridge-review-v2.txt`：最终 harness 审查。
- `wave8-final-a2-command.json`、`wave8-final-a2-summary.json`、`wave8-final-secret-command.json`：当前批次完整静态及历史密钥组件；既有333个docs/evidence排除策略不变，149,323条历史Ruff发现仍NOT GREEN，support及active-evidence缺口继续开放。
- `wave8-afi-frontend-new-fixed-root`、`wave8-afi-frontend-compat-fixed-root`、`wave8-afi-frontend-typecheck-generated-root`、`wave8-afi-frontend-build-stable-root` 对应各自 command JSON 和日志。

冻结 contract SHA-256：`8dc2e5912f5a8c9e371beed3c36c772fe32914f59065d7655310a4e6e3be5c96`；三仓测试副本共享 fixture SHA-256：`bc891b8abaa1f332bf6f1c08ee4737bdada68e10a848f30866dd43dbbe215f72`。本批未修改上述合同或 fixture。它们都是明确标记的合成协议样例，不是现实数据、来源权利或完整性证据。

证据来自多个精确提交上的分项运行，不是一轮current-HEAD组合测试。OpenData专项/静态锚点为`71fdf9cd`，bridge/A2/secret为`ec831160`；AFI最终后端为`6b8f13c6d`，新增前端测试为`e1c032ab`、兼容及稳定构建为`dee1849`、类型检查为`6df616966`。每个收据保留提交与文件hash，公开摘要逐项列出；10个相关production文件的当前字节均与对应通过运行一致。

归档后的公开JSON扫描首轮出现1项generic-api-key告警；独立复审确认它是已记录的Git提交标识，扫描器把含secret字样的收据文件名当成字段名而误判。公开revision元数据改为对象列表，全部值保持不变，未添加allowlist或降低规则；复扫exit 0、0 findings。首次FAIL、复审、字段修正和复扫收据保留在`/tmp/od204-receipts`，位于冻结归档之外；原162文件归档未修改。初始finalizer记录的公开摘要SHA是历史值，当前值以本节及`wave8-public-metadata-correction.json`为准。

## 失败尝试与修正

OpenData 首轮107项功能通过但 producer coverage 87.98%低于90%；补充实际边界行为测试后达到98.91%。AFI 后端先后出现31项失败、单项 alias 预期错误、覆盖率不足，以及新增边界测试中一项错误的 transport timeout 预期；最终均经审查修正后重跑。未降低阈值或新增 coverage exclusions。

AFI 前端曾因日期选择器测试 stub 丢属性、旧 crypto fixture 与既有默认值不符而失败；两项均仅修正测试。首次构建进程退出0但源码 fence 因并行测试提交变化而失败，稳定源码重跑通过。早期类型检查缺生成声明导致50项错误，按既有构建流程生成后通过。所有失败日志保留，不能改写为首次通过。

归档独立审查收据为`/tmp/od204-receipts/wave8-archive-independent-audit.json`，SHA-256 `21f1a0cba555f786b567358fa32ed67b323be3d643c2041b9e4d258db634273d`；该审查在归档冻结后完成，未写回归档。

## 仍开放的迭代范围

本批没有启用真实 provider、数据集、来源凭证、DatasetGrant、AFI 新目录 flag 或旧调度任务；未执行采集、真实历史恢复或切换。真实目录/映射、来源许可、完整历史头部/内部/尾部、退市覆盖、自然周期、备份恢复、单写者切换仍须逐项证明。

87项父控制任务仍为8项 DEV_DONE、9项 IN_PROGRESS、70项 PLANNED；1,103 scheduled tasks、1,066 registered scripts 分母不变。12条财报脚本只完成静态映射与下一片设计，不计为迁移完成。整仓 `make gate`、remote CI、Python 3.10 runtime 和生产验收继续开放。

后续财报切片先冻结单一 Sina 资产负债表 wire 合同，保留报告期、公告日期精度、源更新日期、币种和原始科目标识；单位、修订、rights 与完整覆盖不足时拒绝进入标准化比较或 PIT。不得将旧脚本运行日期当财报业务日期，也不能从最早返回行推断上市起点。
