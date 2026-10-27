# 第十批 Sina 资产负债表候选映射投影计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**CONTRACT_FROZEN / SCOPED_OFFLINE_COMPLETE / NOT_PRODUCTION_ACCEPTED**。本批实现一个纯离线、source-qualified的七项映射候选投影。合同与projector已集成并通过静态review，唯一测试文件已通过独立隔离review及root精确运行；私有归档、公开证据扫描及独立归档审查均已完成。

计划与验收记录：[WAVE9_PLAN.md](./WAVE9_PLAN.md)、[WAVE9_STATUS.md](./WAVE9_STATUS.md)、[WAVE10_STATUS.md](./WAVE10_STATUS.md)。W10工作包以OpenData `9ff72ad668ce161f5132bf866b251acd3c80bbba`为共同基线；合同与projector集成后的root scoped QA source为`1bd226690acd7e4bbd620a480f7e6271c38297fd`。W9负责产生原始Sina wire DTO；W10只从该DTO建立保留源证据的候选映射层，不构成W9或生产数据验收。

## 冻结合同与目标边界

root已冻结`/tmp/od204-receipts/wave10-frozen-sina-partial-projection-contract.txt`，SHA-256 `2ec501ad7d20e9802a4dc1aef3911ec7e6a9b0d8f5af231072e780fdf75b9c9a`；合同决策记录为`/tmp/od204-receipts/wave10-root-contract-decision.json`，v4独立评审`wave10-partial-projection-contract-review-v4.txt`为GREEN。状态为`FROZEN_FOR_OFFLINE_IMPLEMENTATION; NOT_PRODUCTION_APPROVED`。proposal正文中的旧状态措辞是历史文本，按root freeze decision执行v4冻结契约。

输入只能是W9的`SinaFzbFetchedSnapshot`，投影函数为纯内存转换。结果必须始终为`status="partial"`，即便每份报告都匹配全部七项。每个候选必须保留namespace、source ID/title、源原始值与present/empty/null状态、metadata、source ordinal、日期精度、源更新时间、currency和retrieved time；所有未映射项目、缺失映射对和分组marker均需显式保留/计数。缺项只是会计结果，不能补零、合成记录或丢弃源行。

唯一候选空间为`c10-seven-balance-v1`，只在source ID与source title均精确匹配时映射：

| Sina source ID | 精确source title | Namespaced proposed key |
| --- | --- | --- |
| `TOTASSET` | `资产总计` | `assets_total` |
| `TOTCURRASSET` | `流动资产合计` | `total_current_assets` |
| `TOTALNONCASSETS` | `非流动资产合计` | `non_current_nets_total` |
| `CURFDS` | `货币资金` | `cash` |
| `ACCORECE` | `应收账款` | `accounts_receivable` |
| `TOTLIAB` | `负债合计` | `total_debt` |
| `RIGHAGGR` | `所有者权益(或股东权益)合计` | `holder_equity_total` |

这些候选对来自一份`600519.SH`录制响应和C10有限crosswalk，不能扩展为Sina source-wide identity/语义证明。C10的28个Moutai年报对比单元只证明已测单元；不是103期全部科目或所有标的的证明。crosswalk key必须连同精确证据引用和namespace保留：`total_debt`仅对应`TOTLIAB`/`负债合计`，不表示有息债务；`non_current_nets_total`仅对应`TOTALNONCASSETS`/`非流动资产合计`，不表示任何“净额”计算。

## 所有权与依赖

三个隔离分支均以OpenData `9ff72ad668ce161f5132bf866b251acd3c80bbba`为基线。工作包之间按合同→projector→测试串行依赖；不得直接复用旧分支提交或改动他人文件。

