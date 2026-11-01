# 第十批 Sina 七项财务候选投影状态

日期：2026-10-27（Asia/Shanghai）。状态：**SCOPED_OFFLINE_COMPLETE / NOT_PRODUCTION_ACCEPTED**。root已在精确source `1bd226690acd7e4bbd620a480f7e6271c38297fd`完成唯一测试文件及scoped quality gates；49文件私有归档、两个公开证据文件扫描及独立archive audit均通过。本状态只记录source-qualified离线候选投影，不表示Sina source-wide语义、授权、全历史或生产验收。

计划与合同范围见[WAVE10_PLAN.md](./WAVE10_PLAN.md)。W9 raw-wire实现和范围限制见[WAVE9_STATUS.md](./WAVE9_STATUS.md)。

## 实现与冻结边界

合同冻结文本SHA-256为`2ec501ad7d20e9802a4dc1aef3911ec7e6a9b0d8f5af231072e780fdf75b9c9a`。候选合同DTO由commit `954e79c970068915bd1b3bf54563d8733eb8a807`交付；纯投影模块由`d0abab97e182437078898971236af417221da266`交付。两者均通过静态review，并集成至root精确QA source `1bd226690acd7e4bbd620a480f7e6271c38297fd`。唯一新增测试文件由author commit `be057bb0927a710a8e5b233fd28a9b262f0f9f4a`交付，独立隔离review为GREEN。

本批只对录制响应中的七组精确source ID/title对生成`c10-seven-balance-v1`候选，结果始终为`partial`。原值、value state、metadata、source ordinal、日期、更新时间及retrieved time保持source-native；未知项目和缺失映射显式核算。`CNY`仅是有限pilot的准入条件，不代表项目单位；候选key不是规范财务字段，不证明source-wide identity、修订、PIT或完整性。

## 精确验证

| 验证 | 结果 | 范围与限制 |
| --- | --- | --- |
| 候选projection唯一测试文件 | **PASS** | `wave10-candidates-first-root-command.json`：65 passed，44.23秒；source `1bd226690acd7e4bbd620a480f7e6271c38297fd`；测试author commit `be057bb0927a710a8e5b233fd28a9b262f0f9f4a`经`wave10-sina-candidate-test-isolation-review.txt` GREEN；只运行`tests/test_sina_financial_statement_candidate_projection.py`，使用`--noconftest`。 |
| Statement+branch coverage | **PASS** | 同一focused run：candidate contract `97.53086419753086%`，projector `95.36082474226804%`；两模块均达到90%目标，未降低阈值或新增排除。 |
| 隔离环境 | **PASS — FOCUSED** | 复用未变更的W9-owned Python 3.13.5虚拟环境，17个精确pin依赖、无system site packages；无应用启动、HTTP、数据库、scheduler或第三方SDK。不是完整项目extras或OS sandbox。 |
| OpenData scoped static与named gates | **PASS** | `wave10-od-static-first-command.json`：Ruff、format、mypy、Bandit、zero-dep、self-test、public API及brand均通过；981 runtime files，2,501 public callables覆盖率100%。 |
| Full-history secret component | **PASS — COMPONENT ONLY** | `wave10-final-secret-command.json`：Gitleaks 8.30.1扫描905 commits，0 leaks；不代表完整`make gate`。 |
| Whole-resolver A2 | **NOT_RUN_FOR_W10** | W9在旧质量锚点的A2结果不作为W10 fresh A2；W10三个新增Python文件由本批scoped静态检查覆盖。 |
| 私有归档 | **PASS — FROZEN** | `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave10`：49 files，766,405 bytes，1 HTML coverage ZIP；目录0700、文件0600。 |
| 公开validation与archive JSON | **PASS — CREATED** | `docs/afi204-wave10-validation.json` SHA-256 `b66e8d324204d6370b14f38b23f69793b3c4a6749893d7f58e7eed24dba8f02d`；`docs/afi204-wave10-archive.json` SHA-256 `3bb36b02a9f390f76e166dc7e33dc20bf6d9645e9cb0bec68b2dcbc5d84c2bf6`。 |
| 公开JSON secret scan | **PASS** | Gitleaks 8.30.1，0 findings；receipt SHA-256 `581ec0031790dfcfe490e1ed60784ff1eefc3225b71cb9a7e23f4d3e2325e0d8`。扫描覆盖两个公开JSON，归档文件未变。 |
| 独立archive audit | **PASS** | `wave10-archive-independent-audit.json` SHA-256 `57077d7e1c826279bf0cea558c7c4dfaaa609b5005392eb762e805429d9f0250`；验证49/49个W10文件、单个HTML ZIP CRC及安全路径，并复核W7/W8/W9共348个既有归档文件。无findings。 |
| Full `make` gate / remote CI | **NOT_RUN** | 不属于上述精确验证。 |
| Python 3.10 runtime | **NOT_RUN** | 没有3.10解释器运行矩阵结果。 |
| 生产授权与启用 | **OPEN / NOT_APPROVED** | 无来源权利、provider注册、生产grant、FinancialStatement/DWD/PIT接入或任务748启用批准。 |

在W10关闭时，W11仍处设计阶段、合同未冻结且尚未开始实现，因此不属于W10的交付或验收。之后W11合同已冻结并进入实施；截至2026-10-27，13文件核心回归、OpenAPI专项、scoped static、A2（1,222 complete-resolver files/796 unique mypy roots）及976-commit full-history Gitleaks（0 leaks）均通过。W11的182文件私有归档及两个公开metadata已创建、公开JSON复扫0 findings；此前状态记录独立归档审查尚在运行，现已完成25项核验且0 findings。当前计划与真实收据分别见[WAVE11_PLAN.md](./WAVE11_PLAN.md)和[WAVE11_STATUS.md](./WAVE11_STATUS.md)。

## 父迭代范围

父级87项控制任务保持8项`DEV_DONE`、9项`IN_PROGRESS`、70项`PLANNED`；1,103项旧任务与1,066个脚本候选分母均不变，仍需逐项确定来源、证据和迁移去向。source rights、source-wide单位与identity、revision/PIT语义、逐标的全历史head/interior/tail、自然周期、备份恢复与单写者切换继续OPEN。W10离线QA通过不关闭这些条件，也不构成生产接受。
