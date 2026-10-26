# 第九批 Sina 资产负债表原始wire解析与有界抓取计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**CONTRACT_FROZEN / SCOPED_OFFLINE_COMPLETE / NOT_PRODUCTION_ACCEPTED**。本批只建立未注册、source-native的`fzb`（资产负债表）解析与有界抓取seam。实现、root精确测试、scoped gates及独立归档审查均已完成。本计划不代表来源权利、生产授权或历史覆盖验收。

## 冻结依据与切片边界

root已完成独立审查并冻结合同：`/tmp/od204-receipts/wave9-frozen-sina-wire-contract.txt`，SHA-256 `e6da15d2ffc7edd61f2b0fbca89074f17122ab79cdbf59f30928d60c9a519859`。四个实现分支以OpenData `ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`为共同基线。字段、限制、稳定错误码、请求scope和测试判据以该冻结文本为准；任何wire变更须先由root重新评审、版本化并通知所有工作流。

root补充合同1保留原冻结文本不变：`/tmp/od204-receipts/wave9-frozen-cancellation-amendment.txt`，SHA-256 `a9042637b648facc50a5a04dc0260c3eebce965a3cb820be272cbb73b97aedd2`，独立静态复审GREEN。`SinaFzbTransportError`增加独立`cancelled`码，不能把取消描述为超时；fetch继承既有event/deadline，并在解析前和返回前复查，已观察到取消时不返回结果。测试须区分零请求取消、响应后/解析后取消与deadline expiry。该补充不改变来源授权、财务语义或生产启用范围。

现有正向fixture是一次录制的Sina请求：`tests/fixtures/upstream/financial_statement/responses.json.gz`（SHA-256 `fd72f5ec732bb17f2fb7b2c757863c5ded216b57a423a2dcd3488a372af4a0b6`），其`meta.json` SHA-256为`3ad0b1f73908b9c9945e6fc4396c2de439fb206456e86e00a78b284a94bd9cfe`。这一次上海`sh600519`、`fzb`响应含103个报告期及515个空`item_field`结构分组标记。它仅证明这个录制响应，不证明其他标的、深圳请求、接口分页、来源保留期限、权利或全历史完整性；不得改写或重录fixture，也不得用合成正向财务数据替代它。

保留Sina原生日期、更新时间、原始值和metadata：`publish_date`是精度为日的发布日期，`update_time`是独立epoch更新时间，抓取时间另记；十进制外观的`item_value`仍为原字符串，`rCurrency=CNY`不证明每个科目的单位或倍率。五种空field标题是distinct structural group markers，不是财务项目，不得合并成项目、赋予合成ID或推断会计含义。相同项目键的完全重复原行可折叠但须保留全部原始序号；冲突行拒绝整份响应，不可部分发布。

本批禁止注册`Provider("sina")`或添加生产`ALLOWED` policy/grant；不得复用AKShare来源身份。不得编辑`financial_statement.py`、`akshare.yaml`、provider/source registry、权利/verification材料、REST route、`FinancialStatement`、DWD/PIT、迁移或任务清单。不得产出浮点值、revision、coverage、`verified`声明或调用已注册能力。不得激活任务748。本批代码只在显式注入的调用链和测试中可达；后续接入model/provider、来源权利、字段单位/身份映射、revision、coverage和任务启用须单独决策。

## 工作树与文件所有权

四条互斥分支均从共同OpenData基线`ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`开始。复用已验证干净的工作树时保留其旧分支，不覆盖旧历史。

| 工作包 | 工作树与新分支 | 独占文件 | 依赖与交付 |
| --- | --- | --- | --- |
| 合同/架构 | `/tmp/od204-wave8-reference-publication` · `codex/od204-wave9-sina-contract` · author `architecture_review` | `opendata/data/providers/sina/__init__.py`（仅docstring）、`financial_statement_contract.py` | 先使用冻结合同定义DTO、固定host/URL/limits、group marker枚举及安全错误类型；package保持未注册。 |
| 纯解析 | `/tmp/od204-wave8-table-api` · `codex/od204-wave9-sina-parser` · `wave5_frames_review` | `financial_statement_parser.py` | 依赖冻结DTO；只做纯bytes→原始报告解析，不导入HTTP、provider注册、应用入口或环境配置。 |
| 有界抓取 | `/tmp/od204-wave6-http-bounds` · `codex/od204-wave9-sina-fetch` · `wave6_http_bounds` | `financial_statement_wire.py` | 依赖合同和parser；仅通过注入的`FetchContext`与`GovernedHttpClient`执行exact Sina request scope。 |
| 两个定向测试 | `/tmp/od204-wave6-http-boundaries` · `codex/od204-wave9-sina-tests` · `wave6_http_boundaries` | `tests/test_sina_financial_statement_parser.py`、`tests/test_sina_financial_statement_wire.py` | 依赖parser/wire初版及被冻结的positive fixture；只加这两个新测试文件。 |

root独占质量census、共享合同集成、import-graph审查、测试环境allowlist和两文件隔离测试执行。`dev_client`独立审查协议边界；archive reviewer独立审阅最终证据包。分支按“合同→parser→wire→测试审查→root静态审查与隔离运行”串行合并，任何工作包不得改他人独占文件或扩展到未授权范围。