| 工作包 | 工作树与分支 | 独占文件 | 交付 |
| --- | --- | --- | --- |
| 候选合同 | `/tmp/od204-wave8-reference-publication` · `codex/od204-wave10-sina-candidate-contract` · owner `architecture_review` | `opendata/data/providers/sina/financial_statement_candidate_contract.py` | commit `954e79c970068915bd1b3bf54563d8733eb8a807`；唯一合同文件完成并静态review GREEN，已集成。只定义冻结DTO、七对mapping、namespace/status/disposition、固定evidence refs、bounds及sanitized errors；不导入FinancialStatement/PIT。 |
| 纯候选投影 | `/tmp/od204-wave8-table-api` · `codex/od204-wave10-sina-candidate-projector` · owner `wave5_frames_review` | `opendata/data/providers/sina/financial_statement_candidate_projection.py` | commit `d0abab97`；projector实现已静态review GREEN并集成至当前root source。实现snapshot验证、精确ID/title映射、逐报告核算与always-partial输出；仅依赖stdlib、W9 source DTO和新候选合同。 |
| 定向测试 | `/tmp/od204-wave6-http-boundaries` · `codex/od204-wave10-sina-candidate-tests` · owner `wave6_http_boundaries` | `tests/test_sina_financial_statement_candidate_projection.py` | author commit `be057bb0927a710a8e5b233fd28a9b262f0f9f4a`已完成；独立隔离review GREEN，root在source `1bd226690acd7e4bbd620a480f7e6271c38297fd`运行通过。使用W9录制正向fixture，负向用例只对captured response或typed DTO深拷贝变异。 |

root独占质量census、跨分支集成、import graph审查、测试环境及唯一测试运行；独立reviewer审查候选协议与结果证据边界。W9 archive closure后，root已集成合同与projector；作者测试隔离review及root单文件运行均通过。W10私有归档及独立审查现已完成，完整证据见[WAVE10_STATUS.md](WAVE10_STATUS.md)。

## 实施任务

| 任务 | 状态 | 完成条件 |
| --- | --- | --- |
| W10-01 冻结source-native候选合同 | CONTRACT_FROZEN | root decision与v4独立review pin一致；wire/DTO/命名空间/核算顺序变更需重新审查与冻结。 |
| W10-02 定义独立候选DTO和mapping table | IMPLEMENTED_STATIC_REVIEW_GREEN | 合同分支commit `954e79c970068915bd1b3bf54563d8733eb8a807`；`wave10-sina-candidate-contract-implementation-review.txt`为GREEN。七组ID/title/key精确对应；candidate/unmapped类型与`c10-seven-balance-v1`绑定；固定来源证据引用；不依赖域模型或存储。 |
| W10-03 验证W9快照与源身份 | FOCUSED_OFFLINE_VALIDATED | Projector commit `d0abab97e182437078898971236af417221da266`实现精确W9 DTO及query/symbol/paper code/`fzb`/period/date/time验证；每个手工DTO按不可信输入处理。静态review和root精确测试通过。 |
| W10-04 保留原始条目并作精确投影 | FOCUSED_OFFLINE_VALIDATED | 仅ID+title完全匹配成为candidate；raw value/state不参与匹配。原始值、metadata、ordinals和marker保留；unknown ID与title mismatch保留为unmapped；报告输出matched/missing/unmapped accounting。 |
| W10-05 保持有界、always-partial结果 | FOCUSED_OFFLINE_VALIDATED | Projector实施W9 limits与ordinal完整性校验、CNY pilot admission并保持结果always-partial；任一报告无效则整份投影失败。CNY条件不证明科目单位。 |
| W10-06 唯一定向测试文件 | FOCUSED_OFFLINE_VALIDATED | author commit `be057bb0927a710a8e5b233fd28a9b262f0f9f4a`经`wave10-sina-candidate-test-isolation-review.txt` GREEN；root精确单文件`--noconftest`运行65 passed。 |
| W10-07 独立review与root scoped acceptance | SCOPED_OFFLINE_COMPLETE | 一文件隔离测试、coverage、scoped static、named gates、full-history secret component、49文件冻结归档、公开JSON secret scan及独立archive audit均通过；全量A2未对W10运行。Full `make gate`、remote CI、Python 3.10 runtime与生产验收仍开放。 |

