# 第十批 Sina 资产负债表候选映射投影计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**CONTRACT_FROZEN / SOURCE_IMPLEMENTED_STATIC_REVIEW_GREEN / TEST_ISOLATION_REVIEW_PENDING / ACCEPTANCE_PENDING**。本批实现一个纯离线、source-qualified的七项映射候选投影。合同与projector均已通过静态review并集成到OpenData `fd151a46c44fe044f00b3386a6e032a3bc52252a`；唯一测试文件已由作者完成，独立隔离review尚待完成，root没有运行W10测试或coverage。

计划与输入基线：[WAVE9_PLAN.md](./WAVE9_PLAN.md)、[WAVE9_STATUS.md](./WAVE9_STATUS.md)。W10工作包以OpenData `9ff72ad668ce161f5132bf866b251acd3c80bbba`为共同基线；root在W9 scoped closure后集成至当前`fd151a46c44fe044f00b3386a6e032a3bc52252a`。W9负责产生原始Sina wire DTO；W10只从该DTO建立保留源证据的候选映射层，不构成W9或生产数据验收。

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
| 定向测试 | `/tmp/od204-wave6-http-boundaries` · `codex/od204-wave10-sina-candidate-tests` · owner `wave6_http_boundaries` | `tests/test_sina_financial_statement_candidate_projection.py` | author commit `be057bb0`已完成；测试隔离review pending，root未运行。使用W9录制正向fixture，负向用例只对captured response或typed DTO深拷贝变异。单文件、T3/A2测试。 |

root独占质量census、跨分支集成、import graph审查、测试环境及唯一测试运行；独立reviewer审查候选协议与结果证据边界。W9 archive closure后，root已集成合同与projector；测试作者仍在独立worktree，待隔离review后由root运行。

## 实施任务

| 任务 | 状态 | 完成条件 |
| --- | --- | --- |
| W10-01 冻结source-native候选合同 | CONTRACT_FROZEN | root decision与v4独立review pin一致；wire/DTO/命名空间/核算顺序变更需重新审查与冻结。 |
| W10-02 定义独立候选DTO和mapping table | IMPLEMENTED_STATIC_REVIEW_GREEN | 合同分支commit `954e79c970068915bd1b3bf54563d8733eb8a807`；`wave10-sina-candidate-contract-implementation-review.txt`为GREEN，范围限合同声明与import boundaries，不是projector、测试或生产验收。七组ID/title/key精确对应；candidate/unmapped类型与`c10-seven-balance-v1`绑定；固定来源证据引用；不依赖域模型或存储。 |
| W10-03 验证W9快照与源身份 | IMPLEMENTED_STATIC_REVIEW_GREEN | Projector commit `d0abab97`实现精确W9 DTO、expected query、symbol/paper code、`fzb`、报告period、date-only publication、Asia/Shanghai更新时间和UTC retrieval timestamp验证；手工DTO按不可信输入处理。静态review不替代运行测试。 |
| W10-04 保留原始条目并作精确投影 | IMPLEMENTED_STATIC_REVIEW_GREEN | 仅ID+title完全匹配成为candidate；raw value/state不参与匹配。原始值、metadata、ordinals和marker保留；unknown ID与title mismatch保留为unmapped；报告输出matched/missing/unmapped accounting。 |
| W10-05 保持有界、always-partial结果 | IMPLEMENTED_STATIC_REVIEW_GREEN | Projector实施W9 limits与ordinal完整性校验、CNY pilot admission并保持结果always-partial；任一报告无效则整份投影失败。CNY条件不证明科目单位。 |
| W10-06 唯一定向测试文件 | AUTHOR_TEST_READY / ISOLATION_REVIEW_PENDING | author commit `be057bb0`已交付唯一测试文件；等待独立隔离review。root尚未运行。测试使用W9录制fixture及captured response/typed DTO负向变异。 |
| W10-07 独立review与root scoped acceptance | ACCEPTANCE_PENDING | root静态核查import边界和file hashes、使用批准环境运行唯一新测试文件；A2/Ruff/format/strict-mypy/Bandit/public API及coverage receipt归档后才可更新状态。 |

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
5. 合同DTO（commit `954e79c9`）及projector（commit `d0abab97`）已静态review GREEN并集成到root source `fd151a46c44fe044f00b3386a6e032a3bc52252a`；唯一测试文件（author commit `be057bb0`）待独立隔离review，root尚未运行W10测试。静态review不替代执行、coverage或整体批次接受。W9/W10两批的旧失败历史、父矩阵或W9 acceptance不得由本批计划更改。

本批不注册Sina provider、不创建生产grant、不持久化候选、不新增route或调度任务、不修改FinancialStatement/DWD/PIT，也不启用任务748。来源rights、逐标的全历史、source-wide units/identity/revisions、自然周期和生产切换依旧OPEN。父级87项矩阵、1,103项任务与1,066个脚本候选的既有分母和状态保持不变。