## 实施任务与依赖

| 子任务 | 状态 | 交付与完成条件 |
| --- | --- | --- |
| W9-01 冻结Sina wire合同 | CONTRACT_FROZEN | root-reviewed冻结文本与SHA如上；schema、请求参数、错误码或上限不由各流自行变更。 |
| W9-02 建立未注册source package与合同DTO | IMPLEMENTED_AND_FOCUSED_VALIDATED | 候选提交`4d9e01513f8981d73176eefe4c2f9451ed0475e0`仅含docstring package与合同模块，独立静态复审GREEN；严格查询格式`NNNNNN.SH`/`NNNNNN.SZ`、固定`fzb`身份、冻结/slots原始DTO、limits与sanitized errors。合同也处于最终focused source revision并由精确parser/wire运行覆盖。 |
| W9-03 解析报告外层和日期字段 | FOCUSED_OFFLINE_VALIDATED | 精确两文件root测试通过；严格JSON、状态、count/date-list/report-list一一对应、唯一period及限制得到离线覆盖，保持source顺序和精确日期/更新时间语义。 |
| W9-04 解析项目、分组及重复行 | FOCUSED_OFFLINE_VALIDATED | 保留标量metadata与source ordinals；五种marker、重复行及冲突行为在最终两文件测试中验证。首轮duplicate marker失败保留，窄修复后复测通过。 |
| W9-05 实现parser输入边界与错误映射 | FOCUSED_OFFLINE_VALIDATED | 4 MiB与32层深度限制、严格UTF-8/JSON和固定安全错误映射通过root精确测试。 |
| W9-06 实现request校验和governed scope | FOCUSED_OFFLINE_VALIDATED | 缺budget或非QUERY在零HTTP调用下拒绝；固定Sina source/model/operation/host与deadline/cancellation边界在fake transport下验证。 |
| W9-07 实现bounded transport | FOCUSED_OFFLINE_VALIDATED | 固定HTTPS endpoint及参数，不接受caller URL/host/page/type，不跟随redirect；response cap、timeout、status与安全失败行为在fake transport下验证。 |
| W9-08 parser T3录制响应测试 | FOCUSED_OFFLINE_VALIDATED | 录制gzip fixture replay验证103 periods、固定原值、日期/epoch/currency、value states、markers和source ordinals；负例仅变异capture envelope。 |
| W9-09 wire/admission fake-transport测试 | FOCUSED_OFFLINE_VALIDATED | 精确host/params/scope/预算/response cap/status/retrieval time；缺失、UNKNOWN/DENIED及身份不符时transport调用为0；不连网或SDK。 |
| W9-10 独立协议review与root测试前审查 | REVIEWED_AND_PREFLIGHTED | `dev_client`协议/边界复核、import graph检查和有限测试环境审查均完成；focused run使用隔离环境及`--noconftest`。 |
| W9-11 root精确隔离验收与归档 | SCOPED_OFFLINE_COMPLETE | 精确测试、scoped static、A2、secret component、冻结归档及独立archive review均完成；24项审计检查验证80/80文件、2 ZIP CRC/path及旧W7/W8归档不变。整仓`make`及生产接受不在本批声明范围。 |

## 验收顺序与明确限制

1. 实现作者先完成目标文件内的Ruff check/format、strict mypy与Bandit；不改coverage阈值、不加coverage排除、不更新baseline。每个新增data模块的statement与branch coverage目标均至少90%。
2. 测试前由root检查import graph，确认导入parser/wire不会触发`opendata.main`、app启动、默认engine创建或import-time环境读取；随后仅使用root批准的有限测试环境变量。不得读取`.env`或新增未审阅环境值。
3. root仅运行`tests/test_sina_financial_statement_parser.py`与`tests/test_sina_financial_statement_wire.py`，使用`--noconftest`，不加载repository `tests/conftest.py`及其eager app/engine fixtures。若需修改shared budget/HTTP代码，先另行审查scope；本计划不预授权扩大allowlist。
4. Parser正向数据只来自上述录制响应；负向数据限于对captured envelope的schema/limit/identity冲突变异。Wire测试使用注入的fake Requests-compatible session/adapter，不发起实时网络、数据库操作或第三方SDK请求。content-type不在现有bounded response API可证明范围内，不得声称已验证。
5. Final root receipt记录两文件隔离测试85 passed、三个新增data modules均达到90% statement+branch门槛；scoped static、A2及full-history secret component通过。80文件私有归档已冻结，独立archive review 24/24检查通过。即使本批focused gates通过，也只证明这一source-native离线切片的实现行为，不证明来源许可、生产grant、其他标的/市场支持、财报单位、完整历史、listing inception或自然周期。

本批不改变87项父矩阵、1,103项任务或1,066个脚本候选的既有分母与状态。后续注册、授权、字段映射/单位/修订、财报域落库、DWD/PIT、历史补齐及任务748启用均保持OPEN，须基于额外的独立证据和单独批准。归档审查仅完成离线证据包核验，不构成来源或生产接受；完整`make gate`、remote CI与Python 3.10 runtime仍为NOT_RUN。