## 必须保持的语义边界

- Mapping是带版本和证据引用的**候选**，不是规范财务字段。顶层状态始终是`partial`，禁止出现`complete`、`verified`、`canonical`或“coverage-ready”状态。
- 原值只能是W9提供的精确string/null与对应state；不得转float/Decimal、归一化、推断单位/scale，或改变currency、日期、metadata、source ordinal与retrieval time。
- 每份报告声明预期七对；matched ID按source-entry顺序，missing exact pairs按冻结mapping表顺序，unmapped原始ordinals升序。没有出现的来源对只列在missing accounting中，不能构造零行或空行。
- Unknown item不能依据标题猜映射；已知ID但标题不同也保持unmapped，且相应精确对仍记为missing。分组marker保留原序并独立计数，不参与七对财务候选匹配。
- 任何手工DTO的不连续/重复/重叠ordinal、空ordinal tuple、重复report/item/group identity、错误value-state、嵌套或无序metadata、不支持的currency、无效日期/时间或超限输入都必须以固定安全错误拒绝整个projection。W9源parser已经折叠的重复行不得在此层重新合并。
- `rCurrency=CNY`只是本次7项pilot的保守准入条件，不证明每个项目的单位。Source update时间不是公告时间或revision；不填`revision=1`、`source_revision`、`revision_order`、PIT key或`as_of`。

## 测试与静态验收顺序

1. 合同分支先完成review，projector再按冻结字段实现；发现wire/schema问题时暂停并由root重冻合同，禁止自行兼容成第二套DTO。
2. 实现作者只执行静态质量检查：Ruff、format、strict mypy、Bandit、public API约束；projector按`opendata/data/`既有口径满足至少90% statement+branch coverage目标。不得添加exclusions或降低阈值。
3. 测试执行前root审查import graph，确认projector没有HTTP、注册、ORM、app settings、scheduler或database import；root设置有限环境与空工作目录。
4. root只运行新增的`tests/test_sina_financial_statement_candidate_projection.py`，禁用repo conftest并按隔离runner规则执行。positive facts只能来自W9记录bytes；negative inputs从捕获DTO深拷贝变异。不得调用Sina、数据库或第三方SDK。
5. root receipt `wave10-candidates-first-root-command.json`在source `1bd226690acd7e4bbd620a480f7e6271c38297fd`记录精确单文件65 passed、44.23秒，contract/projector statement+branch coverage分别97.5309%和95.3608%；scoped static和Gitleaks也通过。该运行复用未变更的W9-owned 17-pin Python 3.13.5环境。W10 whole-resolver A2未运行。49文件私有归档的独立audit通过，验证W10所有文件及此前W7/W8/W9共348个归档文件；两个公开JSON独立扫描0 findings。**在W10关闭时**，W11仍处设计阶段、合同未冻结；之后W11合同冻结、首轮失败已保留、13文件核心复跑、scoped static/OpenAPI、A2及full-history secret均已通过。W11 182文件归档和两个公开metadata已创建、公开JSON复扫通过；该归档审查当时仍在运行，之后已通过25项独立核验，详见[WAVE11_PLAN.md](./WAVE11_PLAN.md)及[WAVE11_STATUS.md](./WAVE11_STATUS.md)。W9/W10两批的父矩阵和生产边界不因本批scoped QA改变。

本批不注册Sina provider、不创建生产grant、不持久化候选、不新增route或调度任务、不修改FinancialStatement/DWD/PIT，也不启用任务748。来源rights、逐标的全历史、source-wide units/identity/revisions、自然周期和生产切换依旧OPEN。父级87项矩阵、1,103项任务与1,066个脚本候选的既有分母和状态保持不变。
